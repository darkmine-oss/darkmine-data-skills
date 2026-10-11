# Copyright (C) 2026 Darkmine Pty Ltd.

import json

import pandas as pd
import pytest

import darkmine_data_skills
import darkmine_data_skills.gswa.audit_conversion
import darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode
import darkmine_data_skills.validation.check_coverage
import darkmine_data_skills.validation.validate_drillholes


@pytest.fixture(params=['2025-10', '2026-05'])
def source_release(tmp_path, request):
    raw = tmp_path / 'raw'
    raw.mkdir()
    pd.DataFrame([{
        'Id': 1, 'HoleId': 'H1', 'CompanyHoleId': 'CompanyH1',
        'Latitude': -30.0, 'Longitude': 120.0, 'Elevation': 300.0,
        'MaxDepth': 10.0,
    }]).to_parquet(raw / 'dbo_collar.parquet', index=False)
    pd.DataFrame([{
        'Id': 100, 'SampleId': 'S1', 'Latitude': -30.0, 'Longitude': 120.0,
    }]).to_parquet(raw / 'dbo_surfacesample.parquet', index=False)
    new = request.param == '2026-05'
    oxide = 'SiO2_PCT' if new else 'SiO2_PPM'
    value = 50.0 if new else 500000.0
    flat = {
        'Id': 100 if new else 999, 'Fe_PPM': 13.5, oxide: value,
        'Au_GT': 1.2, 'SourceNote': 'publisher value',
        # These coordinates must not become element/analyte columns.
        'X': 123.0, 'Y': 456.0, 'Z': 789.0,
    }
    if not new:
        flat['SurfaceSampleId'] = 100
    # Preserve repeated source analyses, even when downstream QAQC must flag them.
    pd.DataFrame([flat, flat]).to_parquet(raw / 'gsd_ssassayflat.parquet', index=False)
    drill = {
        'Id': 9999, 'Collarid': 1, 'CompanyHoleId': 'CompanyH1',
        'FromDepth': 0.0, 'ToDepth': 1.0, 'Fe_PPM': 13.5, oxide: value,
        'Y_PPM': 2.0, 'Y': 456.0, 'X': 123.0, 'Z': 789.0,
        'CollarLatitude' if new else 'Latitude': -30.0,
        'CollarLongitude' if new else 'Longitude': 120.0,
        'DIP' if new else 'Dip': -90.0, 'Lithology': 'granite',
        'Au_GT': 1.2, 'Dataset': 'Example', 'Anumber': 123,
    }
    pd.DataFrame([drill]).to_parquet(raw / 'gsd_dhassayflat.parquet', index=False)
    return raw, oxide, value


def test_audit_conversion_preserves_surface_join_values_and_duplicates(source_release, tmp_path):
    raw, oxide, value = source_release
    checksums = {path.name: path.read_bytes() for path in raw.glob('*.parquet')}
    out = tmp_path / 'audit'
    manifest = darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    surface = pd.read_parquet(out / 'surface_samples.parquet')
    assert surface['sample_id'].tolist() == ['S1', 'S1']
    assert surface['Fe_PPM'].tolist() == [13.5, 13.5]
    assert surface[oxide].tolist() == [value, value]
    assert surface['source_assay_row_index'].tolist() == [0, 1]
    assert manifest['tables']['surface_samples']['joined_sources'] == ['gsd_ssassayflat']
    coverage = manifest['tables']['surface_samples']['joined_source_coverage']['gsd_ssassayflat']
    assert coverage['join_key'] == ('SurfaceSampleId' if oxide.endswith('_PPM') else 'Id')
    assert coverage['status'] == 'complete'
    assert coverage['matched_rows'] == 2 and coverage['unmatched_rows'] == 0
    assert coverage['mapping']['Fe_PPM'] == 'Fe_PPM'
    assert coverage['mapping'][oxide] == oxide
    assert {'Au_GT', 'SourceNote', 'X', 'Y', 'Z'} <= set(coverage['unmapped_columns'])
    assert not (out / '.conversion-incomplete').exists()
    assert 'gsd_ssassayflat' not in manifest['not_converted']
    assert manifest['converter_version'] == darkmine_data_skills.__version__
    assays = pd.read_parquet(out / 'assays.parquet')
    assert assays['Y_PPM'].tolist() == [2.0]
    assert assays[oxide].tolist() == [value]
    assert not {'X', 'Y', 'Z'} & set(assays.columns)
    assert not {'X', 'Y', 'Z'} & set(surface.columns)
    # Existing QAQC coverage is narrower than frontend display conversion.
    # Unsupported units/metadata must stay visible as unmapped source fields.
    assert {'Au_GT', 'Dataset', 'Anumber'} <= set(manifest['tables']['assays']['unmapped_columns'])
    assert 'Au_GT' not in assays.columns
    assert oxide not in manifest['tables']['assays']['unmapped_columns']
    assert 'Y_PPM' not in manifest['tables']['assays']['unmapped_columns']
    assert 'Collarid' not in manifest['tables']['assays']['unmapped_columns']
    assert {path.name: path.read_bytes() for path in raw.glob('*.parquet')} == checksums


