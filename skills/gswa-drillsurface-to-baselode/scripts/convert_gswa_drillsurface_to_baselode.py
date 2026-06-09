#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Convert a GSWA drill/surface parquet dump into Baselode project files.

The frontend expects canonical files named ``collars``, ``survey``,
``assays``, ``geology`` and ``structure`` as CSV or parquet, with parquet
preferred. This script reads table-level parquet files from a GSWA dump,
assembles the join shapes expected by ``baselode.adaptors.raw_gswa.convert``,
then writes frontend-ready CSV/parquet pairs. It also writes
``flattened_<table>`` files for every GSWA parent table so strip-log tools can
read all downhole interval/point properties, not just the canonical subsets.

Usage
-----
python skills/gswa-drillsurface-to-baselode/scripts/convert_gswa_drillsurface_to_baselode.py SRC_DIR OUT_DIR

Example
-------
python skills/gswa-drillsurface-to-baselode/scripts/convert_gswa_drillsurface_to_baselode.py \
    /Users/tam/Data/darkmine/agents/tenement_assessment_agent/runs/.../postgres_gswa \
    ../baselode-frontend/test-data/my-gswa-project
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import baselode.adaptors.raw_gswa.convert
import baselode.drill.data
import baselode.drill.desurvey


GEOLOGY_ATTRIBUTE_ALIASES = {
    "Lith Code 1": "geology_code",
    "Lith_Code_1": "geology_code",
    "LithCode1": "geology_code",
    "Lith1": "geology_code",
    "Rock Type": "geology_code",
    "Rock_Type": "geology_code",
    "Lith Code 2": "lith_code_2",
    "Lith_Code_2": "lith_code_2",
    "Lithology and Description": "GeologyComment",
    "Lithology Description": "GeologyComment",
    "Description": "GeologyComment",
    "Oxidation": "oxidation",
    "Colour": "colour",
    "Su %": "sulphide_percent",
    "Su Min": "sulphide_mineral",
}

RAW_TO_FLATTENED_COLUMNS = {
    "HoleId": "hole_id",
    "CompanyHoleId": "companyholeid",
    "CollarId": "collarid",
    "Collarid": "collarid",
    "FromDepth": "from",
    "ToDepth": "to",
    "Depth": "depth",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Easting": "easting",
    "Northing": "northing",
    "Elevation": "elevation",
    "Dataset": "project_id",
    "SampleId": "sample_id",
    "CompanySampleId": "company_sample_id",
    "Anumber": "report_number",
}

RAW_METADATA_COLUMNS = {
    "Accuracy",
    "Flag_BadDataValue",
    "Flag_GT",
    "Flag_KnownMetaDataValue",
    "Flag_KnownNoDataValue",
    "Flag_LT",
    "Flag_PCT",
    "Flag_ValidLessThanDetectionLevel",
    "IsTransformed",
    "Last_updated",
    "LoadBy",
    "LoadDate",
    "MRTDetailId",
    "MRTFileId",
    "ModifiedBy",
    "ModifiedDate",
    "Units",
}


def read_table(src_dir, table_name):
    path = src_dir / f"{table_name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def first_existing(df, columns):
    for column in columns:
        if column in df.columns:
            return column
    return None


def drop_duplicate_key_rows(df, key):
    if df.empty or key not in df.columns:
        return df
    return df.drop_duplicates(subset=[key], keep="first")


def coalesce_columns(df, target, candidates):
    present = [c for c in candidates if c in df.columns]
    if not present:
        return df
    if target not in df.columns:
        df[target] = df[present[0]]
    for column in present:
        if column == target:
            continue
        df[target] = df[target].where(df[target].notna(), df[column])
    drop_cols = [c for c in present if c != target]
    return df.drop(columns=drop_cols, errors="ignore")


