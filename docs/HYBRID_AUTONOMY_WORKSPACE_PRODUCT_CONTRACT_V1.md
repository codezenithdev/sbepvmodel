# Product contract metadata

- Status: Approved
- Contract version: 1.0
- Approved direction date: 2026-08-20
- Preserved in repository: 2026-08-27
- Source: approved Hybrid Autonomy Workspace plan
- Authority: controlling interaction and frontend-phase contract
- Conflict rule: when a mockup or the unified plan's phase numbering differs, this written hybrid contract controls the Phase 0/Phase 1 frontend foundation.

---

# Hybrid Autonomy Workspace Plan

## 1. Chosen direction

The product will use one Autonomy workspace with two connected modes:

1. **Investigation Workspace** — the guided flow from Option 2: Ask, Verify evidence, Compare scenarios, Run TEA, Decide.
2. **Decision Brief** — the recommendation-first presentation from Option 3: recommendation, confidence, outcomes, drivers, uncertainty, reversal conditions, evidence, and sign-off.

These are not separate products or disconnected pages. They are two views of the same durable decision case. The interface begins in Investigation mode and transitions into Decision Brief mode when the required TEA results are complete. A user can always return to the investigation, ask follow-up questions, or create a new scenario revision.

The evidence and readiness rail from Option 1 is retained because it gives the system visible trust and traceability without overwhelming the main canvas.

## 2. Product promise and autonomy boundary

The workspace should let an end user ask questions such as:

- Why is the PV result like this?
- What does this metric or assumption mean?
- What is driving the difference between SolarEdge and Solectria?
- Why can’t we try a similar design, cost, degradation rate, or operating assumption?
- What evidence is missing?
- Which option is economically preferable, how certain is that conclusion, and what could reverse it?

The product is **supervised autonomy**, not unattended execution. The system may observe state, identify missing prerequisites, retrieve evidence, explain results, propose controlled scenarios, validate requests, monitor approved work, compare completed TEA results, and draft a recommendation. A named human must still accept evidence, confirm exact TEA request hashes, and sign the final decision.

The agent never calculates lifecycle results itself, bypasses the TEA contract, promotes calibration, waives a data-quality gate, queues a run without confirmation, or signs its own recommendation.

## 3. Primary user journey

### Stage 1 — Ask

The user opens Autonomy, starts or resumes a decision case, and asks a natural-language question. The Decision Agent converts the question into a visible decision frame:

- decision to be made;
- baseline being evaluated;
- metric or outcome that matters;
- known constraints;
- information still needed;
- proposed next action.

The user can edit the decision question directly. The original question remains in the case history.

### Stage 2 — Verify evidence

The deterministic readiness service checks calibration lineage, eligible Annual source, weather coverage, source integrity, active or stale jobs, evidence completeness, and agent availability. The workspace displays each check as Passed, Needs attention, Blocked, or Stale.

The agent explains every issue in plain language. A blocked item must show:

1. what is missing or invalid;
2. why it matters;
3. the exact rule involved;
4. the closest supported action;
5. a deep link to the existing workflow when relevant.

The user may upload evidence, inspect extracted candidate values, and accept or reject each candidate with a rationale. Uploaded content is treated as untrusted evidence, never as instructions to the agent.

### Stage 3 — Compare scenarios

The agent proposes one baseline and up to three alternatives. Each card shows only the assumptions that differ from the baseline, evidence status, validation status, structural-comparison warnings, and expected computational scale.

The user can ask why a scenario is useful, revise an assumption, duplicate a scenario, or remove an unconfirmed draft. The comparison matrix keeps the same Annual source, TEA basis, realization count, and seed visible across all scenarios.

### Stage 4 — Run TEA

Validated scenarios enter a grouped confirmation review. The review displays:

- source and analysis-basis lock;
- exact scenario differences;
- accepted and provisional evidence;
- realization count and seed;
- immutable request hashes;
- expected queue behavior;
- operator name and acknowledgement.

Only the confirmation action creates jobs. The existing worker executes them sequentially. The workspace then becomes a progress monitor with queued, leased, running, completed, failed, interrupted, and retry states.

### Stage 5 — Decide