def test_frontend_conversion_keeps_units_and_separates_spatial_context(source_release, tmp_path):
    raw, oxide, value = source_release
    out = tmp_path / 'frontend'
    converter = darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode
    converter.convert_project(raw, out, hole_id_source='baselode')
    assays = pd.read_parquet(out / 'assays.parquet')
    columns = {column.lower(): column for column in assays.columns}
    assert assays[columns[oxide.lower()]].tolist() == [value]
    assert assays[columns['fe_ppm']].tolist() == [13.5]
    assert assays[columns['y_ppm']].tolist() == [2.0]
    assert assays[columns['au_gt']].tolist() == [1.2]
    assert assays[columns['project_id']].tolist() == ['Example']
    assert assays[columns['anumber']].tolist() == [123]
    assert not {'x', 'y', 'z', 'latitude', 'collarlatitude'} & set(columns)
    assert assays[columns['geology_code']].tolist() == ['granite']
    assert assays[columns['dip']].tolist() == [-90.0]
    flattened = pd.read_parquet(out / 'flattened_gsd_dhassayflat.parquet')
    assert flattened['latitude'].tolist() == [-30.0]
    assert flattened['longitude'].tolist() == [120.0]
    assert flattened['dip'].tolist() == [-90.0]
    assert flattened['source_y'].tolist() == [456.0]
    assert flattened['y'].tolist() == [456.0]
    assert flattened['lithology'].tolist() == ['granite']
    assert flattened[oxide.lower()].tolist() == [value]
    manifest = json.loads((out / 'conversion_manifest.json').read_text())
    assert manifest['tables']['assays']['rows'] == 1


def test_surface_key_case_variant_beats_unrelated_id(source_release, tmp_path):
    raw, _, _ = source_release
    path = raw / 'gsd_ssassayflat.parquet'
    flat = pd.read_parquet(path).drop(columns=['SurfaceSampleId'], errors='ignore')
    flat['SurfaceSampleID'] = 100
    flat['Id'] = 999
    flat.to_parquet(path, index=False)
    out = tmp_path / 'case-variant'
    darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert pd.read_parquet(out / 'surface_samples.parquet')['Fe_PPM'].tolist() == [13.5, 13.5]


def test_ambiguous_surface_keys_fail_instead_of_guessing(source_release, tmp_path):
    raw, _, _ = source_release
    path = raw / 'gsd_ssassayflat.parquet'
    flat = pd.read_parquet(path)
    flat['SurfaceSampleID'] = 100
    flat['SurfaceSampleId'] = 101
    flat.to_parquet(path, index=False)
    with pytest.raises(ValueError, match='Ambiguous surface sample keys'):
        darkmine_data_skills.gswa.audit_conversion.convert(raw, tmp_path / 'ambiguous')


@pytest.mark.parametrize('reverse', [False, True])
def test_mixed_coordinate_aliases_are_order_independent(tmp_path, reverse):
    frame = pd.DataFrame([{
        'Id': 1, 'Latitude': -30.0, 'CollarLatitude': -31.0,
        'Longitude': 120.0, 'CollarLongitude': 121.0, 'Dip': -90.0, 'DIP': -85.0,
    }])
    if reverse:
        frame = frame[frame.columns[::-1]]
    frame.to_parquet(tmp_path / 'gsd_dhassayflat.parquet', index=False)
    result = darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode.flatten_raw_table(
        tmp_path, 'gsd_dhassayflat', pd.DataFrame(), hole_id_source='baselode',
    )
    expected = {'latitude': -30.0, 'collar_latitude': -31.0,
                'longitude': 120.0, 'collar_longitude': 121.0,
                'dip': -90.0, 'source_dip': -85.0}
    assert result[list(expected)].iloc[0].to_dict() == expected


