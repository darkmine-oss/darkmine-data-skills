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
    path/to/download-drill-and-sample-data/postgres_gswa \
    ../baselode-frontend/test-data/my-gswa-project
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import baselode.adaptors.raw_gswa.convert
import baselode.drill.data
import baselode.drill.desurvey
import baselode.export


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


ASSAY_PROVENANCE_COLUMNS = (
    "Flag_PCT",
    "Flag_LT",
    "Flag_GT",
    "Flag_BadDataValue",
    "Flag_KnownNoDataValue",
    "Flag_ValidLessThanDetectionLevel",
    "Units",
)


def build_assay_rows(src_dir, collars_raw):
    """Load assay rows from the GSWA dump.

    Returns ``(df, kind)`` where ``kind`` is one of:

    - ``"flat"`` — wide pre-pivoted rows from ``gsd_dhassayflat`` (analyte
      columns suffixed ``_PPM``, values already normalized to ppm by GSWA).
    - ``"eav"`` — long-form rows from ``dbo_dhgeochemistry`` joined to its
      ``*attr`` EAV table; one row per (interval, analyte). Caller must
      pivot via ``convert_assays`` using ``PPMValue`` as the value column.
      ``Flag_PCT`` only signals original lab unit was percent — ``PPMValue``
      is already in ppm.
    - ``"intervals"`` — geochemistry intervals exist but no ``*attr`` rows;
      hole ids are attached and the frame goes through the flat converter,
      yielding assay intervals with no analyte columns.
    - ``"empty"`` — no assay rows available.
    """
    flat = read_table(src_dir, "gsd_dhassayflat")
    if not flat.empty:
        if "Collarid" in flat.columns and "CollarId" not in flat.columns:
            flat = flat.rename(columns={"Collarid": "CollarId"})
        return attach_hole_ids(flat, collars_raw), "flat"

    intervals = read_table(src_dir, "dbo_dhgeochemistry")
    if intervals.empty:
        return intervals, "empty"
    attrs = read_table(src_dir, "dbo_dhgeochemistryattr")
    # Join collar ids before any early return: the flat converter needs
    # HoleId, and GSWA intervals only carry CollarId.
    intervals = attach_hole_ids(intervals, collars_raw)
    if attrs.empty:
        return intervals, "intervals"
    intervals = intervals.rename(columns={"Id": "DHGeochemistryId"})
    merged = intervals.merge(attrs, on="DHGeochemistryId", how="left", suffixes=("", "_attr"))
    return merged, "eav"


def suffix_analyte_columns_with_ppm(df, *, reserved):
    """Rename pivoted analyte columns to ``<analyte>_ppm`` to match the flat path.

    The flat ``gsd_dhassayflat`` table arrives as ``Au_PPM`` etc., but
    ``baselode.drill.data.load_assays`` lowercases every column name, so
    downstream consumers see ``au_ppm``. Match that convention here so the
    output schema is identical regardless of source path.
    """
    if df.empty:
        return df
    reserved = set(reserved)
    rename = {
        c: f"{c}_ppm"
        for c in df.columns
        if isinstance(c, str)
        and c not in reserved
        and not c.startswith("_")
        and not c.lower().endswith("_ppm")
    }
    return df.rename(columns=rename) if rename else df


def reattach_company_hole_id(assays, eav_rows):
    """Carry ``CompanyHoleId`` through the EAV pivot as ``datasource_hole_id``.

    ``convert_assays`` keeps only the interval keys when it pivots, so the
    company identifier that ``attach_hole_ids`` joined onto every long-form
    row is lost.  The flat path (and the canonical collars / survey tables)
    keep it under ``datasource_hole_id``, so restore it there: the EAV path
    then yields the same identity columns as the flat path and stays keyed
    on the same ``hole_id`` as the collars.
    """
    if assays.empty or "hole_id" not in assays.columns:
        return assays
    if not {"HoleId", "CompanyHoleId"}.issubset(eav_rows.columns):
        return assays
    lookup = eav_rows[["HoleId", "CompanyHoleId"]].dropna(subset=["HoleId"]).copy()
    lookup["HoleId"] = lookup["HoleId"].astype(str).str.strip()
    lookup = lookup.drop_duplicates(subset=["HoleId"], keep="first").set_index("HoleId")["CompanyHoleId"]
    out = assays.copy()
    company = out["hole_id"].astype(str).str.strip().map(lookup)
    if "datasource_hole_id" in out.columns:
        out["datasource_hole_id"] = out["datasource_hole_id"].where(out["datasource_hole_id"].notna(), company)
    else:
        out["datasource_hole_id"] = company
    return out


