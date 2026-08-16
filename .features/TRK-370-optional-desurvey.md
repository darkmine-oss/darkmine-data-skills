# TRK-370: Optional, subset-safe desurvey

## Intent

Keep GSWA canonical conversion useful when only a subset of collar and survey
records can produce a precomputed trace.

## Design

- Coerce and filter required coordinates and survey measurements before calling
  Baselode desurvey.
- Default absent or null elevation to zero.
- Desurvey only hole identifiers shared by the usable collar and survey subsets.
- Return structured status/counts alongside traces and include them in the
  conversion manifest.
- Omit trace files when no trace rows can be generated; preserve every other
  canonical export.

## Verification

- Test mixed-validity inputs, no eligible holes, and missing columns.
- Confirm null elevation produces a valid zero-elevation trace.
- Commit only this ticket's hunks, excluding existing assay/provenance changes.
