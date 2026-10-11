# GSWA release compatibility

The converter supports the 2025-10 and 2026-05 flat assay tables. Package 0.1.1
includes the installable conversion/validation package and the non-repairing
`--preserve-issues` path, alongside direct script invocation.

Surface assays join by the older `SurfaceSampleId` variants when available,
otherwise by `Id` in the 2026-05 table. An older table's unrelated `Id` must not
override its explicit surface sample key. The output retains repeated source
rows and their row references for downstream QAQC.

Canonical drill assays include interval identity and `_PPM`, `_PPB` and `_PCT`
analytes. Spatial/context columns remain in flattened source output; the new
`Y` coordinate must not be interpreted as yttrium. `Y_PPM` is still retained.
Flattened coordinates accept `Latitude`/`Longitude` or
`CollarLatitude`/`CollarLongitude`, and `Dip` or `DIP`. `X`, `Y`, `Z` become
`source_x`, `source_y`, `source_z` without asserting a coordinate reference
system or changing their values.

Values and source unit suffixes are preserved. Percentage values are not
relabelled ppm or rescaled. Publisher field names do not establish scientific
correctness; original raw files and flags must accompany interpretation and
any later recorded QAQC correction. Non-repairing conversion does not imply
chemical QAQC coverage.

Regression fixtures cover both releases, the conflicting old/new surface keys,
duplicate analyses, percent/ppm preservation, genuine yttrium alongside spatial
`Y`, coordinates and orientation, and unchanged input Parquet bytes. Test the
installed wheel as well as source scripts before releasing a new version.
The Baselode database-query adaptor is a separate integration; this change
does not update it or deploy worker package pins.

Copyright (C) 2026 Darkmine Pty Ltd.