def _flag_is_set(value):
    """True for a set provenance flag: bool, non-zero number, or truthy text.

    Numbers matter because a left join onto an interval with no attrs
    promotes an integer flag column to float, so ``1`` arrives as ``1.0``.
    """
    if value is None:
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return not pd.isna(value) and float(value) != 0.0
    return str(value).strip().lower() in {"true", "t", "1", "1.0", "y", "yes"}


def build_assay_provenance(eav_rows):
    """Long-form (interval, analyte) rows with unit/flag provenance.

    Used as a sidecar when the EAV path is taken, so downstream consumers
    can see which analytes were originally reported in percent (``Flag_PCT``)
    or as less-than / greater-than detection limits.
    """
    if eav_rows.empty or "AttributeColumn" not in eav_rows.columns:
        return pd.DataFrame()
    keep = [
        c for c in [
            "HoleId", "CompanyHoleId", "CollarId", "DHGeochemistryId",
            "SampleId", "CompanySampleId", "FromDepth", "ToDepth",
            "AttributeColumn", "AttributeValue", "PPMValue",
            *ASSAY_PROVENANCE_COLUMNS,
        ] if c in eav_rows.columns
    ]
    out = eav_rows[keep].copy()
    out = out[out["AttributeColumn"].notna() & (out["AttributeColumn"].astype(str) != "")]
    # Only worth a sidecar when at least one Flag_* is actually set; a
    # populated Units column alone says nothing the assay table doesn't.
    flag_columns = [c for c in ASSAY_PROVENANCE_COLUMNS if c.startswith("Flag_") and c in out.columns]
    has_signal = any(out[column].map(_flag_is_set).any() for column in flag_columns)
    if not has_signal:
        return pd.DataFrame()
    return out.reset_index(drop=True)


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


def write_frontend_project(frontend, out_dir, metadata):
    tables = {
        table_name: sort_frontend_table(df, table_name)
        for table_name, df in frontend.items()
    }
    return baselode.export.write_project(
        tables,
        out_dir,
        manifest_name="conversion_manifest.json",
        metadata=metadata,
    )


