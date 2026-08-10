# Dashboard frontend sources

`sb_energy_dashboard_modern.html` at the repository root is **generated**. Edit the
partials here, then rebuild:

```bash
python tools/build_dashboard.py
```

Commit the sources *and* the regenerated file together. `tests/test_dashboard_build.py`
fails if they drift apart.

## Why the generated file is still committed

Two consumers read it directly and neither runs a build step first:

- `src/sbepv/api/main.py` serves it with `FileResponse`
- `app/route.ts` inlines it at Vite build time with `import ... from "...?raw"`

Four test modules also assert against its exact text (≈345 substring assertions,
some sensitive to indentation and to the order elements appear in).

## Layout

| Directory | Contents |
| --- | --- |
| `css/` | 14 partials, ~6,100 lines, concatenated into the single `<style>` block |
| `html/` | 9 markup partials, ~1,270 lines, plus `document.template.html` |
| `js/` | 20 partials, ~8,100 lines, concatenated into the single `<script>` block |

`document.template.html` is the surrounding document with three slots —
`{{CSS}}`, `{{MARKUP}}`, `{{JS}}` — that the build fills in.

## Order is load-bearing

Files are concatenated in **filename order**. Two specific constraints:

- **`13-agent-drawer-base.css` must precede `14-agent-drawer-redesign.css`.** The
  redesign is an override layer at equal specificity. Swapping them reverts the
  Solar Agent drawer's appearance with no error and no failing text assertion.
- **The JS partials are one classic script sharing globals**, not ES modules.
  Several contain immediate-execution wiring (event listeners, `setInterval`, the
  final `restoreDashboardState()` call) that depends on earlier partials having run.

Converting the JS to ES modules would introduce a real circular import:
`resetClientState` reads `chatInput`/`chatSidebar`, which are declared ~900 lines
later in the chat layer, while the chat layer calls back into `saveDashboardState`.
That works today only because nothing executes until the whole script has parsed.

## Markup partials are slices, not fragments

The markup partials are ordered pieces of one document, not independently
well-formed fragments: `.app-shell` and `#annualPanel` are wrappers that span
several partials. Only the concatenation is valid HTML. The build test is what
guarantees the result is correct.
