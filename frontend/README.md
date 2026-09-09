# Dashboard frontend sources

This directory is the dashboard's **only source of truth**. There is no committed
generated HTML file and no manual assembly step.

Two consumers assemble the same sources directly:

- `src/sbepv/dashboard.py` builds the Render/FastAPI fallback and refreshes its
  bounded cache whenever a template or partial changes.
- `frontend/dashboard.ts` uses Vite raw imports to build the Sites/Vinext version.

After editing a partial, run the Python tests and `npm run build`. The former checks
the source and Render contracts; the latter validates the Vite/Cloudflare contract.

The bounded real-browser smoke test uses Playwright with mocked same-origin APIs:

```bash
npm run test:browser:smoke
```

On Windows it uses the installed Chrome channel. On other fresh machines, install
the managed Chromium binary once with `npx playwright install chromium`; set
`PLAYWRIGHT_BROWSER_CHANNEL` to an installed Playwright channel when appropriate.
Screenshots from failures are written below `output/playwright/` and stay untracked.

## Layout

| Path | Contents |
| --- | --- |
| `dashboard.ts` | Vite assembler used by `app/route.ts` |
| `css/` | Ordered partials concatenated into the single `<style>` block |
| `html/` | Ordered markup partials plus `document.template.html` |
| `js/` | Ordered partials concatenated into the single classic `<script>` block |

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

## Annual-energy CDF chart

The annual results CDF chart uses the selected eligible, complete, source-verified
weather years. Energies are sorted in increasing order and assigned midpoint
probabilities `p_i = (i - 0.5) / n`, where ranks start at 1 and `n` is the selected
sample count. Equal energies share the average midpoint probability of their
ranks, with every associated year retained in the point label.

The chart labels each point with its energy and year, and connects adjacent distinct
energies using linear interpolation:

```text
F(x) = p_i + (x - E_i) * (p_(i+1) - p_i) / (E_(i+1) - E_i)
E_i <= x <= E_(i+1); x and E are in MWh; plotted percentile = 100 * F(x)
```

For distinct observations, each probability difference is `1 / n`. For tied
observations, the formula uses the probabilities after grouping equal energies.
Interpolation requires at least two eligible years and two distinct energy values.
It uses the underlying full-precision annual results and generates the equation
and interval coefficients again when the selected results or array change. Six
distinct values produce five segments; twelve produce eleven. The expandable
equation table displays energy bounds and equation values to two decimal places;
the underlying interpolation retains full precision. Numeric equations are marked
as approximate. If two distinct bounds round to the same hundredth, that interval
uses symbolic endpoints to avoid displaying division by zero.

The CDF chart uses a 0–100% y-axis. The interpolated curve is defined only within
the observed energy range; no tails are extrapolated. Agreement at the input points
is inherent to interpolation, so the chart does not report a fit R-squared value.
This presentation does not change the backend's exported empirical CDF (`i / n`),
the existing type-7 P50/P90 summary quantiles, or any TEA calculations.

## Opening charts

Click a loaded chart, or focus it and press Enter or Space, to open it in a new
browser tab. Image charts use their existing image URL, preserving the artifact
access checks. Annual SVG charts open a snapshot with their styles, year labels,
and, for the interpolated CDF, its current equation table. Empty or unavailable
charts do not open a tab. The original dashboard stays open.
The TEA v5 chart image and its **Chart** action are native links targeting a new
tab; the image link becomes available only after the verified plot loads.

## Supported TEA calculation

The dashboard uses the v5 paired commercial LCOE calculation. Its interpretation
text and percentile table appear below the full-width CDF chart. Autonomy, the
Decision Agent, and TEA v6 calculation, views, and exports have been removed.
Historical database rows and private artifacts are preserved, but retired jobs
cannot be viewed, exported, retried, or used as Solar Agent evidence.
