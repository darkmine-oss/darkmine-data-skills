---
name: drillhole-attach-positions
description: Attach XYZ positions to every assay (or any interval-table) row by interpolating along desurveyed traces. Wraps `baselode.drill.desurvey.attach_assay_positions`. Use when a user asks to "give me 3D positions for every assay", "attach XYZ to intervals", "build a points file from assays", or needs interval-midpoint coordinates for downstream interpolation/plotting.
---

# Drillhole Attach Positions

Attach `easting / northing / elevation` columns to every row of an interval table by interpolating along the project's desurveyed traces.

## Inputs

A Baselode project folder containing:
- An interval table (default `assays.{parquet,csv}`)
- A trace table — either `traces.{parquet,csv}` (already desurveyed) or `collars.{parquet,csv}` + `survey.{parquet,csv}` (this skill will run desurvey itself with `min-curvature`).

## Command

```bash
python skills/drillhole-attach-positions/scripts/attach_positions.py PROJECT_DIR \
    [--table assays] \
    [--anchor midpoint|from|to] \
    [--output OUT_PATH]
```

- `--table` — interval table (default `assays`).
- `--anchor` — which depth along each interval gets the position (default `midpoint`).
- `--output` — output file.  Default: `PROJECT_DIR/<table>_with_xyz.parquet`.

## Outputs

The original interval table plus three new columns:

| Column | Meaning |
|---|---|
| `easting` | Interpolated X (project CRS) |
| `northing` | Interpolated Y |
| `elevation` | Interpolated Z |

## Notes For Agents

- If `traces.{parquet,csv}` is missing, the script desurveys on the fly with `interpolate_trajectory(min-curvature)` and caches nothing — re-run `drillhole-desurvey` first if you want a persistent trace table.
- Rows whose `hole_id` has no trace are dropped from the output with a stderr warning.
- The output keeps every original column — you can feed it straight into the IDW / volume-interpolation tools.
