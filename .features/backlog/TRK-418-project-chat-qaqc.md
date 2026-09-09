# Project chat: drilling data packs and QAQC

Status: historical approved specification, implemented in the TRK-418 working branches. See the implementation documentation under `.features/`.

Tracker: `TRK-418` — Explorer Project chat: WA data packs, Baselode conversion and interactive drilling QAQC.

Backend branch: `feature/TRK-418-project-chat-data-pack-qaqc`, created from `develop`.

Related planning: `TRK-403` (broader composite QAQC pipeline with optional fixes) and `TRK-408` (separate project orchestrator chat). This ticket implements the existing Project chat workflow without automatic repairs or a separate orchestrator surface.

## Outcome

Add two actions to Explorer's existing Project chat:

1. Prepare the project's drilling and surface geochemistry data pack through chat, using the same job and sidebar behaviour as the drilling card's button.
2. Convert the project's downloaded WA raw drilling and surface sample data to Baselode format, then run `darkmine-data-skills/drillhole-validate` against the Baselode drilling tables, preparing the pack first when necessary. Return a durable chat result with an interactive issue table, written reports in Project Files, and coloured collars on the Explorer map. Publish both raw and converted files for auditability.

These actions are unavailable in vanilla Explorer chat. The user should not need to switch to the separate agent-dispatcher chat. Neither preparation nor QAQC holds a chat request open while the background work runs.

## Decisions for review

Confirmed by the user: conversion and QAQC are scoped to WA for now. Use the existing GSWA-to-Baselode skill, retain raw `postgres_gswa` Parquets separately from published Baselode files, and use the Baselode schema for all downstream processing. Partial schema/check coverage is acceptable when clearly reported. Direct database extraction of Baselode data is a future change, not part of this implementation.

The following defaults were proposed for review and are the implementation baseline under the user's approval. WA scope and the conversion/auditability requirements above were explicitly confirmed; the remaining defaults can be revised if the user provides further direction.

| Decision | Proposed first-release behaviour |
| --- | --- |
| QAQC scope | All drillholes in the project's prepared pack; selected subsets deferred. |
| Azimuth 360° | Retain the skill's strict default: flag 360° as an error. No automatic fixes. |
| Map filters | Follow table severity/check filters, initially showing all issues. |
| Platforms | Full interactive web support; readable summary and report links on native. |
| Meaning of download | Prepare server-side Project Files, exactly as the existing button does; do not automatically save files to the user's computer. |
| Report formats | Skill JSON and TXT, plus full issues CSV and a concise Markdown summary. PDF deferred. |
| Entitlements | Existing data-pack entitlement/quota for preparation; QAQC available to those entitled users without a new billing product. Apply bounded worker concurrency. |
| Repeated requests | Reuse an in-flight job; reuse a completed QAQC result only for identical input snapshot, scope, skill version and options. An explicit rerun creates a new report run. |

## Existing implementation and integration points

Paths below are relative to this backend repository unless a repository name is given.

| Area | Observed implementation | Planned use |
| --- | --- | --- |
| Pack initiation | `app/routes/data_pack_routes.py`, `app/services/data_pack_service.py` | Extract shared initiation orchestration for the HTTP button route and chat tool, preserving access, tier, quota, backpressure and duplicate-job checks. |
| Explorer pack UI | `darkmine-explorer/src/components/DataPackSection.web.tsx`, `src/api/data_pack.ts` | The per-category drilling action uses `drill_sample`; do not use `initiate-all`, which also starts unrelated categories. Share status refresh/invalidation with chat. |
| Production pack worker | `the-agents/worker/data_pack_worker.py`, `worker/state_data_pack.py` | Preserve the existing exporter and job. Integrate the dependency handoff and report/input retention here where necessary. |
| Project chat | `app/services/chat_service.py`, `app/services/agent_service.py`, `app/services/chat_tools/` | Register two tools only for an authorised project session; propagate trusted project/session/user context. Current geographic context mainly carries bounds, so explicit project identity is required. |
| Durable jobs | `app/services/agent_job_service.py`, `app/workers/agent_worker.py` | Extend existing job/event/artifact machinery with a fixed QAQC runner and durable dependency tracking. Production execution belongs in the deployed worker, not the API process. |
| Chat rendering | Explorer `src/types/chatData.ts`, `ChatDataBlock.tsx`, `ChatTable.tsx`, `ChatRuntimeProvider.web.tsx` | Extend the existing coarse `type` contract for richer tables and background result delivery. |
| Map integration | Explorer `src/services/chatMapLayers.ts`, `src/components/explorer-map/MapChatLayers.tsx` | Add a project/run-scoped QAQC collar overlay. |
| Reference UI | `baselode-chatty/src/components/IssueTable.tsx`, `src/chat/toolkit.tsx`, `src/map/MapView.tsx`, `server/qaqc.ts` | Reproduce useful table controls, summary and severity styling. Do not copy its local paths, JavaScript fallback, or 10,000-issue result truncation. |
| Validator | `darkmine-data-skills/skills/drillhole-validate/scripts/validate_drillholes.py` | Canonical Python execution. Already produces JSON/TXT and wraps `baselode.drill.validate.validate_drillhole_db`. |
| Input conversion | `darkmine-data-skills/skills/gswa-drillsurface-to-baselode/` | Reuse schema mapping after auditing transformations; add a non-repairing QAQC conversion path. |