def clip_overlapping_intervals(df, *, id_col, hole_col="HoleId",
                               from_col="FromDepth", to_col="ToDepth"):
    if df.empty or not {id_col, hole_col, from_col, to_col}.issubset(df.columns):
        return df

    out = df.copy()
    out[from_col] = pd.to_numeric(out[from_col], errors="coerce")
    out[to_col] = pd.to_numeric(out[to_col], errors="coerce")
    out = out.sort_values([hole_col, from_col, to_col], kind="mergesort")

    rows = []
    for _, group in out.groupby(hole_col, sort=False):
        previous_to = None
        for _, row in group.iterrows():
            current_from = row[from_col]
            current_to = row[to_col]
            if pd.isna(current_from) or pd.isna(current_to):
                rows.append(row)
                continue
            current_from = round(float(current_from), 3)
            current_to = round(float(current_to), 3)
            if previous_to is not None and current_from < previous_to:
                current_from = previous_to
            if current_to <= current_from:
                continue
            row[from_col] = current_from
            row[to_col] = current_to
            rows.append(row)
            previous_to = current_to

    if not rows:
        return out.iloc[0:0].copy()
    return pd.DataFrame(rows).reset_index(drop=True)


def collar_lookup(collars_raw):
    if collars_raw.empty:
        return pd.DataFrame(columns=["CollarId", "HoleId", "CompanyHoleId"])
    keep = [c for c in ["Id", "HoleId", "CompanyHoleId"] if c in collars_raw.columns]
    out = collars_raw[keep].copy()
    if "Id" in out.columns:
        out = out.rename(columns={"Id": "CollarId"})
    return drop_duplicate_key_rows(out, "CollarId")


def attach_hole_ids(df, collars_raw):
    if df.empty or "CollarId" not in df.columns:
        return df
    lookup = collar_lookup(collars_raw)
    if lookup.empty:
        return df
    out = df.merge(lookup, on="CollarId", how="left", suffixes=("", "_collar"))
    return coalesce_columns(
        out,
        "HoleId",
        ["HoleId", "HoleId_collar"],
    )


def build_collar_rows(src_dir):
    collars = read_table(src_dir, "dbo_collar")
    coords = read_table(src_dir, "dbo_collarcoordinate")
    elev = read_table(src_dir, "dbo_collarelevation")
    if collars.empty:
        return collars

    out = collars.copy()
    if not coords.empty and "CollarId" in coords.columns:
        coord_cols = [
            c for c in [
                "CollarId", "Easting", "Northing", "Datum", "Projection",
                "Zone", "Units", "Accuracy",
            ] if c in coords.columns
        ]
        out = out.merge(
            drop_duplicate_key_rows(coords[coord_cols], "CollarId"),
            left_on="Id",
            right_on="CollarId",
            how="left",
        )

    if not elev.empty:
        elev_key = first_existing(elev, ["CollarId", "CollarID"])
        if elev_key is not None:
            elev = elev.rename(columns={elev_key: "CollarId"})
            out = out.merge(
                drop_duplicate_key_rows(elev, "CollarId"),
                left_on="Id",
                right_on="CollarId",
                how="left",
                suffixes=("", "_elev"),
            )

    return out


def build_survey_rows(src_dir, collars_raw):
    surveys = read_table(src_dir, "dbo_dhsurvey")
    return attach_hole_ids(surveys, collars_raw)


def build_assay_rows(src_dir, collars_raw):
    flat = read_table(src_dir, "gsd_dhassayflat")
    if not flat.empty:
        if "Collarid" in flat.columns and "CollarId" not in flat.columns:
            flat = flat.rename(columns={"Collarid": "CollarId"})
        return attach_hole_ids(flat, collars_raw)

    intervals = read_table(src_dir, "dbo_dhgeochemistry")
    attrs = read_table(src_dir, "dbo_dhgeochemistryattr")
    if intervals.empty:
        return intervals
    intervals = attach_hole_ids(intervals, collars_raw)
    intervals = intervals.rename(columns={"Id": "DHGeochemistryId"})
    if attrs.empty:
        return intervals
    return intervals.merge(attrs, on="DHGeochemistryId", how="left", suffixes=("", "_attr"))


