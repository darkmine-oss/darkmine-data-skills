#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Composite drillhole intervals using Baselode's length-weighted compositor.

Reads an interval table (default ``assays``) from a Baselode project
folder, calls :func:`baselode.drill.composite.composite_intervals`,
and writes a tabular result.  Supports both soft- and hard-boundary
modes; in hard mode the residual handling rule is selectable.

Usage
-----
python skills/drillhole-composite/scripts/composite_intervals.py PROJECT_DIR \\
    --value-col au_ppm --length 2.0 [options]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from baselode.drill.composite import composite_intervals


EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


def _read_table(project_dir, stem):
    """Return (DataFrame, format) for ``stem.{parquet,csv}`` — parquet wins."""
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
        raise ValueError(f"Unsupported output extension: {ext!r} (use .csv or .parquet)")


def _human_bytes(n_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_dir", type=Path, help="Path to a Baselode project folder")
    parser.add_argument("--value-col", required=True, help="Column to composite")
    parser.add_argument("--length", required=True, type=float, help="Composite length in metres (> 0)")
    parser.add_argument(
        "--table",
        default="assays",
        help="Which interval table to read (default: assays)",
    )
    parser.add_argument(
        "--method",
        choices=("average", "sum"),
        default="average",
        help="Length-weighted average (default) or sum",
    )
    parser.add_argument(
        "--mode",
        choices=("soft", "hard"),
        default="soft",
        help="Soft (default) lets composites cross contacts; hard resets at boundary_col changes",
    )
    parser.add_argument(
        "--boundary-col",
        default=None,
        help="Required in --mode hard: column that defines domains within a hole",
    )
    parser.add_argument(
        "--residual",
        choices=("discard", "add_to_previous", "distribute"),
        default="discard",
        help="Hard-mode tail handling (default: discard)",
    )
    parser.add_argument("--from-col", default="from")
    parser.add_argument("--to-col", default="to")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file (.csv or .parquet).  Defaults to PROJECT_DIR/composites/<stem>.csv",
    )
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        parser.error(f"PROJECT_DIR does not exist or is not a directory: {project_dir}")
    if args.length <= 0:
        parser.error(f"--length must be > 0, got {args.length}")
    if args.mode == "hard" and not args.boundary_col:
        parser.error("--mode hard requires --boundary-col")

    df, fmt = _read_table(project_dir, args.table)
    if df is None:
        parser.error(
            f"Could not find {args.table}.parquet or {args.table}.csv in {project_dir}"
        )
    for col in (args.from_col, args.to_col, args.value_col, "hole_id"):
        if col not in df.columns:
            parser.error(
                f"Column {col!r} not in {args.table}.{fmt}; available: "
                f"{list(df.columns)[:20]}{'...' if len(df.columns) > 20 else ''}"
            )
    if args.mode == "hard" and args.boundary_col not in df.columns:
        parser.error(
            f"--boundary-col {args.boundary_col!r} not in {args.table}.{fmt}; "
            f"available: {list(df.columns)[:20]}"
        )

    composites = composite_intervals(
        df,
        args.value_col,
        from_col=args.from_col,
        to_col=args.to_col,
        length=args.length,
        method=args.method,
        mode=args.mode,
        boundary_col=args.boundary_col,
        residual=args.residual,
    )

    if args.output is None:
        suffix = f"{args.table}_{args.value_col}_{args.length}m_{args.mode}.csv"
        out_path = project_dir / "composites" / suffix
    else:
        out_path = args.output.resolve()
    _write_table(composites, out_path)

    n_holes = df["hole_id"].nunique() if "hole_id" in df.columns else "?"
    print(f"Composited {len(df):,} source intervals from {n_holes} holes")
    print(f"  table:     {args.table}")
    print(f"  value_col: {args.value_col}")
    print(f"  length:    {args.length} m")
    print(f"  mode:      {args.mode}")
    if args.mode == "hard":
        print(f"  boundary:  {args.boundary_col}")
        print(f"  residual:  {args.residual}")
    print(f"  method:    {args.method}")
    print(f"Result: {len(composites):,} composites")
    if out_path.exists():
        rel = out_path.relative_to(project_dir) if out_path.is_relative_to(project_dir) else out_path
        print(f"Wrote: {rel} ({_human_bytes(out_path.stat().st_size)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
