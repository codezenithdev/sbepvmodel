# Hybrid Autonomy Frontend Foundation Contract

Status: **approved implementation contract**

Version: **1.0**

Date: **2026-08-27**

Scope: **Hybrid Autonomy Workspace Phase 0 and Phase 1 only**

Live recommendation authority: **not part of this historical fixture phase**;
subsequent deterministic recommendation behavior is governed by
`AUTONOMY_CONSERVATIVE_RECOMMENDATION_CONTRACT_V1.md`.

## 1. Authority and interpretation

This contract applies the approved
`HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md` to a fixture-backed frontend
foundation. The hybrid contract controls interaction and phase numbering. The
unified contract continues to control the eventual architecture and end-state
authority boundary.

The approved conservative-dominance addendum controls the later live winner,
no-winner, confidence, warning, and reversal classification. It does not
retroactively turn these Phase 1 fixtures into server results.

For this delivery, Phase 1 means the hybrid contract's shared shell and read-only,
fixture-backed states. It does **not** mean the unified plan's later durable backend
foundation. No Decision Agent, decision-case persistence, evidence storage, scenario
execution API, comparison service, report generator, or TEA calculation change is
authorized.

The recoverable `forecast-autonomy-workflow.html` concept is an earlier Option 1
reference. It may inform readiness, evidence, status, and audit presentation only.
Its nine-stage lifecycle, autonomous controls, blue/gradient language, two-column
layout, and responsive breakpoints are not authoritative. The written hybrid plan
and existing dashboard visual language win.

## 2. Phase 0 deliverables

Phase 0 is complete when:

1. the approved unified and hybrid plans are preserved verbatim under `docs/` with
   repository version metadata;
2. this frontend-foundation contract records the fixture state matrix, authority
   boundary, deterministic transitions, and approval language;
3. the implementation file boundary and verification commands are explicit; and
4. Phase 2 and later work is named but not implemented.

## 3. Fixture authority boundary

All Autonomy data in Phase 1 is deterministic local fixture data. The fixture layer:

- uses one stable case identity, `case_sbe_hybrid_001`, across Investigation and
  Decision Brief views;
- uses structured state enums and fields rather than parsing displayed prose;
- may simulate a state transition for demonstration, but never calls `fetch`, an
  OpenAI client, a decision endpoint, a TEA mutation endpoint, or an existing model
  execution control;
- never calculates lifecycle metrics; displayed numbers are named fixture values
  representing a future deterministic comparison payload;
- never writes evidence, scenarios, sign-offs, reports, jobs, baselines, or agent
  messages to the server;
- never changes Calibration, Annual Simulation, existing TEA, exports, workers,
  Saved Results, or Solar Agent state; and
- labels the state selector and simulated confirmation boundary as fixture-only.

## 4. Required fixture catalog

The frontend exposes every state below through one accessible fixture-state
selector. All case-bearing states use the same case ID and revision unless a state
explicitly demonstrates a superseding revision.

| Fixture ID | Visible condition | Default stage | Default view | Allowed primary action |
| --- | --- | --- | --- | --- |
| `no-case` | No decision cases | Ask | Investigation | Start a decision |
| `new-case` | New case with suggested questions | Ask | Investigation | Frame the question |
| `calibration-blocked` | Calibration missing or unpromoted | Verify evidence | Investigation | Open Calibration |
| `annual-unavailable` | No eligible Annual source | Verify evidence | Investigation | Open Annual Simulation |
| `annual-incomplete` | Annual source coverage incomplete | Verify evidence | Investigation | Inspect source coverage |
| `annual-stale` | A newer verified Annual source exists | Verify evidence | Investigation | Review source lock |
| `evidence-needed` | Required cost evidence missing | Verify evidence | Investigation | Review evidence gaps |
| `evidence-conflict` | Two sources disagree | Verify evidence | Investigation | Compare both sources |
| `agent-unavailable` | Decision Agent unavailable | Ask | Investigation | Continue manual review |
| `scenario-invalid` | Scenario violates a supported rule | Compare scenarios | Investigation | Review nearest supported alternative |
| `ready-to-confirm` | Selected scenarios validated | Run TEA | Investigation | Open grouped confirmation |
| `queued` | Approved fixture jobs waiting | Run TEA | Investigation | Monitor queue |
| `running` | Existing worker progress simulated | Run TEA | Investigation | Monitor progress |
| `failed` | One fixture job failed | Run TEA | Investigation | Review retry guidance |
| `partial-results` | At least one result complete and another failed/running | Run TEA | Investigation | Preview partial results |
| `results-ready` | Comparison bundle complete | Decide | Investigation | Open Decision Brief |
| `recommendation-provisional` | Brief open with provisional evidence | Decide | Decision Brief | Test a reversal |
| `decision-ready` | Recommendation ready for sign-off | Decide | Decision Brief | Prepare sign-off |
| `signed` | Immutable signed fixture revision | Decide | Decision Brief | View signed record |
| `signed-superseded` | Signed revision followed by a new scenario revision | Compare scenarios | Investigation | Review the new revision |
| `network-reconnecting` | Message stream interrupted | Ask | Investigation | Retry fixture connection |
| `shared-case-stale` | Another authenticated user changed the shared case | Verify evidence | Investigation | Refresh case snapshot |