def normalize_geology_attributes(attrs):
    if attrs.empty or "AttributeColumn" not in attrs.columns:
        return attrs
    out = attrs.copy()
    out["AttributeColumn"] = out["AttributeColumn"].replace(GEOLOGY_ATTRIBUTE_ALIASES)
    return out


def make_unique_columns(columns):
    seen = {}
    unique = []
    for column in columns:
        name = str(column)
        count = seen.get(name, 0)
        if count:
            unique.append(f"{name}_{count + 1}")
        else:
            unique.append(name)
        seen[name] = count + 1
    return unique


def build_geology_rows(src_dir, collars_raw):
    intervals = read_table(src_dir, "dbo_dhgeology")
    attrs = normalize_geology_attributes(read_table(src_dir, "dbo_dhgeologyattr"))
    if intervals.empty:
        return intervals
    intervals = attach_hole_ids(intervals, collars_raw)
    intervals = intervals.rename(columns={"Id": "DHGeologyId"})
    intervals = clip_overlapping_intervals(intervals, id_col="DHGeologyId")
    if attrs.empty:
        return intervals
    return intervals.merge(attrs, on="DHGeologyId", how="left", suffixes=("", "_attr"))


def build_structure_rows(src_dir, collars_raw):
    intervals = read_table(src_dir, "dbo_dhstructure")
    attrs = read_table(src_dir, "dbo_dhstructureattr")
    if intervals.empty:
        return intervals
    intervals = attach_hole_ids(intervals, collars_raw)
    intervals = intervals.rename(columns={"Id": "DHStructureId"})
    if attrs.empty:
        return intervals
    return intervals.merge(attrs, on="DHStructureId", how="left", suffixes=("", "_attr"))


def table_names(src_dir):
    return sorted(path.stem for path in src_dir.glob("*.parquet"))


def is_attr_table(table_name):
    return table_name.endswith("attr")


def parent_key_from_attr(attrs):
    if attrs.empty:
        return None
    candidates = [
        c for c in attrs.columns
        if c != "Id" and str(c).endswith("Id")
    ]
    if not candidates:
        return None
    return candidates[0]


def pivot_attr_table(attrs, parent_key):
    if attrs.empty or parent_key not in attrs.columns:
        return pd.DataFrame()
    if "AttributeColumn" not in attrs.columns or "AttributeValue" not in attrs.columns:
        return pd.DataFrame()
    use = attrs[[parent_key, "AttributeColumn", "AttributeValue"]].copy()
    use = use[use["AttributeColumn"].notna()]
    if use.empty:
        return pd.DataFrame(columns=[parent_key])
    use["AttributeColumn"] = use["AttributeColumn"].replace(GEOLOGY_ATTRIBUTE_ALIASES)
    out = (
        use.pivot_table(
            index=parent_key,
            columns="AttributeColumn",
            values="AttributeValue",
            aggfunc="first",
            sort=False,
        )
        .reset_index()
    )
    out.columns.name = None
    return out


