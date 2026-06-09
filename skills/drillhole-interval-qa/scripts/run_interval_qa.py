#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Run interval-table QA helpers from baselode.drill.intervals."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.intervals import (
    clip,
    detect_gaps,
    detect_overlaps,
    merge_tables,
    split_at,
)

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


def _default_output(project_dir, table, action, ext):
    return project_dir / "qa" / f"{table}_{action}.{ext}"


def _cmd_gaps(args, project_dir):
    df, _ = _read_table(project_dir, args.table)
    if df is None:
        raise SystemExit(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")
    result = detect_gaps(df, min_gap=args.min_gap)
    out = args.output or _default_output(project_dir, args.table, "gaps", "csv")
    _write_table(result, out)
    print(f"Scanned {len(df):,} {args.table} rows from {df['hole_id'].nunique()} holes")
    print(f"Found {len(result)} gap(s) (min_gap={args.min_gap} m)")
    return out


def _cmd_overlaps(args, project_dir):
    df, _ = _read_table(project_dir, args.table)
    if df is None:
        raise SystemExit(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")
    result = detect_overlaps(df)
    out = args.output or _default_output(project_dir, args.table, "overlaps", "csv")
    _write_table(result, out)
    print(f"Scanned {len(df):,} {args.table} rows from {df['hole_id'].nunique()} holes")
    print(f"Found {len(result)} overlap(s)")
    return out


def _cmd_split_at(args, project_dir):
    df, fmt = _read_table(project_dir, args.table)
    if df is None:
        raise SystemExit(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")
    depths = [float(d) for d in args.depths.split(",")]
    result = split_at(df, depths)
    out = args.output or _default_output(project_dir, args.table, "split", fmt or "parquet")
    _write_table(result, out)
    print(f"Split {len(df):,} {args.table} rows at {depths} → {len(result):,} rows")
    return out


def _cmd_clip(args, project_dir):
    df, fmt = _read_table(project_dir, args.table)
    if df is None:
        raise SystemExit(f"Could not find {args.table}.{{parquet,csv}} in {project_dir}")
    result = clip(df, from_depth=args.from_depth, to_depth=args.to_depth)
    out = args.output or _default_output(project_dir, args.table, "clip", fmt or "parquet")
    _write_table(result, out)
    print(f"Clipped {len(df):,} {args.table} rows to [{args.from_depth}, {args.to_depth}) → {len(result):,} rows")
    return out


def _cmd_merge_tables(args, project_dir):
    names = [t.strip() for t in args.tables.split(",") if t.strip()]
    tables = []
    for name in names:
        df, _ = _read_table(project_dir, name)
        if df is None:
            raise SystemExit(f"Could not find {name}.{{parquet,csv}} in {project_dir}")
        tables.append(df)
    result = merge_tables(tables)
    stem = "_".join(names) + "_merged"
    out = args.output or _default_output(project_dir, stem, "merge", "parquet")
    _write_table(result, out)
    print(f"Merged {len(names)} tables → {len(result):,} segmented rows")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    sub = p.add_subparsers(dest="action", required=True)

    g = sub.add_parser("gaps")
    g.add_argument("--table", default="assays")
    g.add_argument("--min-gap", type=float, default=0.0)
    g.add_argument("--output", type=Path, default=None)

    o = sub.add_parser("overlaps")
    o.add_argument("--table", default="assays")
    o.add_argument("--output", type=Path, default=None)

    s = sub.add_parser("split-at")
    s.add_argument("--table", default="assays")
    s.add_argument("--depths", required=True, help="Comma-separated list of depths (m)")
    s.add_argument("--output", type=Path, default=None)

    c = sub.add_parser("clip")
    c.add_argument("--table", default="assays")
    c.add_argument("--from-depth", type=float, default=None)
    c.add_argument("--to-depth", type=float, default=None)
    c.add_argument("--output", type=Path, default=None)

    m = sub.add_parser("merge-tables")
    m.add_argument("--tables", required=True, help="Comma-separated list of interval-table stems")
    m.add_argument("--output", type=Path, default=None)

    args = p.parse_args(argv)
    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    dispatch = {
        "gaps": _cmd_gaps,
        "overlaps": _cmd_overlaps,
        "split-at": _cmd_split_at,
        "clip": _cmd_clip,
        "merge-tables": _cmd_merge_tables,
    }
    out = dispatch[args.action](args, project_dir)
    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
