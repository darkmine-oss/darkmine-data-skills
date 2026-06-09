#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Import downhole-geophysics LAS files into a Baselode project."""

import argparse
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.las import load_geophysics_las


def _collect_sources(path, recursive):
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise SystemExit(f"--source not a file or directory: {path}")
    iterator = path.rglob("*.las") if recursive else path.glob("*.las")
    files = sorted(iterator)
    if not files:
        raise SystemExit(f"No .las files found under {path}")
    return files


def _write_table(df, path, fmt):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.to_parquet(path, compression="snappy", index=False)
    else:
        df.to_csv(path, index=False)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--hole-id", default=None)
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--null-sentinel", type=float, default=None)
    p.add_argument("--output-name", default="geophysics")
    p.add_argument("--format", choices=("parquet", "csv"), default="parquet")
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    sources = _collect_sources(args.source.resolve(), args.recursive)
    if args.hole_id is not None and len(sources) > 1:
        p.error("--hole-id is only valid with a single LAS file")

    frames = []
    for las_path in sources:
        try:
            df = load_geophysics_las(
                las_path,
                hole_id=args.hole_id,
                null_sentinel=args.null_sentinel,
            )
        except Exception as exc:
            print(f"WARN: skipping {las_path.name}: {exc}", file=sys.stderr)
            continue
        frames.append(df)

    if not frames:
        raise SystemExit("No LAS files imported successfully.")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["hole_id", "depth"]).reset_index(drop=True)

    out = project_dir / f"{args.output_name}.{args.format}"
    _write_table(combined, out, args.format)

    channels = [c for c in combined.columns if c not in ("hole_id", "depth")]
    print(f"Imported: {len(sources)} LAS files")
    print(f"Rows: {len(combined):,} over {combined['hole_id'].nunique()} holes")
    print(f"Channels ({len(channels)}): {', '.join(channels)}")
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
