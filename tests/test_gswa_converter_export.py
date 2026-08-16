# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import json
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
SPEC = importlib.util.spec_from_file_location("gswa_converter_export", SCRIPT_PATH)
GSWA_CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GSWA_CONVERTER)


def test_frontend_project_uses_baselode_export_contract(tmp_path):
    frontend = {
        "collars": pd.DataFrame({
            "hole_id": ["B", "A", "C"],
            "project_id": [90315, "DG", None],
            "easting": [500100.0, 500000.0, 500200.0],
            "northing": [6900100.0, 6900000.0, 6900200.0],
        }),
        "flattened_example": pd.DataFrame({
            "hole_id": ["B", "A"],
            "from": [10.0, 0.0],
            "to": [20.0, 10.0],
            "source_value": [1, "DG"],
            "attributes": [{"b": 2, "a": 1}, None],
        }),
    }
    metadata = {
        "source_dir": "source",
        "output_dir": str(tmp_path),
        "hole_id_source": "company",
        "precomputed_desurvey": {"status": "omitted"},
        "flattened_tables": ["flattened_example"],
    }

    manifest = GSWA_CONVERTER.write_frontend_project(frontend, tmp_path, metadata)

    on_disk = json.loads((tmp_path / "conversion_manifest.json").read_text())
    assert on_disk == manifest
    assert manifest["format_version"] == 1
    assert manifest["metadata"] == metadata
    assert manifest["tables"]["collars"]["rows"] == 3
    assert manifest["tables"]["flattened_example"]["files"] == {
        "csv": "flattened_example.csv",
        "parquet": "flattened_example.parquet",
    }

    collars_csv = pd.read_csv(tmp_path / "collars.csv", dtype={"project_id": "string"})
    collars_parquet = pd.read_parquet(tmp_path / "collars.parquet")
    assert collars_csv["hole_id"].tolist() == ["A", "B", "C"]
    assert collars_parquet["hole_id"].tolist() == ["A", "B", "C"]
    assert collars_parquet["project_id"].tolist()[:2] == ["DG", "90315"]
    assert pd.isna(collars_parquet.loc[2, "project_id"])

    flattened_csv = pd.read_csv(tmp_path / "flattened_example.csv")
    flattened_parquet = pd.read_parquet(tmp_path / "flattened_example.parquet")
    assert len(flattened_csv) == len(frontend["flattened_example"])
    assert len(flattened_parquet) == len(frontend["flattened_example"])
    assert flattened_parquet["source_value"].tolist() == ["DG", "1"]
    assert flattened_parquet.loc[1, "attributes"] == '{"a":1,"b":2}'
