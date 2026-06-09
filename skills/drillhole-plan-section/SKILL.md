---
name: drillhole-plan-section
description: Project drillhole traces (and optional interval samples) into a plan view or a cross-section frame, then render as a Plotly 2D scatter. Wraps `baselode.drill.view_2d.plan_view` and `section_view`. Use when a user asks to "plot a plan view of the holes", "give me a cross section through 9000mE 12000mN at azimuth 90", or "show a section of assays coloured by Au".
---

# Drillhole Plan / Section

Produce a 2D plan view or vertical cross-section.

## Inputs

A Baselode project folder containing:
- `traces.{parquet,csv}` (or `collars` + `survey` for on-the-fly desurvey)
- Optionally an interval table to overlay (`assays`, `geology`, etc.) — the script will attach XYZ to it via `attach_assay_positions`.

## Command

```bash
# Plan view
python skills/drillhole-plan-section/scripts/render_view.py PROJECT_DIR plan \
    [--depth-slice TOP,BOTTOM] \
    [--colour-by au_ppm] \
    [--overlay-table assays] \
    [--output OUT.html]

# Section view
python skills/drillhole-plan-section/scripts/render_view.py PROJECT_DIR section \
    --origin EASTING,NORTHING \
    --azimuth 90 \
    [--width 50] \
    [--colour-by au_ppm] \
    [--overlay-table assays] \
    [--output OUT.html]
```

- `--depth-slice TOP,BOTTOM` — keep only trace samples whose `z` (elevation) is within `[BOTTOM, TOP]`.
- `--origin` — section anchor in `EASTING,NORTHING`.
- `--azimuth` — section orientation (degrees from north).
- `--width` — section corridor full-width in metres (default 50 — i.e. ±25 m).
- `--colour-by` — column to colour the markers/lines by (numeric or categorical).
- `--overlay-table` — interval table to attach XYZ to and plot alongside the traces.
- `--output` — output file.  Default: `PROJECT_DIR/views/<plan|section_<az>>.html`.

## Outputs

A standalone HTML Plotly figure (CDN-loaded plotly.js).  Use `.png`/`.svg`/`.pdf` suffix on `--output` for static export (requires Kaleido).

## Notes For Agents

- The section frame is `(along, across)` where `along` = distance along the azimuth and `across` = perpendicular distance from the section plane (clipped to ±half-width).
- For exploration scoping, run `plan` first to find a sensible origin, then a `section` through it.
- The overlay table is filtered to the same depth-slice / corridor before plotting.
