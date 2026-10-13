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
- `precomputed_desurveyed.{parquet,csv}` when at least one shared hole has
  usable collar coordinates and survey measurements
- `assays_provenance.{parquet,csv}` only when the EAV path is used and any
  `Flag_*` provenance flag (`Flag_PCT`, `Flag_LT`, `Flag_GT`, ...) is set on
  the source attrs;
  one row per (interval, analyte) with the original `AttributeValue` and
  publisher `PPMValue`
- `flattened_<source_table>.{parquet,csv}` for every GSWA parent table,
  including joined attribute columns where matching `*attr` tables exist
- `conversion_manifest.json`

Parquet and CSV files both contain the full converted dataset. Parquet is
preferred by Baselode consumers when both formats are supported. Parquet files
are written with Snappy compression so browser loaders such as `hyparquet` can
read them without a custom ZSTD decompressor.

## Dependencies

Install the dependencies declared in `pyproject.toml` / `requirements.txt`.
This branch requires its pinned Baselode source candidate for geology expansion.
A historical minimum version alone is insufficient for preserving mode.

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
- Precomputed traces are optional. Missing/null/non-numeric coordinates or
  survey measurements are excluded, and absent/null elevation defaults to
  zero. Trace rows expose this fallback through `elevation_defaulted`. If no
  shared hole remains, the other canonical files are still written
  and `conversion_manifest.json` records `precomputed_desurvey.status` as
  `omitted` with a reason and input/valid row counts.
- CSV/Parquet normalization, atomic file replacement, and the format-versioned
  project manifest use `baselode.export` from Baselode 0.1.47+. GSWA-specific
  source paths, hole-ID policy, flattened table selection, and trace status are
  retained under the manifest's `metadata` object.
- Assay values and unit suffixes are preserved as supplied by GSWA. The
  2026-05 flat release uses `_PCT` for major oxides; `_PPM` remains ppm-labelled
  source data. Publisher values and unit metadata can conflict. Do not treat a
  column name or `Flag_PCT` as proof that every value is normalised.
- Both the 2025-10 and 2026-05 flat table shapes are supported. Spatial fields
  remain in flattened source output (`source_x`, `source_y`, `source_z`);
  default frontend assays retain assay columns and non-spatial metadata, including
  unfamiliar unit suffixes.
  `Y_PPM` remains an analyte; coordinate `Y` does not become yttrium.
- When the flat table is missing, the default converter pivots source
  `PPMValue` and retains flagged source text in `assays_provenance`. This is
  preservation of publisher data, not scientific correction.

## Non-repairing downstream conversion

The installable Python package exposes `gswa-drillsurface-to-baselode`. Add
`--preserve-issues` for a WA Baselode dataset suitable for QAQC. This mode
uses canonical column maps without validation, clipping, orientation repair
or desurvey. It writes source row references and a checksum/coverage manifest.
Keep the original raw Parquets alongside the Baselode outputs. Unsupported
structure/EAV mappings remain explicitly outside converted coverage. The
default frontend conversion mode retains its existing validation behaviour.
Surface assay joins prefer the old `SurfaceSampleId` column when present and
use `Id` for the 2026-05 shape. Repeated flat rows and original values remain
available for downstream QAQC; this converter does not repair assay units.
This mode maps `_PPM`, `_PPB`, `_PCT` analytes; other fields remain raw and are
reported in `unmapped_columns`, outside canonical QAQC coverage. It uses source
Baselode/GSWA hole IDs and rejects explicit `--hole-id-source company`.
Use a new or empty output directory; this mode refuses to mix current output
with files from an earlier conversion.

Copyright (C) 2026 Darkmine Pty Ltd.


## Preserving geology attributes

Preserving mode writes one geology row per source interval, with reviewed text
fields (`lithology`, secondary lithologies, alteration, weathering, colour,
texture, structure, mineralisation, unit, stratigraphy and comments).
`geology_code` mirrors the selected lithology for existing plotting consumers.
The explicit alias table lives in `scripts/geology_attributes.py`.

`attributes_extra` is JSON text containing other normalized attributes, all
original attribute records, parent source metadata and ranked `_conflicts`.
Blank values cannot mask a usable lower-priority candidate. Original values
remain in JSON evidence. `attribute_clash_count` counts conflicting fields.
No clipping, interval repair or company-code decoding occurs.

This branch pins the exact Baselode source candidate providing attribute expansion.
Replace the source dependency with its published version before PyPI publication.
Use project/AOI-sized exports: this mode currently materializes geology EAV
records in memory; state-scale batching remains outside this execution path.

For preserving-mode branch development, from this repository root run:

```bash
python -m pip install -r requirements.txt
```

The bootstrap skill now installs the same checkout dependency with all extras.
Exports without geology attributes still work without importing that API.
This branch uses a development version and is not a PyPI publication candidate
until its source dependency is replaced with a released Baselode version.

### Expansion input requirements

Geology expansion requires unique non-null parent IDs, unique non-null attribute
IDs and resolvable attribute parent keys. Mapped text attributes must be text or
null; unparseable or numeric modification dates on mapped candidates are
rejected. Unmapped values and metadata are preserved without promotion.

If these source-contract requirements fail, the whole conversion is explicitly
incomplete: `.conversion-incomplete` remains and no success manifest is written.
Raw inputs stay unchanged. Inspect the reported source issue before retrying in
a fresh directory. This is intentional: assigning orphan records or choosing
between ambiguous source keys would invent provenance. It differs from
interval-only conversion, which previously retained all EAV records solely raw.
