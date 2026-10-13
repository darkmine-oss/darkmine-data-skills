# Copyright (C) 2026 Darkmine Pty Ltd.

import json
import pandas as pd
import pytest
from darkmine_data_skills.gswa import audit_conversion


def write_source(tmp_path, attrs=None, end_depth=True):
    raw = tmp_path / 'raw'
    raw.mkdir()
    # Repeated public hole identifiers must not expand a source-key join.
    pd.DataFrame({'Id': [1, 2], 'HoleId': ['H', 'H']}).to_parquet(raw / 'dbo_collar.parquet')
    parents = pd.DataFrame({'Id': [10, 11, 12], 'CollarId': [1, 1, 2],
                            'FromDepth': [0.123456789012345, 20., 20.], 'MRTFileId': [8, 9, 9]})
    if end_depth:
        parents['ToDepth'] = [71., None, None]
    parents.to_parquet(raw / 'dbo_dhstructure.parquet')
    if attrs is not None:
        attrs.to_parquet(raw / 'dbo_dhstructureattr.parquet')
    return raw, parents


def test_one_table_bounds_orientation_groups_and_all_evidence(tmp_path):
    attrs = pd.DataFrame({
        'Id': list(range(1, 12)), 'DHStructureId': [10]*8 + [11]*3,
        'AttributeColumn': ['Dip', 'Dip_Direction', 'Structure_Type', 'Structure_Origin',
                            'Comments', 'Plane_Dip', 'Computed_Plane_Dip', 'Material_Description',
                            'Alpha', 'Beta', 'Weathering'],
        'AttributeValue': ['-79.65', '137.94', 'FRA', '3', 'Logged comment', '58', '57',
                           'Original material description', '55', '360', 'W'],
        'MRTDetailId': [100]*11})
    raw, parents = write_source(tmp_path, attrs)
    before = {p.name: p.read_bytes() for p in raw.glob('*.parquet')}
    out = tmp_path / 'out'
    manifest = audit_conversion.convert(raw, out)
    frame = pd.read_parquet(out / 'structure.parquet')
    assert len(frame) == 3
    assert frame['_source_structure_id'].tolist() == [10, 11, 12]
    assert frame['_source_collar_id'].tolist() == [1, 1, 2]
    assert frame.hole_id.tolist() == ['H', 'H', 'H']
    pd.testing.assert_series_equal(frame['from'], parents.FromDepth, check_names=False)
    pd.testing.assert_series_equal(frame['to'], parents.ToDepth, check_names=False)
    pd.testing.assert_series_equal(frame.depth, parents.FromDepth, check_names=False)
    assert frame.loc[0, 'dip'] == -79.65
    assert frame.loc[0, 'azimuth'] == 137.94
    assert pd.isna(frame.loc[1, 'dip'])
    assert frame.loc[1, 'beta'] == 360
    assert frame.loc[0, 'structure_type'] == 'FRA'
    assert frame.loc[0, 'comments'] == 'Logged comment'
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['plane_dip'] == '58'
    assert extra['computed_plane_dip'] == '57'
    assert extra['material_description'] == 'Original material description'
    assert extra['_source_record']['FromDepth'] == parents.loc[0, 'FromDepth']
    assert len(extra['_attribute_records']) == 8
    assert json.loads(frame.loc[2, 'attributes_extra'])['_attribute_records'] == []
    coverage = manifest['tables']['structure']['joined_source_coverage']['dbo_dhstructureattr']
    assert coverage['retained_attribute_records'] == 11
    assert coverage['complete_dip_azimuth_rows'] == 1
    assert coverage['complete_alpha_beta_rows'] == 1
    assert coverage['missing_end_depth_rows'] == 2
    assert manifest['sources']['dbo_dhstructureattr']['converted_to'] == ['structure']
    assert not (out / 'structure_attributes.parquet').exists()
    assert {p.name: p.read_bytes() for p in raw.glob('*.parquet')} == before


@pytest.mark.parametrize('value', ['bad', 'NaN', 'Infinity', '1e999'])
def test_numeric_parse_failures_remain_evidence(tmp_path, value):
    attrs = pd.DataFrame({'Id': [1], 'DHStructureId': [10],
                          'AttributeColumn': ['Dip'], 'AttributeValue': [value]})
    raw, _ = write_source(tmp_path, attrs)
    out = tmp_path / 'out'
    manifest = audit_conversion.convert(raw, out)
    frame = pd.read_parquet(out / 'structure.parquet')
    assert pd.isna(frame.loc[0, 'dip'])
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['_attribute_records'][0]['value'] == value
    assert extra['_numeric_parse_issues'][0]['selected_text'] == value
    assert manifest['tables']['structure']['joined_source_coverage']['dbo_dhstructureattr']['numeric_parse_failures'] == 1


def test_absent_end_depth_and_attribute_table_are_not_fabricated(tmp_path):
    raw, parents = write_source(tmp_path, end_depth=False)
    out = tmp_path / 'out'
    manifest = audit_conversion.convert(raw, out)
    frame = pd.read_parquet(out / 'structure.parquet')
    assert 'to' not in frame
    assert frame.depth.tolist() == parents.FromDepth.tolist()
    assert frame.dip.isna().all()
    assert manifest['tables']['structure']['joined_sources'] == []


