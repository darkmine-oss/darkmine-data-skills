# Copyright (C) 2026 Darkmine Pty Ltd.

"""Explicit GSWA geology attribute promotion for non-repairing exports."""
import json

import pandas as pd
import baselode.datamodel.attributes

FIELDS = ['lithology', 'lithology_2', 'lithology_3', 'alteration', 'weathering',
          'colour', 'texture', 'structure', 'mineralisation', 'unit', 'stratigraphy', 'comments']

# Reviewed aliases: company values are preserved, not decoded or standardized.
ALIASES = [
    ('lith1', 'lithology', 1), ('lith_1', 'lithology', 2),
    ('lithology1', 'lithology', 3), ('lithology_1', 'lithology', 4), ('lith', 'lithology', 5),
    ('lith_2', 'lithology_2', 1), ('lith2', 'lithology_2', 2),
    ('lithology2', 'lithology_2', 3), ('lithology_2', 'lithology_2', 4),
    ('lith3', 'lithology_3', 1), ('lith_3', 'lithology_3', 2),
    ('alteration', 'alteration', 1), ('weathering', 'weathering', 1),
    ('colour', 'colour', 1), ('color', 'colour', 2), ('texture', 'texture', 1),
    ('structure', 'structure', 1), ('mineralisation', 'mineralisation', 1),
    ('mineralization', 'mineralisation', 2), ('unit', 'unit', 1), ('stratigraphy', 'stratigraphy', 1),
    ('comments', 'comments', 1), ('cmnt', 'comments', 2), ('description', 'comments', 3),
    ('Lith Code 1', 'lithology', 6), ('LithCode1', 'lithology', 7), ('Rock Type', 'lithology', 8),
    ('Lith Code 2', 'lithology_2', 5),
    ('Lithology Description', 'comments', 4), ('Lithology and Description', 'comments', 5),
    ('GeologyComment', 'comments', 6),
    ('Lith1_Code', 'lithology', 0), ('Lith2_Code', 'lithology_2', 0),
    ('Lith1_Colour1', 'colour', 10), ('Lith1_Texture', 'texture', 10),
    ('Lith1_Structure', 'structure', 10),
]
MAPPING = [{'name': name, 'target': target, 'priority': priority} for name,target,priority in ALIASES]


def expand(frame, raw_parents, raw_attributes):
    """Preserve parents and every attribute record in a single canonical table."""
    parents = frame.copy()
    parents['_source_interval_id'] = raw_parents.iloc[parents['source_row_index']]['Id'].to_numpy()
    attributes = raw_attributes.rename(columns={
        'DHGeologyId': 'parent_id', 'Id': 'attribute_id', 'AttributeColumn': 'name',
        'AttributeValue': 'value', 'ModifiedDate': 'modified_date',
        'ModifiedBy': 'modified_by', 'MRTDetailId': 'mrt_detail_id'})
    result = baselode.datamodel.attributes.promote_attributes(
        parents, attributes, MAPPING, FIELDS, parent_key='_source_interval_id')
    # Compatibility alias for current categorical plotting consumers.
    result['geology_code'] = result['lithology']
    # Non-promoted source parent fields also remain in the same JSON expansion.
    source_records = [{k:baselode.datamodel.attributes.json_scalar(v) for k,v in row.items()}
                      for row in raw_parents.iloc[result['source_row_index']].to_dict('records')]
    payloads = []
    for original_extra, source_row in zip(result['attributes_extra'], source_records):
        extra = json.loads(original_extra)
        extra['_source_record'] = source_row
        payloads.append(json.dumps(extra, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')))
    result['attributes_extra'] = pd.array(payloads, dtype='string')
    retained = sum(len(json.loads(v).get('_attribute_records', [])) for v in result['attributes_extra'])
    if retained != len(raw_attributes):
        raise ValueError('Geology attribute source accounting failed')
    return result, {'input_rows': len(raw_attributes), 'retained_attribute_records': retained,
                    'status': 'complete' if retained else 'empty', 'mapping': MAPPING,
                    'promoted_nonnull_rows': {f:int(result[f].notna().sum()) for f in FIELDS},
                    'intervals_with_clashes': int((result['attribute_clash_count'] > 0).sum()),
                    'clash_fields': int(result['attribute_clash_count'].sum()),
                    'json_encoding': 'UTF-8 JSON text; parse as JSONB when loading PostgreSQL',
                    'source_record_columns': list(raw_parents.columns)}
