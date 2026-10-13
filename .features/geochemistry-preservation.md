# Source-record geochemistry preservation

Prefer original geochemistry parents over publisher flat intervals when present.
Preserve one row per source Id, all parent/attribute scalars and original flags.
Exact reviewed elemental aliases feed publisher numeric projections without unit
conversion or raw-text fallback. Qualified/source-invalid results stay JSON;
differing eligible numeric values yield flat nulls and explicit conflicts.
Text descriptors reuse the existing Baselode evidence primitive. No API change
in Baselode is required. The mapping CSV must ship inside the installed package.

Process complete parent groups for deterministic, batch-independent results.
Reject ambiguous/orphan/null source identities; retain incomplete markers on
failure. Parent schemas must remain stable when a first batch has null metadata.
Scientific eligibility and nested-assay QAQC remain separate subsequent work.

Validation: source-record grain, repeated samples, exact identity/value precision,
null qualifier flags, percentage/ppb labels with already-scaled publisher values,
qualified/nonfinite/no-data candidates, numeric conflicts/agreement, error labels,
absent attributes/end depths, empty exports, malformed keys/flags and equivalent
output across parent batch sizes/child order. Full package tests and peer review.
