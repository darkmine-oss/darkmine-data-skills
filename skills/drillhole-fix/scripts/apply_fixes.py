#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Apply Baselode's automated drillhole QA fixes to a project folder.

Wraps :mod:`baselode.drill.validate`'s fix helpers.  Non-destructive:
writes a parallel ``fixed/`` directory rather than overwriting the
source files.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from baselode.drill.validate import (
    drop_orphan_intervals,
    fix_overlaps,
    fix_single_station_surveys,
    normalize_azimuth,
    swap_inverted_intervals,
)

VALID_FIXES = (
    "inverted-intervals",
    "orphan-intervals",
    "overlaps",
    "normalize-azimuth",
    "single-station-surveys",
)
EXTENSIONS_BY_PRIORITY = ("parquet", "csv")
INTERVAL_TABLE_NAMES = ("assays", "geology", "structure")


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
        df.to_parquet(path.with_suffix(".parquet"), compression="snappy", index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _parse_fixes(arg):
    if arg.strip().lower() == "all":
        return list(VALID_FIXES)
    requested = [f.strip() for f in arg.split(",") if f.strip()]
    bad = [f for f in requested if f not in VALID_FIXES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown --fix value(s): {bad}; valid: {VALID_FIXES} (or 'all')"
        )
    # Honour the canonical apply order, not the input order.
    return [f for f in VALID_FIXES if f in requested]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    p.add_argument("--fix", required=True, type=_parse_fixes,
                   help=f"Comma-separated subset of {VALID_FIXES} (or 'all')")
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--interval-tables", default=None,
                   help=f"Comma-separated subset of {INTERVAL_TABLE_NAMES}.  Default: all present.")
    p.add_argument("--overlap-touching-tol", type=float, default=0.01,
                   help="Maximum overlap (m) treated as a snap-me rounding glitch.  Default 0.01.")
    p.add_argument("--overlap-merge-tol", type=float, default=0.05,
                   help="Max relative diff between a candidate superset and its inner mean.  Default 0.05.")
    p.add_argument("--overlap-coverage-min", type=float, default=0.95,
                   help="Min coverage of a candidate superset by finer rows.  Default 0.95.")
    args = p.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")
    out_dir = (args.out_dir or (project_dir / "fixed")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    collar, c_fmt = _read_table(project_dir, "collars")
    if collar is None:
        p.error(f"Required 'collars' table not found in {project_dir}")
    survey, s_fmt = _read_table(project_dir, "survey")

    interval_names = args.interval_tables.split(",") if args.interval_tables else None
    if interval_names:
        interval_names = [t.strip() for t in interval_names if t.strip()]
        bad = [t for t in interval_names if t not in INTERVAL_TABLE_NAMES]
        if bad:
            p.error(f"--interval-tables values not recognised: {bad}; valid: {INTERVAL_TABLE_NAMES}")
    else:
        interval_names = list(INTERVAL_TABLE_NAMES)

    interval_tables = {}
    for name in interval_names:
        df, fmt = _read_table(project_dir, name)
        if df is not None:
            interval_tables[name] = (df, fmt)

    report = {}
    conflicts_by_table = {}
    overlap_reports = []

    # 1. swap inverted intervals first — corrects from/to ordering that
    #    later checks read.
    if "inverted-intervals" in args.fix:
        for name, (df, fmt) in interval_tables.items():
            before = (df.get("to", 0) < df.get("from", 0)).sum() if "to" in df.columns and "from" in df.columns else 0
            fixed = swap_inverted_intervals(df)
            interval_tables[name] = (fixed, fmt)
            report.setdefault("inverted-intervals", []).append(
                {"table": name, "rows_swapped": int(before)}
            )

    # 2. drop orphans
    if "orphan-intervals" in args.fix:
        for name, (df, fmt) in interval_tables.items():
            before_rows = len(df)
            fixed = drop_orphan_intervals(df, collar)
            dropped = before_rows - len(fixed)
            interval_tables[name] = (fixed, fmt)
            report.setdefault("orphan-intervals", []).append(
                {"table": name, "rows_dropped": int(dropped)}
            )

    # 3. fix overlaps — the load-bearing one.  Resolves touching /
    #    duplicate / resampled-superset overlaps automatically and
    #    surfaces genuine conflicts to a review CSV.
    if "overlaps" in args.fix:
        for name, (df, fmt) in interval_tables.items():
            if df.empty or "from" not in df.columns or "to" not in df.columns:
                continue
            before_rows = len(df)
            fixed, conflicts, overlap_report = fix_overlaps(
                df,
                touching_tol=args.overlap_touching_tol,
                merge_tol=args.overlap_merge_tol,
                coverage_min=args.overlap_coverage_min,
                return_diagnostics=True,
            )
            interval_tables[name] = (fixed, fmt)
            kinds = overlap_report["kind"].value_counts().to_dict() if not overlap_report.empty else {}
            report.setdefault("overlaps", []).append({
                "table": name,
                "rows_before": int(before_rows),
                "rows_after": int(len(fixed)),
                "by_kind": {k: int(v) for k, v in kinds.items()},
                "conflicts_remaining": int(len(conflicts)),
            })
            if not conflicts.empty:
                conflicts_by_table[name] = conflicts
            if not overlap_report.empty:
                overlap_reports.append(overlap_report.assign(table=name))

    # 4. normalize azimuth
    if "normalize-azimuth" in args.fix and survey is not None:
        before = ((survey["azimuth"] < 0) | (survey["azimuth"] >= 360)).sum() if "azimuth" in survey.columns else 0
        survey = normalize_azimuth(survey)
        report["normalize-azimuth"] = {"rows_normalised": int(before)}

    # 5. pad single-station surveys — nice-to-have, runs last.
    if "single-station-surveys" in args.fix and survey is not None:
        before_rows = len(survey)
        survey = fix_single_station_surveys(survey, collar)
        padded = len(survey) - before_rows
        report["single-station-surveys"] = {"holes_padded": int(padded)}

    # Write all tables back out under fixed/.
    _write_table(collar, out_dir / "collars", c_fmt)
    if survey is not None:
        _write_table(survey, out_dir / "survey", s_fmt or "parquet")
    for name, (df, fmt) in interval_tables.items():
        _write_table(df, out_dir / name, fmt)

    # Persist overlap conflicts + audit log.
    for name, conflicts in conflicts_by_table.items():
        review_path = out_dir / "conflicts" / f"{name}_overlaps_to_review.csv"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        conflicts.to_csv(review_path, index=False)
    if overlap_reports:
        combined = pd.concat(overlap_reports, ignore_index=True)
        combined.to_csv(out_dir / "overlap_audit_log.csv", index=False)

    (out_dir / "fix_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("Applied fixes:")
    # Lead with overlaps (the load-bearing fix), then the others.
    headline = [f for f in ("overlaps",) if f in args.fix]
    rest = [f for f in args.fix if f not in headline]
    for fix_name in headline + rest:
        entry = report.get(fix_name)
        print(f"  - {fix_name}: {entry}")
    if conflicts_by_table:
        total_conflicts = sum(len(c) for c in conflicts_by_table.values())
        print(f"  ! {total_conflicts} row(s) still in overlap conflict — see conflicts/*.csv for review")
    rel = out_dir.relative_to(project_dir) if out_dir.is_relative_to(project_dir) else out_dir
    print(f"Wrote: {rel}/ (+ fix_report.json{', overlap_audit_log.csv' if overlap_reports else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
