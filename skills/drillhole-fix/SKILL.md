---
name: drillhole-fix
description: Apply Baselode's automated drillhole-QA fixes to a project folder — auto-resolve safe interval overlaps (touching, duplicate, resampled superset), swap inverted intervals, drop orphan intervals, wrap azimuths to `[0, 360)`, and pad single-station surveys. Pairs with `drillhole-validate`: validate flags issues with fix recipes, this skill applies them. Use when a user asks to "fix the overlaps", "QA this project and fix what you safely can", "drop orphan assays", "normalize azimuths", or "auto-fix the QA issues".
---

# Drillhole Fix

Apply targeted fixes to a Baselode project folder.  Each fix maps to one of `baselode.drill.validate`'s helper functions, ordered by *severity* — overlaps are the load-bearing failure mode (they corrupt compositing, intercepts, IDW), so they run first by convention:

| `--fix` value | Helper | What it does |
|---|---|---|
| `overlaps` | `fix_overlaps(table)` | **Critical.** Resolves safe overlaps automatically (see classes below) and surfaces only genuine value-conflicts for human review. |
| `inverted-intervals` | `swap_inverted_intervals(table)` | Swap `from` / `to` where `to < from` (data-entry slip). |
| `orphan-intervals` | `drop_orphan_intervals(table, collar)` | Drop interval rows whose `hole_id` doesn't appear in `collars`. |
| `normalize-azimuth` | `normalize_azimuth(survey)` | Wrap survey azimuth into `[0, 360)` — `360` → `0`, negatives → `+360`. |
| `single-station-surveys` | `fix_single_station_surveys(survey, collar)` | *Nice-to-have.* For each hole with exactly one survey station, append a synthetic second station at total depth so desurvey can build a straight-line trace. |

## Overlap classes resolved automatically

| Class | Pattern | Fix |
|---|---|---|
| **Touching** | `A.to > B.from` by less than `--overlap-touching-tol` (default 0.01 m) | Snap `A.to = B.from` (float-rounding cleanup) |
| **Duplicate** | Identical `(hole_id, from, to)` *and* identical value columns | Drop all but the first |
| **Resampled superset** | A longer interval fully contains shorter ones whose length-weighted mean ≈ longer's value within `--overlap-merge-tol` (default 5%) AND covers `--overlap-coverage-min` (default 95%) | Drop the longer, keep the higher-resolution rows |
| **Conflict** | Same depth zone, materially different values, or partial overlap | Left in place; written to `conflicts/<table>_overlaps_to_review.csv` |

## Inputs

A Baselode project folder.  Tables read on demand:

- `collars.{parquet,csv}` — required.
- `survey.{parquet,csv}` — for the survey-targeting fixes.
- `assays.{parquet,csv}` / `geology.{parquet,csv}` / `structure.{parquet,csv}` — for the interval-targeting fixes (when present).

## Command

```bash
python skills/drillhole-fix/scripts/apply_fixes.py PROJECT_DIR \
    --fix overlaps,inverted-intervals,orphan-intervals,normalize-azimuth,single-station-surveys \
    [--out-dir OUT_DIR] \
    [--interval-tables assays,geology,structure] \
    [--overlap-touching-tol 0.01] \
    [--overlap-merge-tol 0.05] \
    [--overlap-coverage-min 0.95]
```

- `--fix` (required) — comma-separated list, or `all`.
- `--out-dir` — output directory (default: `PROJECT_DIR/fixed/`).  Original files are never touched.
- `--interval-tables` — restrict the interval-targeting fixes to a subset.
- `--overlap-*` — tune the overlap classifier (see table above).

## Outputs

```
fixed/
├── collars.parquet                       (mirrored unchanged)
├── survey.parquet                        (azimuth normalised, single-stations padded)
├── assays.parquet                        (overlaps resolved, orphans dropped, etc.)
├── geology.parquet
├── conflicts/
│   └── assays_overlaps_to_review.csv     (only when conflicts remain)
├── overlap_audit_log.csv                 (per-row trail of what was resolved)
└── fix_report.json                       (counts per fix)
```

`fix_report.json` shape:

```json
{
  "overlaps": [
    {
      "table": "assays",
      "rows_before": 1207,
      "rows_after": 1196,
      "by_kind": { "duplicate": 4, "superset": 5, "touching": 2 },
      "conflicts_remaining": 3
    }
  ],
  "inverted-intervals":     [{"table": "assays", "rows_swapped": 2}],
  "orphan-intervals":       [{"table": "assays", "rows_dropped": 0}],
  "normalize-azimuth":      {"rows_normalised": 7},
  "single-station-surveys": {"holes_padded": 3}
}
```

## Notes For Agents

- **Lead with overlaps in your summary** — they're the failure mode that breaks downstream analytics.  Single-station-survey counts can be high but are mostly cosmetic; don't make them the headline.
- All fixes are **non-destructive**: `PROJECT_DIR` is never modified.  Point downstream skills (`drillhole-desurvey`, `drillhole-composite`, etc.) at the `fixed/` folder.
- The canonical apply order is deterministic: `inverted-intervals` → `orphan-intervals` → `overlaps` → `normalize-azimuth` → `single-station-surveys`.  Inversions are corrected before overlap classification reads from/to, and the survey-targeting fixes run last (they don't interact with intervals).
- Anything left in `conflicts/*.csv` is genuinely surgical: same depth zone, materially different values.  These need a geologist, not an agent.  Flag them, don't guess.
- Re-run `drillhole-validate` against the `fixed/` folder to confirm the issue count dropped.
