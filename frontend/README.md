# Dashboard frontend sources

This directory is the dashboard's **only source of truth**. There is no committed
generated HTML file and no manual assembly step.

Two consumers assemble the same sources directly:

- `src/sbepv/dashboard.py` builds the Render/FastAPI fallback and refreshes its
  bounded cache whenever a template or partial changes.
- `frontend/dashboard.ts` uses Vite raw imports to build the Sites/Vinext version.

After editing a partial, run the Python tests and `npm run build`. The former checks
the source and Render contracts; the latter validates the Vite/Cloudflare contract.

## Layout

| Path | Contents |
| --- | --- |
| `dashboard.ts` | Vite assembler used by `app/route.ts` |
| `css/` | 16 partials concatenated into the single `<style>` block |
| `html/` | 11 markup partials plus `document.template.html` |
| `js/` | 22 partials concatenated into the single classic `<script>` block |

`document.template.html` is the surrounding document with three slots:
`{{CSS}}`, `{{MARKUP}}`, and `{{JS}}`. Both assemblers require each slot exactly
once, require every partial group to be nonempty, normalize line endings, and remove
one trailing newline from each partial before joining them.

## Order is load-bearing

Files are concatenated in filename order. Two specific constraints:

- **`13-agent-drawer-base.css` must precede `14-agent-drawer-redesign.css`.** The
  redesign is an override layer at equal specificity. Swapping these files reverts
  the Solar Agent drawer's appearance without a syntax error.
- **The JavaScript partials are one classic script sharing globals.** Several carry
  immediate-execution wiring (`event` listeners, `setInterval`, and the final
  `restoreDashboardState()` call) that depends on earlier partials having run.

Converting the JavaScript to ES modules would introduce a real circular import:
`resetClientState` reads `chatInput` and `chatSidebar`, which are declared later in
the chat layer, while the chat layer calls back into `saveDashboardState`. That
works today because nothing executes until the whole classic script has parsed.

## Markup partials are slices, not fragments

The markup files are ordered pieces of one document, not independently well-formed
fragments. `.app-shell` and `#annualPanel`, for example, span multiple files. Only
the assembled result is valid HTML.

## Hybrid Autonomy workspace

The approved Phase 0 and Phase 1 authority is recorded in
`docs/HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md`. The preserved unified and hybrid
plans remain product contracts under `docs/`; the hybrid plan controls the current
interaction and phase numbering when the plans differ.

The Autonomy frontend is assembled from:

- `html/55-autonomy-workspace.html` — the shared case shell, five-stage
  Investigation Workspace, evidence/readiness rail, live scenario and execution
  surfaces, server-backed Decision Brief authority, immutable sign-off history,
  report controls, and isolated fixture sign-off preview;
- `css/16-autonomy-workspace.css` — namespaced desktop, tablet, mobile,
  reduced-motion, and forced-colors behavior; and
- `js/07-autonomy-workspace.js` — authenticated live case, evidence, scenario,
  execution, deterministic comparison-bundle, immutable Decision Brief, human
  sign-off, and manager-report clients plus deterministic fixture previews and the
  shared view, tab, drawer, dialog, focus, keyboard, reconnect, and polling
  behavior.

Live Ask, Verify, Compare, and Run content comes only from authenticated Autonomy
APIs. Scenario cards expose server-owned allowed actions and canonical request
hashes; grouped confirmation sends the exact selected revisions, named operator,
rationale, acknowledgement, expected case revision, and idempotency key. Execution
polling links to the existing TEA job contract and exposes only the server-permitted
cancel and retry controls. Browser state never grants mutation or execution
authority.

Live Decide is enabled only by the server-returned `open_decision_brief` allowed
action. The browser reads or creates exact comparison snapshots through
`/api/autonomy/cases/{case_id}/comparison-bundles` and reads or creates unsigned
immutable brief revisions through `/api/autonomy/cases/{case_id}/decision-briefs`.
Bundle creation sends only the expected case revision, immutable confirmation ID,
and named operator. Brief creation sends only the expected case revision, bundle
ID, canonical bundle SHA-256, named operator, and idempotency key. The browser never
submits result values, picks an attempt, recalculates TEA, derives recommendation
thresholds, or grants an allowed action.

Every live metric retains its server-supplied unit, percentile definition, null or
missing state, selected scenario revision, TEA job and attempt, source snapshot,
and provenance. Partial Results retain every selected non-complete status and never
produce a final recommendation. The browser presents the server's versioned
recommendation sidecar and exact classification, confidence, warning, limitation,
and reversal records; it never derives winner or confidence thresholds. Ask why
reveals only the persisted evidence and contract output; it never invokes the
Decision Agent.

Sign-off and report authority is also server-owned. The browser enables Accept,
Reject, Defer, draft generation, final generation, verification, and download only
for an allowed-action record scoped to the exact brief or report ID. Sign-off sends
typed owner and rationale plus the server-published acknowledgement text, version,
and required provisional-warning acknowledgement IDs verbatim. Every authority
mutation includes `X-Autonomy-Human-Action: 1`; that marker does not replace the
backend's authenticated-principal check. Immutable receipts and history remain
visible after a brief is superseded. Draft PDFs are always labeled as watermarked,
final PDFs require a sign-off, and technical CSV/XLSX links are constructed only
from validated TEA job IDs on same-origin API routes.

The hosted Sites proxy credential is a service connection, never a human
principal. It therefore rejects sign-off, report-generation, and shadow-review
mutations before they reach Render. Those authority actions are available only in
the directly opened Render/FastAPI dashboard after shared Basic authentication.
Release-counted shadow reviews use the strict v2 checklist and must identify an
active-contract draft report, snapshot hash, PDF hash, and report identity; the
backend reopens and verifies the private PDF before storing the immutable review.
Report verification/download and other read-only views may still traverse the
proxy. This is a deliberate v1 limitation of shared Basic Auth, not a browser
header convention; a future Sites identity provider must be verified end to end
before proxy authority can be enabled.

The fixture selector remains an explicit, offline preview catalog for the stable
case identity `case_sbe_hybrid_001`. Fixture mode may change local presentation
state, but must not call `fetch`, an OpenAI client, a decision endpoint, a TEA
mutation endpoint, or an existing model execution control. It must not write
evidence, scenarios, jobs, sign-offs, reports, baselines, or agent messages.

The live and fixture Decision Brief roots share the same case header and view switch
but remain separate descendants of the shared tabpanel. Live mode renders only
server-sanitized bundle and brief records, including partial, classification-pending,
stale, superseded, verification-failure, agent-unavailable, and API-unavailable
states, along with server-authorized sign-off and report controls. In fixture mode,
grouped confirmation previews queue state and creates no job; fixture sign-off
transitions only to the clearly labeled local signed preview state and never shares
the live authority dialog or APIs.

The existing Solar Agent is removed from the visual and accessibility trees only
while Autonomy mode is active. Calibration, Annual Simulation, the existing TEA,
exports, workers, Saved Results, and Solar Agent state and behavior remain unchanged.

After changing the Autonomy foundation, verify the focused source and assembly
contracts before the production build:

```bash
python -m unittest -v tests.test_autonomy_frontend tests.test_dashboard_build tests.test_project_layout
npm run typecheck
npm run build
```

Also inspect the assembled dashboard at desktop (1280 CSS pixels or wider), tablet
(768–1279), and mobile (390 and below), including keyboard-only navigation, both
modal focus cycles, screen-reader names/status text, reduced motion, and forced
colors. Confirm the original three dashboard modes before and after entering
Autonomy; their controls, saved state, and results must not change.
