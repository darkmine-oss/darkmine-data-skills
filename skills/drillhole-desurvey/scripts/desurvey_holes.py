#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Desurvey drillholes from a Baselode project folder.

Reads ``collars`` + ``survey`` from the project, runs the chosen
Baselode desurvey method (minimum curvature / balanced tangential /
tangential / midpoint tangential), and writes the resulting trace table.
Every trace starts at the collar: when a hole's first station sits below
md 0 its orientation is extended straight up to the collar.  By default writes
to the canonical ``precomputed_desurveyed.{parquet,csv}`` pair the
frontend + downstream skills look for.

Usage
-----
python skills/drillhole-desurvey/scripts/desurvey_holes.py PROJECT_DIR [options]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from baselode.drill.desurvey import (
    balanced_tangential_desurvey,
    midpoint_tangential_desurvey,
    minimum_curvature_desurvey,
    tangential_desurvey,
)

METHODS = {
    "minimum_curvature": minimum_curvature_desurvey,
    "balanced_tangential": balanced_tangential_desurvey,
    "tangential": tangential_desurvey,
    "midpoint_tangential": midpoint_tangential_desurvey,
}
EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


def _read_table(project_dir, stem):
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if not path.exists():
            continue
        if ext == "parquet":
            return pd.read_parquet(path), "parquet"
        return pd.read_csv(path), "csv"
    return None, None


def _write_table(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower().lstrip(".")
    if ext == "parquet":
        df.to_parquet(path, compression="snappy", index=False)
    elif ext == "csv":
        df.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported output extension: {ext!r}")


def _human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_dir", type=Path, help="Path to a Baselode project folder")
    parser.add_argument(
        "--method",
        choices=tuple(METHODS),
        default="minimum_curvature",
        help="Desurvey method (default: minimum_curvature)",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=1.0,
        help="Trace interpolation step in metres between survey stations (default: 1.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Explicit output path (.csv or .parquet).  Overrides the canonical-pair default.",
    )
    parser.add_argument(
        "--no-write-canonical",
        dest="write_canonical",
        action="store_false",
        help=(
            "Skip writing the canonical precomputed_desurveyed.{parquet,csv} pair; "
            "honour only --output"
        ),
    )
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        parser.error(f"PROJECT_DIR does not exist or is not a directory: {project_dir}")
    if args.step <= 0:
        parser.error(f"--step must be > 0, got {args.step}")

    collars, c_fmt = _read_table(project_dir, "collars")
    if collars is None:
        parser.error(f"Required 'collars' table not found in {project_dir}")
    survey, s_fmt = _read_table(project_dir, "survey")
    if survey is None:
        parser.error(f"Required 'survey' table not found in {project_dir}")

    fn = METHODS[args.method]
    traces = fn(collars, survey, step=args.step)
    # Stable sort makes runs diffable.
    if "hole_id" in traces.columns and "md" in traces.columns:
        traces = traces.sort_values(["hole_id", "md"], kind="stable").reset_index(drop=True)

    n_holes = traces["hole_id"].nunique() if "hole_id" in traces.columns else 0
    print(f"Desurveyed {n_holes} holes")
    print(f"  method:  {args.method}")
    print(f"  step:    {args.step} m")
    print(f"Trace rows: {len(traces):,}")

    outputs = []
    if args.write_canonical and args.output is None:
        outputs.append(project_dir / "precomputed_desurveyed.parquet")
        outputs.append(project_dir / "precomputed_desurveyed.csv")
    if args.output is not None:
        outputs.append(args.output.resolve())

    if not outputs:
        # --no-write-canonical AND no --output → write nothing but
        # still surface the summary above.  Returns success.
        return 0

    for out in outputs:
        _write_table(traces, out)
        rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
        print(f"Wrote: {rel} ({_human_bytes(out.stat().st_size)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
