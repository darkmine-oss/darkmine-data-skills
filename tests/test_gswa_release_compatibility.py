# Copyright (C) 2026 Darkmine Pty Ltd.

import json

import pandas as pd
import pytest

import darkmine_data_skills
import darkmine_data_skills.gswa.audit_conversion
import darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode
import darkmine_data_skills.validation.check_coverage


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
    assert not {'x', 'y', 'z', 'dip', 'lithology', 'latitude', 'collarlatitude'} & set(columns)
    flattened = pd.read_parquet(out / 'flattened_gsd_dhassayflat.parquet')
    assert flattened['latitude'].tolist() == [-30.0]
    assert flattened['longitude'].tolist() == [120.0]
    assert flattened['dip'].tolist() == [-90.0]
    assert flattened['source_y'].tolist() == [456.0]
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