The data-skills repository currently has no root Python packaging manifest. Baselode already has a Python package definition. The pack worker currently replaces prior category artifacts and deletes old objects; its WA drilling output allowlist also does not generally publish QAQC JSON/TXT. Reports must not be inserted naively into that replacement path.

## Feature 1: prepare data pack through chat

Example: “Please download the drilling and surface data pack.”

1. Resolve the project from the authenticated chat session. Validate project access, polygon, entitlement and quota using the same shared service as the button.
2. Initiate the `drill_sample` category or return its existing in-flight job. Do not accept model-supplied user identity, storage paths or arbitrary project scope.
3. Persist a structured job reference with project ID, category, job ID, actual status and whether an existing job was reused.
4. Immediately refresh the sidebar summary, attach its existing job polling, and refresh Files when artifacts become available. This works with the sidebar closed and after navigation/reload; it must not depend on a mounted card receiving a transient event.
5. End the chat turn promptly after successful job acceptance: “Data pack is now downloading, go check the files area”. Reused in-flight jobs say it is already downloading; explicitly reused ready data says it is already available. Errors report the actual failure and never claim the download started.

Maintain the button's existing behaviour for explicit preparation of a previously completed pack. QAQC prerequisite resolution may reuse a suitable successful pack instead of forcing a refresh. Geometry changes invalidate suitability even if the pack falls within an existing age-based reuse window.

Extend the shared WA preparation workflow with the conversion stage below, so button and chat preparations both expose raw and Baselode outputs. Show separate preparation/conversion progress: raw files may become available before conversion finishes, but downstream readiness requires a published Baselode dataset. Existing raw-only packs can be converted without downloading them again.

## WA data pipeline and published Baselode dataset

Current pipeline: `raw postgres_gswa export → GSWA-to-Baselode conversion → published Baselode dataset → drillhole-validate → reports`.

Invoke the existing `darkmine-data-skills/skills/gswa-drillsurface-to-baselode` skill (the GSWA-to-Baselode conversion action), with the fidelity changes described below. Conversion is a durable, reusable stage, not a private temporary transformation inside a QAQC invocation. QAQC and all subsequent processing consume the published Baselode schema rather than raw provider tables. Reuse a completed conversion only when its source artifact checksums, converter version/options and Baselode schema version match; concurrent consumers share in-flight conversion work.

Expose clearly separated groups in Project Files, with proposed paths under the pack snapshot:

| Files group | Proposed relative path | Contents |
| --- | --- | --- |
| Raw GSWA data | `raw/postgres_gswa/` | Unmodified source table Parquets, including tables not yet represented in Baselode. Existing source paths may be retained with the same clear grouping. |
| Baselode data | `baselode/` | Canonical drilling and surface sample outputs supported by the converter, plus `conversion_manifest.json`. Publish Parquet and any CSV outputs generated by the skill. |
| QAQC reports | `qa/<run-id>/` | Findings, summary and check coverage linked to the exact Baselode dataset and its raw sources. |

Flattened raw-table exports, if produced by the converter, must be labelled as supplementary source data rather than canonical Baselode coverage. Do not invent mappings for unsupported tables or require complete schema coverage before shipping. Preserve those tables in the raw group and list them as not converted/not validated. Surface sample conversion follows the supported mapping; `drillhole-validate` does not thereby gain surface QAQC checks.

