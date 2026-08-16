---
name: gswa-drillsurface-to-baselode
description: Convert GSWA drillhole and surface-sample parquet dumps (postgres_gswa/*.parquet) into Baselode-compatible project files, including collars, surveys, assays, geology, structure, desurveyed traces, and flattened raw tables for baselode-frontend or AI data tools.
version: v0.1.0
---

# GSWA Drill/Surface To Baselode

Use this skill when a user asks to convert a GSWA drillhole and surface-sample
parquet dump (`postgres_gswa/*.parquet`) into Baselode-compatible project
files for AI agents, data tools, or the `baselode-frontend` folder loader.

## What It Converts

The converter reads table-level GSWA parquet exports, assembles the join shapes
expected by Baselode's raw GSWA adaptor, and writes canonical Baselode files:

- `collars.{parquet,csv}`
- `survey.{parquet,csv}`
- `assays.{parquet,csv}`
- `geology.{parquet,csv}`
- `structure.{parquet,csv}`
- `precomputed_desurveyed.{parquet,csv}` when collar coordinates and surveys
  are available
- `flattened_<source_table>.{parquet,csv}` for every GSWA parent table,
  including joined attribute columns where matching `*attr` tables exist
- `conversion_manifest.json`

Parquet and CSV files both contain the full converted dataset. Parquet is
preferred by Baselode consumers when both formats are supported. Parquet files
are written with Snappy compression so browser loaders such as `hyparquet` can
read them without a custom ZSTD decompressor.

## Dependencies

Requires `baselode` to be importable.  `pip install "baselode[all]"` into the
active Python environment if you haven't already (the [`setup`](../setup/SKILL.md)
skill does this in one shot for a fresh clone).

## Command

From the `darkmine-data-skills` repo root:

```bash
python skills/gswa-drillsurface-to-baselode/scripts/convert_gswa_drillsurface_to_baselode.py SRC_DIR OUT_DIR
```

Example:

```bash
python skills/gswa-drillsurface-to-baselode/scripts/convert_gswa_drillsurface_to_baselode.py \
  path/to/download-drill-and-sample-data/postgres_gswa \
  ../baselode-frontend/test-data/gswa-20260602_033532
```

## Options

- `--hole-id-source company` uses GSWA `CompanyHoleId` as the frontend-facing
  `hole_id` and preserves raw IDs in `datasource_hole_id`. This is the default.
- `--hole-id-source baselode` keeps the raw Baselode/GSWA `HoleId`.

## Notes For Agents

- The source folder should include tables such as `dbo_collar.parquet`,
  `dbo_collarcoordinate.parquet`, `dbo_dhsurvey.parquet`,
  `gsd_dhassayflat.parquet`, `dbo_dhgeology.parquet`, and matching `*attr`
  tables when available.
- The converter delegates canonical schema mapping to
  `baselode.adaptors.raw_gswa.convert`; local code handles table-dump joins,
  frontend cleanup, flattened raw-table exports, GSWA geology attribute aliases,
  and tiny overlap clipping for geology intervals that fail Baselode validation
  after rounding.
- If `structure` has zero rows, the output file is still written so consumers
  can rely on a stable project shape.
