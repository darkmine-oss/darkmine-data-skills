# GSWA release compatibility

The converter supports the 2025-10 and 2026-05 flat assay tables. Package 0.1.1
includes the installable conversion/validation package and the non-repairing
`--preserve-issues` path, alongside direct script invocation.

Surface assays join by the older `SurfaceSampleId` variants when available,
otherwise by `Id` in the 2026-05 table. An older table's unrelated `Id` must not
override its explicit surface sample key. The output retains repeated source
rows and their row references for downstream QAQC.

The default frontend converter retains assay columns, including unfamiliar unit
suffixes, and metadata such as dataset/report identifiers. Known spatial/context columns
remain in flattened source output; the new
`Y` coordinate must not be interpreted as yttrium. `Y_PPM` is still retained.
Flattened coordinates accept `Latitude`/`Longitude` or
`CollarLatitude`/`CollarLongitude`, and `Dip` or `DIP`. `X`, `Y`, `Z` become
`source_x`, `source_y`, `source_z` without asserting a coordinate reference
system or changing their values.
If both coordinate naming conventions occur together, keep `latitude` and
`collar_latitude` separately (likewise longitude); `Dip` and `DIP` become `dip`
and `source_dip`. These choices do not depend on source column order. Surface
parent keys are matched case-insensitively; multiple competing keys fail clearly.

Values and source unit suffixes are preserved. Percentage values are not
relabelled ppm or rescaled. Publisher field names do not establish scientific
correctness; original raw files and flags must accompany interpretation and
any later recorded QAQC correction. Non-repairing conversion does not imply
chemical QAQC coverage.

The non-repairing QAQC converter has narrower canonical coverage: interval
identity and `_PPM`, `_PPB`, `_PCT` assay columns. Other fields, including an
unrecognised unit such as `_GT`, remain in the original raw Parquets and are
listed in the manifest's `unmapped_columns`. They are not evaluated by canonical
drill checks. Always deliver the raw files with that coverage manifest; a
converted dataset is not a complete scientific validation of every source field.
This preserves the existing partial-coverage contract rather than treating
unknown units as verified canonical measurements.

`--preserve-issues` uses source Baselode/GSWA hole IDs. An explicit conflicting
`--hole-id-source company` is rejected; ordinary frontend conversion still
defaults to company hole IDs.

Non-repairing conversion requires an empty output directory so stale, previously
repaired files cannot be mistaken for new QAQC input. A null hole ID on an
existing collar remains null and is flagged by validation; it is distinct from
an interval with no parent collar. Coverage lists written analytes as mapped.
Present tables missing required columns produce an incomplete report and exit
code 2; absent optional tables remain explicit skips.
An empty flat assay table falls back to available parent geochemistry intervals
so those intervals still receive QAQC. Invalid interval bounds are flagged,
including infinities, without changing input rows. Point-model structures are
explicitly outside interval-check coverage and generate a coverage warning;
they are not treated as malformed interval tables.

Regression fixtures cover both releases, the conflicting old/new surface keys,
duplicate analyses, percent/ppm preservation, genuine yttrium alongside spatial
`Y`, coordinates and orientation, and unchanged input Parquet bytes. Test the
installed wheel as well as source scripts before releasing a new version.
The Baselode database-query adaptor is a separate integration; this change
does not update it or deploy worker package pins.

Copyright (C) 2026 Darkmine Pty Ltd.
