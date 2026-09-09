# Deployable conversion and QAQC — TRK-418

The `darkmine-data-skills` Python wheel exposes `gswa-drillsurface-to-baselode` and `drillhole-validate`. It packages the existing scripts and skill metadata, pins Baselode 0.1.56, and preserves direct script invocation. The package CI builds and tests the installed wheel without a sibling checkout. No model calls or runtime dependency installation occur during either skill.

Use `gswa-drillsurface-to-baselode RAW_DIR OUT_DIR --preserve-issues` for downstream QAQC. This mode reuses Baselode's canonical column mappings while bypassing its validating loaders. It preserves duplicates, invalid orientations, interval boundaries and source row references. Output Parquet/CSV and `conversion_manifest.json` record loaded and unmapped sources, source/output checksums, mappings and coverage. Unused raw files are inspected through Parquet metadata rather than loaded into pandas. Keep the original raw directory alongside the generated dataset.

The first release maps collars, surveys, assay intervals/available flat analytes, geology intervals and surface samples/available flat assays. Structure and EAV attribute pivots are deliberately unconverted; original tables remain raw. No desurvey or automatic repair occurs in this mode. Existing frontend conversion mode retains its previous behaviour.

`drillhole-validate BASELODE_DIR OUT_DIR` executes the pinned Baselode check functions with per-check/table coverage. Reports include executed, partial, skipped and failed checks, evaluated/excluded counts and reasons, including checks with no findings. Missing survey data is explicitly reported for collar holes. Exit codes: 0 for no error findings, 1 for error findings, 2 for incomplete execution. Consumers must validate the report rather than treating every exit code 1 as findings.

The original JSON/TXT reports remain available. The Explorer worker enriches source/display identity, emits CSV/Markdown/provenance, persists issues for paging and retains the raw/Baselode/report chain. Surface conversion does not imply surface QAQC. Coverage is structural and WA-only; schema completeness, lab QAQC and automatic repairs are outside this feature.

Run tests using this repository's `.venv` after loading `./.env`. `tests/test_project_qaqc.py` covers fidelity, missing survey data, azimuth options, depth-limit partial coverage and zero-finding checks. Existing converter tests cover compatibility with the default conversion mode.

Copyright (C) 2026 Darkmine Pty Ltd.