No state may end in a dead-end error. Every blocked, failed, stale, or unavailable
state states what remains safe and offers exactly one supported recovery action.

## 5. Shared shell contract

Autonomy is a fourth top-level dashboard mode. Existing mode labels, order, and
behavior remain unchanged. The shared Autonomy shell contains:

- a case selector, editable title treatment, decision question, status, owner,
  Annual source lock, TEA basis lock, updated time, and New Decision control;
- an Investigation / Decision Brief view switch when result evidence permits;
- the five-stage stepper `Ask → Verify evidence → Compare scenarios → Run TEA →
  Decide`;
- a compact readiness strip for Calibration, Annual source, Weather coverage, TEA
  evidence, and Decision Agent;
- a fixture-state selector clearly described as local preview data; and
- one live status region for restrained transition announcements.

Solar Agent UI is removed from the visual and accessibility trees only while
Autonomy is active. Its state and history are not cleared or repurposed. The
fixture-backed Decision Agent panel is separate and performs no network work.

## 6. Investigation Workspace contract

At 1280 CSS pixels and wider, Investigation uses a `320px / minmax(0, 1fr) / 320px`
grid:

1. Decision Agent conversation and case history;
2. the selected stage canvas; and
3. Evidence, Assumptions, Readiness, and Provenance rail tabs.

The center canvas contains the complete manager-demo path:

- Ask: editable decision frame, constraints, and suggested path;
- Verify evidence: readiness blockers, source lineage, candidate evidence, and
  acceptance boundary;
- Compare scenarios: one baseline and three alternatives, baseline-relative
  differences, evidence status, validation, and structural warnings;
- Run TEA: grouped confirmation, immutable fixture hashes, operator identity,
  acknowledgement, queue, progress, failure, and retry presentation; and
- Decide: completed/partial bridge into Decision Brief.

All quantitative claims carry one basis label: Measured fact, Model result,
Accepted assumption, Public evidence, or Agent interpretation.

## 7. Decision Brief contract

Decision Brief uses the same case ID, source lock, basis lock, scenario revision,
and fixture results as Investigation. It contains:

- recommendation and confidence without overstating certainty;
- top reasons and largest unresolved uncertainty;
- P5/P50/P95 lifecycle cost, lifecycle energy, and approved economic outcome
  fixtures;
- scenario-preference probability and evidence completeness;
- table-first cost distribution, energy distribution, joint outcome, sensitivity,
  scenario comparison, and convergence/quality panels;
- reversal conditions that state direction, simulation status, and needed evidence;
- evidence, caveats, provenance, and a decision timeline;
- a compact follow-up agent surface; and
- Accept, Reject, or Defer sign-off with owner, rationale, acknowledgement, and
  immutable-revision language.

Partial results may open a clearly labeled preview, but recommendation and sign-off
controls remain unavailable. Fixture numbers never claim to be server results.

## 8. Deterministic transition rules

- `no-case`, new, blocked, stale, invalid, queued, running, failed, partial, agent
  unavailable, and reconnecting states open in Investigation at the first relevant
  incomplete stage.
