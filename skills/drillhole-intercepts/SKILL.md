---
name: drillhole-intercepts
description: Find significant assay intercepts in a Baselode project — contiguous downhole runs above a grade threshold with total length above a length threshold.  Wraps `baselode.drill.intercepts.significant_intercepts`.  Use when a user asks to "find significant Au intercepts above 0.5 g/t over 5 m", "extract gold hits from these holes", "report significant Cu intercepts", or similar exploration-style queries.
version: v0.1.0
---

# Drillhole Intercepts

Use this skill to extract significant assay intercepts from a Baselode project folder.  An intercept is a contiguous downhole run where every interval meets or exceeds `min_grade`, and the total run length is at least `min_length`.

## Inputs

A Baselode project folder containing an interval table (default `assays.{parquet,csv}`).

## Command

```bash
python skills/drillhole-intercepts/scripts/find_intercepts.py PROJECT_DIR \
    --assay-field au_ppm \
    --min-grade 0.5 \
    --min-length 2.0 \
    [--table assays] \
    [--output OUT_PATH]
```

Required:
- `PROJECT_DIR` — Baselode project folder.
- `--assay-field` — assay column to threshold on (e.g. `au_ppm`, `cu_pct`).
- `--min-grade` — minimum value an interval must meet to enter a run.
- `--min-length` — minimum total run length (m) to report.

Optional:
- `--table` — interval table to read (default `assays`).
- `--output` — output file (`.csv` or `.parquet`).  Default: `PROJECT_DIR/intercepts/<table>_<field>_<minGrade>x<minLength>.csv`.

## Outputs

One row per significant intercept:

| Column | Meaning |
|---|---|
| `hole_id` | Hole carrying the intercept |
| `from`, `to` | Downhole start/end (m) |
| `length` | `to - from` (m) |
| `avg_grade` | Length-weighted mean of `assay_field` across the run |
| `n_samples` | Number of source intervals in the run |
| `assay_field` | The column name (echoed for downstream filtering) |
| `label` | Pretty string e.g. `"5.0 m @ 1.23 au_ppm"` |

## Notes For Agents

- The threshold is **per source interval**, not per composite — every interval in a run must meet `min_grade`.  Run `drillhole-composite` first if you want intercepts computed against composited bins.
- `0` intercepts is a perfectly valid result; the output file is still written (empty) so downstream tools have a stable contract.
