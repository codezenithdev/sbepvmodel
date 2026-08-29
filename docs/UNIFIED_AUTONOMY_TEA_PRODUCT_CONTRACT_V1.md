# Product contract metadata

- Status: Approved
- Contract version: 1.0
- Approved direction date: 2026-08-20
- Preserved in repository: 2026-08-27
- Source: approved unified autonomy/TEA plan
- Authority: architecture and end-state product boundary
- Delivery note: for the current frontend-foundation delivery, Phase 0 and Phase 1 use the fixture-only definitions in the Hybrid Autonomy Workspace contract. This contract does not authorize backend, Decision Agent, evidence-service, scenario-execution, report-generation, or TEA-kernel changes.

---

# Unified PV Autonomy and TEA Decision System

## Product outcome

Turn the dashboard from a collection of automated workflows into a supervised decision system. The Autonomy workspace should keep the forecast chain understandable and ready, answer end-user PV and technoeconomic questions from traceable evidence, construct controlled alternatives, run the existing deterministic TEA only after confirmation, and preserve a signed decision record.

The final user journey is:

1. Ask a decision question.
2. Inspect calibration, Annual Simulation, weather-year, and evidence readiness.
3. Explain the current result and its limitations.
4. Create one baseline and up to three alternatives.
5. Validate every scenario against deterministic rules.
6. Confirm the exact frozen TEA requests.
7. Run the existing probabilistic TEA jobs through the leased worker.
8. Compare outcomes, uncertainty, sensitivity, and reversal conditions.
9. Ask follow-up “why,” “what,” and “why not” questions.
10. Accept, reject, or defer the recommendation and generate a signed PDF brief.

## Product boundaries

- Add a dedicated top-level **Autonomy** tab.
- Keep the existing Calibration, Annual Simulation, and Technoeconomic Analysis workflows intact.
- Keep Solar Agent on Calibration and Annual pages; hide it in Autonomy.
- Add a separate **Decision Agent** for Autonomy.
- The Decision Agent covers PV performance, model behavior, forecast readiness, TEA, finance assumptions, scenario feasibility, and cited public PV/TEA evidence.
- The Decision Agent does not answer unrelated general-assistant questions.
- Missing Calibration or Annual prerequisites produce an exact explanation and deep link to the existing workflow; the Decision Agent does not silently create or execute those jobs.
- No model or agent may approve its own run, waive a quality gate, promote a baseline, accept evidence, or sign a decision.
- No physical plant control is introduced.

## Unified architecture

### 1. Readiness controller

A deterministic readiness service observes durable dashboard state and calculates:

- promoted Calibration lineage and review quality;
- eligible Annual source availability;
- weather coverage and source integrity;
- the configured forecast policy;
- active, failed, interrupted, or stale jobs;
- whether a newer verified Annual source is available for a decision case;
- TEA input and evidence completeness.

It runs on Autonomy-page open and relevant lifecycle events, not on a timer. It returns a structured status and allowed next actions. The Decision Agent may explain this result, but cannot override it.

Forecast policy defaults:

- full calendar years from 2012 through the previous year;
- exclude 2011, the current partial year, and known incomplete 2022–2023 data by default;
- one-hour source interval;
- at least ten source-verified complete years;
- require a verified promoted calibration lineage;
- dashboard-only notifications;
- named operator confirmation for any run or promotion action.

### 2. Decision Agent

Use one Python OpenAI Agents SDK agent with narrow function tools and structured output. It may:

- read a decision case and readiness result;
- inspect eligible Annual sources;
- read immutable TEA summaries, sensitivity, convergence, evidence, and provenance;
- search cited public sources when internal evidence is insufficient;
- inspect preserved uploaded evidence;
- extract candidate values and source locations;
- create and revise TEA scenario drafts;
- invoke deterministic scenario validation;
- compare completed scenarios through a deterministic comparison bundle;
- save explanations and suggested next actions.

It may not queue a TEA job. The user-facing confirmation endpoint is the only execution boundary.

Operational defaults:

- use the configured OpenAI model rather than hard-coding one;
- high reasoning effort;
- maximum four tool calls per turn;
- 45-second request timeout;
- initial request plus two retryable retries;
- no parallel side-effecting tools;
- store dashboard messages locally in SQLite and send bounded context with `store=False`;
- preserve trace identifiers and sanitized tool outcomes for audit.

### 3. Existing calculation systems

- Calibration and Annual Simulation remain the source of physics and forecast evidence.
- TEA remains a sibling durable job type with its own table, worker entry point, routes, immutable source snapshot, calculation kernel, and exports.
- The Decision Agent never calculates lifecycle metrics itself.
- Every number shown before a TEA run is an input or hypothesis, not a predicted outcome.
- Every result number comes from the existing TEA result payload or a deterministic comparison service.

## Decision case model

Add durable SQLite records for:

