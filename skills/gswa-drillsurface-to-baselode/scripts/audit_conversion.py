# Copyright (C) 2026 Darkmine Pty Ltd.

"""Non-repairing canonical conversion for downstream QAQC.

Uses Baselode's column maps without its validating loaders. Raw artifacts
remain authoritative, including fields outside the current canonical model.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet
import baselode.adaptors.raw_gswa.columns


CONVERTER_VERSION = '0.1.4.dev0'


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def orphan_identity(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f'gswa:orphan-collar:{value}'


def convert(src_dir, out_dir):
    """Write canonical files and coverage for project-size exports.

    Attribute records are materialized in memory; subset state-scale EAV
    exports before using this project conversion path.
    """
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise ValueError('Non-repairing conversion requires an empty output directory')
    incomplete = out_dir / '.conversion-incomplete'
    incomplete.write_text('Conversion has not completed. Use a fresh output directory to retry.\n')
    paths = {path.stem: path for path in sorted(src_dir.glob('*.parquet'))}
    # Resolve the API early only when this export contains geology attributes.
    if 'dbo_dhgeologyattr' in paths:
        if __package__:
            from . import geology_attributes
        else:
            import geology_attributes
    if 'dbo_dhstructure' in paths:
        if __package__:
            from . import structure_attributes
        else:
            import structure_attributes
    if 'dbo_dhstructureattr' in paths and 'dbo_dhstructure' not in paths:
        if pyarrow.parquet.ParquetFile(paths['dbo_dhstructureattr']).metadata.num_rows:
            raise ValueError('Structure attributes require their raw parent table')
    maps = baselode.adaptors.raw_gswa.columns
    needed = {'dbo_collar','dbo_dhsurvey','gsd_dhassayflat','dbo_dhgeochemistry','dbo_dhgeology','dbo_dhgeologyattr','dbo_surfacesample','gsd_ssassayflat','dbo_dhstructure','dbo_dhstructureattr'}
    sources = {name: pd.read_parquet(path) for name,path in paths.items() if name in needed}
    if 'dbo_collar' not in sources:
        raise ValueError('Required raw table dbo_collar.parquet is missing')
    collars = sources['dbo_collar']
    if 'HoleId' not in collars or 'Id' not in collars:
        raise ValueError('Raw collars require Id and HoleId')
    # Null keys cannot identify a parent, even though pandas merges nulls.
    lookup = collars.loc[collars['Id'].notna(), ['Id', 'HoleId']].drop_duplicates()
    if lookup['Id'].duplicated().any():
        raise ValueError('Conflicting HoleId values for a CollarId; cannot map intervals faithfully')
    lookup = lookup.rename(columns={'Id': 'CollarId', 'HoleId': '_parent_hole_id'})
    assay_source = 'gsd_dhassayflat'
    if assay_source not in sources or (sources[assay_source].empty and 'dbo_dhgeochemistry' in sources):
        assay_source = 'dbo_dhgeochemistry'
    spec = {
        'collars': ('dbo_collar', maps.GSWA_RAW_TO_BASELODE_COLLAR),
        'survey': ('dbo_dhsurvey', maps.GSWA_RAW_TO_BASELODE_SURVEY),
        'assays': (assay_source, maps.GSWA_RAW_TO_BASELODE_INTERVAL),
        'geology': ('dbo_dhgeology', maps.GSWA_RAW_TO_BASELODE_INTERVAL),
        'surface_samples': ('dbo_surfacesample', maps.GSWA_RAW_TO_BASELODE_SURFACE_SAMPLE),
        'structure': ('dbo_dhstructure', maps.GSWA_RAW_TO_BASELODE_INTERVAL),
    }
    # Structure retains source bounds; its point-view depth uses the start.
    manifest = {'version': 1, 'schema': 'baselode', 'acquisition_mode': 'raw_gswa_conversion',
                'converter_version': CONVERTER_VERSION, 'options': {'preserve_issues': True, 'hole_id_source': 'baselode'},
                'tables': {}, 'sources': {}, 'limits': [
                    'WA only. Unmapped source tables remain raw; conversion is not scientific QAQC.',
                    'Geology and structural attributes use reviewed flat fields and JSON source evidence; other EAV families remain raw.',
                    'Surface sample conversion includes available flattened assays; no surface QAQC or EAV assay pivot.',
                    'Surface assays without a usable matching parent remain raw; joined_source_coverage counts these rows.',
                    'Assay values and unit suffixes are preserved from the publisher, not scientifically verified or repaired.',
                    'No repairs, orientation normalization, clipping or desurvey performed.']}
    for name, path in paths.items():
        metadata = pyarrow.parquet.ParquetFile(path)
        manifest['sources'][name] = {'rows': metadata.metadata.num_rows, 'columns': metadata.schema_arrow.names,
                                     'sha256': checksum(path), 'converted_to': []}
    for name, (source, mapping) in spec.items():
        if source not in sources:
            manifest['tables'][name] = {'status': 'absent', 'source': source, 'rows': 0}
            continue
        raw = sources[source].copy()
        raw['source_row_index'] = range(len(raw))
        raw['source_table'] = source
        extra_sources = []
        joined_source_coverage = {}
        structural_coverage = None
        if name == 'surface_samples' and 'gsd_ssassayflat' in sources and 'Id' in raw:
            flat = sources['gsd_ssassayflat'].copy()
            # 2026-05 uses Id as the surface sample key. Older releases also
            # have an unrelated Id, so always prefer their explicit parent key.
            parent_keys = [column for column in flat if column.lower() == 'surfacesampleid']
            if len(parent_keys) > 1:
                raise ValueError('Ambiguous surface sample keys in gsd_ssassayflat')
            key = parent_keys[0] if parent_keys else ('Id' if 'Id' in flat else None)
            if key:
                analytes = [key for key in flat if key.lower().endswith(('_ppm', '_ppb', '_pct'))]
                joined_mapping = {key: mapping['Id'], **{column: column for column in analytes}}
                matched = flat[key].notna() & flat[key].isin(raw['Id'].dropna())
                unmatched_rows = int((~matched).sum())
                joined_source_coverage['gsd_ssassayflat'] = {
                    'join_key': key, 'mapping': joined_mapping,
                    'status': 'partial' if unmatched_rows else ('complete' if len(flat) else 'empty'),
                    'input_rows': len(flat), 'matched_rows': int(matched.sum()),
                    'unmatched_rows': unmatched_rows, 'null_key_rows': int(flat[key].isna().sum()),
                    'orphan_key_rows': int((flat[key].notna() & ~matched).sum()),
                    'unmatched_reason': 'Null or unmatched parent keys remain in the original raw source; no surface QAQC'
                        if unmatched_rows else None,
                    'unmapped_columns': [column for column in flat if column not in joined_mapping],
                }
                flat['source_assay_row_index'] = range(len(flat))
                raw = raw.merge(flat.loc[flat[key].notna(), [key, 'source_assay_row_index', *analytes]], left_on='Id', right_on=key, how='left', sort=False)
                extra_sources.append('gsd_ssassayflat')
        if 'Collarid' in raw and 'CollarId' not in raw:
            raw = raw.rename(columns={'Collarid': 'CollarId'})
        if name not in ('collars', 'surface_samples') and 'CollarId' in raw:
            raw = raw.merge(lookup, on='CollarId', how='left', validate='many_to_one', sort=False,
                            indicator='_collar_join_status')
            if 'HoleId' not in raw:
                raw['HoleId'] = raw['_parent_hole_id']
            else:
                # Resolve missing derived identity from its explicit parent key;
                # source values remain available unchanged in the raw artifact.
                raw['HoleId'] = raw['HoleId'].fillna(raw['_parent_hole_id'])
            # Preserve orphan identities so the orphan check can report them.
            missing_parent = raw['_collar_join_status'].eq('left_only') & raw['HoleId'].isna() & raw['CollarId'].notna()
            raw['HoleId'] = raw['HoleId'].astype(object)
            raw.loc[missing_parent, 'HoleId'] = raw.loc[missing_parent, 'CollarId'].map(orphan_identity)
        used = {key: value for key, value in mapping.items() if key in raw}
        # Only canonical columns plus source references belong to this dataset.
        columns = list(used) + ['source_table', 'source_row_index']
        if name in ('assays', 'surface_samples'):
            columns += [key for key in raw if key.lower().endswith(('_ppm', '_ppb', '_pct')) and key not in columns]
        if 'source_assay_row_index' in raw:
            columns.append('source_assay_row_index')
        source_mapping = {}
        for original in sources[source].columns:
            selected = 'CollarId' if original == 'Collarid' and 'CollarId' not in sources[source] else original
            if selected in columns:
                source_mapping[original] = used.get(selected, selected)
        frame = raw[columns].rename(columns=used)
        if frame.columns.duplicated().any():
            raise ValueError(f'Ambiguous canonical column mapping in {source}')
        for key in ('hole_id', 'datasource_hole_id', 'sample_id'):
            if key in frame:
                frame[key] = frame[key].astype('string')
        if name == 'geology' and 'dbo_dhgeologyattr' in sources:
            frame, coverage = geology_attributes.expand(frame, sources[source], sources['dbo_dhgeologyattr'])
            source_mapping['Id'] = '_source_interval_id'
            for original in sources[source].columns:
                source_mapping.setdefault(original, f'attributes_extra._source_record.{original}')
            extra_sources.append('dbo_dhgeologyattr')
            joined_source_coverage['dbo_dhgeologyattr'] = coverage
        if name == 'structure':
            attributes = sources.get('dbo_dhstructureattr', pd.DataFrame(
                columns=['Id', 'DHStructureId', 'AttributeColumn', 'AttributeValue']))
            frame, structural_coverage = structure_attributes.expand(frame, sources[source], attributes)
            source_mapping['Id'] = '_source_structure_id'
            collar_key = 'CollarId' if 'CollarId' in sources[source] else 'Collarid'
            source_mapping[collar_key] = '_source_collar_id'
            for original in sources[source].columns:
                source_mapping.setdefault(original, f'attributes_extra._source_record.{original}')
            if 'dbo_dhstructureattr' in sources:
                extra_sources.append('dbo_dhstructureattr')
                joined_source_coverage['dbo_dhstructureattr'] = structural_coverage
        files = {}
        for ext in ('parquet', 'csv'):
            path = out_dir / f'{name}.{ext}'
            if ext == 'parquet':
                frame.to_parquet(path, index=False, compression='snappy')
            else:
                frame.to_csv(path, index=False)
            files[ext] = path.name
        manifest['tables'][name] = {'status': 'converted' if len(frame) else 'empty', 'source': source,
                                    'rows': len(frame), 'columns': list(frame.columns), 'mapping': source_mapping,
                                    'unmapped_columns': [key for key in sources[source] if key not in source_mapping],
                                    'files': files, 'sha256': checksum(out_dir / files['parquet'])}
        if structural_coverage is not None:
            manifest['tables'][name]['structural_conversion'] = structural_coverage
        manifest['sources'][source]['converted_to'].append(name)
        for extra_source in extra_sources:
            manifest['sources'][extra_source]['converted_to'].append(name)
        manifest['tables'][name]['joined_sources'] = extra_sources
        manifest['tables'][name]['joined_source_coverage'] = joined_source_coverage
    manifest['not_converted'] = [name for name, info in manifest['sources'].items() if not info['converted_to']]
    target = out_dir / 'conversion_manifest.json'
    temporary = out_dir / 'conversion_manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(target)
    incomplete.unlink()
    return manifest
