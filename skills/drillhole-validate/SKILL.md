---
name: drillhole-validate
description: Run the full Baselode drillhole-database QA pass over a project folder. Detects duplicate hole IDs, survey rows with null azimuth/dip, holes with no usable survey station, single-station surveys, out-of-range azimuth/dip, orphan intervals, negative-length intervals, intervals beyond max depth, gaps, overlaps, and below-detection-limit sentinels. Use when a user asks to "QA these drill holes", "find overlaps", "check the assays", or otherwise wants a structural integrity report on a Baselode project before downstream work like compositing or desurveying.
version: v0.1.0
---

# Drillhole Validate

Use this skill when a user asks to QA a drillhole database — find overlapping intervals, gaps, orphan rows, or any other structural issues — over a Baselode project folder.

## What It Checks

Wraps `baselode.drill.validate.validate_drillhole_db` over a project folder.  The check matrix:

**Collar / survey**
- Duplicate `hole_id` in collars (`error`)
- Survey rows with a null or non-numeric depth / azimuth / dip (`error`, `survey_null_orientation`) — desurvey silently ignores these rows
- Holes with no usable survey station at all, including collar holes with no survey rows (`warning`, `survey_no_usable_stations`) — these silently drop out of the desurvey
- Survey holes that have only a single usable station (`warning`)
- Azimuth out of `[0, 360)` (or `[0, 360]` with `--allow-full-circle`)
- Dip out of `[-90, 90]`

**Per interval table (assays / geology / structure / …)**
- Orphan intervals (no matching collar)
- Negative `to < from`
- Intervals beyond the collar's `max_depth`
- Gaps between consecutive intervals on the same hole
- Overlaps between consecutive intervals on the same hole
- Below-detection-limit sentinels (e.g. `"<0.05"` strings in numeric assay columns)

Every issue carries a severity (`error` / `warning` / `info`), the affected hole / table / row, a human-readable message, and a fix recipe when one's available.

## Inputs

A Baselode project folder containing canonical files in CSV or Parquet form (Parquet preferred when both exist):

```
project/
├── collars.{parquet,csv}    (required)
├── survey.{parquet,csv}     (required for survey checks)
├── assays.{parquet,csv}     (optional)
├── geology.{parquet,csv}    (optional)
└── structure.{parquet,csv}  (optional)
```

`collars` is required.  Other tables are validated when present and skipped silently when absent.

## Command

```bash
python skills/drillhole-validate/scripts/validate_drillholes.py PROJECT_DIR [OUT_DIR]
```

- `PROJECT_DIR` — path to a Baselode project folder.
- `OUT_DIR` — optional; where to write the `drillhole_validation_report.json` (and `.txt` summary).  Defaults to `PROJECT_DIR/qa/`.

Options:

- `--allow-full-circle` — accept `azimuth = 360` as valid (default rejects it as the strict `[0, 360)` mathematical convention).
- `--print-summary` (default on) — also print a one-line-per-check summary to stdout for quick eyeballing.
- `--no-print-summary` — suppress stdout summary; still writes the files.

## Outputs

- `drillhole_validation_report.json` — full structured report:
  ```json
  {
    "summary": { "error": 12, "warning": 5, "info": 0 },
    "issues":  [ { "check": "interval_overlap", "severity": "error", ... }, ... ]
  }
  ```
- `drillhole_validation_report.txt` — human-readable per-issue listing grouped by check + severity.

## Exit Code

- `0` if no `error`-severity issues were found (`warning` and `info` allowed).
- `1` if any error-severity issues exist.

So a CI step like `python ... && echo ok` works without parsing the report.

## Notes For Agents

- Reads Parquet via `pyarrow` if available, else `pandas.read_parquet` (which needs `pyarrow` or `fastparquet` installed).
- The Parquet-vs-CSV preference is fixed: Parquet wins when both exist for a given table.  Mirrors the loader in `baselode-frontend`.
- If the hole count in a desurvey output is lower than the collar count, look at `survey_no_usable_stations` first — it lists exactly the holes desurvey will drop.  The fix recipe is `drillhole-fix --fix unusable-survey-rows,synthesise-collar-station,single-station-surveys`.

## Deployed execution and coverage

The installable Python package exposes `drillhole-validate` and pins the tested
Baselode engine. JSON/TXT reports include per-check/table execution coverage,
including zero-finding checks, excluded inputs, skipped checks and failures.
An empty/absent survey is reported for collar holes. Exit code 2 indicates
incomplete execution; exit code 1 indicates error findings only when a valid
complete report was written. Surface/laboratory QAQC and unmapped tables are
not implicitly checked. See `.features/project-qaqc-package.md`.

Copyright (C) 2026 Darkmine Pty Ltd.