- `decision_cases`: question, title, status, source and basis lock, active recommendation revision, timestamps;
- `decision_messages`: user and assistant messages, citations, trace IDs, timestamps;
- `decision_evidence_assets`: file identity, SHA-256, media type, extraction, acceptance state;
- `decision_scenarios`: baseline/alternative label, immutable revision, request, request hash, validation, TEA job link;
- `decision_events`: append-only evidence acceptance, confirmation, lifecycle insight, and sign-off events;
- `decision_reports`: immutable case snapshot, report identity, hash, and signed status.

Use reserved identifiers such as `case_`, `dmsg_`, `evi_`, `dsc_`, and `drpt_`.

Case states:

`draft → evidence_needed or blocked → ready_to_run → running → results_ready → decision_ready → signed → archived`

Confirmed scenario requests, job links, accepted evidence receipts, sign-offs, and report snapshots are immutable. Editing a confirmed scenario creates a new revision. A TEA job or used evidence asset cannot be deleted while referenced by a case.

Because the deployment uses shared Basic Auth, v1 cases are shared across authenticated dashboard users. Run confirmations and sign-offs require a typed operator or decision-owner name plus rationale.

## Evidence system

Evidence categories remain aligned with the TEA contract:

- project actual;
- direct quote or primary document;
- public benchmark;
- engineering judgment;
- secondary synthesis.

Public research rules:

- internal dashboard evidence wins for site-specific facts;
- web evidence requires source title, organization, URL, date, access date, and excerpt or derivation;
- agent-proposed numerical values are never accepted automatically;
- engineering judgment and secondary synthesis remain provisional and require explicit acceptance and rationale;
- disagreement between sources is shown, not silently resolved.

Evidence uploads:

- accept PDF, XLSX, CSV, PNG, JPEG, and WebP;
- maximum 10 MB per file, 10 files and 50 MB per case;
- reject executable content, macros, legacy XLS, SVG, archive bombs, MIME mismatches, and unsafe filenames;
- stream-hash files and store them under a hidden content-addressed root;
- never expose server filesystem paths;
- treat document content as untrusted data and ignore embedded instructions;
- extract candidate field, value, unit, confidence, and source location;
- require the user to accept each candidate before it can enter a runnable scenario.

Extend the TEA evidence schema without breaking existing metadata-only citations by adding a `server_managed_content_v1` preservation mode. Freeze file hash and byte count into job provenance and re-verify them before worker execution.

## Scenario and execution contract

- One case contains one baseline and at most three alternatives.
- All scenarios in a case share one Annual source and one TEA analysis basis.
- Use the same realization count and seed by default.
- A controlled comparison changes only declared assumptions.
- A structural comparison changes cost-stack structure and receives a visible warning that causal attribution is limited.
- A cross-source or cross-basis request must start a new case.
- The agent may build a guided TEA draft from accepted inputs; advanced or unsupported structures deep-link to the existing expert TEA form.
- Scenario validation returns field-level errors, the violated contract rule, and nearest supported alternatives.
- Agent-created unconfirmed drafts expire after seven days.
- The user may select up to four validated scenarios and approve them in one batch review.
- Batch confirmation includes operator name, exact request hashes, source identity, evidence receipts, expected queue behavior, and acknowledgement text.
- The server atomically creates the TEA jobs under the existing orchestration lock; the existing worker executes them sequentially.
- A retry creates a new TEA job from the same frozen request and snapshot.

## Question and recommendation behavior

Classify each user question as:

- definition;
- current-state explanation;
- root-cause or driver explanation;
- result comparison;
- scenario or sensitivity request;
- feasibility or “why not” question;
- decision-summary request.

Every answer labels its basis as measured fact, model result, accepted assumption, public evidence, or agent interpretation.

For “why can’t we try this,” return:

1. whether it is possible;
2. the exact blocking rule or missing evidence;
3. why that rule protects the analysis;
4. the closest supported alternative;
5. the next action or deep link.

After TEA completion, build a deterministic comparison bundle containing request differences, P5/P50/P95 metrics, outcome probabilities, sensitivity drivers, convergence, evidence status, and provenance. The agent turns that bundle into a conditional recommendation:

- SolarEdge, Solectria, or no decisive winner;
- strong, mixed, or provisional confidence;
- key cost and energy drivers;
- important uncertainty and evidence gaps;
- conditions likely to reverse the recommendation;
- one or two useful follow-up scenarios.

The agent must propose a new scenario rather than invent an uncalculated reversal threshold.

## Frontend design

Add an Autonomy tab using the dashboard’s current teal, white, pale green, muted gray, typography, spacing, and accessible-control language.

Desktop Decision Canvas:

- top case bar with case selector, editable question, status, lifecycle insight, and New Decision;
- embedded conversation workspace for questions, citations, and follow-ups;
- scenario workspace for baseline plus three alternatives, exact differences, evidence completeness, validation, selection, and job progress;
- persistent evidence and assumptions rail;
- readiness strip for Calibration, Annual source, weather coverage, TEA evidence, and agent availability;
- full-width results view with recommendation, confidence, cost/energy distributions, joint outcome probabilities, sensitivity, convergence, caveats, and reversal conditions;
- final sign-off bar with accept, reject, defer, name, rationale, PDF, and technical exports.

