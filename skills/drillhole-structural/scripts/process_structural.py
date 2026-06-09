#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Apply structural-data transforms from baselode.drill.structural."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.desurvey import minimum_curvature_desurvey
from baselode.drill.structural import (
    attach_structure_positions,
    normalize_dip_azimuth,
    project_structures_to_section,
    structural_to_tadpole,
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


def _resolve_traces(project_dir):
    traces, _ = _read_table(project_dir, "traces")
    if traces is not None:
        return traces
    collars, _ = _read_table(project_dir, "collars")
    survey, _ = _read_table(project_dir, "survey")
    if collars is None or survey is None:
        raise SystemExit("Missing traces, and missing collars/survey to desurvey from.")
    return minimum_curvature_desurvey(collars, survey)


def _parse_pair(value):
    parts = [float(x.strip()) for x in value.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected two comma-separated numbers, got {value!r}")
    return tuple(parts)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    sub = p.add_subparsers(dest="action", required=True)

    a = sub.add_parser("attach-positions")
    a.add_argument("--output", type=Path, default=None)

    t = sub.add_parser("tadpole")
    t.add_argument("--scale", type=float, default=1.0)
    t.add_argument("--output", type=Path, default=None)

    s = sub.add_parser("project-to-section")
    s.add_argument("--origin", type=_parse_pair, required=True, help="EASTING,NORTHING")
    s.add_argument("--azimuth", type=float, required=True)
    s.add_argument("--output", type=Path, default=None)

    n = sub.add_parser("normalize-azimuth")
    n.add_argument("--output", type=Path, default=None)

    args = p.parse_args(argv)
    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    structures, _ = _read_table(project_dir, "structure")
    if structures is None:
        p.error(f"Could not find structure.{{parquet,csv}} in {project_dir}")

    if args.action == "attach-positions":
        traces = _resolve_traces(project_dir)
        result = attach_structure_positions(structures, traces)
    elif args.action == "tadpole":
        result = structural_to_tadpole(structures, scale=args.scale)
    elif args.action == "project-to-section":
        result = project_structures_to_section(structures, origin=args.origin, azimuth=args.azimuth)
    else:  # normalize-azimuth
        result = normalize_dip_azimuth(structures)

    out = args.output or (project_dir / "structural" / f"{args.action}.parquet")
    _write_table(result, out)

    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Source: structure ({len(structures):,} rows from {structures['hole_id'].nunique()} holes)")
    print(f"Action: {args.action} → {len(result):,} rows")
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
