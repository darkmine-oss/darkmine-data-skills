# Copyright (C) 2026 Darkmine Pty Ltd.

"""Reviewed structural attributes with original bounds and numeric evidence."""
import json

import numpy as np
import pandas as pd
import baselode.datamodel.attributes

NUMERIC_FIELDS = ['dip', 'azimuth', 'alpha', 'beta']
FIELDS = NUMERIC_FIELDS + ['structure_type', 'structure_origin',
                           'origin_reliability', 'weathering', 'comments']
# Deliberately exclude plane/calculated/local angles: these are different
# measurements, not fallback aliases for the logged orientation fields.
MAPPING = [{'name': name, 'target': target, 'priority': 0} for name, target in [
    ('Dip', 'dip'), ('Dip_Direction', 'azimuth'), ('Alpha', 'alpha'), ('Beta', 'beta'),
    ('Structure_Type', 'structure_type'), ('Structure_Origin', 'structure_origin'),
    ('Origin_Reliability', 'origin_reliability'), ('Weathering', 'weathering'),
    ('Comments', 'comments')]]


def expand(frame, raw_parents, raw_attributes):
    """Return one row per original observation and full attribute evidence.

    depth is the supplied start, never a midpoint. Original from/to values
    stay unchanged; absent ToDepth columns are not created. Selected numeric
    text becomes a finite float or null with _numeric_parse_issues evidence.
    Out-of-range finite angles are retained for later QAQC, without clipping.
    """
    required = {'Id', 'CollarId', 'FromDepth'}
    if not required.issubset(raw_parents):
        raise ValueError(f'Structure expansion requires raw columns: {sorted(required)}')
    parents = frame.copy()
    selected = raw_parents.iloc[parents['source_row_index']]
    parents['_source_structure_id'] = selected['Id'].to_numpy()
    parents['_source_collar_id'] = selected['CollarId'].to_numpy()
    # Plotting convention: use the original start; never fill or invent to.
    parents['depth'] = parents['from'].copy()
    attributes = raw_attributes.rename(columns={
        'DHStructureId': 'parent_id', 'Id': 'attribute_id', 'AttributeColumn': 'name',
        'AttributeValue': 'value', 'ModifiedDate': 'modified_date',
        'ModifiedBy': 'modified_by', 'MRTDetailId': 'mrt_detail_id'})
    result = baselode.datamodel.attributes.promote_attributes(
        parents, attributes, MAPPING, FIELDS, parent_key='_source_structure_id')
    payloads = [json.loads(v) for v in result['attributes_extra']]
    parse_counts = {}
    for field in NUMERIC_FIELDS:
        text = result[field].copy()
        numeric = pd.to_numeric(text, errors='coerce').astype('float64')
        invalid = text.notna() & ~np.isfinite(numeric)
        parse_counts[field] = int(invalid.sum())
        for position in np.flatnonzero(invalid.to_numpy()):
            payloads[position].setdefault('_numeric_parse_issues', []).append({
                'field': field, 'selected_text': text.iloc[position],
                'reason': 'Not a finite numeric value; original attribute records retained'})
        result[field] = numeric.where(~invalid, np.nan)
    source_records = [{k: baselode.datamodel.attributes.json_scalar(v) for k, v in row.items()}
                      for row in selected.to_dict('records')]
    for payload, record in zip(payloads, source_records):
        payload['_source_record'] = record
        payload.setdefault('_attribute_records', [])
    result['attributes_extra'] = pd.array([
        json.dumps(v, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
        for v in payloads], dtype='string')
    retained = sum(len(v.get('_attribute_records', [])) for v in payloads)
    if retained != len(raw_attributes):
        raise ValueError('Structure attribute source accounting failed')
    paired_dip = result[['dip', 'azimuth']].notna().all(axis=1)
    paired_core = result[['alpha', 'beta']].notna().all(axis=1)
    return result, {
        'input_rows': len(raw_attributes), 'retained_attribute_records': retained,
        'status': 'complete' if retained else 'empty', 'mapping': MAPPING,
        'promoted_nonnull_rows': {f: int(result[f].notna().sum()) for f in FIELDS},
        'observations_with_clashes': int((result['attribute_clash_count'] > 0).sum()),
        'clash_fields': int(result['attribute_clash_count'].sum()),
        'numeric_parse_failure_rows': parse_counts,
        'numeric_parse_failures': sum(parse_counts.values()),
        'depth_anchor': 'from (source interval start); no end depth filled or inferred',
        'missing_end_depth_rows': int(result['to'].isna().sum()) if 'to' in result else len(result),
        'end_depth_column_present': 'to' in result,
        'complete_dip_azimuth_rows': int(paired_dip.sum()),
        'complete_alpha_beta_rows': int(paired_core.sum()),
        'both_orientation_pairs_rows': int((paired_dip & paired_core).sum()),
        'neither_complete_orientation_pair_rows': int((~paired_dip & ~paired_core).sum()),
        'json_encoding': 'UTF-8 JSON text; parse as JSONB when loading PostgreSQL',
        'source_record_columns': list(raw_parents.columns)}
