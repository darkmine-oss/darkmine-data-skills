#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Render a single-hole strip log as html / png / svg / pdf."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.view import (
    plot_drillhole_traces_subplots,
    plot_geology_strip_log,
    plot_strip_log,
)

EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


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


def _write_figure(fig, path, fmt):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "html":
        fig.write_html(str(path), include_plotlyjs="cdn")
    else:
        fig.write_image(str(path), format=fmt)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--hole-id", required=True)
    p.add_argument("--mode", choices=("categorical", "geology", "traces"), default="categorical")
    p.add_argument("--table", default=None)
    p.add_argument("--label-col", default="lithology")
    p.add_argument("--value-cols", default=None)
    p.add_argument("--colour-map", default=None)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--format", choices=("html", "png", "svg", "pdf"), default=None)
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    table = args.table or ("geology" if args.mode == "geology" else "assays")
    df, _ = _read_table(project_dir, table)
    if df is None:
        p.error(f"Could not find {table}.{{parquet,csv}} in {project_dir}")
    hole = df[df["hole_id"] == args.hole_id]
    if hole.empty:
        p.error(f"No rows in {table} for hole_id={args.hole_id!r}")

    if args.mode == "categorical":
        fig = plot_strip_log(hole, label_col=args.label_col, colour_map=args.colour_map)
    elif args.mode == "geology":
        fig = plot_geology_strip_log(hole)
    else:  # traces
        value_cols = _comma_list(args.value_cols)
        if not value_cols:
            p.error("--value-cols required for --mode traces")
        configs = [{"type": "numeric", "value_col": c} for c in value_cols]
        fig = plot_drillhole_traces_subplots(hole, configs)

    if args.output:
        out = args.output.resolve()
        fmt = args.format or out.suffix.lstrip(".").lower() or "html"
    else:
        fmt = args.format or "html"
        out = project_dir / "strip_logs" / f"{args.hole_id}_{args.mode}.{fmt}"

    _write_figure(fig, out, fmt)
    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Hole: {args.hole_id}  ({len(hole):,} rows from {table})")
    print(f"Mode: {args.mode}")
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