def make_precomputed_desurveyed(collars, surveys):
    required_collar = {"hole_id", "easting", "northing"}
    required_survey = {"hole_id", "depth", "azimuth", "dip"}
    details = {
        "status": "omitted",
        "reason": None,
        "input_collar_rows": int(len(collars)),
        "input_survey_rows": int(len(surveys)),
        "valid_collar_rows": 0,
        "defaulted_elevation_rows": 0,
        "valid_survey_rows": 0,
        "eligible_holes": 0,
        "trace_rows": 0,
    }
    if collars.empty or surveys.empty:
        details["reason"] = "empty_input"
        return pd.DataFrame(), details

    missing_collar = required_collar.difference(collars.columns)
    missing_survey = required_survey.difference(surveys.columns)
    if missing_collar or missing_survey:
        details["reason"] = "missing_required_columns"
        details["missing_collar_columns"] = sorted(missing_collar)
        details["missing_survey_columns"] = sorted(missing_survey)
        return pd.DataFrame(), details

    collar_columns = ["hole_id", "easting", "northing"]
    if "elevation" in collars.columns:
        collar_columns.append("elevation")
    desurvey_collars = collars[collar_columns].copy()
    if "elevation" not in desurvey_collars.columns:
        desurvey_collars["elevation"] = np.nan

    survey_columns = ["hole_id", "depth", "azimuth", "dip"]
    desurvey_surveys = surveys[survey_columns].copy()
    for column in ["easting", "northing", "elevation"]:
        desurvey_collars[column] = pd.to_numeric(
            desurvey_collars[column], errors="coerce",
        )
    desurvey_collars = desurvey_collars.replace([np.inf, -np.inf], np.nan)
    defaulted_elevation = desurvey_collars["elevation"].isna()
    desurvey_collars["elevation"] = desurvey_collars["elevation"].fillna(0.0)
    for column in ["depth", "azimuth", "dip"]:
        desurvey_surveys[column] = pd.to_numeric(
            desurvey_surveys[column], errors="coerce",
        )
    desurvey_surveys = desurvey_surveys.replace([np.inf, -np.inf], np.nan)

    desurvey_collars = desurvey_collars.dropna(
        subset=["hole_id", "easting", "northing"],
    )
    desurvey_surveys = desurvey_surveys.dropna(
        subset=["hole_id", "depth", "azimuth", "dip"],
    )
    details["valid_collar_rows"] = int(len(desurvey_collars))
    defaulted_elevation = defaulted_elevation.loc[desurvey_collars.index]
    details["defaulted_elevation_rows"] = int(defaulted_elevation.sum())
    defaulted_elevation_holes = set(
        desurvey_collars.loc[defaulted_elevation, "hole_id"]
    )
    details["valid_survey_rows"] = int(len(desurvey_surveys))

    eligible_holes = set(desurvey_collars["hole_id"]).intersection(
        desurvey_surveys["hole_id"],
    )
    details["eligible_holes"] = int(len(eligible_holes))
    if not eligible_holes:
        details["reason"] = "no_eligible_holes"
        return pd.DataFrame(), details

    desurvey_collars = desurvey_collars[
        desurvey_collars["hole_id"].isin(eligible_holes)
    ]
    desurvey_surveys = desurvey_surveys[
        desurvey_surveys["hole_id"].isin(eligible_holes)
    ]
    traces = baselode.drill.desurvey.build_traces(
        desurvey_collars,
        desurvey_surveys,
        step=5.0,
    )
    traces["elevation_defaulted"] = traces["hole_id"].isin(
        defaulted_elevation_holes
    )
    details["trace_rows"] = int(len(traces))
    if traces.empty:
        details["reason"] = "no_trace_rows"
        return traces, details

    details["status"] = "written"
    return traces, details


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
    assay_rows, assay_kind = build_assay_rows(src_dir, collars_raw)
    assay_provenance = pd.DataFrame()
    if assay_kind == "eav":
        pivoted_assays = baselode.adaptors.raw_gswa.convert.convert_assays(
            assay_rows,
            extras="spread",
            value_col="PPMValue",
        )
        # `convert_assays` pivots `AttributeColumn` to plain analyte names
        # (`Au`, `Cu`, ...); suffix `_PPM` so output matches the flat-table
        # column convention regardless of which source path was used.
        reserved = {
            "hole_id", "from", "to", "mid", "collar_id",
            "sample_id", "datasource_sample_id", "datasource_hole_id",
            "extra", "geometry",
        }
        converted["assays"] = reattach_company_hole_id(
            suffix_analyte_columns_with_ppm(pivoted_assays, reserved=reserved),
            assay_rows,
        )
        assay_provenance = build_assay_provenance(assay_rows)
    else:
        converted["assays"] = baselode.adaptors.raw_gswa.convert.convert_assays_flat(
            assay_rows,
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

    precomputed, precomputed_details = make_precomputed_desurveyed(
        frontend["collars"],
        frontend["survey"],
    )
    if not precomputed.empty:
        frontend["precomputed_desurveyed"] = frontend_cleanup(
            precomputed,
            hole_id_source="baselode",
        )

    if not assay_provenance.empty:
        # Same identity convention as the canonical tables: hole_id is the
        # GSWA id and the company id travels as datasource_hole_id, so the
        # sidecar joins to assays/collars on hole_id under either policy.
        provenance_columns = {
            **{k: v for k, v in RAW_TO_FLATTENED_COLUMNS.items() if k in assay_provenance.columns},
            "CompanyHoleId": "datasource_hole_id",
        }
        provenance = assay_provenance.rename(columns=provenance_columns)
        provenance.columns = make_unique_columns(
            str(c).strip().lower().replace(" ", "_") for c in provenance.columns
        )
        frontend["assays_provenance"] = frontend_cleanup(
            provenance, hole_id_source=hole_id_source,
        )

    flattened = build_flattened_tables(
        src_dir,
        collars_raw,
        hole_id_source=hole_id_source,
    )
    for table_name, df in flattened.items():
        frontend[table_name] = frontend_cleanup(df, hole_id_source="baselode")

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(src_dir),
        "output_dir": str(out_dir),
        "hole_id_source": hole_id_source,
        "precomputed_desurvey": precomputed_details,
        "flattened_tables": sorted(k for k in frontend if k.startswith("flattened_")),
    }
    return write_frontend_project(frontend, out_dir, metadata)


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
    print(f"source: {manifest['metadata']['source_dir']}")
    print(f"output: {manifest['metadata']['output_dir']}")
    for table_name, info in manifest["tables"].items():
        parquet_path = out_dir / info["files"]["parquet"]
        print(
            f"{table_name:22s} rows={info['rows']:>8d} "
            f"cols={len(info['columns']):>4d} "
            f"parquet={parquet_path.stat().st_size / 1024:>8.1f} KiB"
        )
    print(f"manifest: {out_dir / 'conversion_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
