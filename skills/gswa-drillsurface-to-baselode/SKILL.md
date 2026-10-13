---
name: gswa-drillsurface-to-baselode
description: Convert GSWA drillhole and surface-sample parquet dumps (postgres_gswa/*.parquet) into Baselode-compatible project files, including collars, surveys, assays, geology, structure, desurveyed traces, and flattened raw tables for baselode-frontend or AI data tools.
metadata:
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
This branch requires its pinned Baselode source candidate for attribute expansion.
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
Keep the original raw Parquets alongside the Baselode outputs. Unreviewed
EAV mappings remain explicitly outside converted coverage. The
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
Use project/AOI-sized exports: this mode currently materializes geology and structural EAV
records in memory; state-scale batching remains outside this execution path.

For preserving-mode branch development, from this repository root run:

```bash
python -m pip install -r requirements.txt
```

The bootstrap skill now installs the same checkout dependency with all extras.
Exports without geology attributes or structural tables still work without importing that API.
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


## Preserving structural observations

Preserving mode writes one `structure` row per source Id with original `from`/`to`,
`_source_structure_id`, `_source_collar_id` and `depth = from`. Missing end depths
stay null; absent end-depth source columns are not created. Plotting uses the
start depth, without replacing the interval extent. This convention is documented
in Baselode's plotting code and the structural processing script.

The reviewed mapping in `scripts/structure_attributes.py` promotes Dip,
Dip_Direction (structural azimuth), Alpha, Beta, Structure_Type, Structure_Origin,
Origin_Reliability, Weathering and Comments. Core-relative and logged plane angles
remain separate. Sparse Plane_*, Computed_Plane_* and local angles remain distinct
JSON attributes; they do not backfill generic orientation fields.

Reuse the same source-record/conflict expansion as geology. Numeric projections
retain original text in JSON; failed/non-finite numeric parses become flat nulls
with `_numeric_parse_issues` and manifest counts. Finite angles outside expected
ranges remain unchanged for QAQC. Source type/origin/reliability codes are not decoded.
No normalization or alpha/beta interpretation runs during conversion.

Source parent and attribute IDs must be unique/non-null with resolvable attribute
parents; missing structural parent tables with nonempty attributes fail explicitly.
The incomplete marker and source preservation rules above also apply here.

Legacy measured `DipDrn` and comment `StructComment`/`Description` aliases remain
supported with lower priority, using the existing public GSWA mapping meanings.
Generic `Type`/`Reliability` are deliberately not equated with `Structure_Type`/
`Origin_Reliability` without source codebook evidence; alternative `alpha_2`,
`beta_2` and `a` fields also stay distinct JSON attributes. No cross-field
interpretation is inferred merely because a name occurs in an older vocabulary.

The validator recognizes structural point views by their `depth` column, even
when original bounds are retained. It reports interval checks as outside
structural coverage instead of marking valid null end depths as broken intervals.
Structural orientation and extent QAQC remain a separate subsequent stage.

Structural parents require Id, FromDepth and CollarId (the existing Collarid
spelling is also accepted). Missing start-depth columns make conversion explicitly
incomplete rather than manufacturing an anchor or silently omitting a present
table. Original source column names remain intact in parent JSON evidence.


## Preserving downhole geochemistry

When `dbo_dhgeochemistry` is present, preserving mode uses one assay row per
source Id, retaining repeats, sample identifiers and original depth bounds.
The publisher flat table is a separate comparison source, not a parent-ID join
or an overwrite. Exports without raw parents retain the previous flat path;
nonempty attributes without their parent table fail explicitly.

The installed `scripts/geochemistry_analyte_map.csv` maps exact reviewed labels
to 34 elemental columns. Error labels, oxides, method-specific and repeat labels
remain distinct JSON evidence until explicitly mapped. Punctuation-stripping
normalization must not make `Cu +/-` an alias of Cu. Descriptor promotion reuses
Baselode's text/evidence primitive; chemical projection uses exact labels.

Each numeric field uses the supplied `PPMValue` without rescaling or a raw-text
fallback. Finite candidates with known LT/GT, valid-less-than, no-data, metadata
or bad-data flags (or explicit leading < or > source text) remain in JSON and
cannot supply an exact-value flat projection. Null flags are preserved as null;
projection eligibility does not establish scientific validity. Negative finite
values without a source qualifier are preserved for subsequent QAQC.

All eligible candidates must agree exactly to populate a flat field. Otherwise
it stays null, with `_conflicts` and `_assay_selection` exposing original IDs,
candidates and exclusion reasons. No averaging, first-row winner, half-limit
substitution or superseded-record filtering occurs. All source parent/attribute
scalars, flags and method references remain in the JSON evidence ledger.

The writer batches complete source parent groups, making projection independent
of child row ordering and parent batch size. It materializes the project-sized
Arrow attribute table but bounds Python dictionaries/JSON to each parent batch;
state-scale external-memory processing remains outside this path. Invalid/null/
duplicate source IDs, orphan attributes or non-boolean qualifier flags produce an
incomplete run rather than an invented relationship.

Source provenance and projection counts are conversion evidence. Follow with
explicit unit/method, qualifier and repeated-analysis QAQC before modelling;
the general interval validator does not validate all nested assay semantics.

For partial exports with raw parent headers and populated publisher flat results,
missing or empty `dbo_dhgeochemistryattr` makes full source-record conversion explicitly
incomplete. Fetch/include the attribute file before retrying; do not treat a
header-only projection as converted assays. Header-only exports without any flat
results may still preserve their source records with empty projection coverage.
Qualifier schema validation covers every source record, including unmapped labels.

An empty raw parent table does not displace populated publisher flat assays;
that export retains the flat path with raw empty tables outside converted coverage.
Source collar identities keep the full raw column type across parent batches,
including nullable integer keys and batches containing only null collars.
Unmapped convenience values live under `_unmapped_attributes`, keyed by exact
original labels; `Cu` and `Cu +/-` remain distinct there as well as in the ledger.
