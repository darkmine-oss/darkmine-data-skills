---
name: drillhole-omf-export
description: Export a Baselode project to an Open Mining Format (.omf) file — collars as a point set, traces as a line set, and any interval tables as colour-able line sets keyed off chosen value columns. Wraps `baselode.drill.omf.{collars_to_omf_points, traces_to_omf_lines, intervals_to_omf_lines, write_omf}`. Use when a user asks to "export to OMF", "share with Leapfrog", "make an OMF for the geologist", "build an OMF with assays and geology coloured", or similar.
---

# Drillhole OMF Export

Bundle a Baselode project into a single `.omf` file that downstream packages (Leapfrog, Surpac, Vulcan plugins, omf-python) can read directly.

## Inputs

A Baselode project folder containing:
- `collars.{parquet,csv}` (required)
- `survey.{parquet,csv}` (required if `traces` is missing — desurveyed on the fly)
- Optional `traces.{parquet,csv}`
- Optional interval tables: any of `assays`, `geology`, `structure`, or custom stems passed via `--include-intervals`.

## Command

```bash
python skills/drillhole-omf-export/scripts/export_omf.py PROJECT_DIR \
    [--output OUT.omf] \
    [--include-intervals assays,geology] \
    [--assays-cols au_ppm,cu_pct] \
    [--geology-cols lithology] \
    [--collar-cols depth_eoh,prospect] \
    [--author "Tamara Vasey"] \
    [--description "GSWA pilot 2026"]
```

- `--output` — destination `.omf`.  Default: `PROJECT_DIR/<folder-name>.omf`.
- `--include-intervals` — comma-separated list of interval tables to ship.  Default: any present out of `assays,geology,structure`.
- `--<table>-cols` — per-table comma-separated list of value columns to attach as per-segment data.  Default: all numeric/object columns except the structural ones (`hole_id`, `from`, `to`).
- `--collar-cols` — extra collar columns to attach as per-vertex data.
- `--author`, `--description` — OMF project metadata.

## Outputs

A single `.omf` file containing:

| Element | Source |
|---|---|
| `collars` (PointSet) | collars + selected attributes |
| `traces` (LineSet) | desurveyed traces |
| `assays`, `geology`, etc. (LineSet per table) | intervals re-projected onto trace geometry |

## Notes For Agents

- Rows missing `easting / northing / elevation` are dropped silently (collars) or skipped (interval rows whose hole isn't in `traces`).
- The OMF write step requires the `omf` Python package — `pip install omf` if it isn't installed.
- For very large datasets prefer Parquet inputs; the script reads them column-by-column into pandas before re-emitting as OMF arrays.
