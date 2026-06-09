#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Clean below-detection-limit sentinels from an interval table."""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.validate import BDL_STRATEGIES, replace_below_detection_limit

EXTENSIONS_BY_PRIORITY = ("parquet", "csv")
_BDL_STRING_RE = re.compile(r"^\s*<\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$")

# Column-name suffixes that mark a column as an assay analyte.  Other
# columns (latitude, dip, depth, etc.) often carry legitimate negative
# values and should NOT be auto-cleaned.
ANALYTE_SUFFIXES = (
    "_ppm",   # parts-per-million (most common)
    "_ppb",   # parts-per-billion
    "_pct",   # percent
    "_oz_t",  # ounces per ton
    "_g_t",   # grams per ton
)


def _read_table(project_dir, stem):
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if path.exists():
            df = pd.read_parquet(path) if ext == "parquet" else pd.read_csv(path)
            return df, ext
    return None, None


def _write_table(df, path, fmt):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.to_parquet(path.with_suffix(".parquet"), compression="zstd", index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _count_string_bdl(series):
    if not pd.api.types.is_string_dtype(series):
        return 0
    n = 0
    for value in series:
        if isinstance(value, str) and _BDL_STRING_RE.match(value):
            n += 1
    return n


def _count_negative_bdl(series, enabled):
    if not enabled or not pd.api.types.is_numeric_dtype(series):
        return 0
    return int((series < 0).sum())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--table", default="assays")
    p.add_argument("--columns", default=None,
                   help="Comma-separated columns to clean.  Default: all numeric or string columns.")
    p.add_argument("--strategy", choices=BDL_STRATEGIES, default="half-mdl")
    p.add_argument("--no-numeric-negatives", dest="numeric_negatives",
                   action="store_false", default=True,
                   help="Skip negative-numeric BDL handling.  Use when negatives are real signed values.")
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    df, fmt = _read_table(project_dir, args.table)
    if df is None:
        p.error(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")

    if args.columns:
        columns = [c.strip() for c in args.columns.split(",") if c.strip()]
        missing = [c for c in columns if c not in df.columns]
        if missing:
            p.error(f"Requested columns not present in {args.table}: {missing}")
    else:
        # Auto-detect: assay columns are typed by their unit suffix.  This
        # avoids false positives on columns like `latitude`, `dip`, `azimuth`,
        # or `elevation` that legitimately carry negative values.
        columns = [
            c for c in df.columns
            if c.lower().endswith(ANALYTE_SUFFIXES)
            and (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]))
        ]
        if not columns:
            p.error(
                f"No analyte columns auto-detected in {args.table} (expected names "
                f"ending in {ANALYTE_SUFFIXES}).  Pass --columns to list them explicitly."
            )

    per_column = {}
    for col in columns:
        per_column[col] = {
            "string_replaced": _count_string_bdl(df[col]),
            "negative_replaced": _count_negative_bdl(df[col], args.numeric_negatives),
        }

    cleaned = replace_below_detection_limit(
        df,
        columns=columns,
        strategy=args.strategy,
        numeric_negative_sentinels=args.numeric_negatives,
    )

    out_dir = (args.out_dir or (project_dir / "cleaned")).resolve()
    _write_table(cleaned, out_dir / args.table, fmt or "parquet")

    report = {
        "table": args.table,
        "strategy": args.strategy,
        "numeric_negatives": args.numeric_negatives,
        "rows": len(cleaned),
        "columns": per_column,
    }
    (out_dir / "bdl_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    total_str = sum(v["string_replaced"] for v in per_column.values())
    total_neg = sum(v["negative_replaced"] for v in per_column.values())
    touched_cols = [c for c, v in per_column.items() if v["string_replaced"] or v["negative_replaced"]]

    print(f"Source: {args.table} ({len(df):,} rows, {len(columns)} candidate columns)")
    print(f"Strategy: {args.strategy}")
    print(f"Replaced: {total_str:,} '<X' strings + {total_neg:,} negative numerics across {len(touched_cols)} columns")
    if touched_cols and total_str + total_neg > 0:
        topn = sorted(touched_cols, key=lambda c: -(per_column[c]["string_replaced"] + per_column[c]["negative_replaced"]))[:5]
        for c in topn:
            v = per_column[c]
            print(f"  {c:20s}  strings={v['string_replaced']:>6}  negatives={v['negative_replaced']:>6}")
    rel = out_dir.relative_to(project_dir) if out_dir.is_relative_to(project_dir) else out_dir
    print(f"Wrote: {rel}/{args.table}.{fmt or 'parquet'} (+ bdl_report.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