Responsive behavior:

- wide desktop: conversation, scenario, and evidence columns;
- tablet: conversation and scenario split, evidence as drawer;
- mobile: Ask, Scenarios, Evidence, and Decision tabs with sticky composer and confirmation bar.

Required visible states:

- no case;
- readiness blocked;
- evidence needed;
- scenario draft;
- ready for confirmation;
- queued/running;
- partial results;
- decision ready;
- signed;
- agent unavailable while manual workflows remain usable.

## Manager decision brief

Generate the PDF from the signed structured case snapshot rather than a new model response. Include:

- decision question and disposition;
- conditional recommendation and confidence;
- baseline and alternative comparison;
- P5/P50/P95 cost, energy, LCOE/LCOO, and probability evidence;
- sensitivity drivers and reversal conditions;
- assumptions, uploaded evidence, public citations, and provisional-input warnings;
- calibration, Annual, TEA job, request, source, and report hashes;
- decision-owner name, rationale, and timestamp;
- links or identifiers for each scenario’s existing CSV/XLSX exports.

Draft reports are visibly watermarked. A signed revision is immutable; later analysis creates a new report revision.

## API surface

- Create, list, read, rename, and archive decision cases.
- Stream Decision Agent messages with status, citation, scenario-draft, final, and error events.
- Run an idempotent readiness/lifecycle evaluation.
- Upload, inspect, download, accept, and remove unreferenced evidence.
- Create, revise, and validate scenario drafts.
- Confirm a scenario batch with hashes and operator identity.
- Poll linked TEA jobs through existing status contracts.
- Record accept/reject/defer sign-off.
- Generate and download a verified PDF report.

The new services call existing Python validators and store methods directly; they do not call the application’s HTTP endpoints internally.

## Delivery sequence

### Phase 0 — contract and visual target

- Approve this unified behavior contract and selected frontend direction.
- Add a decision-layer and server-managed-evidence addendum to the TEA contract.
- Define structured agent outputs, tool schemas, state transitions, and approval copy.

### Phase 1 — durable foundation

- Add SQLite migration, tables, indexes, immutability triggers, and serializers.
- Add content-addressed evidence storage and verified downloads.
- Add deterministic readiness and scenario comparison services.

### Phase 2 — Decision Agent and APIs

- Add the separate Agents SDK package and narrow tools.
- Add case, message-stream, evidence, scenario, confirmation, lifecycle, sign-off, and report APIs.
- Add bounded context, retry, tracing, and prompt-injection protections.

### Phase 3 — Autonomy frontend

- Add the fourth mode tab and Decision Canvas.
- Preserve canonical `frontend/` assembly order and classic-script constraints.
- Connect case history, streaming chat, readiness, uploads, scenario validation, batch confirmation, job progress, results, sign-off, and downloads.
- Hide Solar Agent only while Autonomy is active.

### Phase 4 — PDF and decision experience

- Add deterministic report generation and hash verification.
- Add recommendation, caveat, sensitivity, reversal-condition, and evidence-trace presentation.
- Complete responsive and accessibility behavior.

### Phase 5 — shadow rollout

- Gate with `DECISION_AGENT_ENABLED` and `DECISION_AGENT_SHADOW_MODE`.
- Run twenty behavior eval cases and ten human-reviewed live shadow cases.
- Enable scenario confirmation only after zero unauthorized execution, complete numeric citation coverage, and successful result/report tie-outs.

## Verification and acceptance

Backend tests cover migrations, immutable fields, cross-table guards, evidence hashes, malformed uploads, prompt injection, atomic confirmation, idempotency, worker restart, retry, and signed report verification.

Agent evals cover definitions, “why,” “why not,” missing prerequisites, missing evidence, conflicting evidence, unsupported assumptions, scenario drafting, tool-call limits, timeouts, public citations, uploaded evidence, result explanation, and refusal to execute without confirmation.

Frontend tests cover every workspace state, exact scenario differences, confirmation identity, focus management, keyboard operation, screen-reader announcements, tablet/mobile layouts, and OpenAI-unavailable fallback.

Release validation requires:

- all existing Python tests;
- new Autonomy and decision-layer tests;
- dashboard assembly tests;
- TypeScript checks and `npm run build`;
- visual verification at desktop, tablet, and mobile sizes;
- deterministic PDF-to-result tie-outs;
- existing Calibration, Annual, TEA, exports, worker leasing, and Solar Agent behavior unchanged.

## Definition of done

A mixed technical or management user can open Autonomy, ask a PV/TEA question, understand readiness and evidence, create controlled alternatives, confirm exact TEA jobs, follow their progress, receive a traceable conditional recommendation, ask follow-up questions, sign the decision, and download a verified manager PDF—without the agent calculating results, bypassing human authority, weakening the TEA contract, or breaking the existing dashboard workflows.