The conversion manifest records raw and output artifact IDs/checksums, source-to-canonical table/column mappings, schema and converter versions/options, input/output row counts, unmapped tables/fields, rejected or unrepresentable rows and reasons. Retain raw files and converted files together for every snapshot referenced by a retained report, not merely while the run is active. Pack refresh must not break this audit chain. Publish the Baselode manifest only after its required outputs are complete; failed conversion leaves raw files accessible and reports conversion failure, without marking downstream QAQC as passed.

Future, deferred pipeline: `database Baselode export → published Baselode dataset → downstream processing`. Define the dataset manifest/readiness boundary now so downstream consumers do not depend on conversion or raw file paths. Record acquisition mode (currently `raw_gswa_conversion`; later `database_baselode_export`). A future direct export may have no raw snapshot and should carry database extraction provenance instead. Do not implement direct database export or require synthetic raw files in that future path.

## Feature 2: run drilling QAQC

Example: “Please run a QAQC analysis over the drillhole data.”

1. Authorise the project/session and create or reuse a durable QAQC run. Record the originating session/message, requesting user, project geometry fingerprint, scope and validation options.
2. If an eligible published Baselode dataset exists, bind the run to its exact artifacts and provenance. If only raw files exist, enqueue/reuse conversion. If preparation/conversion is running, attach to it. Otherwise initiate the same `drill_sample` job and record the preparation and conversion dependencies durably.
3. Return immediately: “I’m downloading the project data first, then I’ll run QAQC and post the results here.” With ready inputs: “QAQC is running. I’ll post the results here and save the report in Files.”
4. A worker resumes the run when the Baselode dataset is published, stages that consistent input snapshot, invokes the packaged validation skill, and publishes reports and the result. Show “Converting WA data to Baselode format” during the prerequisite conversion stage.
5. Persist the completion message and structured table so they appear in the originating chat without another user prompt. On reopening, load the same result from history. If the user is in another project, do not apply this run to that project's map.

Proposed lifecycle: `waiting_for_data → waiting_for_conversion → queued → running → succeeded`, skipping prerequisites already satisfied, with `failed` and `cancelled` terminal alternatives. Implement with existing job status/progress fields where appropriate and Alembic migrations for any required new fields, dependency links, uniqueness constraints or outbox records. A waiting dependency must not occupy a busy worker slot.

Use durable claims, heartbeats, bounded retries, timeouts and an idempotent completion/outbox key. Duplicate tool calls or worker retries must not create duplicate packs, reports or completion messages. Multiple requesting sessions may subscribe to the same run, with one completion per subscriber. Recover pending completions after process restarts, including when the initial chat acknowledgement has not yet committed.

Preparation failure/cancellation ends the dependent run with a clear explanation. Cancelling QAQC detaches its dependency and does not cancel a data pack other users/actions may need. Recheck access before serving results; project deletion follows existing project cleanup policy. A findings report containing errors is a successfully completed analysis, not a failed job.

## Input fidelity and scientific scope

- Validate the downloaded project polygon's dataset, not the current viewport or a chat preview limited to a few rows. Do not query a newer live dataset midway through the run.
- Canonical inputs are `collars`, `survey`, `assays`, `geology` and `structure`, preferring Parquet. Collars are required. Record loaded, empty, absent, unsupported and failed tables separately.
- Audit the existing GSWA converter before reuse: it includes frontend cleanup and tiny-overlap clipping. QAQC must preserve invalid rows, duplicates, interval boundaries, BDL values and original orientations so preprocessing does not conceal findings. Do not desurvey as a prerequisite to validation.
- Keep stable source/provider IDs separate from displayed company hole IDs. Preserve source artifact/table/row mappings through joins; document whether a displayed row number is a canonical row index or a source row. Do not merge different holes with the same display label or remove true duplicates.
- Conversion and QAQC are WA-only in this release. Validate the WA portion of mixed packs and show conspicuous coverage limits in both chat and report. Existing download coverage is unchanged. If no supported data exists, report unsupported coverage rather than “passed”. Expansion to other states is deferred until the WA workflow works.
- Missing survey/optional tables must be visible in coverage; no collars and zero-row collars need explicit outcomes. “No issues found” applies only to checks actually performed.
- This is structural drillhole QAQC. Surface data is downloaded and converted where supported, but not validated by this skill. Laboratory QAQC, standards/blanks/duplicates analysis and automatic repairs are outside this feature.
- Derive totals and per-check counts from the full report. Generate a grounded summary with affected-hole counts and representative issues; never infer full totals from a displayed page. Describe suggestions as suggestions, not applied fixes or guaranteed downstream failures.

