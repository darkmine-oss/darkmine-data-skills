---
name: drillhole-fix
description: Apply Baselode's automated drillhole-QA fixes to a project folder — auto-resolve safe interval overlaps (touching, duplicate, resampled superset, and dataset-precedence via `--prefer-dataset`), swap inverted intervals, drop orphan intervals, drop unusable survey rows, synthesise a collar station for holes with no usable survey, wrap azimuths to `[0, 360)`, and pad single-station surveys. Pairs with `drillhole-validate`: validate flags issues with fix recipes, this skill applies them. Use when a user asks to "fix the overlaps", "QA this project and fix what you safely can", "drop orphan assays", "normalize azimuths", "rebuild the missing surveys", "prefer the 0.5 m campaign", or "auto-fix the QA issues".
version: v0.1.0
---

# Drillhole Fix

Apply targeted fixes to a Baselode project folder.  Each fix maps to one of `baselode.drill.validate`'s helper functions.  Overlaps are the load-bearing failure mode (they corrupt compositing, intercepts, IDW) and should be the headline finding in any QA summary, but the canonical apply order is `inverted-intervals` → `orphan-intervals` → `overlaps` → `unusable-survey-rows` → `synthesise-collar-station` → `normalize-azimuth` → `single-station-surveys` — inversions are corrected before overlap classification reads from/to, and the survey fixes run last in an order where each one feeds the next.

| `--fix` value | Helper | What it does |
|---|---|---|
| `overlaps` | `fix_overlaps(table)` | **Critical.** Resolves safe overlaps automatically (see classes below) and surfaces only genuine value-conflicts for human review. |
| `inverted-intervals` | `swap_inverted_intervals(table)` | Swap `from` / `to` where `to < from` (data-entry slip). |
| `orphan-intervals` | `drop_orphan_intervals(table, collar)` | Drop interval rows whose `hole_id` doesn't appear in `collars`. |
| `unusable-survey-rows` | `drop_unusable_survey_rows(survey)` | Drop survey rows whose depth / azimuth / dip is null or non-numeric.  Desurvey already ignores them, so no trace changes — the table just stops lying about what it holds. |
| `synthesise-collar-station` | `synthesise_collar_station(survey, collar)` | For each hole with no usable survey station (every row unusable, or no rows at all), add a station at depth 0 oriented from the collar's `azimuth` / `dip` columns (`--collar-azimuth-col` / `--collar-dip-col`, matched case-insensitively).  Falls back to vertical and *counts* those holes in the report. |
| `normalize-azimuth` | `normalize_azimuth(survey)` | Wrap survey azimuth into `[0, 360)` — `360` → `0`, negatives → `+360`. |
| `single-station-surveys` | `fix_single_station_surveys(survey, collar)` | For each hole with exactly one usable survey station (including ones just synthesised), append a synthetic second station at `collar.max_depth` so desurvey can build a straight-line trace. |

## Overlap classes resolved automatically

| Class | Pattern | Fix |
|---|---|---|
| **Touching** | `A.to > B.from` by less than `--overlap-touching-tol` (default 0.01 m) | Snap `A.to = B.from` (float-rounding cleanup) |
| **Duplicate** | Identical `(hole_id, from, to)` *and* identical value columns | Drop all but the first |
| **Resampled superset** | A longer interval fully contains shorter ones whose length-weighted mean ≈ longer's value within `--overlap-merge-tol` (default 5%) AND covers `--overlap-coverage-min` (default 95%) | Drop the longer, keep the higher-resolution rows |
| **Dataset precedence** (opt-in) | Two overlapping rows come from different datasets listed in `--prefer-dataset` | Drop the row from the lower-ranked dataset.  Rows from unlisted datasets are never dropped this way |
| **Conflict** | Same depth zone, materially different values, or partial overlap | Left in place; written to `conflicts/<table>_overlaps_to_review.csv` |

Dataset precedence is the rule-based answer to two sampling campaigns interleaved over the same depths (say 0.5 m and 1 m intervals from different programs).  `--prefer-dataset "campaign_0.5m,campaign_1m"` keeps the 0.5 m rows wherever the two overlap and leaves 1 m rows alone where they're the only coverage.  The dataset lives in `--dataset-col` (default `project_id`, which is what the GSWA converter writes from the raw `Dataset` field).

## Inputs

A Baselode project folder.  Tables read on demand:

