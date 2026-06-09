---
name: drillhole-composite
description: Composite drillhole assay/geology intervals to a fixed downhole length using Baselode's length-weighted IDW-style compositor. Supports soft-boundary mode (composites cross contacts), hard-boundary mode (composites reset at every change in a coded domain column like lithology), and three residual-handling rules. Use when a user asks to "composite these holes to 2 m", "1 m composites of Au_ppm", "lithology-respecting composites", or similar resource-style compositing tasks.
---

# Drillhole Composite

Use this skill when a user asks to composite drillhole intervals — typically assays or geophysics — down to a fixed bin length.  Wraps `baselode.drill.composite.composite_intervals` over a Baselode project folder.

## Modes

**Soft boundary** (default, `--mode soft`)
- Bins extend across each hole's full `[min(from), max(to))` range.
- Composites may cross geological contacts; values are length-weighted across whatever source intervals overlap the bin.
- Matches the FractalGeoAnalytics `dhcomp` / Leapfrog convention.

**Hard boundary** (`--mode hard --boundary-col COL`)
- Composites reset at every change in `COL` within a hole (e.g. lithology, regolith, alteration).
- No composite spans a coded contact.
- Three residual-handling rules for the short tail at the end of a domain:
  - `--residual discard` (default) — drop the residual.
  - `--residual add_to_previous` — merge the residual into the previous composite within the same domain.
  - `--residual distribute` — choose `round(D / length)` equal-length bins covering the whole domain.

## Inputs

A Baselode project folder.  Reads the selected interval table:

```
project/
├── collars.{parquet,csv}    (not directly used; left in place)
├── assays.{parquet,csv}     (default --table)
├── geology.{parquet,csv}    (optional --table geology)
└── ...
```

The interval table must carry `hole_id`, `from`, `to`, and the column named via `--value-col`.  Hard-boundary mode also needs the column named via `--boundary-col`.

## Command

```bash
python skills/drillhole-composite/scripts/composite_intervals.py \
    PROJECT_DIR \
    --value-col au_ppm \
    --length 2.0 \
    --output OUT_PATH \
    [--method average|sum] \
    [--mode soft|hard] \
    [--boundary-col lithology] \
    [--residual discard|add_to_previous|distribute] \
    [--table assays|geology|geophysics] \
    [--from-col from] [--to-col to]
```

Required:
- `PROJECT_DIR` — Baselode project folder.
- `--value-col` — the numeric column to composite.
- `--length` — composite length in metres (must be > 0).

Optional:
- `--output` — output file path.  Both `.csv` and `.parquet` extensions are accepted; the format is inferred.  Defaults to `PROJECT_DIR/composites/<table>_<value-col>_<length>m_<mode>.{csv}`.
- `--table` — which interval table to read.  Default `assays`.
- `--method {average,sum}` — length-weighted average (default) or sum.
- `--mode {soft,hard}` — boundary handling.  Default `soft`.
- `--boundary-col` — required when `--mode hard`.
- `--residual {discard,add_to_previous,distribute}` — hard-mode tail handling.  Default `discard`.
- `--from-col` / `--to-col` — column-name overrides.  Defaults `from` / `to`.

## Outputs

A single tabular file with the composites.  Columns: `hole_id`, `from`, `to`, `<value-col>`, plus `<boundary-col>` in hard mode.

Also prints a summary to stdout:

```
Composited 14,608 source intervals from 89 holes
  table:        assays
  value_col:    au_ppm
  length:       2.0 m
  mode:         soft
  method:       average
Result: 5,231 composites
Wrote: composites/assays_au_ppm_2.0m_soft.csv (267 KB)
```

## Notes For Agents

- Mass balance is preserved: `sum(value × overlap)` over source intervals equals the contribution into the composites (within each bin's coverage window in `average` mode; over the full hole in `sum` mode, modulo intervals dropped by hard-mode residual handling).
- The output Parquet, when chosen, uses Snappy compression for compatibility with the same browser readers that consume Baselode project files.
- True-thickness compositing (perpendicular-to-reference-plane bins) is available via `baselode.drill.composite.composite_true_thickness` but is **not** wrapped here yet — needs a desurveyed trace, which the desurvey skill produces.  Run that first, then a follow-up skill can wrap true-thickness if/when needed.
