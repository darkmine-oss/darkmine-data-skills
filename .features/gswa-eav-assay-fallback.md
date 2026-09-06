# GSWA converter: EAV assay fallback + provenance sidecar

## Intent

Some GSWA exports ship `dbo_dhgeochemistry` + `dbo_dhgeochemistryattr`
(long-form EAV) without the pre-pivoted `gsd_dhassayflat` table.  The
converter used to push those long-form rows through the flat converter and
lose every analyte.  Pivot them instead, and keep the unit / detection-limit
flags available as a sidecar.

## Design

- `build_assay_rows` returns `(rows, kind)` with `kind` in `flat`, `eav`,
  `intervals` (geochemistry rows but no attrs) or `empty`.  Hole ids are
  attached before any early return so the flat converter always has `HoleId`.
- The EAV path pivots on `PPMValue` (already ppm; `Flag_PCT` only records the
  lab's original unit), suffixes analyte columns `_ppm` to match the flat
  path, and re-attaches `CompanyHoleId` as `datasource_hole_id` so both paths
  emit the same identity columns and stay keyed on the same `hole_id` as the
  collars.
- `assays_provenance.{parquet,csv}` is written only when at least one
  `Flag_*` is actually set (a populated `Units` column alone is not a signal),
  keyed like the canonical tables.

## Verification

- `tests/test_gswa_converter_eav_assays.py`: path detection, hole-id
  attachment on the no-attrs path, analyte suffixing, provenance gating
  (bool and string flags), end-to-end EAV conversion under both hole-id
  policies, and flat-vs-EAV identity/analyte parity.
- Codex review (`codex review --uncommitted`) findings addressed: early
  return before `attach_hole_ids`; `CompanyHoleId` dropped by the pivot.

## Known, out of scope

Under `--hole-id-source company` the canonical tables (collars, survey,
assays, geology, structure) keep the GSWA `hole_id` with the company id in
`datasource_hole_id`; only the `flattened_*` tables switch `hole_id` to the
company id.  That predates this change (the baselode adaptor renames
`CompanyHoleId` before `prefer_company_hole_id` ever sees it) and is
documented here rather than changed.
