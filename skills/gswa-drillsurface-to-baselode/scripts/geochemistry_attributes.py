# Copyright (C) 2026 Darkmine Pty Ltd.

"""Source-record assays with complete evidence and unambiguous publisher projections."""
import csv
import hashlib
import json
import math
import numbers
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import baselode.datamodel.attributes

MAP_PATH = Path(__file__).with_name('geochemistry_analyte_map.csv')
DESCRIPTORS = ['sample_type', 'sample_method', 'sample_category', 'sample_condition',
               'sampled_by', 'date_sampled', 'superseded', 'has_duplicate']
TEXT_MAPPING = [{'name': name, 'target': target, 'priority': 0} for name, target in [
    ('Sample_Type', 'sample_type'), ('Sample_Method', 'sample_method'),
    ('Sample_Category', 'sample_category'), ('Sample_Condition', 'sample_condition'),
    ('Sampled_By', 'sampled_by'), ('Date_Sampled', 'date_sampled'),
    ('Superseded', 'superseded'), ('Has_Duplicate', 'has_duplicate')]]
EXCLUSION_FLAGS = ['Flag_LT', 'Flag_GT', 'Flag_KnownNoDataValue', 'Flag_KnownMetaDataValue',
                   'Flag_BadDataValue', 'Flag_ValidLessThanDetectionLevel']
RENAME = {'DHGeochemistryId': 'parent_id', 'Id': 'attribute_id',
          'AttributeColumn': 'name', 'AttributeValue': 'value',
          'ModifiedDate': 'modified_date', 'ModifiedBy': 'modified_by', 'MRTDetailId': 'mrt_detail_id'}


def load_mapping():
    """Load exact reviewed labels; punctuation-stripping is not chemical mapping."""
    with MAP_PATH.open(newline='') as stream:
        mapping = list(csv.DictReader(stream))
    labels = [row['raw_name'] for row in mapping]
    if len(labels) != len(set(labels)) or any(not value for value in labels):
        raise ValueError('Geochemistry mapping requires unique nonempty exact labels')
    return mapping


def exclusion_reasons(record):
    """No raw-text numeric fallback, unit conversion or inferred negative censoring."""
    reasons = []
    value = record.get('PPMValue')
    if value is None:
        reasons.append('missing_publisher_value')
    elif isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        reasons.append('non_finite_or_non_numeric_publisher_value')
    for flag in EXCLUSION_FLAGS:
        bit = record.get(flag)
        if bit is not None and not isinstance(bit, bool):
            raise ValueError(f'Attribute {record["attribute_id"]}: {flag} must be boolean or null')
        if bit is True:
            reasons.append(flag)
    text = record.get('value')
    if isinstance(text, str) and text.lstrip().startswith(('<', '>')):
        reasons.append('qualified_source_text')
    return reasons