## Explicit validation check coverage

Every JSON/TXT/Markdown report and the chat result must identify the checks actually performed under the `drillhole-validate` umbrella, including checks that produced zero findings. Present these as individual checks/subchecks; the current implementation invokes Baselode functions rather than separate skill processes. Do not imply that other skills in the repository were run.

The currently inspected validator invokes these check IDs:

| Check ID | Scope and purpose |
| --- | --- |
| `duplicate_hole_ids` | Collar identity duplicates. |
| `survey_null_orientation` | Missing/non-numeric survey depth, azimuth or dip. |
| `survey_no_usable_stations` | Collar holes without usable survey stations, including absent surveys. |
| `single_station_surveys` | Holes with only one usable survey station. |
| `azimuth_range` | Survey azimuth range under the recorded full-circle option. |
| `dip_range` | Survey dip range. |
| `orphan_intervals` | Interval hole IDs without matching collars. |
| `negative_lengths` | Interval end before start. |
| `intervals_beyond_max_depth` | Intervals exceeding available collar maximum depth. |
| `interval_gaps` | Gaps between intervals. |
| `interval_overlaps` | Overlapping intervals. |
| `below_detection_limit` | BDL sentinels in eligible string columns. |

The last six run separately for each supplied interval table (`assays`, `geology`, `structure`). This does not imply structure-specific orientation checks or comprehensive assay/laboratory QAQC. Build the execution inventory from the pinned engine and actual invocation, not just this static list or the unique check IDs appearing in findings.

For each check/table entry record engine/subcheck identity and version, required inputs, `executed`, `partial`, `skipped` or `failed` status, evaluated row/hole counts, excluded counts/reasons, parameters and finding counts by severity. Distinguish absent source data, unsupported Baselode mapping, empty tables, missing required columns and invalid values excluded by the check. A function returning no issues after an early exit is not evidence it evaluated the table. Add execution coverage instrumentation to the skill/Baselode boundary where necessary.

Show a “Checks performed and coverage” section, including zero-finding checks, and a separate “Not checked” section. For example, a depth-limit check with some missing collar maximum depths is partial and reports how many intervals could be evaluated. Absence of a survey file can still allow the collar-level no-usable-stations check to execute, while row-level survey checks have no input. Failed checks make the analysis incomplete; never summarise it as a clean pass. The chat summary states that findings cover only the listed supported checks/tables, and links to the full coverage inventory.

## Packaging and execution

Add a distributable Python package to `darkmine-data-skills`, with a supported callable/CLI entry point for `drillhole-validate`, packaged skill metadata/resources, declared runtime dependencies and a versioned report contract. Keep existing script invocation working through a thin wrapper. Include the conversion entry point needed by the worker.

Build and install versioned wheels in CI/deployment, with the worker pinning a tested data-skills/Baselode pair and declaring dependencies in its requirements. A public package-index release can follow; deployment must not depend on publishing one or on a mutable branch, sibling checkout or developer `.venv` path. Keep existing open-source licence metadata.

Use a fixed allowlisted command or package function with argument arrays and isolated temporary directories. Do not execute arbitrary commands from chat or dynamically install packages at run time. The Python skill is the authoritative engine; dependency failure is a visible operational failure rather than a silent JavaScript fallback.

The CLI returns exit code 1 for findings with error severity. Accept that as completed only when a valid, complete report is present; crashes can also return 1. Validate the report schema and artifact publication before marking success. Record skill, Baselode and adapter versions plus options and input checksums in provenance.

## Reports, storage and API contract

Store reports as immutable per-run artifacts, exposed alongside the drilling data in Project Files under `qa/<run-id>/`:

