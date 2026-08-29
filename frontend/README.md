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

## Hybrid Autonomy Phase 1 fixture foundation

The approved Phase 0 and Phase 1 authority is recorded in
`docs/HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md`. The preserved unified and hybrid
plans remain product contracts under `docs/`; the hybrid plan controls the current
interaction and phase numbering when the plans differ.

The Autonomy frontend is assembled from:

- `html/55-autonomy-workspace.html` — the shared case shell, five-stage
  Investigation Workspace, Decision Brief, evidence/readiness rail, confirmation,
  and sign-off surfaces;
- `css/16-autonomy-workspace.css` — namespaced desktop, tablet, mobile,
  reduced-motion, and forced-colors behavior; and
- `js/07-autonomy-workspace.js` — deterministic local fixture states and view,
  tab, drawer, dialog, focus, and keyboard behavior.

All Phase 1 Autonomy content is local preview data for one stable case identity,
`case_sbe_hybrid_001`. The fixture state selector must expose the complete contract
catalog without network access. It may change local presentation state, but must
not call `fetch`, an OpenAI client, a decision endpoint, a TEA mutation endpoint,
or an existing model execution control. It must not calculate lifecycle values or
write evidence, scenarios, jobs, sign-offs, reports, baselines, or agent messages.

The Investigation and Decision Brief roots share the same case header, source lock,
basis lock, revision, and fixture results. A stage selection changes only the
visible section. Opening the brief and returning to Investigation are explicit,
deterministic transitions. The grouped confirmation button previews queue state and
creates no job; fixture sign-off transitions only to the local signed state.

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