def expand_batch(frame, raw_parents, attributes, mapping):
    """Expand complete parent groups, retaining every record and original scalar."""
    lookup = {item['raw_name']: item['target'] for item in mapping}
    fields = sorted(set(lookup.values()))
    selected_parents = raw_parents.iloc[frame['source_row_index'].astype('int64')]
    parents = frame.copy()
    parents['_source_geochemistry_interval_id'] = selected_parents['Id'].to_numpy()
    collar_key = 'CollarId' if 'CollarId' in selected_parents else 'Collarid'
    parents['_source_collar_id'] = selected_parents[collar_key].to_numpy()
    if 'CompanySampleId' in selected_parents:
        parents['company_sample_id'] = pd.array(selected_parents['CompanySampleId'], dtype='string')
    source_attributes = attributes.rename(columns=RENAME)
    result = baselode.datamodel.attributes.promote_attributes(
        parents, source_attributes, TEXT_MAPPING, DESCRIPTORS,
        parent_key='_source_geochemistry_interval_id')
    values = {field: [] for field in fields}
    payloads, clash_counts = [], []
    summary = Counter()
    exclusions = Counter()
    statuses = {field: Counter() for field in fields}
    original_parents = selected_parents.to_dict('records')
    for original_extra, original_parent, text_clashes in zip(
            result['attributes_extra'], original_parents, result['attribute_clash_count']):
        extra = json.loads(original_extra)
        records = extra.setdefault('_attribute_records', [])
        extra['_source_record'] = {k: baselode.datamodel.attributes.json_scalar(v)
                                   for k, v in original_parent.items()}
        candidates = {}
        for record in records:
            target = lookup.get(record['name'])
            if target is None:
                continue
            reasons = exclusion_reasons(record)
            exclusions.update(reasons)
            candidates.setdefault(target, []).append({
                'attribute_id': record['attribute_id'], 'name': record['name'],
                'publisher_value': record.get('PPMValue'), 'eligible': not reasons,
                'exclusion_reasons': reasons})
        selection = {}
        numeric_clashes = 0
        for field in fields:
            choices = candidates.get(field, [])
            eligible = [item for item in choices if item['eligible']]
            distinct = {item['publisher_value'] for item in eligible}
            if len(distinct) == 1:
                value = eligible[0]['publisher_value']
                status = 'unambiguous_publisher_value'
            elif len(distinct) > 1:
                value, status = None, 'conflict'
                numeric_clashes += 1
            else:
                value, status = None, 'unavailable'
            values[field].append(value)
            statuses[field][status] += 1
            if choices:
                selection[field] = {'status': status,
                    'eligible_attribute_ids': [item['attribute_id'] for item in eligible],
                    'candidates': choices}
            if status == 'conflict':
                extra.setdefault('_conflicts', {})[field] = choices
        if selection:
            extra['_assay_selection'] = selection
        payloads.append(json.dumps(extra, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')))
        clash_counts.append(int(text_clashes) + numeric_clashes)
        summary['retained_attribute_records'] += len(records)
        summary['mapped_attribute_records'] += sum(len(v) for v in candidates.values())
        summary['numeric_conflict_fields'] += numeric_clashes
        summary['observations_with_numeric_conflicts'] += bool(numeric_clashes)
        summary['observations_with_clashes'] += bool(int(text_clashes) + numeric_clashes)
    result['attributes_extra'] = pd.array(payloads, dtype='string')
    result['attribute_clash_count'] = clash_counts
    for field in fields:
        result[field] = pd.Series(values[field], index=result.index, dtype='float64')
    return result, summary, exclusions, statuses


def write(frame, raw_parents, attribute_path, out_dir, chunk_size=2000):
    """Write parent batches without changing result selection across chunk sizes.

    The Arrow attribute table remains in memory for project-sized exports;
    Python dictionaries/JSON are bounded to complete parent batches. A source
    parent key is never split across batches. Outputs are Snappy Parquet/CSV.
    """
    required = {'Id', 'FromDepth'}
    if not required.issubset(raw_parents) or not {'CollarId', 'Collarid'}.intersection(raw_parents):
        raise ValueError('Geochemistry requires Id, FromDepth and CollarId (or Collarid)')
    if raw_parents.Id.isna().any() or raw_parents.Id.duplicated().any():
        raise ValueError('Geochemistry parent IDs must be unique and non-null')
    refs = frame['source_row_index']
    if len(frame) != len(raw_parents) or refs.nunique() != len(raw_parents):
        raise ValueError('Geochemistry parent source coverage must be one-to-one')
    if chunk_size < 1:
        raise ValueError('Geochemistry chunk_size must be positive')
    if attribute_path is None:
        attributes = pa.table({name: pa.array([], type=kind) for name, kind in [
            ('Id', pa.int64()), ('DHGeochemistryId', pa.int64()),
            ('AttributeColumn', pa.string()), ('AttributeValue', pa.string()), ('PPMValue', pa.float64())]})
    else:
        attributes = pq.read_table(attribute_path)
    needed = {'Id', 'DHGeochemistryId', 'AttributeColumn', 'AttributeValue', 'PPMValue'}
    if not needed.issubset(attributes.column_names):
        raise ValueError(f'Geochemistry attributes missing columns: {sorted(needed - set(attributes.column_names))}')
    if attributes['Id'].null_count or pc.count_distinct(attributes['Id']).as_py() != len(attributes):
        raise ValueError('Geochemistry attribute IDs must be unique and non-null')
    if attributes['DHGeochemistryId'].null_count or (len(attributes) and not pc.all(pc.is_in(
            attributes['DHGeochemistryId'], value_set=pa.array(raw_parents.Id))).as_py()):
        raise ValueError('Geochemistry attributes contain null or orphan parent keys')
    mapping = load_mapping()
    fields = sorted({item['target'] for item in mapping})
    summary, exclusions = Counter(), Counter()
    statuses = {field: Counter() for field in fields}
    populated = Counter()
    out_dir = Path(out_dir)
    parquet = out_dir / 'assays.parquet'
    csv_path = out_dir / 'assays.csv'
    writer = None
    output_columns = None
    parent_schema = pa.Schema.from_pandas(frame, preserve_index=False)
    schema = None
    # An empty parent export still produces a stable typed table.
    starts = range(0, len(frame), chunk_size) if len(frame) else [0]
    try:
        with csv_path.open('w', newline='') as stream:
            for start in starts:
                batch = frame.iloc[start:start + chunk_size].copy().reset_index(drop=True)
                parent_ids = raw_parents.iloc[batch['source_row_index'].astype('int64')]['Id']
                selected = attributes.filter(pc.is_in(attributes['DHGeochemistryId'], value_set=pa.array(parent_ids)))
                result, counts, rejected, batch_statuses = expand_batch(batch, raw_parents, selected.to_pandas(), mapping)
                summary.update(counts)
                exclusions.update(rejected)
                for field, counts in batch_statuses.items():
                    statuses[field].update(counts)
                populated.update({field: int(result[field].notna().sum()) for field in fields + DESCRIPTORS})
                if schema is None:
                    inferred = pa.Schema.from_pandas(result, preserve_index=False)
                    schema = pa.schema([parent_schema.field(name) if name in parent_schema.names
                                        else inferred.field(name) for name in result.columns])
                table = pa.Table.from_pandas(result, schema=schema, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(parquet, table.schema, compression='snappy')
                    output_columns = list(result.columns)
                writer.write_table(table)
                result.to_csv(stream, index=False, header=start == 0)
    finally:
        if writer is not None:
            writer.close()
    if summary['retained_attribute_records'] != len(attributes):
        raise ValueError('Geochemistry attribute source accounting failed')
    coverage = {
        'status': 'complete' if len(attributes) else 'empty', 'input_rows': len(attributes),
        **{name: int(summary[name]) for name in ['retained_attribute_records', 'mapped_attribute_records',
           'numeric_conflict_fields', 'observations_with_numeric_conflicts', 'observations_with_clashes']},
        'mapping': mapping, 'mapping_sha256': hashlib.sha256(MAP_PATH.read_bytes()).hexdigest(),
        'descriptor_mapping': TEXT_MAPPING, 'promoted_nonnull_rows': dict(populated),
        'exclusion_reason_counts': dict(exclusions), 'field_status_counts': {k: dict(v) for k, v in statuses.items()},
        'selection_policy': 'Exact labels; finite uncensored publisher PPMValue; identical eligible values agree; differing values yield flat null',
        'unit_policy': 'Publisher numeric values unchanged; no raw-text numeric fallback or unit conversion; units scientifically unverified',
        'grain': 'one row per source geochemistry Id', 'parent_batch_size': chunk_size,
        'source_record_columns': list(raw_parents.columns),
        'json_encoding': 'UTF-8 JSON text; parse as JSONB when loading PostgreSQL'}
    return output_columns, coverage
