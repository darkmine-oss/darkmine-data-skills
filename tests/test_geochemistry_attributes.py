# Copyright (C) 2026 Darkmine Pty Ltd.

import json

import pandas as pd
import pytest
from darkmine_data_skills.gswa import audit_conversion, geochemistry_attributes


def write_raw(tmp_path, attributes, parents=None):
    raw = tmp_path / 'raw'
    raw.mkdir()
    pd.DataFrame({'Id': [1, 2], 'HoleId': ['H', 'H']}).to_parquet(raw / 'dbo_collar.parquet')
    if parents is None:
        parents = pd.DataFrame({'Id': [10, 11, 12], 'CollarId': [1, 1, 2],
            'SampleId': ['S', 'S', 'T'], 'CompanySampleId': ['C', 'C', None],
            'FromDepth': [0.123456789012345, 0.123456789012345, 5.],
            'ToDepth': [1., 1., None], 'Units': [None, 'm', None], 'MRTFileId': [8, 8, 9]})
    parents.to_parquet(raw / 'dbo_dhgeochemistry.parquet')
    if attributes is not None:
        attributes.to_parquet(raw / 'dbo_dhgeochemistryattr.parquet')
    return raw, parents


def attrs(names, values, ppm, parents=None, **flags):
    return pd.DataFrame({'Id': list(range(1, len(names) + 1)),
        'DHGeochemistryId': parents if parents is not None else [10] * len(names),
        'AttributeColumn': names, 'AttributeValue': values, 'PPMValue': ppm,
        'MRTDetailId': [100 + i for i in range(len(names))], **flags})


def test_full_source_grain_and_qualifiers_do_not_use_publisher_flat(tmp_path):
    a = attrs(['Cu_pct', 'Au_ppb', 'Cu +/-', 'Cu_ME-MS61r_ppm', 'Cu', 'Sample_Type', 'Superseded'],
              ['0.0006', '1000', '999', '777', '<3', 'CORE', '-1'],
              [6.000000476837158, 1., 999., 777., -3., None, None],
              parents=[10, 10, 10, 10, 11, 11, 11],
              Flag_LT=[None, False, None, False, True, None, None],
              Flag_PCT=[False, False, None, None, False, None, None])
    raw, parents = write_raw(tmp_path, a)
    pd.DataFrame({'Id': [10], 'Collarid': [1], 'FromDepth': [0.], 'ToDepth': [1.],
                  'Cu_PPM': [12345.]}).to_parquet(raw / 'gsd_dhassayflat.parquet')
    before = {p.name: p.read_bytes() for p in raw.glob('*.parquet')}
    output = tmp_path / 'output'
    manifest = audit_conversion.convert(raw, output)
    frame = pd.read_parquet(output / 'assays.parquet')
    assert len(frame) == 3
    assert frame['_source_geochemistry_interval_id'].tolist() == [10, 11, 12]
    assert frame.sample_id.tolist() == ['S', 'S', 'T']
    assert frame.hole_id.tolist() == ['H', 'H', 'H']
    pd.testing.assert_series_equal(frame['from'], parents.FromDepth, check_names=False)
    pd.testing.assert_series_equal(frame['to'], parents.ToDepth, check_names=False)
    assert frame.loc[0, 'cu_ppm'] == 6.000000476837158
    assert frame.loc[0, 'au_ppm'] == 1.
    assert pd.isna(frame.loc[1, 'cu_ppm'])
    assert frame.loc[1, 'sample_type'] == 'CORE'
    assert frame.loc[1, 'superseded'] == '-1'
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['_source_record']['FromDepth'] == parents.loc[0, 'FromDepth']
    assert len(extra['_attribute_records']) == 4
    assert extra['_attribute_records'][0]['value'] == '0.0006'
    assert extra['_attribute_records'][0]['Flag_PCT'] is False
    assert extra['_attribute_records'][0]['Flag_LT'] is None
    assert extra['_assay_selection']['cu_ppm']['eligible_attribute_ids'] == [1]
    assert json.loads(frame.loc[2, 'attributes_extra'])['_attribute_records'] == []
    info = manifest['tables']['assays']
    assert info['source'] == 'dbo_dhgeochemistry'
    assert info['geochemistry_conversion']['retained_attribute_records'] == 7
    assert manifest['sources']['gsd_dhassayflat']['converted_to'] == []
    assert manifest['sources']['dbo_dhgeochemistryattr']['converted_to'] == ['assays']
    assert {p.name: p.read_bytes() for p in raw.glob('*.parquet')} == before


def test_conflicts_remain_null_and_equal_results_agree(tmp_path):
    a = attrs(['Cu', 'Cu_ppm', 'Au', 'Au_ppb'], ['6', '7', '1', '1000'], [6., 7., 1., 1.])
    raw, _ = write_raw(tmp_path, a)
    audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert pd.isna(frame.loc[0, 'cu_ppm'])
    assert frame.loc[0, 'au_ppm'] == 1.
    assert frame.loc[0, 'attribute_clash_count'] == 1
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['_assay_selection']['cu_ppm']['status'] == 'conflict'
    assert len(extra['_conflicts']['cu_ppm']) == 2
    assert extra['_assay_selection']['au_ppm']['eligible_attribute_ids'] == [3, 4]


