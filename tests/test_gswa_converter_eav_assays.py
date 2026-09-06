# SPDX-License-Identifier: GPL-3.0-or-later

"""EAV assay fallback: pivot dbo_dhgeochemistry + attr when gsd_dhassayflat
is absent, keep the hole-ID policy consistent, and write the provenance
sidecar only when a flag is actually set."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT
    / "skills"
    / "gswa-drillsurface-to-baselode"
    / "scripts"
    / "convert_gswa_drillsurface_to_baselode.py"
)
SPEC = importlib.util.spec_from_file_location("gswa_converter_eav", SCRIPT_PATH)
GSWA_CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GSWA_CONVERTER)


def _write_eav_source(src_dir, *, flag_pct=True):
    pd.DataFrame({
        "Id": [11, 12],
        "HoleId": ["GSWA-0001", "GSWA-0002"],
        "CompanyHoleId": ["AC01", "AC02"],
        "Dataset": ["DG", "DG"],
        "Latitude": [-32.0, -32.1],
        "Longitude": [119.0, 119.1],
        "MaxDepth": [50.0, 60.0],
    }).to_parquet(src_dir / "dbo_collar.parquet", index=False)
    pd.DataFrame({
        "Id": [1, 2, 3, 4],
        "CollarId": [11, 11, 12, 12],
        "Depth": [0.0, 50.0, 0.0, 60.0],
        "Dip": [-60.0, -60.0, -90.0, -90.0],
        "Azimuth": [90.0, 90.0, 0.0, 0.0],
    }).to_parquet(src_dir / "dbo_dhsurvey.parquet", index=False)
    pd.DataFrame({
        "Id": [101, 102, 103],
        "CollarId": [11, 11, 12],
        "FromDepth": [0.0, 1.0, 0.0],
        "ToDepth": [1.0, 2.0, 1.0],
        "SampleId": [5001, 5002, 5003],
        "CompanySampleId": ["S1", "S2", "S3"],
    }).to_parquet(src_dir / "dbo_dhgeochemistry.parquet", index=False)
    pd.DataFrame({
        "Id": [1, 2, 3, 4, 5, 6],
        "DHGeochemistryId": [101, 101, 102, 102, 103, 103],
        "AttributeColumn": ["Au", "SiO2", "Au", "SiO2", "Au", "SiO2"],
        "AttributeValue": ["0.5", "51.5", "1.5", "48.0", "<0.01", "50.0"],
        "PPMValue": [0.5, 515000.0, 1.5, 480000.0, 0.005, 500000.0],
        "Flag_PCT": [False, flag_pct, False, flag_pct, False, flag_pct],
        "Flag_LT": [False, False, False, False, True, False],
        "Units": ["ppm", "pct", "ppm", "pct", "ppm", "pct"],
    }).to_parquet(src_dir / "dbo_dhgeochemistryattr.parquet", index=False)


@pytest.fixture
def eav_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_eav_source(src)
    return src


def test_build_assay_rows_reports_the_eav_path(eav_source):
    collars_raw = GSWA_CONVERTER.read_table(eav_source, "dbo_collar")
    rows, kind = GSWA_CONVERTER.build_assay_rows(eav_source, collars_raw)
    assert kind == "eav"
    assert len(rows) == 6
    assert set(rows["CompanyHoleId"]) == {"AC01", "AC02"}


def test_intervals_without_attrs_still_get_hole_ids_and_convert(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_eav_source(src)
    (src / "dbo_dhgeochemistryattr.parquet").unlink()
    collars_raw = GSWA_CONVERTER.read_table(src, "dbo_collar")
    rows, kind = GSWA_CONVERTER.build_assay_rows(src, collars_raw)
    assert kind == "intervals"
    assert set(rows["HoleId"]) == {"GSWA-0001", "GSWA-0002"}
    # Codex review: returning before attach_hole_ids left the flat converter
    # without HoleId and aborted the whole export.
    out_dir = tmp_path / "out"
    GSWA_CONVERTER.convert_project(src, out_dir, hole_id_source="baselode")
    assays = pd.read_parquet(out_dir / "assays.parquet")
    assert len(assays) == 3
    assert not (out_dir / "assays_provenance.parquet").exists()


def test_suffix_analyte_columns_with_ppm_leaves_reserved_and_existing_alone():
    df = pd.DataFrame([["A", 0.0, 1.0, 0.5, 51.5, 10.0, "x"]],
                      columns=["hole_id", "from", "to", "au", "SiO2", "cu_ppm", "_internal"])
    out = GSWA_CONVERTER.suffix_analyte_columns_with_ppm(df, reserved={"hole_id", "from", "to"})
    assert list(out.columns) == ["hole_id", "from", "to", "au_ppm", "SiO2_ppm", "cu_ppm", "_internal"]


def test_provenance_sidecar_requires_a_set_flag(eav_source):
    collars_raw = GSWA_CONVERTER.read_table(eav_source, "dbo_collar")
    rows, _ = GSWA_CONVERTER.build_assay_rows(eav_source, collars_raw)
    assert len(GSWA_CONVERTER.build_assay_provenance(rows)) == 6

    quiet = rows.copy()
    quiet["Flag_PCT"] = False
    quiet["Flag_LT"] = False
    assert GSWA_CONVERTER.build_assay_provenance(quiet).empty  # Units alone is not a signal

    as_text = rows.copy()
    as_text["Flag_PCT"] = "False"
    as_text["Flag_LT"] = ["False"] * 4 + ["True", "False"]
    assert len(GSWA_CONVERTER.build_assay_provenance(as_text)) == 6


def test_eav_conversion_keeps_assays_keyed_like_the_collars(eav_source, tmp_path):
    out_dir = tmp_path / "out"
    manifest = GSWA_CONVERTER.convert_project(eav_source, out_dir, hole_id_source="company")

    assert (out_dir / "conversion_manifest.json").exists()
    collars = pd.read_parquet(out_dir / "collars.parquet")
    assays = pd.read_parquet(out_dir / "assays.parquet")
    # Canonical tables share one hole_id keyspace whichever path built the
    # assays; the company id travels as datasource_hole_id, as it does for
    # collars, survey and the flat assay path.
    assert set(assays["hole_id"]) == set(collars["hole_id"])
    assert set(assays["hole_id"]) == {"GSWA-0001", "GSWA-0002"}
    assert assays.sort_values(["hole_id", "from"])["datasource_hole_id"].tolist() == ["AC01", "AC01", "AC02"]
    assert {"au_ppm", "sio2_ppm"}.issubset(assays.columns)
    assert assays.sort_values(["hole_id", "from"])["au_ppm"].tolist() == [0.5, 1.5, 0.005]

    provenance = pd.read_parquet(out_dir / "assays_provenance.parquet")
    assert len(provenance) == 6
    assert set(provenance["hole_id"]) == set(collars["hole_id"])
    assert provenance.loc[provenance["attributecolumn"] == "SiO2", "flag_pct"].all()
    assert "assays_provenance" in json.dumps(manifest)


def test_eav_and_flat_paths_emit_the_same_identity_columns(eav_source, tmp_path):
    eav_out = tmp_path / "eav"
    GSWA_CONVERTER.convert_project(eav_source, eav_out, hole_id_source="company")
    eav_assays = pd.read_parquet(eav_out / "assays.parquet")

    flat_src = tmp_path / "flat"
    flat_src.mkdir()
    _write_eav_source(flat_src)
    (flat_src / "dbo_dhgeochemistry.parquet").unlink()
    (flat_src / "dbo_dhgeochemistryattr.parquet").unlink()
    pd.DataFrame({
        "Id": [1, 2, 3], "Collarid": [11, 11, 12], "FromDepth": [0.0, 1.0, 0.0], "ToDepth": [1.0, 2.0, 1.0],
        "SampleId": [5001, 5002, 5003], "CompanySampleId": ["S1", "S2", "S3"],
        "Au_PPM": [0.5, 1.5, 0.005], "SiO2_PPM": [515000.0, 480000.0, 500000.0],
    }).to_parquet(flat_src / "gsd_dhassayflat.parquet", index=False)
    flat_out = tmp_path / "flat_out"
    GSWA_CONVERTER.convert_project(flat_src, flat_out, hole_id_source="company")
    flat_assays = pd.read_parquet(flat_out / "assays.parquet")

    for column in ("hole_id", "datasource_hole_id", "au_ppm", "sio2_ppm"):
        assert column in eav_assays.columns and column in flat_assays.columns
        assert eav_assays.sort_values(["hole_id", "from"])[column].tolist() == \
            flat_assays.sort_values(["hole_id", "from"])[column].tolist(), column


def test_eav_conversion_under_the_baselode_hole_id_policy(eav_source, tmp_path):
    out_dir = tmp_path / "out"
    GSWA_CONVERTER.convert_project(eav_source, out_dir, hole_id_source="baselode")
    collars = pd.read_parquet(out_dir / "collars.parquet")
    assays = pd.read_parquet(out_dir / "assays.parquet")
    assert set(collars["hole_id"]) == {"GSWA-0001", "GSWA-0002"}
    assert set(assays["hole_id"]) == {"GSWA-0001", "GSWA-0002"}


def test_eav_conversion_skips_provenance_when_no_flag_is_set(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_eav_source(src, flag_pct=False)
    attrs = pd.read_parquet(src / "dbo_dhgeochemistryattr.parquet")
    attrs["Flag_LT"] = False
    attrs.to_parquet(src / "dbo_dhgeochemistryattr.parquet", index=False)
    out_dir = tmp_path / "out"
    GSWA_CONVERTER.convert_project(src, out_dir, hole_id_source="company")
    assert not (out_dir / "assays_provenance.parquet").exists()
    assert (out_dir / "assays.parquet").exists()


def test_provenance_recognises_numeric_flags_promoted_to_float_by_the_join(tmp_path):
    """Codex review: integer flags become 1.0 when an interval has no attrs."""
    src = tmp_path / "src"
    src.mkdir()
    _write_eav_source(src)
    attrs = pd.read_parquet(src / "dbo_dhgeochemistryattr.parquet")
    attrs["Flag_PCT"] = 0
    attrs["Flag_LT"] = [0, 0, 0, 0, 1, 0]
    attrs.to_parquet(src / "dbo_dhgeochemistryattr.parquet", index=False)
    intervals = pd.read_parquet(src / "dbo_dhgeochemistry.parquet")
    intervals = pd.concat([intervals, pd.DataFrame({
        "Id": [104], "CollarId": [12], "FromDepth": [1.0], "ToDepth": [2.0],
        "SampleId": [5004], "CompanySampleId": ["S4"],
    })], ignore_index=True)
    intervals.to_parquet(src / "dbo_dhgeochemistry.parquet", index=False)

    collars_raw = GSWA_CONVERTER.read_table(src, "dbo_collar")
    rows, kind = GSWA_CONVERTER.build_assay_rows(src, collars_raw)
    assert kind == "eav"
    assert rows["Flag_LT"].dtype.kind == "f"  # promoted by the unmatched interval
    assert len(GSWA_CONVERTER.build_assay_provenance(rows)) == 6

    out_dir = tmp_path / "out"
    GSWA_CONVERTER.convert_project(src, out_dir, hole_id_source="company")
    assert (out_dir / "assays_provenance.parquet").exists()
    assert len(pd.read_parquet(out_dir / "assays.parquet")) == 4
