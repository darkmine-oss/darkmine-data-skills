---
name: drillhole-interval-qa
description: Run interval-table QA on Baselode project tables — detect gaps and overlaps, split intervals at arbitrary depths, clip to a depth window, or merge multiple interval tables into one. Wraps `baselode.drill.intervals` helpers. Use when a user asks to "find sample gaps", "detect overlapping intervals", "split assays at the geology boundaries", "clip to 0-200 m", or "merge assays and geology into one table".
version: v0.1.0
---

# Drillhole Interval QA

Wrap `baselode.drill.intervals` so an agent can ask interval-level questions in plain English.  One script, four sub-commands:

| Sub-command | Helper | What it does |
|---|---|---|
| `gaps` | `detect_gaps(df, min_gap=...)` | Report holes/depths where consecutive intervals are not flush. |
| `overlaps` | `detect_overlaps(df)` | Report holes/depths where intervals overlap. |
| `split-at` | `split_at(df, depths)` | Split every interval that straddles one of `depths` into two rows. |
| `clip` | `clip(df, from_depth, to_depth)` | Keep only the part of every interval inside `[from_depth, to_depth)`. |
| `merge-tables` | `merge_tables(tables)` | Re-segment two-or-more interval tables onto a common from/to grid. |

## Inputs

A Baselode project folder with at least one interval table (`assays`, `geology`, `structure`, or any custom stem).

## Command

```bash
python skills/drillhole-interval-qa/scripts/run_interval_qa.py PROJECT_DIR ACTION [...]
```

Per-action arguments:

```bash
# Find gaps in assays where consecutive intervals are >0.1 m apart
... gaps --table assays --min-gap 0.1 [--output OUT]

# Find overlaps in geology
... overlaps --table geology [--output OUT]

# Split assays at 100, 200, 300 m
... split-at --table assays --depths 100,200,300 [--output OUT]

# Clip geology to [0, 250) m
... clip --table geology --from-depth 0 --to-depth 250 [--output OUT]

# Merge assays + geology onto a common segmentation
... merge-tables --tables assays,geology [--output OUT]
```

Defaults:
- `--output` — for read-only actions (`gaps`, `overlaps`) defaults to `PROJECT_DIR/qa/<table>_<action>.csv`; for mutating actions (`split-at`, `clip`, `merge-tables`) defaults to `PROJECT_DIR/qa/<table>_<action>.parquet`.

## Outputs

`gaps` / `overlaps` — one row per offence:

| Column | Meaning |
|---|---|
| `hole_id` | Hole carrying the gap/overlap |
| `prev_to` | End of the earlier interval |
| `next_from` | Start of the later interval |
| `gap` / `overlap` | Difference (m) |

`split-at` / `clip` / `merge-tables` — new interval table with the same columns as the input.

## Notes For Agents

- `gaps` and `overlaps` are pure diagnostics — they do **not** modify the source table.  Use `drillhole-fix` (or run `split-at` + a downstream filter) to actually repair.
- `merge-tables` is the right tool when downstream skills want one table per hole with combined attributes (e.g. assays merged with geology codes).  Both tables must share `hole_id` / `from` / `to` semantics.
- `split-at` is non-destructive within a single hole: a `100` split inside a `90→110` interval produces a `90→100` row and a `100→110` row, each carrying the original interval's attributes.
