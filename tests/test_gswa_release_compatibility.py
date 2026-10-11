# Copyright (C) 2026 Darkmine Pty Ltd.

import json

import pandas as pd
import pytest

import darkmine_data_skills
import darkmine_data_skills.gswa.audit_conversion
import darkmine_data_skills.gswa.convert_gswa_drillsurface_to_baselode


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
