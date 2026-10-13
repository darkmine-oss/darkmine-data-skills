# GSWA preserving geology expansion

Preserving conversion adds explicit mapped geology fields and one JSON expansion column to each original interval. The interval count, boundaries and existing source references remain unchanged. Original attribute records and parent metadata stay in `attributes_extra`; no second attribute table is emitted. Conflicting candidates remain visible and deterministic field selection is recorded.

GSWA alias policy lives in the skills package; the generic promotion primitive lives in Baselode. Coverage manifests count retained attribute records and populated flat fields. The converter retains its incomplete marker on rejected relationships. The released skills package requires Baselode 0.1.60+; branch validation uses the corresponding local source candidate before release.