When enough results are complete, the workspace switches to Decision Brief mode. The system presents a conditional recommendation supported by deterministic comparison data. The user can inspect supporting evidence, ask follow-up questions, return to Investigation mode, add another scenario revision, or accept, reject, or defer the recommendation.

Signing freezes an immutable decision snapshot and enables the verified manager PDF.

## 4. Shared application shell

The two modes share one stable shell so the transition feels like the case matured rather than the user navigated to another tool.

### Global navigation

- Existing top-level dashboard navigation remains unchanged.
- Add **Autonomy** as a new top-level mode.
- Hide the existing Solar Agent drawer only while Autonomy is active.
- Show the separate Decision Agent inside the Autonomy workspace.

### Case header

The header remains visible in both modes and contains:

- case selector and search;
- editable case title;
- short decision question;
- case status;
- decision owner;
- Annual source and TEA basis lock;
- last updated time;
- New Decision action;
- Investigation / Decision Brief view switch when results exist;
- compact overflow menu for rename, archive, export, and case details.

### Five-stage stepper

The stepper is the primary orientation device:

`Ask → Verify evidence → Compare scenarios → Run TEA → Decide`

Each step can be Complete, Current, Needs attention, Blocked, or Not started. Clicking a completed step changes the visible workspace section but never changes the case state. Blocked steps open the exact blocker summary rather than silently doing nothing.

### Readiness strip

A compact strip under the stepper shows:

- Calibration;
- Annual source;
- Weather coverage;
- TEA evidence;
- Decision Agent.

The strip is always visible in Investigation mode and collapses to a one-line provenance summary in Decision Brief mode.

## 5. Investigation Workspace layout

### Desktop, 1280 px and wider

Use a three-region grid:

- **Left, 320 px:** Decision Agent conversation and case history.
- **Center, flexible:** current stage canvas, scenario comparison, charts, validation, and job progress.
- **Right, 320 px:** evidence, assumptions, readiness detail, and provenance.

The center is visually dominant. Side regions may collapse independently to icon tabs, giving the analysis canvas more space during scenario comparison.

### Left: Decision Agent

The agent panel contains:

- active question and conversation thread;
- starter prompts based on case state;
- responses divided into Answer, Basis, Limits, and Next action;
- evidence chips that open the supporting source in the right rail;
- scenario proposals rendered as reviewable cards rather than hidden tool activity;
- sticky composer supporting text and evidence attachment;
- clear status for thinking, checking readiness, validating, waiting for confirmation, or unavailable.

Every quantitative claim carries a basis label: Measured fact, Model result, Accepted assumption, Public evidence, or Agent interpretation.

### Center: stage canvas

The center changes with the selected step:

- **Ask:** editable decision frame, key context, initial explanation, and suggested investigation path.
- **Verify:** readiness checklist, source timeline, evidence gaps, extracted candidates, and acceptance actions.
- **Compare:** baseline plus alternatives, difference matrix, scenario validity, and evidence completeness.
- **Run TEA:** final confirmation summary, job queue, progress timeline, warnings, and retry controls.
- **Decide:** compact bridge into the full Decision Brief with preliminary outcome summary.

### Right: evidence and assumptions rail

The rail has four tabs:

1. Evidence
2. Assumptions
3. Readiness
4. Provenance

Evidence entries show category, source, date, extraction location, hash, acceptance state, and which scenario fields consume them. Conflicting sources remain side by side. Provisional evidence uses a persistent warning treatment until explicitly accepted.

## 6. Decision Brief layout

Decision Brief mode prioritizes the conclusion while keeping the investigation one click away.

### Recommendation hero

The first card answers the decision question directly:

- SolarEdge, Solectria, or No decisive winner;
- Strong, Mixed, or Provisional confidence;
- one-sentence conditional recommendation;
- top three reasons;
- largest unresolved uncertainty;
- actions: Ask why, Test a reversal, Return to investigation, and Prepare sign-off.

The hero must never imply certainty that the underlying comparison does not support.

### Outcome row

Show the most decision-relevant results with P5, P50, and P95 context:

- lifecycle cost difference;
- lifecycle energy difference;
- LCOE or approved economic metric difference;
- probability each alternative is preferable;
- evidence-completeness indicator.

Every metric links back to the scenario result and provenance. Numbers are populated only from TEA payloads or deterministic comparison services.

