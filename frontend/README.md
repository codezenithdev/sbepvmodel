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
| `css/` | 14 partials concatenated into the single `<style>` block |
| `html/` | 9 markup partials plus `document.template.html` |
| `js/` | 20 partials concatenated into the single classic `<script>` block |

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
