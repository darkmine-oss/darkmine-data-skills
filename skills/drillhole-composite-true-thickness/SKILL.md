---
name: drillhole-composite-true-thickness
description: Composite drillhole intervals on a *true-thickness* basis relative to a reference plane (e.g. the lode dip and dip-direction). Wraps `baselode.drill.composite.composite_true_thickness`. Use when a user asks to "composite at 1 m true thickness", "report grades perpendicular to the orebody", or "give me a 0.5 m true-width composite at dip 60 / az 270".
version: v0.1.0
---

# Drillhole True-Thickness Composite

Composite assays on a true-thickness coordinate.  Each source interval is weighted by `cos(angle-between-hole-and-plane-normal)`; the composites then span a fixed amount of true thickness rather than downhole length.

## Inputs

A Baselode project folder containing:
- An interval table (default `assays.{parquet,csv}`)
- Either a precomputed `traces.{parquet,csv}` or `collars` + `survey` (this skill desurveys on the fly if needed).

## Command

```bash
python skills/drillhole-composite-true-thickness/scripts/composite_true_thickness.py PROJECT_DIR \
    --value-field au_ppm \
    --ref-dip 60 \
    --ref-dip-azimuth 270 \
    [--table assays] \
    [--length 1.0] \
    [--method average|min|max|sum] \
    [--output OUT_PATH]
```

Required:
- `--value-field` — column to composite (e.g. `au_ppm`).
- `--ref-dip` — reference plane dip in degrees (0 = horizontal).
- `--ref-dip-azimuth` — reference plane dip-direction in degrees (0 = N, 90 = E).

Optional:
- `--table` — interval table (default `assays`).
- `--length` — composite length in **true** metres (default `1.0`).
- `--method` — aggregation (default `average`, length-weighted).
- `--output` — output path.  Default: `PROJECT_DIR/composites/<table>_<field>_truethk_<length>m.parquet`.

## Outputs

One row per composite:

| Column | Meaning |
|---|---|
| `hole_id` | Hole id |
| `from`, `to` | Downhole start/end (m) of the source span |
| `true_thickness` | True thickness covered (m) |
| `<value-field>` | Composited value |

## Notes For Agents

- Holes whose midpoint orientation is sub-parallel to the reference plane (true-thickness factor close to 0) will produce very few — possibly zero — composites: that is geometrically correct, not a bug.
- Pair with `drillhole-composite` for downhole-length composites; pair with `drillhole-intercepts` to extract significant runs from the true-thickness composite.