def flatten_raw_table(src_dir, table_name, collars_raw, *, hole_id_source):
    df = read_table(src_dir, table_name)
    if df.empty:
        return df

    out = df.copy()
    attr_name = f"{table_name}attr"
    attrs = read_table(src_dir, attr_name)
    parent_key = parent_key_from_attr(attrs)
    if parent_key is not None:
        # Only rename `Id` -> parent_key when there's no existing column with
        # that name; otherwise the rename would create duplicate columns and
        # break the subsequent merge.
        if "Id" in out.columns and parent_key not in out.columns:
            out = out.rename(columns={"Id": parent_key})
        if parent_key in out.columns:
            pivoted = pivot_attr_table(attrs, parent_key)
            if not pivoted.empty:
                out = out.merge(pivoted, on=parent_key, how="left")

    if "Collarid" in out.columns and "CollarId" not in out.columns:
        out = out.rename(columns={"Collarid": "CollarId"})
    out = attach_hole_ids(out, collars_raw)

    # Surface-sample tables do not have downhole context, but coordinates and
    # attrs are still useful as flattened schema exports.
    if table_name == "dbo_surfacesample":
        coords = read_table(src_dir, "dbo_surfacesamplecoordinate")
        if not coords.empty and "SurfaceSampleId" in coords.columns and "Id" in out.columns:
            out = out.merge(
                coords.drop_duplicates(subset=["SurfaceSampleId"]),
                left_on="Id",
                right_on="SurfaceSampleId",
                how="left",
                suffixes=("", "_coord"),
            )

    out = out.drop(columns=[c for c in RAW_METADATA_COLUMNS if c in out.columns], errors="ignore")
    out = out.rename(columns={k: v for k, v in RAW_TO_FLATTENED_COLUMNS.items() if k in out.columns})
    out.columns = make_unique_columns(
        str(c).strip().lower().replace(" ", "_") for c in out.columns
    )

    if "hole_id" in out.columns and hole_id_source == "company":
        out = prefer_company_hole_id(out)

    if "hole_id" in out.columns:
        out["hole_id"] = out["hole_id"].astype(str).str.strip()
        out = out[(out["hole_id"] != "") & (out["hole_id"].str.lower() != "nan")]

    out["_source_table"] = table_name
    return out.reset_index(drop=True)


def build_flattened_tables(src_dir, collars_raw, *, hole_id_source):
    flattened = {}
    for table_name in table_names(src_dir):
        if is_attr_table(table_name):
            continue
        df = flatten_raw_table(
            src_dir,
            table_name,
            collars_raw,
            hole_id_source=hole_id_source,
        )
        if df.empty:
            flattened[f"flattened_{table_name}"] = df
            continue
        flattened[f"flattened_{table_name}"] = df
    return flattened


def prefer_company_hole_id(df):
    if df.empty or "companyholeid" not in df.columns:
        return df
    out = df.copy()
    raw_hole_id = out["hole_id"] if "hole_id" in out.columns else None
    company_hole_id = out["companyholeid"].astype(object)
    company_hole_id = company_hole_id.where(company_hole_id.notna(), raw_hole_id)
    if raw_hole_id is not None:
        if "datasource_hole_id" not in out.columns:
            out["datasource_hole_id"] = raw_hole_id
        else:
            out["datasource_hole_id"] = out["datasource_hole_id"].where(
                out["datasource_hole_id"].notna(), raw_hole_id
            )
    out["hole_id"] = company_hole_id.astype(str).str.strip()
    return out


def frontend_cleanup(df, *, hole_id_source):
    out = df.copy()
    out = out.drop(columns=["geometry", "extra"], errors="ignore")
    out.columns = make_unique_columns(str(c).strip() for c in out.columns)
    if hole_id_source == "company":
        out = prefer_company_hole_id(out)
    internal = [c for c in out.columns if c.startswith("_")]
    out = out.drop(columns=internal, errors="ignore")
    if "hole_id" in out.columns:
        out["hole_id"] = out["hole_id"].astype(str).str.strip()
        out = out[(out["hole_id"] != "") & (out["hole_id"].str.lower() != "nan")]
    return out.reset_index(drop=True)


def normalize_for_parquet(df):
    out = df.copy()
    for column in out.columns:
        if out[column].dtype == "object":
            out[column] = out[column].map(normalize_cell)
    return out