### Analysis canvas

Use two rows:

- **Row 1:** cost distribution, energy distribution, and joint outcome probability.
- **Row 2:** sensitivity drivers, scenario comparison, and convergence/quality status.

Charts must include a table fallback and a plain-language interpretation. Tooltips state units, percentile meaning, source job, and scenario.

### Reversal conditions

This section is central to the product, not buried in caveats. It shows:

- assumptions most likely to change the recommendation;
- which direction they would need to move;
- whether that condition has already been simulated;
- evidence needed to reduce uncertainty;
- a button to create a new controlled scenario.

The agent may propose a reversal test but cannot invent an uncalculated threshold.

### Evidence and caveats

Summarize accepted evidence, provisional inputs, conflicts, missing data, model limitations, and source lineage. Each item links to its full record in the Investigation Workspace.

### Decision timeline and compact agent

The right side becomes a narrow case timeline: question created, evidence accepted, scenarios confirmed, jobs completed, recommendation produced, and sign-off. A compact Decision Agent remains available for follow-up questions without displacing the brief.

### Sign-off bar

The final sticky bar includes Accept, Reject, or Defer; typed decision-owner name; rationale; timestamp; acknowledgement; and PDF generation. Signing creates a new immutable report revision. Existing signed revisions remain available.

## 7. Mode transition rules

The transition is deterministic:

- A new or blocked case opens in Investigation mode at the first incomplete stage.
- A running case opens at Run TEA with the job monitor visible.
- When all selected scenarios complete, show a non-blocking “Decision brief ready” banner.
- If at least one result completes and another fails, stay in Investigation mode and offer a clearly labeled Partial results preview.
- When the comparison bundle is complete, switch to Decision Brief on the user’s next explicit action or on page open; do not interrupt active typing.
- A signed case opens in Decision Brief mode.
- “Return to investigation” preserves all results and opens the most relevant earlier stage.
- Editing a confirmed assumption creates a new scenario revision and visibly marks the current brief as superseded, never silently mutating it.

## 8. Critical interaction patterns

### “Why is it like this?”

Return a structured explanation:

1. direct answer;
2. main drivers ranked by impact;
3. evidence for each driver;
4. uncertainty or competing explanations;
5. next useful check or scenario.

### “What is this?”

Define the term in plain language, show the exact dashboard definition and unit, explain how it enters the TEA, and link to the calculation provenance.

### “Why can’t we try this?”

Return whether it is possible, the exact blocking rule or missing evidence, why the rule protects validity, the nearest supported alternative, and an action to proceed. Unsupported input must never produce a dead-end error message.

### Scenario proposal

An agent proposal appears as a draft card with changed fields, rationale, evidence state, and Validate action. It does not enter the execution queue.

### Evidence acceptance

Candidate values appear beside their source excerpt or cell reference. The user accepts or rejects each candidate separately and supplies rationale for provisional categories.

### Confirmation

The execution boundary is a dedicated review surface, not a chat reply. It requires explicit selection, operator identity, acknowledgement, and a final Confirm TEA runs action.

## 9. Required states and recovery behavior

The frontend must intentionally design and test these states:

- no decision cases;
- new case with suggested questions;
- calibration missing or unpromoted;
- Annual source unavailable, incomplete, or stale;
- evidence missing;
- evidence conflicting;
- agent unavailable while manual dashboard workflows remain usable;
- scenario invalid;
- ready for confirmation;
- jobs queued or running;
- one job failed;
- partial results;
- all results ready;
- recommendation provisional;
- recommendation ready for sign-off;
- signed case;
- signed case superseded by a new revision;
- network interruption and message-stream reconnection;
- stale browser state after another authenticated user changes the shared case.

Every error must preserve the case, state what remains safe, and provide one supported recovery action.

## 10. Visual language

Use the current dashboard’s teal, white, pale green, muted gray, typography, spacing, and control language. The Autonomy workspace should feel native to the dashboard, not like a separate AI application.

Suggested semantic treatments:

- teal: navigation, active step, selected case, primary actions;
- green: passed, completed, accepted evidence;
- amber: provisional, stale, partial, needs attention;
- red: hard contract block, failed job, invalid request;
- blue-gray: informational provenance and agent interpretation;
- purple accent used sparingly for generated scenario proposals, never for authoritative results.

