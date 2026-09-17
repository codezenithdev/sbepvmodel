# SB Energy PV Operations Dashboard

This dashboard models the SolarEdge and Solectria arrays at the SBE Innovation
Center. It collects measured Bazefield data, supports reviewed seasonal
calibration, runs Annual Simulations with MIDC SolarTAC weather, and compares
commercial lifecycle costs through the supported TEA v5 calculation. Solar Agent
explains results and proposes model scenarios under the existing confirmation
policy.

This is the consolidated project manual. Development rules remain in
[AGENTS.md](AGENTS.md), and numerical authority remains in the unchanged
[TEA calculation contract](docs/TECHNOECONOMIC_CALCULATION_CONTRACT.md), including
its versioned addenda. This manual explains those contracts; it does not replace
them. License and attribution files remain separate wherever supplied.

## Contents

- [Supported workflows](#supported-workflows)
- [Local setup](#local-setup)
- [Configuration](#configuration)
- [Data Collection and saved work](#data-collection-and-saved-work)
- [Calibration and validation](#calibration-and-validation)
- [Annual Simulation](#annual-simulation)
- [Technoeconomic Analysis](#technoeconomic-analysis)
- [Frontend development](#frontend-development)
- [Architecture and data integrity](#architecture-and-data-integrity)
- [Testing](#testing)
- [Deployment](#deployment)
- [Cache design and improvement plan](#cache-design-and-improvement-plan)
- [Full code sweep](#full-code-sweep)
- [Troubleshooting](#troubleshooting)
- [Historical delivery and design records](#historical-delivery-and-design-records)
- [Documentation migration](#documentation-migration)

## Supported workflows

| Workflow | Input and result | Required boundary |
| --- | --- | --- |
| Data Collection | Download historian data, inspect summaries/charts, export CSV/XLSX. | Collection alone does not calibrate, promote a baseline, or run a model. |
| Calibration / validation | Compare physics predictions with measured data; optionally fit seasonal corrections. | Calibrated runs require the visible source-data review and confirmation. |
| Annual Simulation | Model selected SolarTAC years, optionally inheriting a promoted reviewed calibration. | Preserve source coverage, seasonal lineage, operating limits, and eligible-year labels. |
| Technoeconomic Analysis | Seeded paired commercial Solectria and SolarEdge lifecycle LCOE from a frozen completed Annual source. | Source/evidence verification, assumption acceptance, and calculation confirmation precede execution. |
| Solar Agent | Explain model evidence and propose supported scenarios or sweeps. | Existing validation, immutable requests, confirmation rules, and promotion guards remain authoritative. |

The dashboard opens in **Data Collection** on fresh loads and reloads. Remembered
model drafts and jobs remain available separately. **PV model** returns to the
remembered model workspace; **Operations** stays with collection. Opening the page
does not submit jobs. A later restoration response must not override a tab or
editor the user has already selected.

Autonomy, the Decision Agent, and TEA v6 were retired on September 9, 2026. Their
historical database references and private artifacts remain protected. Retired
jobs cannot be viewed, exported, retried, or supplied as Solar Agent evidence.
The explicit Cliff Ho approval boundary in AGENTS.md applies to any proposed
reintroduction; historical plans or environment examples do not enable them.

## Local setup

Use **Python 3.12 or newer**, preferably **3.13.14** to match the Render
configuration, and **Node.js 22.13.0 or newer**. Check the interpreter actually
used by your shell. Python 3.11 is unsupported. Runtime dependency pins live in
[requirements.txt](requirements.txt); [pyproject.toml](pyproject.toml) reads that
file rather than maintaining another list.

From the repository root, reuse an existing supported environment or create one:

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
```

Activate the environment before subsequent Python commands. On Windows,
`.\.venv\Scripts\python.exe` selects it explicitly. Copy
[env.example](env.example) to `.env` and configure the credentials needed for your
workflows. Never commit `.env` or real secrets.

Run the Python backend and its dashboard:

```bash
python -m uvicorn sbepv.api.main:app --app-dir src --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Missing Bazefield/OpenAI keys
prevent historian retrieval/Solar Agent requests respectively; the dashboard can
still load. The example environment contains Basic Auth placeholders: replace
them for protected local use, or leave both Basic Auth variables unset for
unprotected local development.

`--app-dir src` puts the package on the import path. An editable install with
`python -m pip install -e .` also makes `sbepv` importable. For frontend development,
install locked Node dependencies only when needed:

```bash
npm ci
npm run dev
```

The separate frontend uses the server-side Render proxy described under
[deployment](#deployment). Point it at the intended test backend and configure
its service credentials before exercising mutation controls. A local frontend
does not imply that its API requests are local.

## Configuration

[src/sbepv/api/config.py](src/sbepv/api/config.py),
[env.example](env.example), and [render.yaml](render.yaml) define configuration.
Keep credentials in the local environment or hosting secret store, never in
browser code, screenshots, logs, or committed files.

| Setting | Purpose |
| --- | --- |
| `BAZEFIELD_API_KEY`, `BAZEFIELD_BASE_URL` | Historian credential and optional origin; origin defaults to the SB Energy Bazefield API. |
| `OPENAI_API_KEY` | Required for Solar Agent. |
| `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT` | Optional settings; consult current defaults in `config.py`. |
| `OPENAI_REQUEST_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | Provider request bounds; defaults are 45 seconds and zero provider retries. |
| `DASHBOARD_BASIC_USER`, `DASHBOARD_BASIC_PASSWORD` | Backend shared authentication; configure both for shared deployment. |
| `PV_DASHBOARD_OUTPUT_DIR` | Outputs/private state; defaults to repo `outputs/`. Relative values resolve from the repo. Use durable storage on Render. |
| `PV_DASHBOARD_ALLOWED_ORIGINS` | CORS allowlist for direct FastAPI clients; the same-origin Sites proxy is a separate path. |
| `PV_DASHBOARD_ENABLE_LEGACY_RUN` | Leave unset in production. Enables legacy unreviewed calibration; unnecessary for explicitly uncalibrated runs. |
| `PV_DASHBOARD_MAX_ACTIVE_JOBS` | Combined model and TEA admission limit; default 25, range 1–500. |
| `PV_DASHBOARD_JOB_HEARTBEAT_SECONDS` | Worker heartbeat; default 10 seconds. |
| `PV_DASHBOARD_JOB_STALE_SECONDS` | Stale-lease threshold; default 120 seconds, at least three heartbeats. |
| `PV_DASHBOARD_MAX_ACTIVE_DATA_COLLECTIONS` | Concurrent collections; default 2, range 1–8. |
| `PV_DASHBOARD_MAX_DATA_COLLECTION_RECORDS` | Collection records; default 250, range 10–1,000. |
| `PV_DASHBOARD_DATA_COLLECTION_RETENTION_DAYS` | Collection retention; default 7 days, range 1–90. |
| `PV_DASHBOARD_DATA_COLLECTION_STORAGE_MB` | Collection budget; default 1,024 MiB, range 64–4,096 MiB. |

Configuration imports create directories, and state imports open/migrate SQLite.
For ad hoc checks, set an isolated output directory **before** importing API
modules. Changing environment variables after import does not redirect stores.
The unittest bootstrap provides its own temporary output root when one is not
explicitly configured; an explicit value must itself be a safe test location.

## Data Collection and saved work

Collection uses the selected historian window and aggregation interval, bounded
to 366 days and 200,000 rows plus configured concurrency/retention/storage limits.
Records use atomic writes and source hashes. Active downloads are protected from
cleanup. Private files are accessed through collection routes, not unrestricted
output URLs. Collection currently assumes one API process; review durable
ownership and cross-process coordination before scaling processes or instances.

The collection form uses two date/time columns where space permits and one on
phones. Mobile inputs/collapse controls have at least 44px height, long summary
values wrap, and collection closes the shared chat drawer so an invisible modal
cannot leave the page inert.

| Saved work | Lifetime and recovery |
| --- | --- |
| Browser state | Drafts, preferences, chat history, job references, and cached result state. Server-owned evidence must be revalidated; browser storage may be denied or full. |
| Recent activity | Active jobs and the ten newest terminal activities from SQLite; open **Ask Solar Agent → Runs → History**. |
| Saved results | Up to ten explicitly pinned completed Calibration/Annual results. **Saved results** supports view, rename, export, and removal without rerunning. Separate from recent history. |

Preserve the entire output root and SQLite state together. Public workbooks or
plots alone cannot restore reviewed inputs, baseline lineage, saved-result
identities, or completed TEA evidence.

## Calibration and validation

The **Calibrate the model** choice selects either direct physics validation or
reviewed calibration for the exact requested Bazefield period.

1. Select dates, interval, efficiencies, IAM, backtracking, optional curtailment,
   and calibration mode.
2. With calibration disabled, `POST /api/run` explicitly sends
   `calibrate_model=false`, retrieves data, and returns physics predictions.
3. With calibration enabled, `POST /api/calibration-reviews` retrieves/profiles
   a private snapshot without starting the model.
4. Inspect every issue and allowed **Retain**/**Exclude** choice. Recommended
   choices may be preselected, but still require human review.
5. **Apply decisions & calibrate** opens the decision gate. Only **Confirm
   decisions & calibrate** acknowledges review and queues through
   `POST /api/calibration-reviews/{review_id}/run`.
6. The receipt preserves decisions, row counts, and the bound job. Results carry
   factors, coverage, confidence, excluded-row audit, original model error,
   diagnostics, and source hashes.

Direct calibrated requests are rejected by default, including omitted
`calibrate_model` because its API default is true. Reviewed endpoints accept
calibration-enabled requests only. Uncalibrated results cannot become reviewed
calibration baselines.

### Quality review and time handling

Checks cover required columns, invalid/duplicate/out-of-window timestamps, gaps,
irregular cadence, missing/non-numeric values, broad physical bounds, near-zero
power under strong irradiance, power without irradiance, and roughly four-hour
sensor flatlines. Each issue has a stable ID, severity, columns/count, allowed
actions, and recommendation. Invalid timestamps require exclusion; gaps are
informational because missing rows cannot be removed. A choice applies to
**every affected row**, not only the displayed sample.

**Show affected rows** uses hash-verified
`GET /api/calibration-reviews/{review_id}/rows`. The dashboard starts with 50 rows;
ordinary API pages are bounded to 200. **Load more**, **Last 50**, and explicit
**Load all rows** avoid inflating initial summaries/browser storage. Public
summaries exclude raw source rows. Source values remain canonical UTC; review
dates/examples/expiry use DST-aware `America/Denver`. Ambiguous/nonexistent local
boundary times are rejected. Requested windows are end-exclusive.

Review receipts and unbound raw snapshots expire after 24 hours. Reviewed CSVs
bound to durable model jobs remain scientific evidence for reproducible scenarios
and must not be removed as expired cache. Review/source artifacts remain private.

### Seasonal factors and physical limits

Local `America/Denver` seasons are Winter December–February, Spring March–May,
Summer June–August, and Fall September–November. The selected range is not expanded.
Every retained row contributes, including night, low-output, and weather-fallback
rows. Without a ceiling, the factor is measured AC energy divided by uncalibrated
modeled AC energy. With a ceiling, solve the monotonic clipped-energy equation:

```text
final predicted AC power = min(uncalibrated AC power × factor, active system cap)
sum(final predicted AC power × interval) = sum(measured AC power × interval)
```

Solectria combines ten 24-module string I–V curves in parallel at its installed
XGI 1500-250 inverter's single MPPT, constrains operation to 860–1,250 V,
defaults conversion to 98.5% CEC efficiency, and enforces a 250 kW nameplate.
Optional curtailment adds another ceiling. SolarEdge's calibration ceiling is
the optional user limit; Solectria's is the lower applicable ceiling. An
unreachable measured target or zero positive modeled energy stops calibration.
Final seasonal energy totals reconcile within 0.01 kWh.

Factors outside the typical 0.5–1.5 range are retained and flagged, not capped.
Integration is bounded to the requested interval so a gap/exclusion cannot make
a later sample represent missing hours. Full-precision factors, source hashes,
and review lineage remain in promoted baselines and exports.

Same-input scenarios reuse the immutable profile without refitting, preserving
the effect of changed efficiency/IAM/settings. Required seasons and source hashes
must match. Solar Agent can propose reviewed same-input scenarios; a new date,
time, interval, or measured source requires the visible Calibration form.
Confirmation/promotion independently enforce reviewed-source lineage.

With at least 30 comparable samples, diagnostic regression relates the
measured/model ratio to available temperature, wind, GHI, DNI, DHI, and elapsed
time. Associations do not alter predictions or establish causation. They cannot
isolate soiling from correlated weather/time without additional evidence.

## Annual Simulation

Select one or more SolarTAC years from 2011 through the current year. Supported
intervals are whole-minute divisors of a day from 1 through 60 minutes, including
1, 5, 15, 30, 45, and 60, or exactly one hour. Coarser hour/day samples are rejected
before queueing because they cannot preserve solar geometry. Selections above
**1,048,575 time-series rows** are rejected before download to preserve Excel
exportability; one full year at one-minute resolution has about 525,600 rows.

SolarTAC source keys use fixed MST (`Etc/GMT+7`), with minute keys for sub-hour
data; calibration-season assignment remains DST-aware. The 2011 source starts
February 11. Current-year data ends at the latest complete fixed-MST day. Both
stay labeled partial and are excluded from the full-year empirical distribution.
Coverage/source verification determine eligibility; requested years are not
automatically complete.

A promoted reviewed calibration supplies frozen factors and editable starting
backtracking, efficiency, IAM, and curtailment settings. Changes are shown and
recorded relative to the baseline. Annual dates are independent of the historian
window. MIDC data never refits calibration. The model computes physics predictions,
applies the frozen local-season factor, then operating limits and integration.
Physics-only columns remain in outputs. Runs without a calibration baseline remain
physics-only.

The only cross-season exception is **Fall from Spring for Annual Simulation**.
The optional **Use spring calibration factors for fall** checkbox defaults to off.
Select it for a provisional comparison while Fall data is limited: each system's
exact Spring factor replaces its Fall factor for September–November in this run,
even when reviewed Fall factors exist. With it off, available Fall factors apply.
If Fall is absent and Spring exists, the existing fallback confirmation is still
offered. Both paths require review of the exact SolarEdge/Solectria Spring factors
before queueing/downloading. Consent is bound to the request, baseline, mapping,
and checkbox choice; the server rechecks them and records the substitution in
results, workbook, and provenance. Other missing seasons block the run; changed
inputs/baselines require new review. The promoted profile is never modified.
This is a comparison assumption, not validation of Spring factors for Fall; use
the reviewed Fall factors to compare again as Fall data becomes more complete.

### Annual-energy chart interpretation

The browser's interpolated CDF uses selected, complete, source-verified years.
Sort energies increasingly and assign midpoint ranks `p_i = (i - 0.5) / n`.
Ties share their average rank probability and retain all year labels. Between
distinct adjacent energies:

```text
F(x) = p_i + (x - E_i) × (p_(i+1) - p_i) / (E_(i+1) - E_i)
E_i ≤ x ≤ E_(i+1); x and E are in MWh; plotted percentile = 100 × F(x)
```

At least two eligible years and distinct energies are required. Underlying values
retain full precision; the equation table rounds to two decimals and labels numeric
equations approximate. Endpoints rounding to the same hundredth use symbolic
bounds to avoid a displayed zero denominator. The axis spans 0–100%, with no
extrapolated tails. Sample-point agreement follows from interpolation; no fit
R-squared is reported. This presentation does not change exported ECDF (`i / n`),
type-7 P50/P90 summaries, or TEA. Cumulative percentiles and energy exceedance
probabilities remain explicitly distinguished.

## Technoeconomic Analysis

Supported v5 compares paired **commercial Solectria and SolarEdge lifecycle LCOE**
in declared real-dollar units per MWh of AC energy. Each headline has a full
right-continuous empirical CDF and type-7 P10/P50/P90. SolarEdge-minus-Solectria
LCOE is a separate per-realization diagnostic: subtracting two marginal medians
does not give its median. Results are modeled scenarios, not validated forecasts
or vendor quotes.

The [approved calculation contract](docs/TECHNOECONOMIC_CALCULATION_CONTRACT.md)
governs formulas, tolerances, sampling, eligibility, evidence, and exports.
Version 5 and its shared-CAPEX/report addenda govern the current paired workflow.
Historical v1–v4 identities/results are not rewritten; v4's standalone SolarEdge
result is not relabeled as paired v5.

### Frozen source and paired calculation

TEA freezes a verified completed Annual source's eligible weather population,
capacities, request, calibration lineage, hashes, and evidence. Each realization
shares weather year, target capacity/basis, finance, degradation, life, and dollar
year across technologies; each system still uses its own energy and normalization.
An enabled positive frozen clipping/curtailment limit supplies the AC operating
basis. Otherwise exact verified installed module nameplates supply a DC basis.
Neither the reviewed 125 kWac example nor rounded “140 kW” is a universal constant.
Target/source basis mismatch blocks submission.

```text
specific energy = source AC energy / system source capacity
target first-year energy = specific energy × same-rated target capacity
lifecycle LCOE = present-value lifecycle cost / present-value lifecycle energy
paired delta = LCOE_SolarEdge - LCOE_Solectria
```

The equivalent-annual cost/energy ratio must agree with lifecycle LCOE. The kernel
owns the calculation; agents/charts/reports cannot derive competing authoritative
results from rounded summaries. Each technology has one initial CAPEX line at
`t=0`, one annual O&M line at year-end, and optional sourced replacements at
explicit year-ends. Units are constant USD/target-W or USD/target-W-year.
Coverage cannot overlap within a system/year, input IDs are unique across systems,
and all dollar years match finance. Fixed, Uniform, Triangular, and bounded Normal
distributions follow the contract.

Generic NREL 2024 ATB benchmarks remain labeled generic rather than system-specific
quotes: 1.56 USD/Wac CAPEX and 0.022 USD/Wac-year O&M, or 1.17 USD/Wdc and
0.01658 USD/Wdc-year, in 2022 dollars and a 30-year life. Source:
[NREL ATB on OpenEI](https://data.openei.org/submissions/6006), DOI 10.25984/2377191.
Do not invent optimizer replacements, vendor prices, failure schedules, or
maintenance charges. Provisional inputs retain evidence, rationale, and acceptance.

### Assumptions editor and defaults

**Edit assumptions** has **Project**, **System costs**, **Finance**, and **Review**
tabs. Project selects the verified Annual source and its refresh/open actions.
System costs separates common base CAPEX, SolarEdge additions, and per-system O&M.
Finance contains discount, degradation, realizations, and seed. Review summarizes
inputs and requires justification/acceptance before calculation confirmation.

**Next**/**Back** step through tabs; direct navigation remains available. Arrow keys,
Home, and End navigate tabs. Validation reveals the invalid section. Navigation
preserves inputs/acceptance; edits clear acceptance. The neutral white/gray dialog
uses a scrolling body and visible actions on narrow screens. Frozen-request review
shows actual source, sampling, finance, costs, and evidence, not invented post-run
totals. Close/cancel controls respect in-flight submission.

New scenarios use September 15 approved defaults: **100 MWac / 134 MWdc**, **30
years**, **10,000 realizations**, **seed 20260916**. Common CAPEX is shared;
SolarEdge adds optimizer hardware and an independent installation draw. Original
DC costs convert using the entered DC/AC cost-capacity ratio. Midpoint previews are
deterministic input summaries, not completed simulation medians. LHS samples
continuous assumptions; balanced seeded paired weather-year allocation is separate.

The default constant-dollar year is **2024** and editable. Changing it declares
price basis without inflation-adjusting entered prices. Drafts persist year/costs
across reopening/reload. Existing custom drafts retain values; older drafts without
a year keep their original 2022 basis. **Restore defaults** keeps the selected
source. Compatible AC source changes preserve modified assumptions; shared CAPEX
requires both systems' verified AC limits. Reports omit original component
allocations when common CAPEX or dollar basis changes.

### Results and reports

Schema-5 `paired_commercial` results retain each source/target bridge, cost-line
summaries, signed deltas, convergence, and numerical provenance. Full CDF populations
and realizations stay in sealed evidence/exports; display projections are not the
calculation population. Per-weather-year counts partition realizations. Export
checks tie out capacities, energies, timing/costs, lifecycle/equivalent-annual
LCOE, percentiles, CDFs, and deltas independently.

The UI shows the full-width paired CDF, interpretation, and accessible percentile
table. Failed charts leave tables usable. Technical IDs/versions/hashes remain
in records/exports. Curves share an axis, with line styles as well as color;
equal quantile positions are not paired realizations.

Completed TEAs offer **Download PDF report**, **Download Word report**, and
the workbook. **Include technical appendix** is checked by default and applies
to both document downloads. Clearing it omits the appendix without editing the
scenario or revoking reviewed assumptions. Both export endpoints accept
`include_technical_appendix=true|false`; requests without the option include it.
The CSV-bundle UI button is removed; sealed CSVs and historical
API access remain for integrity/compatibility. Read-only, on-demand PDF/DOCX
generation verifies frozen inputs, calibration/Annual lineage, saved arrays, and
exports. Missing/tampered evidence blocks download without changing job status.
Editing drafts never rewrites completed results.

Report format v2.4.1 places contents after the title metadata, excluding the title
from the contents. Its Executive Summary covers Objectives, Approach, and Results,
followed by Introduction and Objectives, Data Collection, Modeling and Calibration,
Annual Simulation, and Technoeconomic Analysis. Measured-period energy is kept
distinct from full-year predictions, and seasonal calibration coverage qualifies
their comparison. The summary subtracts the two full-precision system medians;
this is distinct from the median of paired LCOE differences. Cost tables and the
individual-system lifecycle LCOE CDFs remain, while the paired-difference CDF is
omitted. Signed standardized rank-regression tornado charts for both systems are
in the main TEA section, with sample counts and model R-squared. O&M predictors
and exclusion notes identify the owning system explicitly. Lifecycle CDFs are
redrawn from the verified sealed realizations as native vector graphics in PDF
and PNGs from the same data in Word; the saved chart artifact still passes its integrity
checks. Calibration factors display four decimal places, while comparisons use
saved precision. Confirmed identical fitted and applied profiles are summarized
without a duplicate factor table.

The optional technical appendix uses concise equation tables with short meanings,
units, saved assumptions, and statistical methods. Detailed physics descriptions
require a recognized frozen model identity; unavailable historical details remain
unavailable. References and provenance remain available. P10/P50/P90 stability
plots use cumulative prefixes of the verified saved realizations in their original
order; their final points tie out to the headline percentiles. This presentation
does not change the existing convergence criteria or status. Evidence, availability,
and all integrity checks are the same with the appendix included or omitted.

An optional seasonal energy diagnostic can inspect currently available calibration
and Annual workbooks. It must reconcile their contents to frozen Annual totals,
saved factors and caps, and SHA-verified reviewed measurements. The report labels
this separately as current workbook evidence with newly calculated SHA-256 values;
it does not represent those bytes as historically sealed evidence. Missing or
unreconciled workbooks leave the diagnostic unavailable without replacing saved
results or launching a new simulation.

The title retains the analysis timestamp and labels the generating dashboard
version separately from report format v2.4.1; there is no separate visible report
date. `PV_DASHBOARD_RELEASE` supplies a release label when configured; otherwise
`package.json` supplies an explicitly labeled package-declared version.
`PV_DASHBOARD_BUILD_ID`, then `RENDER_GIT_COMMIT`, supplies the build identifier;
if neither is available it is shown as not recorded. The generating software
identity does not establish the dashboard version used for a historical analysis:
missing historical version metadata remains not recorded. New filenames follow
`LCOE_Comparison_v2.4.1_{full|summary}_{run_id}.{pdf|docx}`, with a sanitized run ID.
Previously downloaded reports and their filenames are preserved.
Generation metadata may change file hashes without changing numerical evidence.

PDF links/bookmarks use final page numbers. Word uses native Title/Heading styles
and TOC/page fields; refresh fields after opening/editing for its pagination.
Both share one presentation model, chart data, and values. Dependencies
are ReportLab 4.4.9 and python-docx 1.2.0; the server does not need Microsoft Word.

## Frontend development

`frontend/` is the sole source. There is no committed generated HTML or manual
assembly step. `src/sbepv/dashboard.py` builds the Render fallback with a bounded,
source-aware cache; `frontend/dashboard.ts` uses Vite raw imports for Sites.

| Source | Assembly contract |
| --- | --- |
| `html/document.template.html` | Exactly one `{{CSS}}`, `{{MARKUP}}`, and `{{JS}}` slot. |
| `css/` | Filename-ordered partials joined into one style block. |
| `html/` | Filename-ordered slices of one document, not independently valid fragments. |
| `js/` | Filename-ordered partials forming one classic script with shared globals. |

Assemblers require nonempty groups, normalize line endings, and remove one trailing
newline per partial. Keep slot/newline behavior equivalent. File order matters:
`13-agent-drawer-base.css` precedes equal-specificity overrides in
`14-agent-drawer-redesign.css`. JavaScript immediate wiring/restoration depends on
earlier declarations. An ES-module conversion requires resolving shared state/cycles,
not simply adding a script attribute. Markup shells span partials; inspect the
assembled document.

Click a loaded chart, or focus and press Enter/Space, to open its authorized URL
in another tab. Annual SVG charts open a styled snapshot with labels/current
equations. Empty charts do not open. TEA's verified image and **Chart** action use
native links. Source hashes and artifact access checks remain in effect.

Preserve stable result IDs and state-driven labels. Original physics values appear
only when provided; unavailable numbers stay unavailable. Measured-system comparison
follows both system rows. Annual confirmation shows actual factors/settings and
returns focus on dismissal. Native dialogs need explicit centering because of the
global reset. Preserve scroll ownership, sticky headers/actions, keyboard focus,
reduced-motion/forced-colors behavior, table alternatives, and 44px phone targets.

## Architecture and data integrity

```text
Browser → Render dashboard OR Sites dashboard/proxy
                            ↓
                  FastAPI validation/authentication
                            ↓
         SQLite jobs, immutable requests, reviews, baselines, saved results
                            ↓
                    Leased background worker
                            ↓
         Physics / calibration / Annual / isolated TEA calculation
                            ↓
               Verified artifacts and provenance
```

| Area | Main paths |
| --- | --- |
| Physics/calibration | `src/sbepv/model.py`, `calibration.py`, `ingest/` |
| API/configuration | `src/sbepv/api/main.py`, `config.py`, `schemas.py`, `serializers.py` |
| Persistence/baselines | `src/sbepv/store.py`, `api/job_store.py`, `review_store.py`, `baselines.py` |
| Worker lifecycle | `src/sbepv/worker/loop.py`, `completion.py`, `run_validation.py`, `run_annual.py` |
| TEA | `src/sbepv/technoeconomic.py`, `api/technoeconomic.py`, `worker/run_technoeconomic.py`, `technoeconomic_reporting.py`, `technoeconomic_report.py`, `technoeconomic_presets.py` |
| Solar Agent | `src/sbepv/agent/`, `src/sbepv/api/proposals.py` |
| UI/hosting | `frontend/`, `app/`, `lib/`, TypeScript `worker/`, `build/`, `public/` |
| Standalone batch | `src/run_pipeline.py` |

Background jobs are leased through SQLite. Heartbeats reveal dead workers;
lease fencing prevents an old attempt overwriting a newer one. TEA has separate
tables, worker entry, routes, immutable sources, and exports; generic model
mutation/promotion must not absorb TEA jobs.

The Python package is `sbepv`; `app/` belongs to the frontend router. Paths use
repo landmarks (`pyproject.toml` and `src/sbepv/`), not fixed parent depth. Access
settings/singletons through modules (`config.OUTPUT_DIR`, `state.AGENT_STORE`) so
test patches work. Avoid shadowing imported modules and keep patchable calls
qualified. Config imports load `.env`/create directories; state imports migrate
SQLite. Some imports intentionally remain function-local. `model`/`reporting`
select matplotlib `Agg` before worker plotting. `_JobCancelled` has one shared
type, and SQLite DDL enforces immutable proposals and job requests.

The memory job mirror preserves `input_plots` and `traceback` on refresh because
they may exist only in memory. Source hashes, reviewed CSVs, baseline lineage,
request immutability, leases, and artifact privacy are integrity controls, not
optional caches.

TEA gates on numerical behavior, not only version strings. Approved probes cover
PCG64DXSM/SeedSequence, bounded-normal inverse CDF, type-7 quantiles, and
`log1p`/`expm1` at twelve significant decimal digits. Probe changes alter the
contract. Bit-exact provenance is reported separately; compatible runtimes can
differ by a few ULPs. LAPACK rank/least-squares have separate platform sensitivity.
Never change seeds, fingerprints, tolerances, or scientific expectations to obtain
a passing test.

## Testing

Run from the repo root with supported Python and Node; check their versions first.
The unittest bootstrap uses temporary API outputs by default. If explicitly setting
`PV_DASHBOARD_OUTPUT_DIR`, use a disposable test path **before** imports/discovery.
Ad hoc API scripts also need explicit isolation. Never use real databases,
promoted baselines, reviewed source files, or model outputs as disposable fixtures.

Create ignored repo-root `analysis/` if absent; one historian comparison test uses
it. PowerShell example:

```powershell
New-Item -ItemType Directory -Force -Path analysis | Out-Null
python -m unittest discover -v
```

Common focused/frontend checks:

```bash
python -m unittest -v tests.test_project_layout tests.test_dashboard_build
npm run typecheck
npm run lint
npm run build
npm run test:browser:smoke
node --experimental-strip-types --test --test-isolation=none tests/*.test.mjs
git diff --check
```

`npm test` runs Python discovery. `npm run test:browser` first checks Agent frontend
contracts and then Playwright. Bounded browser checks use mocked APIs and synthetic
numerical fixtures. Windows uses installed Chrome. Elsewhere install managed
Chromium once with `npx playwright install chromium`, or set
`PLAYWRIGHT_BROWSER_CHANNEL` to an appropriate installed channel. Failure
screenshots go to ignored `output/playwright/`.

| Scope | Required evidence |
| --- | --- |
| Documentation | Reference/command consistency and `git diff --check`; no application build solely for prose. |
| UI/assembly | Assembly and affected frontend/workflow tests, typechecking where relevant, build, and browser interaction for changed behavior. |
| Calibration/ingestion | Review gates, intervals/timezones, quality decisions, hashes, and energy reconciliation. |
| Annual/physics | Numerical expectations, inherited calibration, coverage, operating limits, units, and exports. |
| TEA | Contract reference cases, seed determinism, source/evidence checks, isolation, exports/reports, and changed UI. |
| Store/worker/cache | Project layout, persistence, retry/cancellation, lost leases, baseline selection, source integrity, workflow boundaries. |
| Cross-workflow Python/runtime | Full Python suite, plus frontend checks/build for frontend impact. |

An external MIDC reconciliation fixture may be absent and cause its reference
test to skip. Report actual current reasons/counts. Restricted Windows process or
temporary-directory access may block checks; rerun only with appropriate access
and isolated paths. Builds do not prove browser behavior; mocked browser tests do
not prove production integration; green tests cannot prove all possible bugs absent.
Record actual commands, failures/repairs, reruns, and untested boundaries per delivery.
Historical counts below are not the current sweep's results.

## Deployment

**Render runs the Python backend. The user publishes the frontend through Sites.**
Backend changes require a Render release; UI/proxy changes require an integrated
Sites build. Local edits, testing, or documentation consolidation do not publish.

### Render backend

Inspect [render.yaml](render.yaml) against the existing service before changing
deployment. It declares `sbepvmodel`, Python in Oregon, `/healthz`, and a persistent
disk at `/var/data`:

```text
Build: pip install -r requirements.txt
Start: uvicorn sbepv.api.main:app --app-dir src --host 0.0.0.0 --port $PORT
PYTHON_VERSION: 3.13.14
PV_DASHBOARD_OUTPUT_DIR: /var/data/outputs
```

Configure provider secrets and both Basic Auth values in Render. Leave legacy
unreviewed calibration disabled. Optional model overrides can remain at code
defaults unless a verified access/configuration issue requires them.

Blueprint comments record **unresolved historical drift**: `plan: starter` differs
from a previously observed `1c-2g` instance, and the observed service once used a
fixed port. Those comments are not fresh live inspection. Confirm the actual plan
and planned service list before sync: a wrong name can create an empty second
service, and a wrong plan can resize/restart the existing service. If using the
Render CLI, validate with `render blueprints validate ./render.yaml` first.

Include `src/`, `frontend/`, `public/`, `pyproject.toml`, and `requirements.txt`.
Version-controlled upload avoids omissions from hand-picked files. The backend
needs `frontend/` for assembly and `public/annual-warning.png` for its warning route.
Exclude secrets, real outputs, generated data/workbooks/images, caches, and logs.

Back up SQLite and the complete output root consistently, including private
review/Annual/TEA evidence. Restore into isolation and verify lineage before using
recovered results. Verify durable job/collection ownership and cleanup coordination
before increasing API processes or instances.

### Sites frontend and proxy

`app/route.ts` serves HTML. API/output catch-all routes delegate to
`lib/render-proxy.ts`. Configure server-side:

| Setting | Purpose |
| --- | --- |
| `RENDER_BACKEND_ORIGIN` | Intended backend; code default is `https://sbepvmodel.onrender.com`. |
| `RENDER_BASIC_USER`, `RENDER_BASIC_PASSWORD` | Backend service credentials. |

The proxy enforces an API allowlist. Missing credentials produce 503; backend
credential rejection becomes a sanitized 502. Never embed service credentials in
browser HTML/JS. Verify intended Sites entry-point access: a server-side proxy
using backend Basic Auth does not itself create separate browser-user login.
Preserve the host's intended access controls when publishing.

Deploy backend changes before a dependent frontend, then publish the integrated
Sites build through the user's workflow. `.openai/hosting.json` or a successful
build does not authorize or prove deployment.

### Release verification

1. Verify deployed revisions and `/healthz` returning `{"status":"ok"}`.
2. Check intended access behavior through Render and Sites.
3. Verify Collection landing, draft restoration, phone/desktop usability, and
   late responses preserving active edits.
4. Inspect API `private, no-store` headers and artifact conditional/range behavior,
   including expected errors, through both front doors.
5. For an authorized live calibration, use a short known-good period and explicit
   review; check decisions, factors, provenance, plots, and exports.
6. Verify an existing completed Annual/TEA source and downloads without silently
   rerunning; new work needs its normal review/confirmation.
7. Confirm Solar Agent answers from intended context without exposing credentials.

Builds/mocked fixtures do not replace live verification. Share dashboard access
through the intended channel, never provider API keys.

## Cache design and improvement plan

The audit covered restoration, browser persistence, polling, HTTP/proxy behavior,
plot reuse, assembly, job mirrors, reviews, and collection retention. Live Render
memory/disk/network pressure and cache-hit rates were not measured. Source
inspection alone cannot establish production speedups.

### Existing layers and integrated startup work

| Layer | Current role and controls |
| --- | --- |
| Browser state | Drafts/preferences/job IDs plus cached results/chat; server-owned evidence is revalidated. Chat has limits, protected conversations, quota compaction, and failure states. |
| Client snapshots | Job progress and activity cards. |
| HTTP APIs | Mutable `/api/` responses are `private, no-store` in FastAPI/proxy; upstream proxy API fetches bypass caches. |
| Plots/outputs | Origin access policy, ETag/Last-Modified, conditional/range requests, and `Vary` are retained. Reuse unchanged loaded/loading plots; failed loads retry and explicit result application refreshes. |
| HTML assembly | Python source-aware `lru_cache(maxsize=2)` invalidates when sources change; HTTP document remains no-store. |
| Job mirror | SQLite-backed records plus runtime-only `state.JOBS` fields. |
| Reviews | 24-hour retention, with job-owned source evidence treated separately. |
| Collections | Atomic records, hashes, quotas, retention, deduplication, active-download pins. |

The first batch integrated Collection landing/responsiveness, hidden-mobile-chat
recovery, baseline startup timeout use, plot reuse, and HTTP policy consistency.
It preserved the completed local TEA design/science. The subsequent full sweep
also fixed response-body deadlines, poll coordination, stale response ordering,
and durable job authority, as recorded below.

### Prioritized follow-up

Completed correctness repairs and remaining improvements are separated here.
Open items require measurement or additional implementation; they are not claims
of completed optimization.

| Priority/status | Finding | Resolution or completion criteria |
| --- | --- | --- |
| P1 fixed | Direct workflows and Agent could independently poll one job. | Direct polling owns active Calibration/Annual runs; Agent polling resumes after monitoring stops. Regressions cover recovery and concurrent reads. |
| P1 fixed | Late status/refresh/chat responses could overwrite newer state or revive deleted/reset work. | Identity/generation checks guard polls, manual card reads, nested recovery, reset, and successful actions. Explanations retain their original conversation; old chat replies/cleanup cannot affect newer sends. |
| P1 fixed | Shared deadlines ended at headers and replaced caller signals; TEA requests were unbounded. | Deadlines cover headers/body and preserve caller cancellation. TEA distinguishes supersession from timeout; timed-out mutations are not automatically retried. |
| P1 fixed | Job lookup could use a stale mirror after durable absence/errors. | Durable mirrors are marked; missing records discard them and storage errors propagate. Only genuine legacy rows use compatibility fallback; lost leased jobs cannot be recreated in memory. |
| P2 open | Completed job mirrors remain unbounded. | Bound terminal mirrors while preserving active jobs, input plots, diagnostics, leases, and baseline ordering; measure bytes as well as entries. |
| P2 open | Frequent saves serialize full results/forms/chat repeatedly. | Measure bytes/writes, add versioned migration/coalescing, protect drafts, signal failures, fetch completed results by ID when omitting cached payloads. |
| P2 open | Temporary reviews lack aggregate admission/storage budgets. | Separate pending/orphan/expired/job-owned files; bound disposable storage; retain evidence when ownership cannot be verified. |
| Conditional/open | Collection coordination is process-local; startup recovery fails active records. | Verify topology; introduce durable ownership before multiple API processes. |
| P2 open | All CSS/markup/JS is inline in a no-store document. | Measure transfer/parsing before considering versioned assets; preserve ordered globals and both assemblers. |

Landing, responsive layout, HTTP policy, and plot reuse complete the original
twelve-item audit list. Remaining source entry points include
`frontend/js/08-dashboard-state.js`, `09-validation-run.js`, `10-annual-run.js`,
`15-chat-action-cards.js`, `17-agent-activity-rendering.js`, `18-agent-actions.js`,
`19-chat-send-and-cache.js`, `src/sbepv/api/job_store.py`, `review_store.py`,
`collect_data.py`, and `lib/render-proxy.ts`.

Prioritize ownership/ordering before expanding caching. A historical latest-job
ID is insufficient ownership because retry may reuse it; release ownership when
monitoring stops and before scheduling the next read. Test deferred headers/body,
late success/error/404, and out-of-order refreshes without stale notifications,
timers, or restored deleted work.

For memory bounds, distinguish durable mirrors from supported legacy-only entries.
Protect active leases, input plots, tracebacks, and baseline insertion-order
semantics. A count cap is not a total byte bound; measure exceptional entries
separately. Re-reading evicted records must preserve SQLite/artifacts and must not
turn storage failure into cached success.

For persistence, adapt restoration to fetch by ID before omitting full results;
the current helper expects cached result data. Use migration rather than clearing
old drafts, preserve chat compaction, and coalesce unchanged/rapid writes with
explicit draft checkpoints. Exit flushing alone cannot protect the final edit.

### Measurements and regression gates

Use identical clean-load, restored-session, active-run, and completed-result
workloads before/after. Record requests/duplicate polls, plot bytes, dashboard/chat
storage separately, write frequency, mirror occupancy, and cleanup. Use synthetic
or appropriately protected data; exclude secrets, chat content, and raw measured
values from telemetry.

An earlier local snapshot measured **1,612,653 UTF-8 bytes** of assembled HTML,
**250,520 bytes** at estimated gzip level 9, and **444,002 TEA JavaScript source
bytes**. These predate the final design and are not current network, parsing,
latency, or cache-hit measurements. Re-measure after changes. Redis, service
workers, and offline scientific-result caching are not prerequisites.

Regression gates include saved/fresh sessions, storage denial/quota, 320–1,440px
layouts and zoom-equivalent viewports, late navigation, reset/delete/retry/cancel
races, stuck headers/bodies, database absence/errors, active-job pressure, source
ownership, restart recovery, and TEA isolation. Verify deployed policy through both
front doors separately.

`no-store` prevents storage; `no-cache` requires validation before reuse;
`private` excludes shared-cache storage. These do not replace authentication.
References: [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2)
and [Cloudflare Request API](https://developers.cloudflare.com/workers/runtime-apis/request/).

## Full code sweep

The local sweep repaired the cache/request correctness issues above and these
additional defects:

- Basic Auth now compares UTF-8 bytes, so non-ASCII credentials cannot trigger a
  `compare_digest` server error; both credential comparisons are evaluated.
- Active-job discovery covers the supported 500-job ceiling. An older Annual
  baseline can no longer disappear behind 100 newer jobs and bypass the duplicate
  baseline guard. SQLite admission limits remain transactional.
- Historian `.env` discovery uses the project location when invoked elsewhere;
  explicit paths and existing environment values retain their precedence.
- Plain unittest discovery chooses a temporary output root before API imports
  unless an explicit root is provided. Explicit roots remain the caller's
  responsibility; fixtures must still redirect other external paths as needed.
- Obsolete proxy tests now verify that retired Autonomy routes remain denied.
  Obsolete Decision Agent environment examples were removed.
- Initial TEA cost placeholders use `Unavailable`, consistent with the existing
  presentation contract; the local TEA layout and calculation contract are retained.

Local verification completed with these results:

| Check | Result |
| --- | --- |
| Full Python discovery, Python 3.13.14, temporary API outputs | 833 run: 832 passed, one skipped; no failures/errors. |
| Affected Python frontend/assembly/UI tests after the final chat guards | 164 passed. |
| All Node regression files | 38 passed, including 26 request-lifecycle cases. |
| Playwright smoke suite with mocked APIs | 18 passed; fresh/restored landing, delayed hydration, mobile/desktop, TEA editing, charts, and source retry. |
| TypeScript, ESLint, production frontend build | Passed. |
| Python dependency consistency (`pip check`) | Passed. |
| Documentation links/anchors, retained contract digest, diff whitespace | Passed. |

The full Python run preceded the final frontend-only chat guards; affected Python
frontend tests, all Node tests, browser tests, lint, and the build were rerun after
those changes. Full-run evidence is in `output/full-sweep-final-python.json` and
`output/full-sweep-final-python.log`. The skipped test is
`tests.test_annual_simulation.MidcReferenceHourTests.test_2025_generated_keys_match_reference_with_known_tolerance`:
the 2025 MIDC reconciliation fixtures are absent. Collection and TEA mobile/desktop
captures in `output/playwright/` use synthetic fixtures, not measured results.

This sweep does not certify the absence of all bugs. Mocked browser tests, scientific regressions,
and local builds do not measure live service availability, production memory,
multi-process ownership, or real network throughput. Next, measure cache occupancy
and storage writes, implement terminal-mirror limits and browser-save coalescing,
then bound disposable review storage. Verify process topology before expanding
Collection concurrency across API processes. Deployment and live integration
verification remain separate; this sweep did not publish either host.

## Troubleshooting

| Symptom/limit | Check |
| --- | --- |
| Page loads but collection/chat fails | Provider credentials, intended API origin, auth, and sanitized returned errors. Never print key values. |
| Proxy 503 or credential 502 | Host-side service credentials and backend origin. |
| Python install fails under 3.11 | Select supported 3.12+, preferably the configured 3.13 runtime. |
| TEA numerical gate fails | Inspect runtime/provenance; do not bypass probes or alter fingerprints. |
| Missing `analysis/` in full tests | Create the ignored directory. Missing external MIDC reference data is a separate skip. |
| Results disappear after replacement/restart | Persistent disk and complete SQLite/artifact backup. |
| Historian CLI launched elsewhere | Default `.env` lookup now resolves from the source checkout; explicit paths and environment precedence remain supported. |
| Metadata says `sbe_pv_model.py` | Historical provenance retained deliberately, not a missing active module. |
| Too many export rows | Reduce years or use a coarser supported interval; never silently truncate. |
| Stale Word contents/pages | Refresh native fields; frozen numerical evidence is unchanged. |

`src/run_pipeline.py` remains a standalone legacy batch entry with no imported
callers; it needs its own exercised verification when changed. No `.python-version`
enforces the local runtime. Deployment drift/process topology require operational
inspection rather than inference from a build.

## Historical delivery and design records

These dated records preserve context from the consolidated documents. They are not
fresh production observations or the current sweep's results. Captures may be
machine-local and generated files absent. Original detailed prose is recoverable
from Git using the migration paths below; historical designs are not new authority.

### September 15 comparison for September 17 delivery

The recorded local shared-CAPEX v5 comparison used 100 MWac / 134 MWdc, 30 years,
10,000 realizations, seed 20260916, and proposed 2024 dollars. Recorded deliverables:
`output/pdf/LCOE_comparsion.pdf` and
`output/docx/PV_Comparison_2026-09-15_v2.2_tea_f04eb26c806947dfadec32e49704d441.docx`.
Availability depends on the retained output set.

| Stage | Recorded identity/outcome |
| --- | --- |
| Review | `0c97290a1798425a841e9f7c30a3aec6`; user directed exclusion of all 11 issues. |
| Calibration | `review-0c97290a1798425a841e9f7c30a3aec6`; 976 of 6,647 rows excluded, 5,671 retained, all four seasons fitted, promoted locally. |
| Annual | `a1e1d7919b47`; 2012–2021, 2024, 2025, 105,216 hourly intervals, recorded 100% coverage in all 12 requested years. |
| Primary TEA | `tea_f04eb26c806947dfadec32e49704d441`; recorded stable convergence. |
| UI demonstration | `tea_132495d699784c7fa79edb48ba9febf8`; recorded request/paired results matched the primary. |

Calibration covered December 12, 2025–September 14, 2026 inclusive, hourly, with
125 kWac clipping per system. Fall covered September 1–14 only. Recorded Annual
runtime was 633.999 seconds, not a general runtime guarantee.

| Recorded cumulative LCOE percentile, real 2024 USD/MWh | Solectria | SolarEdge |
| --- | ---: | ---: |
| P10 | 54.3388 | 59.4080 |
| P50 | 59.7234 | 65.1025 |
| P90 | 65.4770 | 71.2008 |
| Deterministic midpoint initial cost, USD | 150,080,000.00 | 154,909,156.75 |

Recorded median paired difference: **+5.3849 USD/MWh**; SolarEdge had lower LCOE
in 0/10,000 realizations for that scenario. SolarEdge added USD 3,891,156.75 hardware
plus USD 938,000 midpoint installation. Midpoint annual O&M was USD 1.407 million
Solectria versus USD 2.010 million SolarEdge. DC costs used 1.34 conversion;
energy normalized from the frozen AC limit. Component allocations were explanatory,
not independently sampled.

Interpretation remained provisional: unresolved major maintenance was not invented,
later vendor/market proxies were not inflation-adjusted, 14.683% of collected rows
were excluded, Fall coverage was limited, and calibration was not independent
validation. The twelve-year weather population constrained inference. Recorded
SolarEdge energy was 3.735% above Solectria before calibration and 1.173% below
afterward, below in every eligible year. That describes a mechanism, not a verified
comparison to an unavailable prior TEA. Generic 2022-dollar benchmarks and this
scenario were not inflation-normalized alternatives.

The original delivery recorded 404 tie-outs/nine Decimal reference cases and a
792-test Python run with one missing-fixture skip, frontend checks, and three
browser checks. Report updates recorded 154 affected tests, then 12 focused v2.2
checks. Final v2.2 was described as eight pages with 13 PDF bookmarks and 16
contents links and rendered PDF/Word inspection. Earlier seven-page/11-bookmark
records describe superseded layouts. These are historical counts, not current
verification claims.

### Startup integration and design history

Collection/cache work was prepared on `codex/data-collection-cache` from `fe89aaa`
and integrated after local TEA design completion. Runtime/design files did not
overlap; two extracted-JS TEA harnesses gained the Collection dependency while
retaining draft/job assertions. Integration recorded 202 selected Python checks:
200 initially passed and two harness failures passed after fixture repairs.
Nine Node checks, typecheck/build, and 18 bounded browser checks passed. Screenshots
used synthetic data. Full Python, live performance, and deployment were outside
that integration. Obsolete legacy proxy tests still expected retired routes then;
the current sweep corrects those expectations without restoring the routes.

Earlier QA covered horizontal Calibration results, Annual inheritance/Fall
confirmation, Saved Results, TEA bridges, assumptions-modal/table iterations, and
frozen-request confirmation. Enduring checks are retained above: meaningful units,
real source values, empty/error states, focus, consent, scroll containment,
responsive tables, and chart fallbacks. The current four-tab editor supersedes the
older table-first/read-only-dollar-year description. Paired v5 supersedes v4's main
view while preserving historical jobs. The July 6 Python-only deployment review
predates the current Sites proxy; its claim that no frontend build existed is obsolete.

Retired Autonomy documents described supervised Investigation/Decision Brief
views, immutable case/evidence/scenario records, human confirmation, and a
deterministic policy. Historical policy identity:
`autonomy-conservative-dominance-v1`, semantic SHA-256
`b5eed8f630cdeb934b1cf5292077be19cf16f14771d4a596975c59c4b614041a`.
Old fixtures, rollout flags, eval commands, agent settings, phase plans, and
acceptance matrices are not current setup guidance. The remaining Decision Agent
eval script imports removed `sbepv.autonomy` and is not a supported application
test entry point. Historical private guards/database references remain protected.

## Documentation migration

The explanatory files below are consolidated here. The calculation contract and
AGENTS.md remain separate governing files, as do licenses/attribution. Committed
history remains in Git; the pre-consolidation working copies, including uncommitted
docs, were preserved locally in `output/full-sweep-before/` with SHA-256 hashes.
Generated reports, scientific data, and visual
QA assets are not documentation duplicates and are outside this consolidation.

| Former file | Current location/treatment |
| --- | --- |
| `frontend/README.md` | Frontend, Annual chart interpretation, TEA editor/reports, testing. |
| `docs/CALIBRATION_WORKFLOW.md` | Calibration/validation and Annual Simulation. |
| `docs/RENDER_DEPLOYMENT.md` | Setup, configuration, deployment. |
| `docs/DEPLOYMENT_REVIEW.md` | Current two-host deployment and dated historical note. |
| `docs/TECHNOECONOMIC_V4_PRODUCT_REQUIREMENTS.md` | TEA compatibility and governing v4 addendum. |
| `docs/TECHNOECONOMIC_V5_PRODUCT_REQUIREMENTS.md` | TEA and governing v5 addendum. |
| `docs/THURSDAY_DELIVERY_2026-09-17.md` | Historical lineage/results/limits and current reports. |
| `docs/DASHBOARD_CACHE_AUDIT_PLAN.md` | Cache findings, priorities, measurements, regression gates. |
| `docs/DATA_COLLECTION_STARTUP_CACHE_WORK.md` | Current startup behavior and dated integration evidence. |
| `design-qa.md` | Frontend acceptance and historical design record. |
| `docs/design-qa/2026-08-02-results-option3.md` | Calibration result layout/history. |
| `docs/design-qa/2026-08-04-annual-simulation-option1.md` | Annual inheritance/confirmation/accessibility. |
| `docs/AUTONOMY_CONSERVATIVE_RECOMMENDATION_CONTRACT_V1.md` | Retired policy identity; historical details in Git. |
| `docs/HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md` | Retired fixture-era design; history in Git. |
| `docs/HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md` | Retired interaction/phase design; history in Git. |
| `docs/UNIFIED_AUTONOMY_TEA_PRODUCT_CONTRACT_V1.md` | Retired architecture; history in Git. |
| `evals/decision_agent/README.md` | Retired eval guidance; not a supported command list. |

The unchanged calculation contract names `frontend/README.md` in its historical
affected-file map and `TECHNOECONOMIC_V5_PRODUCT_REQUIREMENTS.md` as product
guidance. Those explanatory references are now covered by this manual's
[frontend](#frontend-development) and [TEA](#technoeconomic-analysis) sections.
Consolidation does not alter the governing contract or authorize retired work.