def test_synthetic_check_reports_running_package_version():
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.DataFrame({'hole_id': ['H1']}), None, {},
    )
    custom = [check for check in result['checks'] if check['engine'] == 'darkmine-data-skills']
    assert custom
    assert all(check['version'] == darkmine_data_skills.__version__ for check in custom)


@pytest.mark.parametrize('hole_id_source', [None, 'baselode', 'company'])
def test_preserve_issues_cli_hole_identity_is_explicit(source_release, tmp_path, hole_id_source):
    raw, _, _ = source_release
    out = tmp_path / 'identity'
    args = [str(raw), str(out), '--preserve-issues']
    if hole_id_source:
        args += ['--hole-id-source', hole_id_source]
    converter = darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode
    if hole_id_source == 'company':
        with pytest.raises(SystemExit, match='requires --hole-id-source baselode'):
            converter.main(args)
        assert not out.exists()
    else:
        assert converter.main(args) == 0
        manifest = json.loads((out / 'conversion_manifest.json').read_text())
        assert manifest['options']['hole_id_source'] == 'baselode'
        assert pd.read_parquet(out / 'collars.parquet')['hole_id'].tolist() == ['H1']


def test_conversion_refuses_stale_outputs_without_removing_them(source_release, tmp_path):
    raw, _, _ = source_release
    out = tmp_path / 'stale'
    out.mkdir()
    stale = out / 'structure.parquet'
    stale.write_bytes(b'previous conversion')
    with pytest.raises(ValueError, match='empty output directory'):
        darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert stale.read_bytes() == b'previous conversion'
    assert list(out.iterdir()) == [stale]


def test_null_parent_identity_is_preserved_and_flagged_not_called_orphan(tmp_path):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    pd.DataFrame({'Id': [1], 'HoleId': [None]}).to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame({'Id': [10, 11], 'CollarId': [1, 2], 'FromDepth': [0.0, 0.0],
                  'ToDepth': [1.0, 1.0]}).to_parquet(raw / 'dbo_dhgeochemistry.parquet')
    darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    collar = pd.read_parquet(out / 'collars.parquet')
    assays = pd.read_parquet(out / 'assays.parquet')
    assert pd.isna(assays.iloc[0]['hole_id'])
    assert assays.iloc[1]['hole_id'] == 'gswa:orphan-collar:2'
    result = darkmine_data_skills.validation.check_coverage.validate(collar, None, {'assays': assays})
    assert any(issue['check'] == 'missing_hole_id' for issue in result['issues'])
    orphans = [issue for issue in result['issues'] if issue['check'] == 'orphan_intervals']
    assert len(orphans) == 1
    assert orphans[0]['hole_id'] == 'gswa:orphan-collar:2'


@pytest.mark.parametrize('table', ['collar', 'survey', 'assays'])
def test_present_table_missing_required_columns_is_incomplete(table, tmp_path):
    collar = pd.DataFrame({'hole_id': ['H1']})
    survey = pd.DataFrame({'hole_id': ['H1'], 'depth': [0], 'azimuth': [0], 'dip': [-90]})
    intervals = {'assays': pd.DataFrame({'hole_id': ['H1'], 'from': [0], 'to': [1]})}
    if table == 'collar':
        collar = collar.rename(columns={'hole_id': 'HoleID'})
    elif table == 'survey':
        survey = survey.drop(columns='dip')
    else:
        intervals['assays'] = intervals['assays'].drop(columns='to')
    result = darkmine_data_skills.validation.check_coverage.validate(collar, survey, intervals)
    assert result['complete'] is False
    assert any(check['status'] == 'failed' and check['table'] == table for check in result['checks'])
    assert all(check['status'] == 'skipped' for check in result['checks'] if check['table'] == 'structure')
    collar.to_parquet(tmp_path / 'collars.parquet')
    survey.to_parquet(tmp_path / 'survey.parquet')
    intervals['assays'].to_parquet(tmp_path / 'assays.parquet')
    validator = darkmine_data_skills.validation.validate_drillholes
    assert validator.main([str(tmp_path), str(tmp_path / 'qa'), '--no-print-summary']) == 2
    report = json.loads((tmp_path / 'qa/drillhole_validation_report.json').read_text())
    assert report['complete'] is False


