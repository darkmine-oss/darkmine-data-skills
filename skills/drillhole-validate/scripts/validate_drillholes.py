# Copyright (C) 2026 Darkmine Pty Ltd.

# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the Baselode drillhole-database validation suite over a project folder.

Loads collar + survey + interval tables from canonical filenames
(``collars`` / ``survey`` / ``assays`` / ``geology`` / ``structure``) in
Parquet or CSV form, calls
:func:`baselode.drill.validate.validate_drillhole_db`, and writes a JSON
+ text report to ``PROJECT_DIR/qa/`` (or a caller-supplied OUT_DIR).
Exits non-zero when any ``error``-severity issues are found.

Usage
-----
python skills/drillhole-validate/scripts/validate_drillholes.py PROJECT_DIR [OUT_DIR]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

if __package__:
    from . import check_coverage
else:
    import check_coverage

# Canonical project filenames, in the order they're loaded.  Each
# entry maps to (table_name_for_validator, is_required).  Collar +
# survey go straight in; the rest become entries in `interval_tables`.
INTERVAL_TABLES = ("assays", "geology", "structure")
# Same convention the baselode-frontend uses: Parquet wins when
# both formats exist next to each other.
EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


def _read_table(project_dir, stem):
    """Return (DataFrame, format) for ``stem.{parquet,csv}``, or (None, None) when neither exists."""
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if not path.exists():
            continue
        if ext == "parquet":
            return pd.read_parquet(path), "parquet"
        return pd.read_csv(path), "csv"
    return None, None


def _format_issue(issue):
    parts = [
        f"[{issue.get('severity', '?').upper():<7}]",
        f"{issue.get('check', '?')}",
    ]
    table = issue.get("table")
    if table:
        parts.append(f"table={table}")
    hole = issue.get("hole_id")
    if hole:
        parts.append(f"hole={hole}")
    row_index = issue.get("row_index")
    if row_index is not None:
        parts.append(f"row={row_index}")
    msg = issue.get("message")
    if msg:
        parts.append(f"-- {msg}")
    fix = issue.get("fix")
    if fix:
        parts.append(f"(fix: {fix})")
    return " ".join(parts)


def _write_text_report(report, path):
    lines = []
    summary = report["summary"]
    lines.append("Baselode drillhole validation report")
    lines.append("=" * len(lines[-1]))
    lines.append("")
    lines.append('Checks performed and coverage (WA structural QAQC only):')
    for check in report.get('checks', []):
        lines.append(f"  {check['check']} / {check['table']}: {check['status']}; "
                     f"{check['evaluated_rows']} evaluated, {check['excluded_rows']} excluded. "
                     f"{check.get('reason') or ''}")
    lines.append('Surface QAQC, laboratory QAQC and unmapped raw tables are not checked.')
    lines.append("")
    lines.append(
        f"Severity counts: {summary.get('error', 0)} error / "
        f"{summary.get('warning', 0)} warning / {summary.get('info', 0)} info"
    )
    lines.append("")

    # Group issues by check, severity-descending within each.
    grouped = defaultdict(list)
    for issue in report["issues"]:
        grouped[issue.get("check", "(unknown)")].append(issue)

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    for check, issues in sorted(grouped.items()):
        lines.append(f"## {check}  ({len(issues)})")
        for issue in sorted(issues, key=lambda i: severity_rank.get(i.get("severity"), 99)):
            lines.append(f"  {_format_issue(issue)}")
        lines.append("")

    if not report["issues"]:
        lines.append("No issues detected — every check passed.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(report, formats_loaded):
    summary = report["summary"]
    print("Loaded tables:")
    for stem, fmt in formats_loaded.items():
        suffix = f" ({fmt})" if fmt else " (missing)"
        print(f"  - {stem}{suffix}")
    print()
    print(
        f"Severity counts: "
        f"{summary.get('error', 0)} error / "
        f"{summary.get('warning', 0)} warning / "
        f"{summary.get('info', 0)} info"
    )
    if not report["issues"]:
        print("No issues detected.")
        return
    # Print up to 20 issues for the eyeball pass; full list lives in the file.
    print(f"\nFirst {min(20, len(report['issues']))} issues:")
    for issue in report["issues"][:20]:
        print(f"  {_format_issue(issue)}")
    if len(report["issues"]) > 20:
        print(f"  ... +{len(report['issues']) - 20} more (see report files)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_dir", type=Path, help="Path to a Baselode project folder")
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Where to write the report files (default: PROJECT_DIR/qa)",
    )
    parser.add_argument(
        "--allow-full-circle",
        action="store_true",
        help="Accept azimuth=360 as valid (default: rejected per [0, 360) convention)",
    )
    parser.add_argument(
        "--no-print-summary",
        dest="print_summary",
        action="store_false",
        help="Suppress stdout summary; still writes the report files",
    )
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        parser.error(f"PROJECT_DIR does not exist or is not a directory: {project_dir}")

    out_dir = (args.out_dir or (project_dir / "qa")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    formats_loaded = {}

    collar, fmt = _read_table(project_dir, "collars")
    formats_loaded["collars"] = fmt
    if collar is None:
        parser.error(f"Required table 'collars' not found in {project_dir}")

    survey, fmt = _read_table(project_dir, "survey")
    formats_loaded["survey"] = fmt
    if survey is None:
        # Run with an empty survey DataFrame so the collar-level checks
        # still execute and the missing-survey shape is reported.
        survey = pd.DataFrame(columns=["hole_id", "depth", "azimuth", "dip"])

    interval_tables = {}
    for stem in INTERVAL_TABLES:
        df, fmt = _read_table(project_dir, stem)
        formats_loaded[stem] = fmt
        if df is not None:
            interval_tables[stem] = df

    report = check_coverage.validate(
        collar, survey, interval_tables,
        allow_full_circle=args.allow_full_circle,
    )
    report['dataset'] = {'holes': len(collar), 'survey_rows': len(survey),
                         **{name + '_rows': len(table) for name, table in interval_tables.items()}}
    report['tables_loaded'] = formats_loaded

    json_path = out_dir / "drillhole_validation_report.json"
    text_path = out_dir / "drillhole_validation_report.txt"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _write_text_report(report, text_path)

    if args.print_summary:
        _print_summary(report, formats_loaded)
        print()
        print(f"Wrote: {json_path.relative_to(project_dir) if json_path.is_relative_to(project_dir) else json_path}")
        print(f"Wrote: {text_path.relative_to(project_dir) if text_path.is_relative_to(project_dir) else text_path}")

    if not report['complete']:
        return 2
    return 1 if report["summary"].get("error", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
