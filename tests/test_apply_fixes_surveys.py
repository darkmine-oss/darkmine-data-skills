# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end runs of the drillhole-fix script over the survey fixes and
dataset-precedence overlaps added for GH-96."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

import baselode.drill.desurvey
import baselode.drill.validate


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "drillhole-fix" / "scripts" / "apply_fixes.py"
SPEC = importlib.util.spec_from_file_location("apply_fixes", SCRIPT_PATH)
APPLY_FIXES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPLY_FIXES)


def _write_project(tmp_path, collars, survey, assays=None):
    collars.to_csv(tmp_path / "collars.csv", index=False)
    if survey is not None:
        survey.to_csv(tmp_path / "survey.csv", index=False)
    if assays is not None:
        assays.to_csv(tmp_path / "assays.csv", index=False)
    return tmp_path


@pytest.fixture
def project(tmp_path):
    collars = pd.DataFrame({
        "hole_id": ["OK", "NULLS", "NOSURVEY", "NOCOLLARDIP"],
        "easting": [100.0, 200.0, 300.0, 400.0],
        "northing": [1000.0, 2000.0, 3000.0, 4000.0],
        "elevation": [50.0, 50.0, 50.0, 50.0],
        "max_depth": [100.0, 80.0, 60.0, 40.0],
        "Azimuth": [45.0, 90.0, 180.0, None],
        "Dip": [-60.0, -70.0, -55.0, None],
    })
    survey = pd.DataFrame({
        "hole_id": ["OK", "OK", "NULLS", "NULLS"],
        "depth": [0.0, 100.0, 0.0, 40.0],
        "azimuth": [45.0, 45.0, None, None],
        "dip": [-60.0, -60.0, None, None],
    })
    return _write_project(tmp_path, collars, survey)


def test_survey_fixes_rebuild_every_hole_and_revalidate_clean(project, capsys):
    before = baselode.drill.validate.validate_drillhole_db(
        pd.read_csv(project / "collars.csv"), pd.read_csv(project / "survey.csv"),
    )
    assert {i["check"] for i in before["issues"]} == {"survey_null_orientation", "survey_no_usable_stations"}

    assert APPLY_FIXES.main([
        str(project), "--fix", "unusable-survey-rows,synthesise-collar-station,single-station-surveys",
    ]) == 0

    report = json.loads((project / "fixed" / "fix_report.json").read_text())
    assert report["unusable-survey-rows"] == {"rows_dropped": 2}
    synthesised = report["synthesise-collar-station"]
    assert synthesised["holes_synthesised"] == 3
    assert synthesised["from_collar"] == 2
    assert synthesised["vertical_fallback"] == 1
    assert synthesised["vertical_fallback_holes"] == ["NOCOLLARDIP"]
    assert synthesised["rows_dropped"] == 0  # already dropped by unusable-survey-rows
    assert report["single-station-surveys"] == {"holes_padded": 3}

    fixed_collars = pd.read_csv(project / "fixed" / "collars.csv")
    fixed_survey = pd.read_csv(project / "fixed" / "survey.csv")
    by_hole = {hole: group.sort_values("depth") for hole, group in fixed_survey.groupby("hole_id")}
    assert by_hole["NULLS"]["depth"].tolist() == [0.0, 80.0]
    assert by_hole["NULLS"]["azimuth"].tolist() == [90.0, 90.0]
    assert by_hole["NULLS"]["dip"].tolist() == [-70.0, -70.0]
    assert by_hole["NOSURVEY"]["depth"].tolist() == [0.0, 60.0]
    assert by_hole["NOCOLLARDIP"][["azimuth", "dip"]].iloc[0].tolist() == [0.0, -90.0]
    assert by_hole["OK"]["depth"].tolist() == [0.0, 100.0]

    after = baselode.drill.validate.validate_drillhole_db(fixed_collars, fixed_survey)
    assert after["summary"] == {"error": 0, "warning": 0, "info": 0}
    traces = baselode.drill.desurvey.build_traces(fixed_collars, fixed_survey)
    assert traces.groupby("hole_id")["md"].max().to_dict() == {
        "NOCOLLARDIP": 40.0, "NOSURVEY": 60.0, "NULLS": 80.0, "OK": 100.0,
    }

    out = capsys.readouterr().out
    assert "1 hole(s) had no usable collar azimuth/dip" in out

    # Source project untouched.
    assert len(pd.read_csv(project / "survey.csv")) == 4


def test_synthesise_works_when_no_survey_table_exists(tmp_path):
    collars = pd.DataFrame({
        "hole_id": ["A"], "easting": [0.0], "northing": [0.0], "elevation": [0.0],
        "max_depth": [30.0], "azimuth": [10.0], "dip": [-50.0],
    })
    project = _write_project(tmp_path, collars, survey=None)
    assert APPLY_FIXES.main([str(project), "--fix", "synthesise-collar-station,single-station-surveys"]) == 0
    survey = pd.read_parquet(project / "fixed" / "survey.parquet")
    assert survey[["hole_id", "depth", "azimuth", "dip"]].values.tolist() == [
        ["A", 0.0, 10.0, -50.0], ["A", 30.0, 10.0, -50.0],
    ]


def test_prefer_dataset_resolves_interleaved_campaign_overlaps(tmp_path):
    collars = pd.DataFrame({"hole_id": ["A"], "easting": [0.0], "northing": [0.0], "elevation": [0.0]})
    survey = pd.DataFrame({"hole_id": ["A", "A"], "depth": [0.0, 10.0], "azimuth": [0.0, 0.0], "dip": [-90.0, -90.0]})
    assays = pd.DataFrame({
        "hole_id": ["A"] * 6,
        "from": [0.0, 1.0, 2.0, 0.0, 0.5, 1.0],
        "to": [1.0, 2.0, 3.0, 0.5, 1.0, 1.5],
        "au_ppm": [1.0, 2.0, 3.0, 0.2, 5.0, 8.0],
        "project_id": ["one_metre"] * 3 + ["half_metre"] * 3,
    })
    project = _write_project(tmp_path, collars, survey, assays)

    # Without precedence the campaign overlaps are left for a person.
    assert APPLY_FIXES.main([str(project), "--fix", "overlaps", "--out-dir", str(tmp_path / "plain")]) == 0
    plain = json.loads((tmp_path / "plain" / "fix_report.json").read_text())["overlaps"][0]
    assert plain["conflicts_remaining"] == 5
    assert (tmp_path / "plain" / "conflicts" / "assays_overlaps_to_review.csv").exists()

    assert APPLY_FIXES.main([
        str(project), "--fix", "overlaps", "--prefer-dataset", "half_metre,one_metre",
    ]) == 0
    entry = json.loads((project / "fixed" / "fix_report.json").read_text())["overlaps"][0]
    assert entry["by_kind"] == {"precedence": 2}
    assert entry["conflicts_remaining"] == 0
    assert entry["precedence"] == {"column": "project_id", "order": ["half_metre", "one_metre"], "applied": True}
    fixed = pd.read_csv(project / "fixed" / "assays.csv")
    assert fixed["project_id"].tolist() == ["one_metre", "half_metre", "half_metre", "half_metre"]
    assert fixed[fixed["project_id"] == "one_metre"]["from"].tolist() == [2.0]
    assert not (project / "fixed" / "conflicts").exists()
    audit = pd.read_csv(project / "fixed" / "overlap_audit_log.csv")
    assert (audit["kind"] == "precedence").sum() == 2
