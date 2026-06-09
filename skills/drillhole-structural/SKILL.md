---
name: drillhole-structural
description: Process drillhole structural measurements (dip / dip-direction) — attach 3D positions, build tadpole-log coordinates, project to a cross-section, or wrap azimuths into `[0, 360)`. Wraps `baselode.drill.structural.{attach_structure_positions, structural_to_tadpole, project_structures_to_section, normalize_dip_azimuth}`. Use when a user asks to "attach XYZ to structures", "make a tadpole log", "project structures onto this section", or "fix structural azimuths".
version: v0.1.0
---

# Drillhole Structural

Run any of four structural-data transforms on a Baselode project.  Output goes to `PROJECT_DIR/structural/<action>.parquet` by default.

| `action` | Helper | What it produces |
|---|---|---|
| `attach-positions` | `attach_structure_positions(structures, traces)` | Structures table with `easting`, `northing`, `elevation` interpolated along the trace at each row's `depth`. |
| `tadpole` | `structural_to_tadpole(structures, scale=...)` | Two-column `(x, y)` coords for plotting a tadpole log (depth on Y, dip on X, azimuth-tick orientation encoded). |
| `project-to-section` | `project_structures_to_section(structures, origin, azimuth)` | Structures with section-frame coordinates (`along`, `across`) and the in-plane apparent dip. |
| `normalize-azimuth` | `normalize_dip_azimuth(structures)` | Structures with dip-direction wrapped to `[0, 360)` and dip flipped if originally negative. |

## Inputs

A Baselode project folder containing:
- `structure.{parquet,csv}` (required for every action) with at least `hole_id`, `depth`, `dip`, `azimuth`.
- For `attach-positions` and `project-to-section`: `traces.{parquet,csv}` or `collars` + `survey` (this skill desurveys on the fly when needed).

## Command

```bash
python skills/drillhole-structural/scripts/process_structural.py PROJECT_DIR ACTION [...]
```

Per-action arguments:

```bash
# Attach XYZ
... attach-positions [--output OUT]

# Tadpole-log coordinates
... tadpole [--scale 1.0] [--output OUT]

# Section projection
... project-to-section --origin EASTING,NORTHING --azimuth 90 [--output OUT]

# Normalize dip / azimuth
... normalize-azimuth [--output OUT]
```

## Outputs

A Parquet (or CSV via suffix) file with the original columns plus the action's derived columns:

| Action | Added columns |
|---|---|
| `attach-positions` | `easting`, `northing`, `elevation` |
| `tadpole` | `x`, `y` (in the tadpole-plot frame) |
| `project-to-section` | `along`, `across`, `apparent_dip` |
| `normalize-azimuth` | (in-place rewrite of `dip` / `azimuth`) |

## Notes For Agents

- A real *plot* is not produced here — pair with `drillhole-plan-section --overlay-table structure` after `attach-positions` to visualise on a section.
- For oriented core measurements that are in alpha/beta form rather than dip/dip-direction, convert first using `baselode.drill.structural.alpha_beta_to_dip_dipdir` (not exposed by this skill yet).
