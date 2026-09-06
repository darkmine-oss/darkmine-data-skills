---
name: drillhole-desurvey
description: Desurvey drillholes from collar + survey tables in a Baselode project folder into a 3D trace table with x/y/z/md per depth step.  Wraps Baselode's four desurvey methods (minimum curvature — default, balanced tangential, tangential, midpoint tangential for Vulcan comparisons) and writes a canonical `precomputed_desurveyed.{parquet,csv}` file the frontend and downstream skills (true-thickness compositing, IDW volumes) can consume directly.  Use when a user asks to "desurvey these holes", "compute 3D traces", or "build a precomputed-desurveyed file".
version: v0.1.0
---

# Drillhole Desurvey

Use this skill when a user has collar + survey tables and wants 3D trace coordinates for every hole.

## Methods

| Method | When to pick |
|---|---|
| `minimum_curvature` (default) | The industry standard.  Smooth circular-arc segments between survey stations.  Matches commercial software (Surpac / Vulcan / Datamine) to ≤ a few mm. |
| `balanced_tangential` | Average-of-direction-cosines per segment (Walstrom 1969 / Harvey & Eppink 1972).  Cheaper, slightly less accurate than minimum curvature but matches `wellpathpy.tan_method(choice="bal")` to ≤1 cm on every trajectory including strong-dogleg cases. |
| `tangential` | Pure direction at the top of each segment.  Fastest, drifts noticeably on highly inclined or dog-legged holes — avoid for production unless you're matching a specific upstream tool. |
| `midpoint_tangential` | Vulcan's default "Tangent": each station is the *midpoint* of a straight segment, so orientation changes halfway between stations.  Pick this for a like-for-like comparison against Vulcan output. |

Whatever the method, every trace starts at the collar (md 0).  If a hole's first station sits below the collar — a single station at 135 m, say — that station's orientation is extended straight up to md 0, the same convention Vulcan and Surpac use.

## Inputs

A Baselode project folder containing:

```
project/
├── collars.{parquet,csv}    (required — needs easting/northing/elevation)
├── survey.{parquet,csv}     (required — needs depth/azimuth/dip per hole_id)
└── ...
```

## Command

```bash
python skills/drillhole-desurvey/scripts/desurvey_holes.py PROJECT_DIR \
    [--method minimum_curvature|balanced_tangential|tangential|midpoint_tangential] \
    [--step 1.0] \
    [--output OUT_PATH] \
    [--no-write-canonical]
```

Required:
- `PROJECT_DIR` — Baselode project folder.

Optional:
- `--method` — desurvey method (default `minimum_curvature`).
- `--step` — desired downhole interpolation step in metres between recorded survey stations.  Default `1.0`.  Smaller = denser trace but bigger output file.
- `--output` — explicit output path (`.csv` or `.parquet`).  When omitted (and `--no-write-canonical` is not passed), writes to `PROJECT_DIR/precomputed_desurveyed.parquet` (Snappy) AND `PROJECT_DIR/precomputed_desurveyed.csv` so both browser readers and CLI tools see the same file.
- `--no-write-canonical` — skip the canonical pair; honour only `--output`.

## Outputs

A trace table with one row per `(hole_id, md)` and columns:

| Column | Meaning |
|---|---|
| `hole_id` | Hole identifier (matches collars/survey) |
| `md` | Measured depth along the hole (m) |
| `easting`, `northing`, `elevation` | Projected world coordinates (units = the collar CRS's linear unit) |
| `azimuth`, `dip` | Interpolated orientation at the trace point (deg) |

The output is the canonical shape Baselode's downstream tools expect — `baselode-frontend` reads it directly via its project-loader path, and the IDW + true-thickness skills can pick it up by name.

Also prints a summary:

```
Desurveyed 89 holes
  method:  minimum_curvature
  step:    1.0 m
Trace rows: 23,418
Wrote: precomputed_desurveyed.parquet (612 KB)
Wrote: precomputed_desurveyed.csv     (3.4 MB)
```

## Notes For Agents

- Output is sorted by `(hole_id, md)` for stable diffing across runs.
- A hole with a single survey station below the collar gets a straight trace from md 0 to that station; a single station *at* the collar gives a one-vertex trace.  Run `drillhole-validate` first — it flags these as `single_station_surveys` warnings, and `drillhole-fix --fix single-station-surveys` pads them to the collar `max_depth`.
- Survey rows with a null depth / azimuth / dip are ignored, and a hole with no usable row drops out entirely.  `drillhole-validate` reports both (`survey_null_orientation` errors and `survey_no_usable_stations` warnings); `drillhole-fix --fix synthesise-collar-station` rebuilds the missing holes from the collar orientation.
- The Parquet output uses Snappy compression so browser loaders such as `hyparquet` work without an external ZSTD decompressor.
