#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Export a Baselode project folder as a single OMF file."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.desurvey import minimum_curvature_desurvey
from baselode.drill.omf import (
    collars_to_omf_points,
    intervals_to_omf_lines,
    traces_to_omf_lines,
    write_omf,
)

EXTENSIONS_BY_PRIORITY = ("parquet", "csv")
DEFAULT_INTERVAL_TABLES = ("assays", "geology", "structure")
STRUCTURAL_COLS = {"hole_id", "from", "to"}


def _read_table(project_dir, stem):
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if path.exists():
            return (pd.read_parquet(path) if ext == "parquet" else pd.read_csv(path)), ext
    return None, None


def _comma_list(value):
    if not value:
        return None
    return [s.strip() for s in value.split(",") if s.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--include-intervals", default=None)
    p.add_argument("--collar-cols", default=None)
    p.add_argument("--author", default="baselode")
    p.add_argument("--description", default="")
    p.add_argument("--name", default=None,
                   help="OMF project name (default: project folder name)")

    # Per-table value column flags are forwarded by name.
    for stem in DEFAULT_INTERVAL_TABLES:
        p.add_argument(f"--{stem}-cols", dest=f"{stem}_cols", default=None,
                       help=f"Comma-separated value columns for the {stem} table")
    # Allow custom interval tables too via --include-intervals — value
    # cols default to all-non-structural for tables without a flag.
    args, unknown = p.parse_known_args(argv)
    custom_cols = {}
    i = 0
    while i < len(unknown):
        flag = unknown[i]
        if flag.startswith("--") and flag.endswith("-cols") and i + 1 < len(unknown):
            stem = flag[2:-len("-cols")]
            custom_cols[stem] = _comma_list(unknown[i + 1])
            i += 2
        else:
            p.error(f"Unrecognised argument: {flag!r}")

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    collars, _ = _read_table(project_dir, "collars")
    if collars is None:
        p.error(f"Required 'collars' table not found in {project_dir}")
    if "elevation" not in collars.columns:
        print("WARN: collars has no 'elevation' column — filling with 0.0", file=sys.stderr)
        collars = collars.assign(elevation=0.0)

    traces, _ = _read_table(project_dir, "traces")
    if traces is None:
        survey, _ = _read_table(project_dir, "survey")
        if survey is None:
            p.error("No traces.{parquet,csv} and no survey.{parquet,csv} — cannot build traces.")
        traces = minimum_curvature_desurvey(collars, survey)

    requested = _comma_list(args.include_intervals) or list(DEFAULT_INTERVAL_TABLES)
    elements = []
    elements.append(collars_to_omf_points(
        collars,
        attribute_cols=_comma_list(args.collar_cols),
    ))
    elements.append(traces_to_omf_lines(traces))

    interval_summaries = []
    for stem in requested:
        df, _ = _read_table(project_dir, stem)
        if df is None:
            print(f"WARN: requested interval table {stem!r} not found, skipping", file=sys.stderr)
            continue
        if df.empty:
            print(f"WARN: interval table {stem!r} is empty, skipping", file=sys.stderr)
            continue
        if "from" not in df.columns or "to" not in df.columns:
            print(f"WARN: interval table {stem!r} missing from/to columns, skipping", file=sys.stderr)
            continue
        cols_flag = getattr(args, f"{stem}_cols", None)
        if cols_flag is not None:
            value_cols = _comma_list(cols_flag)
        elif stem in custom_cols:
            value_cols = custom_cols[stem]
        else:
            value_cols = [c for c in df.columns if c not in STRUCTURAL_COLS]
        element = intervals_to_omf_lines(df, traces, name=stem, value_cols=value_cols)
        elements.append(element)
        interval_summaries.append((stem, len(df), value_cols))

    out = args.output or (project_dir / f"{project_dir.name}.omf")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_omf(
        elements,
        path=out,
        name=args.name or project_dir.name,
        author=args.author,
        description=args.description,
    )

    print(f"Collars: {len(collars):,}")
    print(f"Traces: {traces['hole_id'].nunique()} holes")
    for stem, n_rows, value_cols in interval_summaries:
        print(f"  {stem}: {n_rows:,} rows ({len(value_cols)} value cols)")
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
