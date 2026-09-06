# TRK-371: Baselode export integration

## Intent

Use the published Baselode export contract for every canonical and flattened
GSWA table while keeping source-specific selection and sorting in this skill.

## Design

- Require Baselode 0.1.47 or newer.
- Remove converter-local cell normalization and CSV/Parquet writers.
- Sort each selected table with the existing GSWA policy, then call
  `baselode.export.write_project` once for atomic paired files and the manifest.
- Store GSWA source, hole-ID, flattened-table, and optional-trace details in the
  generic manifest's `metadata` object.
- Update CLI reporting to consume the Baselode manifest file mapping.

## Verification

- Round-trip mixed identifiers, nulls, and nested values through both formats.
- Check row counts, representative values, deterministic sorting, and manifest
  metadata/file entries.
- Run the existing optional-trace tests from a clean committed snapshot.
- Commit only this ticket's hunks, excluding existing assay/provenance changes.
