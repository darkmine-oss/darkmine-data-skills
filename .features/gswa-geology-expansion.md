# GSWA preserving geology expansion

Preserving conversion adds explicit mapped geology fields and one JSON expansion column to each original interval. The interval count, boundaries and existing source references remain unchanged. Original attribute records and parent metadata stay in `attributes_extra`; no second attribute table is emitted. Conflicting candidates remain visible and deterministic field selection is recorded.

GSWA alias policy lives in the skills package; the generic promotion primitive lives in Baselode. Coverage manifests count retained attribute records and populated flat fields. The converter retains its incomplete marker on rejected relationships. Branch dependencies pin the exact Baselode source commit supplying the new API in both packaging and CI requirements. Replace this source pin with a published version before publishing the skills package. This conversion path materializes project-size EAV inputs; state-scale batching is outside its current scope.
