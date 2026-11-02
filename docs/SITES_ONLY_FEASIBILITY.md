# Sites-only dashboard feasibility and calculation comparison plan

Assessment date: 2026-09-29. Local source reviewed: `c66699d24cbe98b42423735e17a03739b655fba9`.

**Decision recommendation: do not approve the full rebuild yet.** Sites has documented paths for the interface, external HTTPS APIs, secrets, database records, and stored files. A supported scientific runtime and reliable unattended job execution have not been established for Sites. Both are mandatory for this dashboard. A small interface demonstration would not resolve them.

This document completes the requested feature review and defines the proof required before implementation and before migration. It does not authorize or report a rebuild, new Site, provider request, production calculation, or cutover. The user will decide after reviewing the yes/no table. PDF is the requested report format for the candidate. Word and LibreOffice are excluded from that candidate; existing CSV/XLSX outputs remain in scope.

"Sites-only" means the application interface, API, calculations, job execution, state, and exports operate through supported Sites capabilities. Bazefield, MIDC, and OpenAI remain external data/AI providers. A separate compute host, local computer, scheduled Codex job, or external PDF renderer would not satisfy the requested hosting boundary.

## Current evidence and what the dashboard does

The live Sites project `appgprj_6a5bea8e15688191ae18fb869f2d2acc` was read through Sites tools on the assessment date. It is active, reports latest version 17, and uses custom access at [SB Energy Operations Dashboard](https://sbe-pv-operations.sbenergy.chatgpt.site). Runtime configuration names were inspected without printing values. They are `RENDER_BACKEND_ORIGIN`, `RENDER_BASIC_USER`, and `RENDER_BASIC_PASSWORD`. Direct Bazefield and OpenAI credentials are not currently configured there. The local [hosting manifest](../.openai/hosting.json) has `d1: null` and `r2: null`.

These checks establish the existing hosting arrangement. They do not establish that this local revision matches the running Render revision or the published Sites source. The later comparison must identify both deployed revisions explicitly.

The application has five connected workflows:

1. Data Collection retrieves selected measured power and weather series, reports data quality and measured energy, plots them, and supplies CSV/XLSX downloads. It does not calibrate a model.
2. Calibration inspects the historian snapshot, obtains decisions for every actionable issue, predicts both PV systems, fits seasonal corrections, and permits promotion of a reviewed baseline. Physics-only validation is also supported.
3. Annual Simulation retrieves MIDC weather, applies the PV physics and frozen calibration factors, and reports interval, monthly, seasonal, and annual energy. Source coverage determines which years can enter the energy distribution.
4. TEA v5 freezes a completed eligible Annual source and calculates paired commercial lifecycle LCOE with seeded sampling. It stores complete realizations, provenance, sensitivity, convergence, and verified exports.
5. Solar Agent explains stored evidence, researches bounded public topics, proposes scenarios and sweeps, and follows the existing review and confirmation policy. Its answers do not replace the calculation engine.

Analysis library, saved results, charts, downloads, draft restoration, access control, cancellation, retry, baseline promotion, and evidence retention support those workflows. The scientific result includes the source and review history that produced it.

## Feature decision table

**Sites path supported?** Yes means the required building block has a documented implementation path. No means the current implementation cannot run unchanged or no adequate target path has been established; the reason states which. **Equivalent feature verified?** Yes requires evidence for this dashboard on Sites. No is not proof of impossibility. Existing proxy calls through Render do not prove direct Sites execution.

| Feature that must be retained | Sites path supported? | Equivalent feature verified? | Evidence and remaining requirement |
| --- | --- | --- | --- |
| Dashboard pages, forms, charts, navigation | Yes | No | The frontend already has a Sites deployment. Full candidate behavior and interaction parity remain untested. Preserve accessibility, drafts, restored state, and late-response handling. |
| Existing Site audience and server-side access checks | Yes | No | Custom audience is confirmed. New API and artifact routes must enforce it, including unauthorized requests and direct file access. |
| Server-held provider secrets | Yes | No | Sites supports secret environment entries. Candidate Bazefield/OpenAI keys must stay out of browser code, logs, and exported reports. |
| Direct Bazefield API retrieval | Yes | No | Current connector uses HTTPS and bearer authentication. Test the actual provider from Sites, including any provider network restrictions, point access, response size, and failures. |
| Selected measurement groups, units, timestamps, quality flags, measured energy and CSV | Yes | No | These have portable HTTP/data-processing paths. Compare identical raw responses, timezone conversion, end-exclusive windows, selected rows, and full-precision values. |
| Full Data Collection lifecycle, measured plots and XLSX | No | No | Complete execution fit is unestablished. Current background tasks, file records, cancellation, quotas, retention, and chart/workbook generation need a supported execution path and workload test. Preserve usable CSV when optional charts/workbooks fail. |
| Direct MIDC weather retrieval | Yes | No | Ordinary HTTPS CSV retrieval. Test Sites egress and provider errors. Correct first-bin retrieval, aggregation, source gaps, and year eligibility require separate parity checks. |
| Visible review of every flagged data issue | Yes | No | UI, records, and decisions fit Sites APIs/storage. The quality rules, affected row sets, decision receipts, expiry, and blocking behavior must match exactly. |
| Existing pvlib/PVMismatch physics and physics-only validation | No | No | Sites packaging documents a JavaScript ESM Worker, not deployment of the current Python server. Scientific runtime compatibility, numerical behavior, and resource fit remain unproved. |
| Seasonal calibration including clipping-aware fitting | No | No | Depends on the scientific runtime and complete seasonal populations. It must solve the same energy equation and preserve the reviewed input lineage. |
| Baseline promotion and frozen factor reuse | Yes | No | Database/API operations have a path. Promotion guards, source verification, and equivalent calculated factors must pass before this is a usable replacement. |
| Calibrated Annual Simulation, subhour intervals and multiple years | No | No | Physics, memory, durable execution, complete-year eligibility, and all admitted workload sizes are unproved. A smaller demonstration is insufficient. |
| Full TEA v5 sampling and paired lifecycle calculations | No | No | Preserve the pure kernel where possible. No Sites runtime has passed its unchanged numerical probes or complete realization comparison. |
| TEA assumptions, cost-year conversion, acceptance and confirmation | Yes | No | UI and API logic can be ported. Preserve the frozen index snapshot, original amounts, exact conversion receipts, evidence and validation. Calculation execution still depends on the preceding row. |
| Persistent metadata, reviews, jobs and saved results | Yes | No | Sites documents D1. Existing SQL triggers, atomic claims, immutable requests, global model/TEA capacity, and separate TEA mutation boundaries require migration tests. |
| Persistent private inputs, frozen evidence, results and files | Yes | No | Sites documents R2. Preserve source bytes, hashes, retention, private access, and complete lineage. R2 and D1 are not one atomic filesystem transaction. |
| Jobs finish and recover after browser close or interruption | No | No | No supported Sites scientific job runner or queue binding has been established. Current persistent Python threads cannot be reused. Ordinary request continuation is not a durable job runner. |
| Cancellation, retry, progress, stale-worker protection | No | No | API/state logic can be represented, but complete behavior depends on the unestablished durable executor. Duplicate requests and competing attempts must not publish twice. |
| AI conversation through OpenAI | Yes | No | Server-side HTTPS and secret handling are supported. Test the selected model, bounded tool loop, timeout behavior and recoverable failures from Sites itself. |
| AI answers from Calibration/Annual/selected TEA evidence | Yes | No | Port the evidence tools and source checks. Numerical facts must match the selected saved result; missing or tampered evidence must be refused. |
| AI public research with citations | Yes | No | Preserve the separate public query and source handling. Private run context and chat history must not enter the web-search request. |
| AI scenario proposals, confirmation and parameter sweeps | No | No | Proposal APIs have a path, but working actions require the unproved model and job runner. Preserve existing conditional same-source auto-start and mandatory confirmation cases exactly. |
| Analysis library, save/rename/open/export, history and draft restoration | Yes | No | D1/R2 and UI routes can support them. Opening completed evidence must not rerun it, overwrite a draft, or change a promoted baseline. |
| PDF report download without Word | Yes | No | A JavaScript PDF renderer has a plausible Sites implementation path. Unchanged ReportLab execution is unproved. Full report content, links, tables, charts, fonts, pagination and frozen-evidence checks need verification. |
| Existing model/Annual/TEA CSV/XLSX data exports | No | No | Stored downloads fit R2, but complete generation and integrity tie-outs at admitted sizes have not been demonstrated within the target runtime. |
| Migration and recovery of existing saved analyses | No | No | Existing recovery requires the original absolute output path. Moving to D1/R2 needs an explicit identity/path mapping and reconciliation, not a database/file copy alone. |

All candidate equivalence entries are No because a candidate does not yet exist. The supported-path column identifies credible implementation work; the No entries identify reasons not to approve a full rebuild today.

Autonomy, the Decision Agent, and TEA v6 remain retired. Existing compatibility guards and private historical records remain protected. This plan does not reintroduce them. File uploads into chat are not part of the current inspected workflow and are not added to this scope.

## Platform constraints that affect the decision

The installed Sites 0.1.75 guidance requires a JavaScript ESM Worker with `fetch(request, env, ctx)`, supports external HTTP clients, and provisions D1/R2 through its manifest. Its portable setup reference states a 128 MB memory limit per isolate, shared by requests and including WebAssembly memory.

The Sites-specific evidence is the installed [Sites building guidance](<C:/Users/Angushylesh(Shylesh)/.codex/plugins/cache/openai-curated-remote/sites/0.1.75/skills/sites-building/SKILL.md>), lines 273 and 283 through 286; the [portable setup reference](<C:/Users/Angushylesh(Shylesh)/.codex/plugins/cache/openai-curated-remote/sites/0.1.75/skills/sites-building/references/project-setup/portable.md>), line 3; and the [persistence reference](<C:/Users/Angushylesh(Shylesh)/.codex/plugins/cache/openai-curated-remote/sites/0.1.75/skills/sites-building/references/persistence-and-storage.md>). The [recurring updates reference](<C:/Users/Angushylesh(Shylesh)/.codex/plugins/cache/openai-curated-remote/sites/0.1.75/skills/sites-building/references/recurring-updates.md>) describes an authenticated cloud writer. These local links identify the exact installed documentation reviewed; they are not public product guarantees.

Cloudflare documents Python Workers, including Pyodide packages. That does not establish a Sites-supported Python deployment path. Generic Cloudflare WebAssembly support likewise does not prove that Sites can package and run this scientific stack. Python Workers also lack functional threading/multiprocessing and have an ephemeral filesystem. The current FastAPI process, SQLite file, persistent worker thread, and file-based exporters cannot simply be copied over.

No Sites Queue, Workflow, Durable Object alarm, container, or equivalent scientific executor was established from the current skill and tool surface. Sites recurring cloud-task updates are not evidence of this job mechanism. Cloudflare's ordinary `waitUntil()` extends execution by at most 30 seconds after a response or disconnect. Its published CPU allowances must not be assumed to be this Site's effective allowance.

D1 can execute transactional batches. Publishing artifacts across D1 and R2 still needs an application protocol: write an attempt's private objects, verify them, then atomically make only the valid attempt's manifest visible. Preserve fencing, cancellation precedence, retention and orphan cleanup. A download must never advertise incomplete evidence.

Primary platform references:

- [Cloudflare Worker limits and request lifetime](https://developers.cloudflare.com/workers/platform/limits/)
- [Python Worker package support](https://developers.cloudflare.com/workers/languages/python/packages/)
- [Python Worker standard library and ephemeral files](https://developers.cloudflare.com/workers/languages/python/stdlib/)
- [WebAssembly in JavaScript Workers](https://developers.cloudflare.com/workers/runtime-apis/webassembly/javascript/)
- [D1 transactional batches](https://developers.cloudflare.com/d1/worker-api/d1-database/)
- [PDF-LIB capabilities](https://pdf-lib.js.org/)

## Work sequence if the user elects to proceed

The first deliverable would be a bounded feasibility experiment in a new folder, not a full UI rebuild. Stop as soon as a mandatory requirement has no supported solution. Do not spend time porting the interface while compute or durable execution is unresolved.

| Gate | Work and required evidence | Decision |
| --- | --- | --- |
| 1. Establish supported execution | Confirm the actual Sites scientific deployment path, effective limits, private storage access, and a durable executor that works without an open browser. Document whether these are available to this project, not only to generic Cloudflare accounts. | If unavailable, stop the Sites-only plan. An external worker would require a different hosting decision. |
| 2. Prove provider access | In an isolated candidate, retrieve a small authorized Bazefield period and a MIDC sample directly; make one bounded OpenAI request. Check credentials, actual access, source fields, errors and request bounds. | Failure of any required provider access blocks a full rebuild. |
| 3. Prove calculation and capacity | Run unchanged TEA probes and reference cases; execute real PV physics, calibration and Annual calculation on the proposed runtime. Measure CPU, elapsed time, peak memory and output size. Prove cancellation, browser-close completion and interruption recovery. | Reject numerical failures or a reduced supported workload. Do not adjust equations, seeds, tolerances or limits to pass. |
| 4. Implement the complete workflows | Port storage and orchestration around verified calculation functions. Reuse the existing frontend behavior, quality review and Agent policy. Maintain TEA separation. Add PDF rendering from verified evidence. | Each mandatory feature needs its own parity evidence before cutover. |
| 5. Compare both hosted implementations end to end | Execute the paired experiment below on the original Python implementation in an isolated Render test environment and on the candidate Sites deployment. Local-only comparison cannot substitute for hosted verification. | Every mandatory comparison must pass; uncovered discrepancies remain failures or unresolved. |
| 6. Rehearse migration and decide cutover | Migrate a consistent protected copy of all records/artifacts, verify old analyses and reports, exercise restore and rollback, then present the full result for the user's cutover decision. | Keep the current deployment until the evidence supports replacement. |

Suggested folder organization after the decision:

```text
sites-only/
  README.md                 Scope, runtime decision, gate evidence
  contracts/                Frozen specifications and comparison rules
  reference/                Reproducible non-secret test vectors
  experiments/              Runtime, provider, executor and PDF feasibility
  app/                      Dashboard and API routes
  engine/                   Verified physics, calibration, Annual and TEA
  jobs/                     Supported execution and recovery adapters
  storage/                  D1 records and R2 artifact adapters
  reports/                  Frozen-evidence PDF content and rendering
  db/                       Versioned schema and migrations
  tests/parity/             Independent cross-implementation comparisons
  tests/workflows/          Review, confirmation, recovery and UI behavior
```

This is a proposed boundary map, not a choice of a scientific runtime. Private captured data and comparison outputs belong in ignored, access-controlled test storage, not in source control. The new folder must not inherit the live Site project ID by accident. Any eventual staging publication should have its own identity and suitable access.

## Explicit calculation comparison after implementation

The required primary experiment exercises the complete chain on both implementations. Each uses isolated records, artifacts and baseline state so test promotion cannot alter the operational baseline.

1. **Freeze identity and inputs.** Record exact deployed revisions, runtime/package versions, physics identity, TEA contract, cost index snapshot, settings, units and approved comparison rules. Select an explicit historian window with suitable seasonal coverage. Record dates, measurement IDs, interval, aggregate choice and request boundaries. If no suitable reviewed source is available, this is a missing prerequisite, not permission to manufacture measured data.
2. **Prove direct retrieval, then freeze the data.** Exercise both hosted Bazefield connectors and compare source fields and values. Capture one protected raw response bundle for numerical replay. Feed identical captured bytes into both ingestion paths. Independently fetched historian data may be revised upstream, so live downloads alone are not a reproducibility test. Apply the same approach to MIDC, including the prior-day data needed for the first interval.
3. **Run review on both.** Compare issue IDs, severities, affected rows, available actions, blocking states, timestamps, missingness and counts. Apply the same explicit human decision map. Compare retained/excluded rows and reviewed-source bytes or an explicitly specified canonical representation. Do not assume that equal row counts imply equal rows.
4. **Run calibration on both.** Execute their actual physics and fitting. Compare every interval's uncalibrated/calibrated power, duration and energy; per-system seasonal factors; clipping; residuals; row counts; and confidence/diagnostic outputs. Promote the resulting test baseline only inside each isolated test store.
5. **Run Annual independently on both.** Start with the same frozen complete MIDC weather year and identical controls, using each branch's own newly calculated calibration. Compare time rows, weather cleaning, factor application, operating caps, interval energies, monthly/seasonal/year totals, coverage, eligible years, energy CDF and probability labels. Extend to multiple selected years and incomplete source cases.
6. **Run TEA v5 independently on both.** Start with identical accepted assumptions, seed and population size, using each branch's own Annual result. A representative case uses 10,000 realizations and seed 20260916 with an explicitly frozen supported request; do not let mutable defaults choose the scenario. Compare semantic requests, sampled inputs, weather assignments, all realization columns, both systems' present-value cost/energy and LCOE, paired deltas, full CDFs, P10/P50/P90, sensitivity and convergence.
7. **Export PDF on both.** Generate each PDF from its completed sealed evidence without rerunning calculations. Compare all displayed scientific numbers and units to that branch's full-precision result. Inspect every rendered page for complete tables, chart values/axes, captions, contents links, references, appendix, fonts, clipping and page numbering. Compare CSV/XLSX values and formulas where present as well. File hashes can differ because of generation metadata; that does not excuse numerical or content differences.
8. **Exercise Agent and lifecycle behavior.** Ask the same saved-evidence questions and compare cited result IDs, numerical facts, units and tool outcomes. AI prose is not expected to be identical. Exercise proposals, a sweep, confirmation, cancellation, retry, tampered evidence, missing records, closed browser and interrupted execution. Test the current conditional confirmation policy, not a newly simplified policy.

A second diagnostic replay supplies the same frozen baseline and Annual source to both implementations. This isolates downstream errors. It supplements the complete independently calculated chain; passing it alone does not prove end-to-end equality.

## What "the same calculations" must mean

- Require exact source identity, settings, timestamps, row membership, review decisions, counts, categorical classifications, units, sign conventions, seeds, random integer streams, weather assignments and realization order.
- Keep every TEA numerical probe and digest unchanged. Its twelve-significant-digit gate applies to the named probes, not to every output in the application. Record the existing bit-exactness fingerprint separately.
- Compare all full-precision scientific outputs, not only rounded screen values or headline medians. Use only predeclared, applicable arithmetic tolerances. Where no justified cross-runtime tolerance exists, an unexplained difference remains unresolved; do not invent a tolerance after seeing the discrepancy.
- Do not repurpose unrelated validation allowances as migration tolerances. For example, the model-to-CEC reference comparison permits a percentage difference, and the historical MIDC source reconciliation permits a small source-data discrepancy. Neither permits that error between two implementations given identical inputs.
- Report each comparison as bit-identical, within a specifically named accepted tolerance, or failed/unresolved. Document expected differences in host IDs, paths, software identity and generated timestamps while preserving each branch's own complete provenance checks.
- A matching PDF value does not prove matching sealed arrays. A matching median does not prove matching distributions or paired realizations. A passing numerical test does not prove durable execution or provider access.

Chunking is an implementation option only if it preserves the full calculation. LHS strata/permutations and balanced weather assignment depend on the full realization count; independently seeded smaller jobs change the result. Convergence needs the original ordering, and quantiles/rank regression need the full population. Seasonal fitting must use the complete reviewed season. Time integration, interpolation and quality checks need boundary context across chunks. Reduction order and precision must be measured rather than assumed equivalent.

The admitted workload must also be preserved. Current bounds include 200,000 historian review/validation rows, 1,048,575 Annual rows, and up to 100,000 TEA realizations subject to existing export-cell and sensitivity limits. Test representative cases and admitted boundary workloads, including leap years, DST/season boundaries, source gaps, subhour intervals, nonconsecutive years, zero/infeasible calibration, curtailment, far-tail bounded normals, tied distributions, cost-year conversion and incomplete evidence. No silent reduction in supported date range, resolution, realization count, or available outputs is acceptable.

The comparison report must contain each input/request digest, exact software identity, both job IDs, row/column, reference/candidate value, absolute/relative and relevant ULP difference, named tolerance, maximum discrepancy, stage result, resource measurements, artifact identity and PDF inspection evidence. The final equality claim requires every mandatory stage and failure/recovery case to pass.

## Source map and verification status

| Evidence area | Current sources |
| --- | --- |
| Supported workflows and UI | [README](../README.md), [navigation](../frontend/html/20-header-and-tabs.html), [collection](../frontend/html/85-collect-data.html), [Agent](../frontend/html/90-chat-and-agent.html) |
| Provider access and collection | [Bazefield client](../src/sbepv/ingest/bazefield.py), [collection processing](../src/sbepv/ingest/collection.py), [collection lifecycle](../src/sbepv/api/collect_data.py), [MIDC](../src/sbepv/ingest/midc.py) |
| Review, physics, calibration and Annual | [calibration](../src/sbepv/calibration.py), [model](../src/sbepv/model.py), [Annual worker](../src/sbepv/worker/run_annual.py), [model tests](../tests/test_model_runtime.py), [calibration tests](../tests/test_calibration_workflow.py), [Annual tests](../tests/test_annual_simulation.py) |
| TEA contract and independent checks | [calculation contract](TECHNOECONOMIC_CALCULATION_CONTRACT.md), [kernel](../src/sbepv/technoeconomic.py), [source verification](../src/sbepv/api/technoeconomic.py), [export checks](../src/sbepv/technoeconomic_reporting.py), [kernel tests](../tests/test_technoeconomic.py), [worker tests](../tests/test_technoeconomic_worker.py) |
| Agent behavior and confirmations | [chat](../src/sbepv/agent/chat.py), [tool schemas](../src/sbepv/agent/tool_schemas.py), [proposals](../src/sbepv/api/proposals.py), [Agent tests](../tests/test_agent_backend.py), [TEA evidence tests](../tests/test_technoeconomic_agent_evidence.py) |
| Persistence and recovery | [store](../src/sbepv/store.py), [worker](../src/sbepv/worker/loop.py), [backup and restore constraints](BACKUP_AND_RESTORE.md) |
| PDF content and verification | [PDF builder](../src/sbepv/technoeconomic_pdf.py), [report content](../src/sbepv/technoeconomic_report.py), [layout](../src/sbepv/technoeconomic_pdf_layout.py), [full report tests](../tests/test_technoeconomic_full_report.py) |

Completed for this assessment: current source review, live Site metadata/configuration-name inspection, installed Sites capability review, primary platform documentation research, and review of existing relevant test assertions. Application tests, provider connectivity, scientific execution on Sites, numerical comparisons, generated-PDF inspection, migration rehearsal and deployment were not performed. Historical results and inspected tests are not current passing evidence.
