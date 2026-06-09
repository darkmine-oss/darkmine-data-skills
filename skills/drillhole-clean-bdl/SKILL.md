---
name: drillhole-clean-bdl
description: Clean below-detection-limit (BDL) sentinels out of an interval table (typically assays) so downstream visualisation and statistics aren't skewed by `<X` strings or negative-number BDL encodings. Wraps `baselode.drill.validate.replace_below_detection_limit`. Use when a user asks to "replace BDL with half-MDL", "clean the negative assays", "convert `<0.005` to numeric", or notices the 3D viewer's colour ramp wasting half its range on negative grades.
---

# Drillhole Clean BDL

Replace below-detection-limit sentinels in an interval table with imputed values.  Handles both BDL conventions:

| Source value | Treated as | Default replacement (half-MDL) |
|---|---|---|
| `"<0.005"` (string) | BDL at MDL=0.005 | 0.0025 |
| `-0.005` (numeric negative) | BDL at MDL=0.005 | 0.0025 |
| `-10.0` | BDL at MDL=10.0 | 5.0 |
| `0.0` or positive | Real measurement | (untouched) |

## Inputs

A Baselode project folder containing an interval table (default `assays`).

## Command

```bash
python skills/drillhole-clean-bdl/scripts/clean_bdl.py PROJECT_DIR \
    [--table assays] \
    [--columns au_ppm,cu_ppm,...] \
    [--strategy half-mdl|mdl|zero|nan] \
    [--no-numeric-negatives] \
    [--out-dir OUT_DIR]
```

- `--table` — interval table (default `assays`).
- `--columns` — comma-separated list of columns to clean.  Default: every column whose name ends in an analyte-unit suffix (`_ppm`, `_ppb`, `_pct`, `_oz_t`, `_g_t`).  This guard prevents false positives on columns like `latitude`, `dip`, `azimuth`, or `elevation` that legitimately carry negatives.
- `--strategy` — replacement rule.  Default `half-mdl`.
  - `half-mdl`: replace with `MDL / 2` (industry standard for stats).
  - `mdl`: replace with `MDL` (full detection limit).
  - `zero`: replace with `0.0`.
  - `nan`: replace with `NaN` (renders as "no data" in the viewer — best for colour ramps that don't have a "zero" anchor).
- `--no-numeric-negatives` — opt out of treating numeric negatives as BDL.  Use this only if the column genuinely encodes signed values (e.g. magnetic susceptibility residuals).  Default treats them as BDL.
- `--out-dir` — destination directory.  Default: `PROJECT_DIR/cleaned/`.  Original files are never modified.

## Outputs

```
cleaned/
├── assays.parquet       (BDL sentinels replaced)
└── bdl_report.json      (per-column counts)
```

`bdl_report.json` shape:

```json
{
  "table": "assays",
  "strategy": "half-mdl",
  "columns": {
    "au_ppm": { "string_replaced": 0, "negative_replaced": 1208 },
    "cu_ppm": { "string_replaced": 4,  "negative_replaced": 322 },
    "ag_ppm": { "string_replaced": 0,  "negative_replaced": 76 }
  }
}
```

## Notes For Agents

- BDL handling is **lossy** by definition — the original CSV's distinction between "<0.005 detected to one MDL" and "<0.001 detected to a tenth of that MDL" is collapsed into a single numeric value.  Keep the original assays file around if you want to retrace the choice later.
- `half-mdl` is the geochemistry-stats default and what most QA reports assume.  Pick `nan` when the goal is purely visual (drillhole colour-by in the 3D viewer): NaN values render as "no data" and the colour ramp tightens around real positive grades.
- After cleaning, point the 3D viewer at `cleaned/` (or copy `cleaned/assays.parquet` over the original) to see the improved ramp.
- This skill does **not** touch geology / structure columns — only numeric/string analyte columns in the target table.