@pytest.mark.parametrize('flag', geochemistry_attributes.EXCLUSION_FLAGS)
def test_qualified_or_flagged_numbers_are_not_exact_grade_projections(tmp_path, flag):
    raw, _ = write_raw(tmp_path, attrs(['Cu'], ['10'], [10.], **{flag: [True]}))
    audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert pd.isna(frame.loc[0, 'cu_ppm'])
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['_attribute_records'][0][flag] is True
    assert flag in extra['_assay_selection']['cu_ppm']['candidates'][0]['exclusion_reasons']


@pytest.mark.parametrize('value', [None, float('inf'), float('-inf')])
def test_missing_nonfinite_values_do_not_parse_original_text_as_ppm(tmp_path, value):
    raw, _ = write_raw(tmp_path, attrs(['Cu_pct'], ['50'], [value]))
    audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert pd.isna(frame.loc[0, 'cu_ppm'])
    record = json.loads(frame.loc[0, 'attributes_extra'])['_attribute_records'][0]
    assert record['value'] == '50'
    if value is not None:
        assert record['PPMValue']['__type__'] == 'float'


def test_complete_parent_chunks_are_independent_of_child_order_and_chunk_size(tmp_path):
    raw, parents = write_raw(tmp_path, attrs(['Cu', 'Cu', 'Cu', 'Cu_pct'],
        ['6', '8', '2', '0.0002'], [6., 8., 2., 2.], parents=[10, 10, 11, 11]))
    frame = pd.DataFrame({'hole_id': ['H']*3, 'from': parents.FromDepth, 'to': parents.ToDepth,
        'units': parents.Units, 'source_row_index': [0, 1, 2], 'source_table': ['dbo_dhgeochemistry']*3})
    for name, size in [('small', 1), ('large', 3)]:
        path = tmp_path / name
        path.mkdir()
        geochemistry_attributes.write(frame, parents, raw / 'dbo_dhgeochemistryattr.parquet', path, chunk_size=size)
    original = pd.read_parquet(tmp_path / 'small' / 'assays.parquet')
    pd.testing.assert_frame_equal(original, pd.read_parquet(tmp_path / 'large' / 'assays.parquet'))
    reversed_attrs = pd.read_parquet(raw / 'dbo_dhgeochemistryattr.parquet').iloc[::-1]
    reversed_attrs.to_parquet(raw / 'dbo_dhgeochemistryattr.parquet')
    path = tmp_path / 'reversed'
    path.mkdir()
    geochemistry_attributes.write(frame, parents, raw / 'dbo_dhgeochemistryattr.parquet', path, chunk_size=2)
    pd.testing.assert_frame_equal(original, pd.read_parquet(path / 'assays.parquet'))


@pytest.mark.parametrize('failure', ['duplicate_parent', 'duplicate_attribute', 'null_attribute',
                                   'orphan_attribute', 'invalid_flag'])
def test_malformed_source_contract_leaves_incomplete_marker(tmp_path, failure):
    a = attrs(['Cu', 'Cu'], ['1', '2'], [1., 2.])
    if failure == 'duplicate_attribute': a.Id = [1, 1]
    if failure == 'null_attribute': a.Id = pd.Series([1, None], dtype='Int64')
    if failure == 'orphan_attribute': a.DHGeochemistryId = [10, 999]
    if failure == 'invalid_flag': a['Flag_LT'] = ['False', 'True']
    raw, parents = write_raw(tmp_path, a)
    if failure == 'duplicate_parent':
        parents.Id = [10, 10, 12]
        parents.to_parquet(raw / 'dbo_dhgeochemistry.parquet')
    out = tmp_path / 'out'
    with pytest.raises(ValueError):
        audit_conversion.convert(raw, out)
    assert (out / '.conversion-incomplete').exists()
    assert not (out / 'conversion_manifest.json').exists()


def test_no_attributes_and_absent_end_column_keep_original_parent_rows(tmp_path):
    parents = pd.DataFrame({'Id': [10], 'Collarid': [1], 'FromDepth': [3.]})
    raw, _ = write_raw(tmp_path, None, parents)
    manifest = audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert 'to' not in frame
    assert frame['_source_collar_id'].tolist() == [1]
    assert frame.cu_ppm.isna().all()
    assert manifest['tables']['assays']['geochemistry_conversion']['retained_attribute_records'] == 0


def test_empty_parent_table_has_typed_outputs(tmp_path):
    parents = pd.DataFrame({'Id': pd.Series(dtype='int64'), 'CollarId': pd.Series(dtype='int64'),
                            'FromDepth': pd.Series(dtype='float64')})
    raw, _ = write_raw(tmp_path, None, parents)
    audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert frame.empty and 'cu_ppm' in frame and 'attributes_extra' in frame