- `drillhole_validation_report.json`: complete skill report, including per-check execution coverage and omissions.
- `drillhole_validation_report.txt`: human-readable findings and checks performed/not checked.
- `drillhole_validation_issues.csv`: every issue, including stable identity and suggested fix.
- `summary.md`: concise results and coverage.
- `manifest.json`: source pack, raw and Baselode artifact IDs/checksums, conversion manifest reference, geometry/scope, schema/engine/converter versions, options, timestamps, table counts and row mapping metadata.

Use run-owned storage/catalog records surfaced through Project Files, rather than pack category replacement. Retain both the exact raw sources and published Baselode inputs using snapshot references or retention leases before a pack refresh can delete them; keep them for the lifetime of referencing reports. Retain reports/provenance across refreshes, mark historical results as applying to an older pack, and remove them with normal authorised project deletion. Do not silently apply old results to newly downloaded collars.

Proposed API surface: project-scoped QAQC initiation/status, paginated issues with severity/check filters, filtered CSV export, and collar severity data. Final route names should follow existing conventions. Every read/export checks caller access; use artifact IDs and authenticated application endpoints, not credentials or durable signed links embedded in chat history. Counts and CSV exports cover all matching results, independently of page size. CSV output must handle quoting and spreadsheet-formula injection.

Persist a compact chat table payload using `type: "table"`, `data_type: "drillhole_qaqc"`, `view: "qaqc"`, and `payload_type: "drillhole_validation_report"`. Retain the required `columns`, `rows` and `total_count`, adding a contract version, run/project/input references, full summary, coverage, by-check counts, paging/filter metadata and report artifact references. Each issue has a stable issue ID, severity, check, canonical/source/display hole identity, table, row index, message and optional suggested fix. Do not place the entire issue list or geometry into model context.

## Explorer table and map behaviour

The table follows the supplied screenshot while using Explorer's existing design system:

- Project title; full error/warning/info count toggles; check dropdown; dataset and coverage summary, with expandable checks-performed/not-checked inventory including checks with zero findings.
- Severity, check, hole, table, row and message columns. Suggested fixes and source identity are available in row details and CSV.
- Errors first, then warnings and info, with deterministic secondary sorting. Load an initial 100 rows, with incremental loading and correct remaining counts. Filter changes reset paging.
- CSV button exports every filtered issue, with the matching count; a separate full-report link remains available. A filter yielding no results is distinct from a run with no issues.
- Keep the input usable while work runs, with pending/failure states, retry/cancel controls where applicable, and replayable completed results. Provide keyboard access and textual severity labels; colour is supplementary.

Colour affected collars by worst relevant severity: red error, amber warning, distinct info styling. Include a legend and a clear/reset action. Use stable source/provider IDs, not company labels, for joins. Invalid/missing coordinates and orphan issues remain in the table and contribute to an explicit unmapped count.

With the proposed filter-linked behaviour, compute map severity over all filtered issues, not just loaded rows. Clicking a located hole focuses it and exposes its findings; unlocated rows cannot pan the map. Keep the run/input identity attached to the overlay and allow switching between historical reports explicitly. Use the existing MapLibre layer approach with bounded/paged data and server aggregation as needed, avoiding enormous ID expressions or repeated full geometry transfers. Do not override unrelated layers or repeatedly reset the user's camera while paging.

## Architectural trade-offs for this review

| Choice | Benefit | Cost / alternative |
| --- | --- | --- |
| Extend durable jobs and add dependency/completion persistence | Survives disconnects and worker restarts; reuses deployment patterns | Requires schema and worker changes; an in-request task is simpler but cannot meet reliable completion requirements. |
| Package the actual skill | Reproducible deployments and one validation engine | Adds release/version maintenance and Python dependencies; copying validator code would drift. |
| Immutable reports and protected input snapshots | Refresh-safe analysis and replayable history | Additional storage and retention work; attaching reports to replaceable pack artifacts loses history. |
| Server paging/filtering/export and compact chat payload | Full results without oversized chat responses | Additional API/indexing work; client-only filtering would require downloading every issue. |
| Authenticated artifact/report access | Preserves project access boundaries without tokens in persisted URLs | Requires streamed/proxied downloads through existing authenticated patterns. |
| Explorer implementation before Baselode extraction | Validates the component contract against a real workflow | Temporary app ownership; extraction occurs once behaviour is established. |

## Delivery sequence