- `collars.{parquet,csv}` — required.
- `survey.{parquet,csv}` — for the survey-targeting fixes.
- `assays.{parquet,csv}` / `geology.{parquet,csv}` / `structure.{parquet,csv}` — for the interval-targeting fixes (when present).

## Command

```bash
python skills/drillhole-fix/scripts/apply_fixes.py PROJECT_DIR \
    --fix overlaps,inverted-intervals,orphan-intervals,unusable-survey-rows,synthesise-collar-station,normalize-azimuth,single-station-surveys \
    [--out-dir OUT_DIR] \
    [--interval-tables assays,geology,structure] \
    [--overlap-touching-tol 0.01] \
    [--overlap-merge-tol 0.05] \
    [--overlap-coverage-min 0.95] \
    [--prefer-dataset DATASET_A,DATASET_B] [--dataset-col project_id] \
    [--collar-azimuth-col azimuth] [--collar-dip-col dip]
```

- `--fix` (required) — comma-separated list, or `all`.
- `--out-dir` — output directory (default: `PROJECT_DIR/fixed/`).  Original files are never touched.
- `--interval-tables` — restrict the interval-targeting fixes to a subset.
- `--overlap-*` — tune the overlap classifier (see table above).
- `--prefer-dataset` — dataset values in priority order, highest first; enables the dataset-precedence overlap class.  `--dataset-col` names the column (default `project_id`).
- `--collar-azimuth-col` / `--collar-dip-col` — collar columns `synthesise-collar-station` reads the planned orientation from (default `azimuth` / `dip`, matched case-insensitively; dip negative = down).

## Outputs

```
fixed/
├── collars.parquet                       (mirrored unchanged)
├── survey.parquet                        (unusable rows dropped, missing holes synthesised, azimuth normalised, single-stations padded)
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
      "by_kind": { "duplicate": 4, "superset": 5, "touching": 2, "precedence": 3497 },
      "conflicts_remaining": 3,
      "precedence": { "column": "project_id", "order": ["campaign_0.5m", "campaign_1m"], "applied": true }
    }
  ],
  "inverted-intervals":     [{"table": "assays", "rows_swapped": 2}],
  "orphan-intervals":       [{"table": "assays", "rows_dropped": 0}],
  "unusable-survey-rows":   {"rows_dropped": 134},
  "synthesise-collar-station": {
    "holes_synthesised": 134, "from_collar": 130, "vertical_fallback": 4,
    "vertical_fallback_holes": ["TRBC041", "..."], "rows_dropped": 134,
    "collar_columns": {"azimuth": "azimuth", "dip": "dip"}
  },
  "normalize-azimuth":      {"rows_normalised": 7},
  "single-station-surveys": {"holes_padded": 137}
}
```

The `precedence` block only appears when `--prefer-dataset` was passed; `vertical_fallback_holes` is capped at 50 entries (`vertical_fallback_holes_truncated: true` when cut).

## Notes For Agents

- **Lead with overlaps in your summary** — they're the failure mode that breaks downstream analytics.  Single-station-survey counts can be high but are mostly cosmetic; don't make them the headline.
- All fixes are **non-destructive**: `PROJECT_DIR` is never modified.  Point downstream skills (`drillhole-desurvey`, `drillhole-composite`, etc.) at the `fixed/` folder.
- The canonical apply order is deterministic: `inverted-intervals` → `orphan-intervals` → `overlaps` → `unusable-survey-rows` → `synthesise-collar-station` → `normalize-azimuth` → `single-station-surveys`.  Inversions are corrected before overlap classification reads from/to; the survey fixes run last and in dependency order (drop the junk rows, rebuild the holes that are now empty, wrap any collar-sourced azimuth, then pad the single stations — including the ones just synthesised — to `max_depth`).
- Anything left in `conflicts/*.csv` is genuinely surgical: same depth zone, materially different values.  These need a geologist, not an agent.  Flag them, don't guess.  The one exception is interleaved campaigns: if the conflict rows split cleanly by `project_id` (or another dataset column), ask which campaign should win and re-run with `--prefer-dataset` rather than hand-editing thousands of rows.
- `synthesise-collar-station` reports how many holes fell back to vertical.  Say so in the summary — a vertical guess for a hole that was actually drilled at -60° puts every sample in the wrong place, so the user should know which holes to treat with suspicion (`fix_report.json` lists them).
- Re-run `drillhole-validate` against the `fixed/` folder to confirm the issue count dropped.