Cards use restrained borders and low elevation. Dense tables should remain calm and legible. Avoid decorative gradients in analytical areas. Motion is limited to stage transitions, progress, rail expansion, and the Investigation-to-Brief reveal; honor reduced-motion settings.

## 11. Responsive behavior

### Tablet, 768–1279 px

- Conversation and center canvas become a two-column split.
- Evidence opens as a right-side drawer.
- The stepper becomes horizontally scrollable with visible labels.
- Decision Brief charts stack two per row.
- The sign-off bar wraps into two lines without hiding identity or rationale.

### Mobile, below 768 px

- Use four tabs: Ask, Scenarios, Evidence, Decision.
- Keep the composer and run-confirmation action sticky.
- Convert the five-stage stepper to a compact stage selector.
- Scenario comparison becomes a baseline-relative field list rather than a wide table.
- Decision Brief charts stack vertically with table-first fallbacks.
- Sign-off opens a full-screen review sheet.

## 12. Accessibility and trust requirements

- All actions are keyboard operable with a logical focus order.
- Stage, readiness, evidence, and job status never rely on color alone.
- Streaming agent text and job progress use restrained ARIA live announcements.
- Charts have descriptive titles, units, table equivalents, and downloadable data.
- Drawers and confirmation sheets trap and restore focus correctly.
- Source chips expose descriptive labels rather than raw URLs.
- Destructive or irreversible actions state their consequence before confirmation.
- The Decision Agent’s interpretation is visually distinct from deterministic model output.
- Signed and unsigned reports are unmistakable.

## 13. Backend and data bindings

The hybrid UI consumes the decision-layer services defined in the unified system plan:

- case list, details, state, and event timeline;
- deterministic readiness evaluation;
- streamed Decision Agent messages and citations;
- evidence upload, extraction, acceptance, and download;
- scenario draft, revision, validation, and batch confirmation;
- existing TEA job status and results;
- deterministic cross-scenario comparison bundle;
- sign-off and verified report generation.

The UI should render from structured fields and status enums, not parse prose to infer state. Agent messages may explain a state but cannot define permissions or allowed actions.

## 14. Frontend component map

### Shared

- `AutonomyShell`
- `DecisionCaseHeader`
- `AutonomyStageStepper`
- `ReadinessStrip`
- `DecisionAgentPanel`
- `EvidenceRail`
- `CaseStatusBadge`
- `SourceBasisChip`

### Investigation

- `DecisionFrame`
- `ReadinessChecklist`
- `EvidenceCandidateReview`
- `ScenarioCard`
- `ScenarioDifferenceMatrix`
- `ScenarioValidationPanel`
- `BatchConfirmationReview`
- `TeaJobMonitor`
- `PartialResultsBanner`

### Decision Brief

- `RecommendationHero`
- `OutcomeMetricRow`
- `DistributionChartPanel`
- `JointOutcomePanel`
- `SensitivityDriversPanel`
- `ReversalConditionsPanel`
- `EvidenceCaveatsSummary`
- `DecisionTimeline`
- `DecisionSignoffBar`

The current dashboard is assembled from canonical frontend partials and classic scripts. Autonomy-specific HTML, CSS, and JavaScript should be added in filename order without disturbing the load-bearing agent-drawer ordering. Python fallback and Vite slot replacement/newline behavior must remain equivalent.

## 15. Implementation sequence

### Phase 0 — freeze the product contract

- Approve this hybrid interaction contract.
- Map every durable case state to a visible UI state and allowed actions.
- Approve confirmation and sign-off language.
- Confirm the selected visual direction as the implementation target.

Exit: no ambiguity about authority, state transitions, or what the agent may execute.

### Phase 1 — shared shell and read-only states

- Add the Autonomy top-level mode.
- Build the case header, stepper, readiness strip, Investigation grid, Decision Brief shell, and responsive layout.
- Populate with realistic static fixtures for every required state.
- Keep all existing workflows unchanged.

Exit: the full manager-demo journey can be clicked through with fixture data.

### Phase 2 — durable case and readiness foundation

