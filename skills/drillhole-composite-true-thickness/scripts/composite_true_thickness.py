#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Composite drillhole intervals against a reference plane's true thickness."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.composite import composite_true_thickness
from baselode.drill.desurvey import minimum_curvature_desurvey

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
        return traces
    collars, _ = _read_table(project_dir, "collars")
    survey, _ = _read_table(project_dir, "survey")
    if collars is None or survey is None:
        raise SystemExit("No traces.{parquet,csv} found, and missing collars/survey for on-the-fly desurvey.")
    return minimum_curvature_desurvey(collars, survey)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--value-field", required=True)
    p.add_argument("--ref-dip", required=True, type=float)
    p.add_argument("--ref-dip-azimuth", required=True, type=float)
    p.add_argument("--table", default="assays")
    p.add_argument("--length", type=float, default=1.0)
    p.add_argument("--method", default="average", choices=("average", "min", "max", "sum"))
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    df, _ = _read_table(project_dir, args.table)
    if df is None:
        p.error(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")
    if args.value_field not in df.columns:
        p.error(f"--value-field {args.value_field!r} not in {args.table}")

    traces = _resolve_traces(project_dir)

    composites = composite_true_thickness(
        df,
        traces,
        args.value_field,
        ref_dip=args.ref_dip,
        ref_dip_azimuth=args.ref_dip_azimuth,
        length=args.length,
        method=args.method,
    )

    out = args.output or (
        project_dir
        / "composites"
        / f"{args.table}_{args.value_field}_truethk_{args.length}m.parquet"
    )
    _write_table(composites, out)

    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Source: {args.table} ({len(df):,} rows, {df['hole_id'].nunique()} holes)")
    print(f"Reference plane: dip={args.ref_dip}°, dip-az={args.ref_dip_azimuth}°")
    print(f"Composites: {len(composites):,} at {args.length} m true-thickness, method={args.method}")
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