- `results-ready` remains in Investigation until the user explicitly opens the
  Decision Brief. The ready banner is non-blocking and never steals focus.
- `recommendation-provisional` and `decision-ready` represent an explicitly opened
  Decision Brief.
- `signed` opens in Decision Brief.
- Partial-results preview is allowed, stays labeled partial, and cannot enable
  sign-off.
- Return to Investigation preserves case ID, revision, selected fixture, result
  evidence, and the most relevant earlier stage.
- Editing a confirmed assumption creates a visible new revision and marks the prior
  brief superseded; it never mutates the signed fixture.
- A stage-button click changes only the visible section. It never changes case state
  or permissions.
- Active typing is never interrupted by an automatic view switch.

## 9. Approval and authority language

Evidence acknowledgement:

> I reviewed this evidence candidate and understand that provisional evidence
> requires a named rationale before it can support a runnable request.

Grouped TEA confirmation acknowledgement:

> I confirm the selected scenarios, source and basis lock, evidence status,
> realization count, seed, and exact request hashes shown here. I understand the
> production action would create immutable TEA jobs for sequential worker execution.

Phase 1 adds the visible confirmation surface only. Its button says `Preview queued
state` and the adjacent notice says `Fixture preview — no jobs will be created`.

Sign-off acknowledgement:

> I understand that signing freezes an immutable decision snapshot. It does not
> change plant controls, calibration or Annual baselines, existing TEA jobs, or the
> approved calculation contract.

Phase 1 sign-off transitions only to the local `signed` fixture.

## 10. Responsive and accessibility acceptance

### Desktop: 1280px and wider

- three-region Investigation grid at `320px / 1fr / 320px`;
- persistent evidence rail;
- full Decision Brief analysis grid; and
- sticky sign-off without covering content.

### Tablet: 768–1279px

- conversation and stage canvas split;
- evidence rail opens as a modal drawer with Escape, focus trap, and focus restore;
- stepper scrolls horizontally with visible labels;
- Decision Brief analysis panels use two columns where space permits; and
- sign-off wraps without hiding identity, rationale, or acknowledgement.

### Mobile: below 768px

- Ask, Scenarios, Evidence, and Decision tabs;
- compact stage selector;
- sticky composer and confirmation action;
- baseline-relative scenario lists rather than a wide matrix;
- table-first Decision Brief panels; and
- full-screen sign-off review.

Across sizes:

- native controls and buttons are keyboard operable in logical DOM order;
- tablists support Arrow keys, Home, End, Enter, and Space;
- stage/status meaning is always present in text and never color-only;
- `aria-current="step"`, labelled tabpanels, descriptive source controls, restrained
  `aria-live`, and table equivalents are present;
- modal surfaces trap focus, close on Escape, and restore their trigger;
- interactive targets are at least 44 CSS pixels on mobile and mobile form controls
  render at 16px or larger;
- reduced-motion and forced-colors preferences are honored; and
- no horizontal page overflow occurs at 390 CSS pixels.

## 11. Phase 1 acceptance

Phase 1 passes only when:

1. every fixture state is reachable without network access;
2. the complete Ask-to-Decide manager demo is clickable;
3. Investigation and Decision Brief demonstrably share one case and deterministic
   transitions;
4. empty, blocked, running, partial, completed, and signed states are visually and
   accessibly distinct;
5. desktop, tablet, mobile, keyboard, focus, screen-reader semantics, reduced motion,
   and forced colors are verified;
6. Python and Vite assemblers include the same canonical source text;
7. relevant frontend, dashboard assembly, and project-layout tests pass;
8. TypeScript validation and the Vinext production build pass; and
9. Calibration, Annual Simulation, existing TEA, exports, workers, Saved Results,
   and Solar Agent behavior remain unchanged.

## 12. Explicit Phase 2 handoff boundary

The recommended Phase 2 handoff is the hybrid contract's durable case and readiness
foundation: decision-case/event persistence, immutable status transitions,
serializers, and deterministic readiness evaluation. Before that work begins, the
fixture enums and view transitions in this contract should become shared schema
fixtures and server contract tests. Evidence storage, Decision Agent tools, scenario
execution, comparison services, sign-off persistence, PDF generation, and any TEA
kernel change remain later phases and require their own authorization.
