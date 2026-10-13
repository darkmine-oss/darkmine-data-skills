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



@pytest.mark.parametrize('empty_attributes', [False, True])
def test_flat_results_with_missing_raw_attributes_are_explicitly_incomplete(tmp_path, empty_attributes):
    raw, _ = write_raw(tmp_path, attrs(['Cu'], ['1'], [1.]).iloc[:0] if empty_attributes else None)
    pd.DataFrame({'Id': [999], 'Collarid': [1], 'FromDepth': [0.], 'ToDepth': [1.],
                  'Cu_PPM': [10.]}).to_parquet(raw / 'gsd_dhassayflat.parquet')
    output = tmp_path / 'out'
    with pytest.raises(ValueError, match='require dbo_dhgeochemistryattr'):
        audit_conversion.convert(raw, output)
    assert (output / '.conversion-incomplete').exists()
    assert not (output / 'conversion_manifest.json').exists()


def test_non_boolean_flags_on_unmapped_labels_are_rejected(tmp_path):
    raw, _ = write_raw(tmp_path, attrs(['Cu +/-'], ['4'], [None], Flag_LT=['True']))
    with pytest.raises(ValueError, match='boolean or null'):
        audit_conversion.convert(raw, tmp_path / 'out')


def test_company_sample_identifier_has_one_flat_column(tmp_path):
    raw, _ = write_raw(tmp_path, attrs(['Cu'], ['1'], [1.]))
    manifest = audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    assert 'company_sample_id' in frame and 'datasource_sample_id' not in frame
    assert manifest['tables']['assays']['mapping']['CompanySampleId'] == 'company_sample_id'



def test_empty_parents_do_not_displace_available_flat_assays(tmp_path):
    parents = pd.DataFrame({'Id': pd.Series(dtype='int64'), 'CollarId': pd.Series(dtype='int64'),
                            'FromDepth': pd.Series(dtype='float64')})
    raw, _ = write_raw(tmp_path, None, parents)
    pd.DataFrame({'Id': [999], 'Collarid': [1], 'FromDepth': [0.], 'ToDepth': [1.],
                  'Cu_PPM': [10.]}).to_parquet(raw / 'gsd_dhassayflat.parquet')
    manifest = audit_conversion.convert(raw, tmp_path / 'out')
    assert manifest['tables']['assays']['source'] == 'gsd_dhassayflat'
    assert pd.read_parquet(tmp_path / 'out' / 'assays.parquet').Cu_PPM.tolist() == [10.]


def test_nullable_source_collar_identity_is_stable_across_all_null_first_batch(tmp_path):
    parents = pd.DataFrame({'Id': [10, 11], 'CollarId': pd.Series([None, 9007199254740993], dtype='Int64'),
                            'FromDepth': [0., 1.]})
    raw, _ = write_raw(tmp_path, None, parents)
    frame = pd.DataFrame({'hole_id': pd.Series([None, 'H'], dtype='string'), 'from': [0., 1.],
        'source_row_index': [0, 1], 'source_table': ['dbo_dhgeochemistry']*2})
    output = tmp_path / 'out'
    output.mkdir()
    geochemistry_attributes.write(frame, parents, None, output, chunk_size=1)
    result = pd.read_parquet(output / 'assays.parquet')
    assert pd.isna(result.loc[0, '_source_collar_id'])
    assert result.loc[1, '_source_collar_id'] == 9007199254740993
    assert str(result['_source_collar_id'].dtype) == 'Int64'


def test_error_and_assay_convenience_values_keep_exact_names(tmp_path):
    raw, _ = write_raw(tmp_path, attrs(['Cu', 'Cu +/-'], ['10', '1'], [10., None]))
    audit_conversion.convert(raw, tmp_path / 'out')
    frame = pd.read_parquet(tmp_path / 'out' / 'assays.parquet')
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['_unmapped_attributes']['Cu'] == '10'
    assert extra['_unmapped_attributes']['Cu +/-'] == '1'
    assert 'cu' not in extra
    assert frame.loc[0, 'cu_ppm'] == 10.



def test_nonempty_attributes_with_empty_parents_fail_before_flat_fallback(tmp_path):
    parents = pd.DataFrame({'Id': pd.Series(dtype='int64'), 'CollarId': pd.Series(dtype='int64'),
                            'FromDepth': pd.Series(dtype='float64')})
    raw, _ = write_raw(tmp_path, attrs(['Cu'], ['1'], [1.]), parents)
    pd.DataFrame({'Id': [999], 'Collarid': [1], 'FromDepth': [0.], 'ToDepth': [1.],
                  'Cu_PPM': [10.]}).to_parquet(raw / 'gsd_dhassayflat.parquet')
    with pytest.raises(ValueError, match='require source parent records'):
        audit_conversion.convert(raw, tmp_path / 'out')
    assert (tmp_path / 'out' / '.conversion-incomplete').exists()


def test_arrow_export_without_pandas_metadata_keeps_nullable_integer_evidence(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    large = 9007199254740993
    raw, _ = write_raw(tmp_path, None)
    # Construct with Arrow directly: pandas metadata must not be required.
    table = pa.table({'Id': pa.array([10, 11], type=pa.int64()),
        'CollarId': pa.array([None, large], type=pa.int64()),
        'FromDepth': [0., 1.], 'MRTFileId': pa.array([None, large], type=pa.int64())})
    assert not table.schema.metadata
    pq.write_table(table, raw / 'dbo_dhgeochemistry.parquet')
    pd.DataFrame({'Id': [large], 'HoleId': ['H']}).to_parquet(raw / 'dbo_collar.parquet')
    output = tmp_path / 'out'
    audit_conversion.convert(raw, output)
    result = pd.read_parquet(output / 'assays.parquet')
    assert str(result['_source_collar_id'].dtype) == 'Int64'
    assert pd.isna(result.loc[0, '_source_collar_id'])
    assert result.loc[1, '_source_collar_id'] == large
    assert result.loc[1, 'hole_id'] == 'H'
    extra = json.loads(result.loc[1, 'attributes_extra'])
    assert extra['_source_record']['CollarId'] == large
    assert extra['_source_record']['MRTFileId'] == large