- Add decision-case persistence, events, statuses, and serializers.
- Add deterministic readiness evaluation.
- Connect case history, source locks, blocker details, and lifecycle insight.

Exit: a case survives restart and accurately explains prerequisites.

### Phase 3 — evidence and Decision Agent

- Add secure evidence upload, extraction, candidate review, acceptance, and provenance.
- Add bounded Decision Agent conversations, structured outputs, citations, retry, timeout, and unavailable states.
- Implement the “why,” “what,” and “why not” response patterns.

Exit: the agent can investigate and propose, but cannot execute.

### Phase 4 — scenarios and execution boundary

- Add baseline and alternative drafts, revisions, validation, comparison, and expiry.
- Add grouped confirmation with hashes and operator identity.
- Connect atomic TEA job creation and existing sequential worker progress.

Exit: only explicitly confirmed validated requests can run.

### Phase 5 — Decision Brief and reports

- Add deterministic comparison bundle and recommendation presentation.
- Add charts, sensitivity, convergence, caveats, and reversal tests.
- Add sign-off, immutable snapshots, and verified manager PDF.

Exit: completed cases produce a traceable decision and report.

### Phase 6 — QA and shadow rollout

- Test desktop, tablet, and mobile behavior.
- Run accessibility and keyboard checks.
- Validate Python and Vite dashboard assembly equivalence.
- Run agent behavior evals, numerical tie-outs, report tie-outs, and existing regression suites.
- Roll out behind enable and shadow-mode flags before enabling execution confirmation.

Exit: zero unauthorized runs, complete numeric provenance, and no regressions in Calibration, Annual, TEA, worker leasing, exports, or Solar Agent behavior.

## 16. Manager demo storyline

Use a seven-minute narrative:

1. Open an existing case and ask why the two PV systems differ.
2. Show the agent grounding its answer in model, evidence, and readiness state.
3. Reveal one missing or provisional assumption and accept a reviewed evidence candidate.
4. Compare the baseline with three controlled alternatives.
5. Open the exact run-confirmation review and explain the human authority boundary.
6. Jump to completed results and reveal the Decision Brief.
7. Ask what could reverse the recommendation, create a follow-up scenario draft, then show sign-off and the manager PDF.

The core message is: **the dashboard does not merely automate calculations; it conducts a traceable investigation, asks for authority at the right moments, and turns validated analysis into a defensible decision.**

## 17. Product acceptance criteria

The hybrid is complete when a mixed technical and management user can:

- understand where a case is in the five-stage journey;
- ask natural-language PV and TEA questions and inspect the basis of every answer;
- identify missing prerequisites and evidence without reading logs;
- review one baseline and up to three controlled alternatives;
- understand exactly why an unsupported scenario is blocked and what can be tried instead;
- confirm immutable TEA requests with named human authority;
- monitor the existing worker without losing case context;
- understand outcome distributions, sensitivity, uncertainty, and reversal conditions;
- move naturally between investigation detail and executive summary;
- sign and export a verified decision brief;
- do all of this without the agent calculating results, changing approved contract behavior, or executing unconfirmed work.

## 18. Defaults locked for the first implementation

- Desktop-first responsive web application.
- Investigation Workspace is the default for unsigned active cases.
- Decision Brief is the default for signed cases and is offered when comparison results are complete.
- Baseline plus a maximum of three alternatives.
- Evidence rail is persistent on wide desktop and a drawer on smaller screens.
- The switch between modes never creates a new case or loses context.
- Partial results are visible but cannot be presented as a final recommendation.
- Agent proposals are drafts; deterministic services own validation and state.
- Human confirmation is required for evidence acceptance, TEA execution, and sign-off.
- Signed decision snapshots and PDFs are immutable and revisioned.

## 19. Implementation-chat kickoff

Use this plan together with `AGENTS.md`, the unified autonomy/TEA system plan, the selected Option 2 and Option 3 visuals, and the approved TEA calculation contract. Begin with Phase 0 and Phase 1 only: verify the current canonical frontend assembly, map existing design tokens and patterns, create the fixture-backed hybrid shell, and visually validate the full Investigation-to-Decision-Brief journey before connecting new backend behavior. Do not alter existing Calibration, Annual, TEA, worker, export, or Solar Agent behavior during the visual foundation phase.

