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


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def convert(src_dir, out_dir):
    """Write canonical Parquet/CSV plus complete source and coverage inventory."""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    maps = baselode.adaptors.raw_gswa.columns
    paths = {path.stem: path for path in sorted(src_dir.glob('*.parquet'))}
    needed = {'dbo_collar','dbo_dhsurvey','gsd_dhassayflat','dbo_dhgeochemistry','dbo_dhgeology','dbo_surfacesample','gsd_ssassayflat'}
    sources = {name: pd.read_parquet(path) for name,path in paths.items() if name in needed}
    if 'dbo_collar' not in sources:
        raise ValueError('Required raw table dbo_collar.parquet is missing')
    collars = sources['dbo_collar']
    if 'HoleId' not in collars or 'Id' not in collars:
        raise ValueError('Raw collars require Id and HoleId')
    lookup = collars[['Id', 'HoleId']].drop_duplicates()
    if lookup['Id'].duplicated().any():
        raise ValueError('Conflicting HoleId values for a CollarId; cannot map intervals faithfully')
    lookup = lookup.rename(columns={'Id': 'CollarId', 'HoleId': '_parent_hole_id'})
    spec = {
        'collars': ('dbo_collar', maps.GSWA_RAW_TO_BASELODE_COLLAR),
        'survey': ('dbo_dhsurvey', maps.GSWA_RAW_TO_BASELODE_SURVEY),
        'assays': ('gsd_dhassayflat' if 'gsd_dhassayflat' in sources else 'dbo_dhgeochemistry', maps.GSWA_RAW_TO_BASELODE_INTERVAL),
        'geology': ('dbo_dhgeology', maps.GSWA_RAW_TO_BASELODE_INTERVAL),
        'surface_samples': ('dbo_surfacesample', maps.GSWA_RAW_TO_BASELODE_SURFACE_SAMPLE),
    }
    # Structure's canonical schema is a point model. Do not invent an interval
    # mapping merely because the validator supports an optional structure table.
    manifest = {'version': 1, 'schema': 'baselode', 'acquisition_mode': 'raw_gswa_conversion',
                'converter_version': '0.1.0', 'options': {'preserve_issues': True, 'hole_id_source': 'baselode'},
                'tables': {}, 'sources': {}, 'limits': [
                    'WA only. Structure and unmapped source tables are retained raw and not validated.',
                    'EAV assay/geology attributes are retained raw; interval checks use parent rows.',
                    'Surface sample conversion includes available flattened assays; no surface QAQC or EAV assay pivot.',
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
        if name == 'surface_samples' and 'gsd_ssassayflat' in sources and 'Id' in raw:
            flat = sources['gsd_ssassayflat'].copy()
            key = next((key for key in ('SurfaceSampleId', 'SurfacesampleId', 'SurfaceSampleid') if key in flat), None)
            if key:
                analytes = [key for key in flat if key.lower().endswith(('_ppm', '_ppb', '_pct'))]
                flat['source_assay_row_index'] = range(len(flat))
                raw = raw.merge(flat[[key, 'source_assay_row_index', *analytes]], left_on='Id', right_on=key, how='left', sort=False)
                extra_sources.append('gsd_ssassayflat')
        if 'Collarid' in raw and 'CollarId' not in raw:
            raw = raw.rename(columns={'Collarid': 'CollarId'})
        if name not in ('collars', 'surface_samples') and 'CollarId' in raw:
            raw = raw.merge(lookup, on='CollarId', how='left', validate='many_to_one', sort=False)
            if 'HoleId' not in raw:
                raw['HoleId'] = raw['_parent_hole_id']
            # Preserve orphan identities so the orphan check can report them.
            raw['HoleId'] = raw['HoleId'].fillna(raw['CollarId'].map(lambda value: f'gswa:orphan-collar:{value}'))
        used = {key: value for key, value in mapping.items() if key in raw}
        # Only canonical columns plus source references belong to this dataset.
        columns = list(used) + ['source_table', 'source_row_index']
        if name in ('assays', 'surface_samples'):
            columns += [key for key in raw if key.lower().endswith(('_ppm', '_ppb', '_pct')) and key not in columns]
        if 'source_assay_row_index' in raw:
            columns.append('source_assay_row_index')
        frame = raw[columns].rename(columns=used)
        if frame.columns.duplicated().any():
            raise ValueError(f'Ambiguous canonical column mapping in {source}')
        for key in ('hole_id', 'datasource_hole_id', 'sample_id'):
            if key in frame:
                frame[key] = frame[key].astype('string')
        files = {}
        for ext in ('parquet', 'csv'):
            path = out_dir / f'{name}.{ext}'
            if ext == 'parquet':
                frame.to_parquet(path, index=False, compression='snappy')
            else:
                frame.to_csv(path, index=False)
            files[ext] = path.name
        manifest['tables'][name] = {'status': 'converted' if len(frame) else 'empty', 'source': source,
                                    'rows': len(frame), 'columns': list(frame.columns), 'mapping': used,
                                    'unmapped_columns': [key for key in sources[source] if key not in used],
                                    'files': files, 'sha256': checksum(out_dir / files['parquet'])}
        manifest['sources'][source]['converted_to'].append(name)
        for extra_source in extra_sources:
            manifest['sources'][extra_source]['converted_to'].append(name)
        manifest['tables'][name]['joined_sources'] = extra_sources
    manifest['not_converted'] = [name for name, info in manifest['sources'].items() if not info['converted_to']]
    target = out_dir / 'conversion_manifest.json'
    temporary = out_dir / 'conversion_manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(target)
    return manifest