def test_empty_flat_table_does_not_hide_populated_intervals(tmp_path):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    pd.DataFrame({'Id': [1], 'HoleId': ['H1']}).to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame(columns=['Id', 'Collarid', 'FromDepth', 'ToDepth', 'Au_PPM']).to_parquet(raw / 'gsd_dhassayflat.parquet')
    pd.DataFrame({'Id': [10], 'CollarId': [1], 'FromDepth': [2.0], 'ToDepth': [1.0]}).to_parquet(raw / 'dbo_dhgeochemistry.parquet')
    manifest = darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert manifest['tables']['assays']['source'] == 'dbo_dhgeochemistry'
    assert manifest['tables']['assays']['rows'] == 1
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.read_parquet(out / 'collars.parquet'), None,
        {'assays': pd.read_parquet(out / 'assays.parquet')},
    )
    assert any(issue['check'] == 'negative_lengths' for issue in result['issues'])


def test_point_structure_is_explicitly_outside_interval_coverage():
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.DataFrame({'hole_id': ['H1']}), None,
        {'structure': pd.DataFrame({'hole_id': ['H1'], 'depth': [1.0], 'dip': [10.0]})},
    )
    assert result['complete'] is True
    structure = [check for check in result['checks'] if check['table'] == 'structure'
                 and check['check'] not in {'structure_coverage', 'missing_hole_id', 'orphan_intervals', 'below_detection_limit'}]
    assert structure and all(check['status'] == 'skipped' for check in structure)
    assert all('Point-model' in check['reason'] for check in structure)
    assert any(issue['check'] == 'structure_coverage' for issue in result['issues'])


def test_invalid_interval_bounds_are_flagged_without_modifying_rows():
    frame = pd.DataFrame({'hole_id': ['H1'] * 4, 'from': [0.0, 1.0, None, 0.0],
                          'to': [float('inf'), float('-inf'), 3.0, 'bad']})
    original = frame.copy(deep=True)
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.DataFrame({'hole_id': ['H1'], 'max_depth': [100.0]}), None, {'assays': frame},
    )
    invalid = [issue for issue in result['issues'] if issue['check'] == 'interval_invalid_bounds']
    assert [issue['row_index'] for issue in invalid] == [0, 1, 2, 3]
    assert all(issue['severity'] == 'error' for issue in invalid)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize('null_collar_key', [False, True])
def test_missing_parent_keys_remain_distinct_from_known_orphans(tmp_path, null_collar_key):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    collars = pd.DataFrame({'Id': [1], 'HoleId': ['H1']})
    if null_collar_key:
        collars = pd.concat([collars, pd.DataFrame({'Id': [None], 'HoleId': ['Unknown']})], ignore_index=True)
    collars.to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame({'Id': [10, 11, 12], 'CollarId': [None, None, 2.0],
                  'FromDepth': [0.0, 0.0, 0.0], 'ToDepth': [1.0, 1.0, 1.0]}).to_parquet(
        raw / 'dbo_dhgeochemistry.parquet')
    darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assays = pd.read_parquet(out / 'assays.parquet')
    assert assays['hole_id'].isna().tolist() == [True, True, False]
    assert assays.iloc[2]['hole_id'] == 'gswa:orphan-collar:2'
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.read_parquet(out / 'collars.parquet'), None, {'assays': assays},
    )
    missing = [issue for issue in result['issues'] if issue['check'] == 'missing_hole_id']
    assert [issue['row_index'] for issue in missing] == [0, 1]
    assert all(issue['table'] == 'assays' for issue in missing)
    assert not any(issue['check'] == 'interval_overlaps' for issue in result['issues'])
    orphans = [issue for issue in result['issues'] if issue['check'] == 'orphan_intervals']
    assert len(orphans) == 1 and orphans[0]['hole_id'] == 'gswa:orphan-collar:2'


