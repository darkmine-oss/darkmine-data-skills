#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Attach interpolated XYZ to every row of an interval table."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.desurvey import attach_assay_positions, minimum_curvature_desurvey

EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


def _read_table(project_dir, stem):
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if path.exists():
            return (pd.read_parquet(path) if ext == "parquet" else pd.read_csv(path)), ext
    return None, None


def _write_table(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower().lstrip(".")
    if ext == "parquet":
        df.to_parquet(path, compression="snappy", index=False)
    elif ext == "csv":
        df.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported extension: {ext!r}")


def _resolve_traces(project_dir):
    traces, _ = _read_table(project_dir, "traces")
    if traces is not None:
        return traces, "loaded"
    collars, _ = _read_table(project_dir, "collars")
    survey, _ = _read_table(project_dir, "survey")
    if collars is None or survey is None:
        raise SystemExit(
            "No traces.{parquet,csv} found, and could not desurvey: missing collars or survey."
        )
    traces = minimum_curvature_desurvey(collars, survey)
    return traces, "desurveyed-on-the-fly"


def _apply_anchor(df, anchor):
    if anchor == "midpoint":
        return df
    if anchor == "from":
        d = df.copy()
        d["to"] = d["from"]
        return d
    if anchor == "to":
        d = df.copy()
        d["from"] = d["to"]
        return d
    raise ValueError(f"Unknown anchor {anchor!r}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--table", default="assays")
    p.add_argument("--anchor", choices=("midpoint", "from", "to"), default="midpoint")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    df, _ = _read_table(project_dir, args.table)
    if df is None:
        p.error(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")

    traces, trace_source = _resolve_traces(project_dir)

    anchored = _apply_anchor(df, args.anchor)
    out_df = attach_assay_positions(anchored, traces)

    if args.anchor != "midpoint":
        # restore original from / to columns so the row still carries its real interval
        out_df["from"] = df["from"].values
        out_df["to"] = df["to"].values

    missing = out_df["easting"].isna().sum()
    if missing:
        print(f"WARN: {missing:,} rows had no matching trace and got NaN positions", file=sys.stderr)

    out = args.output or (project_dir / f"{args.table}_with_xyz.parquet")
    _write_table(out_df, out)

    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Source: {args.table} ({len(df):,} rows)")
    print(f"Traces: {trace_source} ({traces['hole_id'].nunique()} holes)")
    print(f"Anchor: {args.anchor}")
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
