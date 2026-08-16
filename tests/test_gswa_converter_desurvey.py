# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT
    / "skills"
    / "gswa-drillsurface-to-baselode"
    / "scripts"
    / "convert_gswa_drillsurface_to_baselode.py"
)
SPEC = importlib.util.spec_from_file_location("gswa_converter", SCRIPT_PATH)
GSWA_CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GSWA_CONVERTER)


def test_precomputed_desurvey_uses_only_mutually_valid_rows():
    collars = pd.DataFrame({
        "hole_id": ["valid", "bad_collar", "no_survey"],
        "easting": [500000.0, None, 500200.0],
        "northing": [6900000.0, 6900100.0, 6900200.0],
        "elevation": [None, 310.0, 320.0],
    })
    surveys = pd.DataFrame({
        "hole_id": ["valid", "valid", "valid", "bad_collar", "survey_only"],
        "depth": [0.0, 5.0, 10.0, 0.0, 0.0],
        "azimuth": [0.0, float("inf"), 10.0, 0.0, 0.0],
        "dip": [-60.0, -62.0, -65.0, -60.0, -60.0],
    })

    traces, details = GSWA_CONVERTER.make_precomputed_desurveyed(collars, surveys)

    assert set(traces["hole_id"]) == {"valid"}
    assert traces.iloc[0]["elevation"] == 0.0
    assert details == {
        "status": "written",
        "reason": None,
        "input_collar_rows": 3,
        "input_survey_rows": 5,
        "valid_collar_rows": 2,
        "valid_survey_rows": 4,
        "eligible_holes": 1,
        "trace_rows": len(traces),
    }


def test_precomputed_desurvey_reports_omission_when_no_holes_are_eligible():
    collars = pd.DataFrame({
        "hole_id": ["bad"],
        "easting": [None],
        "northing": [6900000.0],
    })
    surveys = pd.DataFrame({
        "hole_id": ["bad"],
        "depth": [0.0],
        "azimuth": [0.0],
        "dip": [-60.0],
    })

    traces, details = GSWA_CONVERTER.make_precomputed_desurveyed(collars, surveys)

    assert traces.empty
    assert details["status"] == "omitted"
    assert details["reason"] == "no_eligible_holes"
    assert details["valid_collar_rows"] == 0
    assert details["valid_survey_rows"] == 1
    assert details["trace_rows"] == 0


def test_precomputed_desurvey_reports_missing_required_columns():
    collars = pd.DataFrame({"hole_id": ["A"], "easting": [500000.0]})
    surveys = pd.DataFrame({
        "hole_id": ["A"],
        "depth": [0.0],
        "azimuth": [0.0],
        "dip": [-60.0],
    })

    traces, details = GSWA_CONVERTER.make_precomputed_desurveyed(collars, surveys)

    assert traces.empty
    assert details["status"] == "omitted"
    assert details["reason"] == "missing_required_columns"
    assert details["missing_collar_columns"] == ["northing"]
    assert details["missing_survey_columns"] == []