def test_failed_conversion_cannot_validate_partial_output(source_release, tmp_path):
    raw, _, _ = source_release
    path = raw / 'gsd_ssassayflat.parquet'
    flat = pd.read_parquet(path)
    flat['SurfaceSampleID'] = 100
    flat['SurfaceSampleId'] = 101
    flat.to_parquet(path, index=False)
    out, reports = tmp_path / 'partial', tmp_path / 'reports'
    with pytest.raises(ValueError, match='Ambiguous surface sample keys'):
        darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert (out / 'collars.parquet').exists()
    assert (out / '.conversion-incomplete').exists()
    assert not (out / 'conversion_manifest.json').exists()
    with pytest.raises(SystemExit) as stopped:
        darkmine_data_skills.validation.validate_drillholes.main([str(out), str(reports)])
    assert stopped.value.code == 2
    assert not reports.exists()


@pytest.mark.parametrize('join_key', ['Id', 'SurfaceSampleId'])
def test_null_surface_keys_do_not_attach_unrelated_analyses(tmp_path, join_key):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    pd.DataFrame({'Id': [1], 'HoleId': ['H1']}).to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame({'Id': [None, 100], 'SampleId': ['Unknown', 'S1']}).to_parquet(raw / 'dbo_surfacesample.parquet')
    pd.DataFrame({join_key: [None, None, 100, 999], 'Fe_PPM': [10.0, 20.0, 30.0, 40.0]}).to_parquet(raw / 'gsd_ssassayflat.parquet')
    original = (raw / 'gsd_ssassayflat.parquet').read_bytes()
    manifest = darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    coverage = manifest['tables']['surface_samples']['joined_source_coverage']['gsd_ssassayflat']
    assert coverage['status'] == 'partial'
    assert coverage['input_rows'] == 4 and coverage['matched_rows'] == 1
    assert coverage['unmatched_rows'] == 3
    assert coverage['null_key_rows'] == 2 and coverage['orphan_key_rows'] == 1
    assert coverage['unmatched_reason']
    assert (raw / 'gsd_ssassayflat.parquet').read_bytes() == original
    surface = pd.read_parquet(out / 'surface_samples.parquet')
    assert len(surface) == 2
    assert pd.isna(surface.iloc[0]['Fe_PPM'])
    assert pd.isna(surface.iloc[0]['source_assay_row_index'])
    assert surface.iloc[1]['Fe_PPM'] == 30.0
    assert surface.iloc[1]['source_assay_row_index'] == 2


def test_missing_interval_identity_uses_explicit_parent_without_overwriting_source(tmp_path):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    pd.DataFrame({'Id': [1], 'HoleId': ['H1']}).to_parquet(raw / 'dbo_collar.parquet')
    source = raw / 'dbo_dhgeochemistry.parquet'
    pd.DataFrame({'Id': [10], 'CollarId': [1], 'HoleId': [None],
                  'FromDepth': [0.0], 'ToDepth': [1.0]}).to_parquet(source)
    original = source.read_bytes()
    darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert pd.read_parquet(out / 'assays.parquet')['hole_id'].tolist() == ['H1']
    assert source.read_bytes() == original


def test_blank_id_rows_are_flagged_individually_not_grouped():
    collar = pd.DataFrame({'hole_id': ['', '', ' ', 'H1'], 'max_depth': [1.0] * 4})
    assays = pd.DataFrame({'hole_id': ['', '', ' '], 'from': [0.0] * 3, 'to': [2.0] * 3})
    result = darkmine_data_skills.validation.check_coverage.validate(collar, None, {'assays': assays})
    missing = [issue for issue in result['issues'] if issue['check'] == 'missing_hole_id']
    assert len(missing) == 6
    grouped = {'duplicate_hole_ids', 'orphan_intervals', 'interval_overlaps', 'intervals_beyond_max_depth'}
    assert not any(issue['check'] in grouped for issue in result['issues'])
    warnings = [issue for issue in result['issues'] if issue['check'] == 'survey_no_usable_stations']
    assert [issue['hole_id'] for issue in warnings] == ['H1']