def normalize_cell(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def sort_frontend_table(df, table_name):
    if df.empty:
        return df
    sort_cols = []
    if "hole_id" in df.columns:
        sort_cols.append("hole_id")
    if table_name in {"assays", "geology"} or table_name.startswith("flattened_"):
        for column in ["from", "to"]:
            if column in df.columns:
                sort_cols.append(column)
    elif table_name in {"survey", "structure"}:
        if "depth" in df.columns:
            sort_cols.append("depth")
    if not sort_cols:
        return df
    return df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


def write_frontend_pair(df, out_dir, table_name):
    out = sort_frontend_table(normalize_for_parquet(df), table_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{table_name}.csv"
    parquet_path = out_dir / f"{table_name}.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False, compression="snappy")
    return {
        "rows": int(len(out)),
        "columns": list(out.columns),
        "csv_rows": int(len(out)),
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path),
        "parquet_bytes": int(parquet_path.stat().st_size),
    }


def make_precomputed_desurveyed(collars, surveys):
    required_collar = {"hole_id", "easting", "northing"}
    required_survey = {"hole_id", "depth", "azimuth", "dip"}
    if collars.empty or surveys.empty:
        return pd.DataFrame()
    if not required_collar.issubset(collars.columns):
        return pd.DataFrame()
    if not required_survey.issubset(surveys.columns):
        return pd.DataFrame()
    desurvey_collars = collars.copy()
    if "elevation" not in desurvey_collars.columns:
        desurvey_collars["elevation"] = 0.0
    return baselode.drill.desurvey.build_traces(desurvey_collars, surveys, step=5.0)


def convert_project(src_dir, out_dir, *, hole_id_source):
    collars_raw = read_table(src_dir, "dbo_collar")

    converted = {}
    converted["collars"] = baselode.adaptors.raw_gswa.convert.convert_collars(
        build_collar_rows(src_dir),
        extras="spread",
    )
    converted["survey"] = baselode.adaptors.raw_gswa.convert.convert_surveys(
        build_survey_rows(src_dir, collars_raw),
        extras="spread",
    )
    converted["assays"] = baselode.adaptors.raw_gswa.convert.convert_assays_flat(
        build_assay_rows(src_dir, collars_raw),
        extras="spread",
    )
    converted["geology"] = baselode.adaptors.raw_gswa.convert.convert_geology(
        build_geology_rows(src_dir, collars_raw),
        extras="spread",
    )
    converted["structure"] = baselode.adaptors.raw_gswa.convert.convert_structures(
        build_structure_rows(src_dir, collars_raw),
        extras="spread",
    )

    frontend = {}
    for table_name, df in converted.items():
        frontend[table_name] = frontend_cleanup(df, hole_id_source=hole_id_source)

    precomputed = make_precomputed_desurveyed(frontend["collars"], frontend["survey"])
    if not precomputed.empty:
        frontend["precomputed_desurveyed"] = frontend_cleanup(
            precomputed,
            hole_id_source="baselode",
        )

    flattened = build_flattened_tables(
        src_dir,
        collars_raw,
        hole_id_source=hole_id_source,
    )
    for table_name, df in flattened.items():
        frontend[table_name] = frontend_cleanup(df, hole_id_source="baselode")

    summary = {}
    for table_name, df in frontend.items():
        summary[table_name] = write_frontend_pair(
            df,
            out_dir,
            table_name,
        )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(src_dir),
        "output_dir": str(out_dir),
        "hole_id_source": hole_id_source,
        "tables": summary,
        "flattened_tables": sorted(k for k in summary if k.startswith("flattened_")),
    }
    manifest_path = out_dir / "conversion_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src_dir", help="Directory containing GSWA parquet tables.")
    parser.add_argument("out_dir", help="Directory to write frontend project files.")
    parser.add_argument(
        "--hole-id-source",
        choices=["company", "baselode"],
        default="company",
        help="Use CompanyHoleId as frontend hole_id, or keep Baselode/raw HoleId.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    src_dir = Path(args.src_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not src_dir.exists():
        raise SystemExit(f"Source directory does not exist: {src_dir}")
    manifest = convert_project(
        src_dir,
        out_dir,
        hole_id_source=args.hole_id_source,
    )
    print(f"source: {manifest['source_dir']}")
    print(f"output: {manifest['output_dir']}")
    for table_name, info in manifest["tables"].items():
        print(
            f"{table_name:22s} rows={info['rows']:>8d} "
            f"cols={len(info['columns']):>4d} parquet={info['parquet_bytes'] / 1024:>8.1f} KiB"
        )
    print(f"manifest: {out_dir / 'conversion_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