def test_alias_collision_keeps_ranked_source_candidates(tmp_path):
    attrs = pd.DataFrame({'Id': [1, 2], 'DHStructureId': [10, 10],
                          'AttributeColumn': ['Dip_Direction', 'DipDirection'],
                          'AttributeValue': ['090', '180']})
    raw, _ = write_source(tmp_path, attrs)
    out = tmp_path / 'out'
    audit_conversion.convert(raw, out)
    frame = pd.read_parquet(out / 'structure.parquet')
    assert frame.loc[0, 'azimuth'] == 90
    assert frame.loc[0, 'attribute_clash_count'] == 1
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert len(extra['_conflicts']['azimuth']) == 2
    assert extra['_conflicts']['azimuth'][0]['selected'] is True


@pytest.mark.parametrize('failure', ['orphan_attribute', 'duplicate_parent', 'duplicate_attribute',
                                     'null_parent', 'null_attribute', 'numeric_mapped_value'])
def test_bad_structure_identities_are_explicitly_incomplete(tmp_path, failure):
    attrs = pd.DataFrame({'Id': [1, 2], 'DHStructureId': [10, 10],
                          'AttributeColumn': ['Dip', 'Dip_Direction'], 'AttributeValue': ['45', '90']})
    if failure == 'orphan_attribute': attrs['DHStructureId'] = [10, 999]
    if failure == 'duplicate_attribute': attrs['Id'] = [1, 1]
    if failure == 'null_attribute': attrs['Id'] = pd.Series([1, None], dtype='Int64')
    if failure == 'numeric_mapped_value': attrs['AttributeValue'] = [45., 90.]
    raw, parents = write_source(tmp_path, attrs)
    if failure == 'duplicate_parent': parents['Id'] = [10, 10, 12]
    if failure == 'null_parent': parents['Id'] = pd.Series([10, 11, None], dtype='Int64')
    parents.to_parquet(raw / 'dbo_dhstructure.parquet')
    out = tmp_path / 'out'
    with pytest.raises(ValueError):
        audit_conversion.convert(raw, out)
    assert (out / '.conversion-incomplete').exists()
    assert not (out / 'conversion_manifest.json').exists()


def test_orphan_attributes_without_parent_table_fail(tmp_path):
    raw, _ = write_source(tmp_path, pd.DataFrame({'Id': [1], 'DHStructureId': [10],
        'AttributeColumn': ['Dip'], 'AttributeValue': ['45']}))
    (raw / 'dbo_dhstructure.parquet').unlink()
    out = tmp_path / 'out'
    with pytest.raises(ValueError, match='parent'):
        audit_conversion.convert(raw, out)
    assert (out / '.conversion-incomplete').exists()


@pytest.mark.parametrize('end_depth', [True, False])
def test_preserved_structure_bounds_do_not_enable_continuous_interval_checks(tmp_path, end_depth):
    from darkmine_data_skills.validation import check_coverage
    raw, _ = write_source(tmp_path, end_depth=end_depth)
    out = tmp_path / 'out'
    audit_conversion.convert(raw, out)
    structure = pd.read_parquet(out / 'structure.parquet')
    result = check_coverage.validate(pd.DataFrame({'hole_id': ['H'], 'max_depth': [100.]}),
                                     None, {'structure': structure})
    assert result['complete'] is True
    assert not any(i['check'] == 'interval_invalid_bounds' and i['table'] == 'structure'
                   for i in result['issues'])
    interval_checks = [c for c in result['checks'] if c['table'] == 'structure' and
                       c['check'] in {'negative_lengths', 'intervals_beyond_max_depth',
                                      'interval_gaps', 'interval_overlaps'}]
    assert len(interval_checks) == 4 and all(c['status'] == 'skipped' for c in interval_checks)
    assert any(i['check'] == 'structure_coverage' for i in result['issues'])


def test_legacy_measured_aliases_preserve_specific_and_generic_meanings(tmp_path):
    attrs = pd.DataFrame({'Id': list(range(1, 8)), 'DHStructureId': [10]*7,
        'AttributeColumn': ['DipDrn', 'Dip_Direction', 'StructComment', 'Description',
                            'Type', 'Reliability', 'Dip_Calc'],
        'AttributeValue': ['180', '90', 'Original comment', 'Alternate description', 'F', '1', '40']})
    raw, _ = write_source(tmp_path, attrs)
    out = tmp_path / 'out'
    audit_conversion.convert(raw, out)
    frame = pd.read_parquet(out / 'structure.parquet')
    assert frame.loc[0, 'azimuth'] == 90
    assert frame.loc[0, 'comments'] == 'Original comment'
    assert pd.isna(frame.loc[0, 'origin_reliability'])
    assert pd.isna(frame.loc[0, 'dip'])
    extra = json.loads(frame.loc[0, 'attributes_extra'])
    assert extra['reliability'] == '1' and extra['type'] == 'F' and extra['dip_calc'] == '40'
    assert len(extra['_conflicts']['azimuth']) == 2
    assert len(extra['_conflicts']['comments']) == 2