1. Resolve review decisions and approve this spec. During implementation, add matching feature planning files in each changed repository and inspect its local instructions.
2. Implement shared pack initiation and project-only chat tool; wire Explorer sidebar/job/Files refresh. Verify parity with the button before adding QAQC.
3. Package data-skills and add the durable non-repairing WA conversion stage, separate raw/Baselode Files publication, conversion provenance, fixtures and deployment installation. Add per-check execution coverage to validation. Record any necessary Baselode Python adapter/instrumentation changes separately from deferred UI primitives.
4. Add durable QAQC dependencies, input retention, runner, migrations, report publication and idempotent chat completion. Extend `the-agents` production worker rather than relying on the backend's local inline worker.
5. Add the table/API contract, paging/exports, Project Files integration, chat replay and map overlay in Explorer.
6. Validate complete flows and scale with representative data. Document implemented behaviour and limits under each repository's `.features/`.
7. Write a concrete follow-up plan under `baselode/.features/backlog/` for extracting the proven UI primitives. Do not implement that extraction in this feature.

Proposed Baselode follow-up primitives: an issue/result schema; a controlled issue table with severity facets, check selector, pagination and export callbacks; severity badges/legend; and a pure stable-ID-to-severity aggregation/map-style adapter. Explorer retains authentication, jobs, project Files, chat persistence and application map ownership. Plan exports, theming, accessibility, dependency boundaries, contract tests and a demo before adoption; avoid introducing Explorer services or assistant-ui dependencies into the primitives.

## Acceptance and verification

1. The example download prompt in Project chat starts exactly the drilling/surface category, updates the existing sidebar and Files, and responds after queue acceptance without waiting for completion.
2. Vanilla chat cannot discover or execute either action. Forged project/session IDs and unauthorised status/report/export requests fail without starting work or leaking data.
3. Button and chat have equivalent quota, entitlement, geometry, backpressure and concurrency behaviour. Repeated in-flight requests reuse the job.
4. QAQC with ready inputs starts directly. Missing inputs start preparation once; an existing preparation is awaited durably. Failure, cancellation and empty/unsupported data have truthful outcomes.
5. Invalid source rows survive conversion and appear in findings. Test duplicate display IDs across distinct source holes, true duplicate collars, azimuth boundaries, missing surveys, gaps/overlaps, BDL strings and source-row mapping.
6. A valid report with errors completes successfully; process crashes, missing/malformed reports and artifact upload failures do not. Restart/retry does not duplicate reports/messages.
7. Results arrive in the originating chat after the original stream ends, survive reload, and stay correct when another chat turn is in progress. Closing the browser does not stop the run.
8. Full counts, filtering, paging and CSV agree for a report larger than 10,000 issues. The model receives bounded summaries; no full-result truncation changes counts or exports.
9. Map severity precedence, filter synchronisation, row focus, unmapped counts, clearing, stable identity and project switching behave correctly, without requiring all issue rows in the browser.
10. Reports remain in Files and chat history after pack refresh, with historical provenance. Concurrent refresh cannot remove a running analysis's inputs. Project deletion cleans up authorised artifacts.
11. CI builds and installs the wheel in a clean worker environment and runs the CLI without sibling checkout assumptions. Verify the deployed worker entry point and output visibility rules.
12. Button and chat preparations publish raw GSWA and supported Baselode outputs in separate Files groups. Raw-only existing packs convert without re-download; matching conversions are reused. QAQC consumes only the published Baselode snapshot. Conversion failure preserves raw downloads and prevents downstream execution against incomplete output.
13. A retained report resolves to both its exact converted data and original raw snapshot after refresh. Unsupported raw tables remain downloadable and are explicitly listed as outside conversion/QAQC coverage.
14. Reports and chat distinguish executed zero-finding checks, partial evaluation, skipped checks and failures for each table. Verify missing/empty tables, missing columns, unsupported mappings and excluded rows; do not derive coverage from findings alone. Direct Baselode extraction and non-WA adapters remain deferred.

Use focused backend service/route tests, worker/package fixtures, frontend component tests and browser integration checks. Use each Python project's `.venv` and load `.env` before tests/test-like verification. No shared database migrations from local machines: generate migrations here and apply through the approved deployment pipeline, or an explicitly approved isolated local database. This planning change itself does not run jobs, tests against live data, deployments or migrations.

Copyright (C) 2026 Darkmine Pty Ltd.
