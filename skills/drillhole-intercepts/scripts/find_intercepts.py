#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Find significant assay intercepts in a Baselode project folder.

Wraps :func:`baselode.drill.intercepts.significant_intercepts`.

Usage
-----
python skills/drillhole-intercepts/scripts/find_intercepts.py PROJECT_DIR \\
    --assay-field au_ppm --min-grade 0.5 --min-length 2.0 [--table assays] [--output OUT]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.intercepts import significant_intercepts

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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--assay-field", required=True)
    p.add_argument("--min-grade", required=True, type=float)
    p.add_argument("--min-length", required=True, type=float)
    p.add_argument("--table", default="assays")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    df, fmt = _read_table(project_dir, args.table)
    if df is None:
        p.error(f"Could not find {args.table}.parquet or {args.table}.csv in {project_dir}")
    if args.assay_field not in df.columns:
        p.error(f"--assay-field {args.assay_field!r} not in {args.table}.{fmt}")

    intercepts = significant_intercepts(df, args.assay_field, args.min_grade, args.min_length)

    if args.output is None:
        stem = f"{args.table}_{args.assay_field}_{args.min_grade}x{args.min_length}m.csv"
        out = project_dir / "intercepts" / stem
    else:
        out = args.output.resolve()
    _write_table(intercepts, out)

    print(f"Scanned {len(df):,} {args.table} rows from {df['hole_id'].nunique()} holes")
    print(f"  field:      {args.assay_field}")
    print(f"  min_grade:  {args.min_grade}")
    print(f"  min_length: {args.min_length} m")
    print(f"Result: {len(intercepts)} significant intercept(s)")
    if len(intercepts):
        for _, r in intercepts.head(10).iterrows():
            label = r.get("label")
            if not isinstance(label, str):
                grade = r.get("avg_grade", r.get(args.assay_field, float("nan")))
                length = r.get("length", float("nan"))
                label = f"{length:.1f} m @ {grade:.2f} {args.assay_field}"
            print(f"  {label} — hole {r['hole_id']}")
        if len(intercepts) > 10:
            print(f"  ... +{len(intercepts) - 10} more (see {out})")
    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