@pytest.mark.parametrize('hole_id', ['H1', 123])
@pytest.mark.parametrize('first_hole,first_from', [('', 0.0), ('H1', None), (None, float('inf')), ('H1', '1_000')])
def test_overlap_references_point_to_input_rows_after_coverage_filtering(first_hole, first_from, hole_id):
    assays = pd.DataFrame({'hole_id': [None if not first_hole else hole_id, hole_id, hole_id],
                          'from': [first_from, 1.0, 0.0], 'to': [4.0, 3.0, 2.0],
                          'source_row_index': [100, 200, 300]}, index=[10, 20, 30])
    original = assays.copy(deep=True)
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.DataFrame({'hole_id': ['H1']}), None, {'assays': assays},
    )
    overlaps = [issue for issue in result['issues'] if issue['check'] == 'interval_overlaps']
    assert len(overlaps) == 1
    assert overlaps[0]['row_index'] == 2
    assert 'between rows 2 and 1' in overlaps[0]['message']
    individual = [issue for issue in result['issues']
                  if issue['check'] in {'missing_hole_id', 'interval_invalid_bounds'}]
    assert individual and all(issue['row_index'] == 0 for issue in individual)
    pd.testing.assert_frame_equal(assays, original)


def test_point_structures_keep_orphan_and_detection_limit_checks(tmp_path):
    collar = pd.DataFrame({'hole_id': ['H1']})
    structure = pd.DataFrame({'hole_id': ['Unknown'], 'depth': [1.0], 'measurement': ['<0.1']})
    result = darkmine_data_skills.validation.check_coverage.validate(collar, None, {'structure': structure})
    assert result['complete'] is True
    assert {'orphan_intervals', 'below_detection_limit'} <= {issue['check'] for issue in result['issues']}
    collar.to_parquet(tmp_path / 'collars.parquet')
    structure.to_parquet(tmp_path / 'structure.parquet')
    assert darkmine_data_skills.validation.validate_drillholes.main([str(tmp_path), '--no-print-summary']) == 1


def test_other_flattened_tables_keep_existing_xyz_columns(tmp_path):
    pd.DataFrame({'Id': [1], 'X': [100.0], 'Y': [200.0], 'Z': [300.0]}).to_parquet(tmp_path / 'dbo_surfacesample.parquet')
    output = darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode.flatten_raw_table(
        tmp_path, 'dbo_surfacesample', pd.DataFrame(), hole_id_source='baselode',
    )
    assert output[['x', 'y', 'z']].iloc[0].tolist() == [100.0, 200.0, 300.0]


@pytest.mark.parametrize('azimuth', [0.0, None])
@pytest.mark.parametrize('missing_id', [None, '', ' '])
def test_survey_missing_id_has_individual_error(missing_id, azimuth):
    survey = pd.DataFrame({'hole_id': [missing_id], 'depth': [1.0], 'azimuth': [azimuth], 'dip': [-90.0]})
    result = darkmine_data_skills.validation.check_coverage.validate(
        pd.DataFrame({'hole_id': ['H1']}), survey, {},
    )
    missing = [issue for issue in result['issues'] if issue['check'] == 'missing_hole_id']
    assert len(missing) == 1
    assert missing[0]['table'] == 'survey' and missing[0]['row_index'] == 0
    assert not any(issue['check'] == 'orphan_intervals' for issue in result['issues'])
    grouped = [issue for issue in result['issues'] if issue['check'] == 'survey_no_usable_stations']
    assert [issue['hole_id'] for issue in grouped] == ['H1']


def test_converted_surveys_flag_missing_and_orphan_parents(tmp_path):
    raw, out = tmp_path / 'raw', tmp_path / 'out'
    raw.mkdir()
    pd.DataFrame({'Id': [1], 'HoleId': ['H1']}).to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame({'Id': [10, 11, 12], 'CollarId': [None, 2.0, 2.0],
                  'Depth': [1.0, 1.0, 2.0], 'Azimuth': [0.0] * 3, 'Dip': [-90.0] * 3}).to_parquet(
        raw / 'dbo_dhsurvey.parquet')
    darkmine_data_skills.gswa.audit_conversion.convert(raw, out)
    assert darkmine_data_skills.validation.validate_drillholes.main([str(out), '--no-print-summary']) == 1
    result = json.loads((out / 'qa/drillhole_validation_report.json').read_text())
    missing = [issue for issue in result['issues'] if issue['check'] == 'missing_hole_id']
    orphans = [issue for issue in result['issues'] if issue['check'] == 'orphan_intervals']
    assert [issue['row_index'] for issue in missing] == [0]
    assert [issue['row_index'] for issue in orphans] == [1, 2]
    assert all(issue['table'] == 'survey' for issue in missing + orphans)
    assert result['complete'] is True
