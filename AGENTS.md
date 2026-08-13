# Agent guide

Read this before editing. It covers the layout, the rules that break silently if
ignored, and what moved during the 2026-08 restructure — knowledge of the old flat
layout is stale.

Human-facing setup lives in [README.md](README.md); dashboard build details in
[frontend/README.md](frontend/README.md).

## What this is

A physics-based PV performance model for the SBE Innovation Center site (SolarEdge
and Solectria arrays). Three workflows share one FastAPI backend and one dashboard:

- **Calibration / validation** — pull measured data from the Bazefield historian,
  make the user review every flagged data-quality issue, fit per-season correction
  factors, compare modelled vs measured.
- **Annual simulation** — run a full year against MIDC weather data, inheriting a
  promoted calibration baseline.
- **Solar Agent** — an OpenAI-backed chat assistant that can propose and run model
  scenarios and parameter sweeps, gated by an explicit confirmation policy.

Jobs run on a background worker thread, leased through SQLite so a dead worker is
detectable and a lost lease cannot overwrite a newer attempt.

## Commands

```bash
python -m unittest discover -v          # 272 tests; run from the repo root
```

```bash
uvicorn sbepv.api.main:app --app-dir src --reload --port 8000
```

`npm run build` validates and builds the separate vinext/Cloudflare frontend.

## Layout

```
src/sbepv/
  model.py  calibration.py  store.py  reporting.py  paths.py  dashboard.py
  ingest/   bazefield.py  midc.py
  api/      main.py config.py state.py schemas.py validation.py timewindows.py
            artifacts.py plots.py job_store.py review_store.py baselines.py
            proposals.py serializers.py security.py static_files.py
  agent/    prompts.py tool_schemas.py scenario_math.py message_guards.py
            tools.py chat.py
  worker/   loop.py run_validation.py run_annual.py completion.py
frontend/   dashboard.ts  css/ html/ js/   canonical dashboard sources
app/ lib/ worker/ build/      TypeScript frontend (vinext on Cloudflare Workers)
```

## Context-efficient inspection

Treat this guide and the layout above as the repository map. Do not begin a task by
inventorying, recursively searching, or reading the whole repository.

- Map the request to the smallest likely set of files first. Inspect only those
  files, their direct callers or dependencies, and the relevant tests.
- Prefer path-scoped and symbol-scoped `rg` searches. Do not dump entire large files
  when a focused range or symbol is sufficient.
- Reuse facts and file contents already established in the current task unless the
  file may have changed. Do not rescan unchanged areas for every follow-up prompt.
- Skip `.git`, dependency folders, generated output, caches, and build artifacts
  unless the request specifically concerns them.
- A repository-wide scan is appropriate only when the user explicitly requests one
  or a genuinely cross-cutting task cannot be resolved locally. State the reason
  before doing it and summarize results instead of injecting raw output into context.
- This guide is orientation, not proof of current behavior. Before editing, still
  verify the specific implementation and tests affected by the requested change.

## Invariants

These five all fail *silently* — no import error, no failing test — so they are
worth checking before you commit. Three of them have guard tests in
`tests/test_project_layout.py`; keep those passing.

**1. Reach settings and singletons through their module.**

```python
config.OUTPUT_DIR        state.AGENT_STORE        # correct
from .config import OUTPUT_DIR                    # wrong
```

The test suite redirects both at temporary locations by assigning to the module
attribute. A value import captures the original, the patch stops applying, and the
affected tests quietly exercise — and write to — the real `outputs/` directory while
still passing.

**2. Never shadow a module import with a local name.**

A route named `chat`, a local list named `tools`, a parameter named `state` — Python
then treats the name as local for the whole function and you get `UnboundLocalError`
or `AttributeError` at runtime, not at import. This bit twice during the
restructure. `test_no_module_import_is_shadowed` enforces it.

**3. Anything a test patches must be called through its owning module.**

`patch.object(mod, "name")` only intercepts callers that resolve through `mod` at
call time — i.e. callers inside `mod`, or callers writing `mod.name(...)`. If you
move a function, either keep every caller qualified or update the patch target.
Getting this wrong makes the test pass while asserting nothing.

Currently module-qualified for exactly this reason: `plots._render_input_data_plots`,
`job_store._latest_completed_job_id`, `review_store._save_calibration_review`,
`baselines._current_calibration_bundle`, `completion._finish_model_job`,
`run_validation._run_job`, `run_annual._run_annual_job`,
`worker_loop._start_model_worker` / `_stop_model_worker`,
`tools._handle_*_tool`, `chat._openai_agent_response`,
`reporting.verify_source_sha256`.

Watch the aliases: where a module name collides with a local, the import is
renamed rather than the local. In `api/main.py` it is `baselines_module`,
`proposals_module`, `agent_chat`, and `worker_loop`; in `agent/chat.py` it is
`agent_tools`. Match whatever the file already uses.

**4. matplotlib is pinned to `Agg` transitively.**

`sbepv.model` and `sbepv.reporting` set it at import time. `api/plots.py` imports
pyplot lazily and relies on that having already happened. Break the chain and the
worker thread picks a GUI backend and hangs — it does not raise.

Related: `model.plot_results` calls `plt.close("all")`, a process-global that
destroys figures belonging to other callers on the same thread.

**5. `frontend/` is the dashboard's only source of truth.**

There is no committed generated HTML. `sbepv.dashboard` assembles the Render
fallback with a source-aware cache, while `frontend/dashboard.ts` assembles the
Vinext/Sites version through Vite raw imports. Keep their slot replacement and
newline behaviour equivalent. `tests/test_dashboard_build.py` exercises the Python
contract, and `npm run build` exercises the Vite contract. Roughly 345 test
assertions match the assembled text, including indentation and element ordering.

Load order inside `frontend/` is filename order and is load-bearing:
`13-agent-drawer-base.css` must precede `14-agent-drawer-redesign.css` (equal
specificity override), and the JS partials are one classic script sharing globals,
not ES modules.

## Other things that will surprise you

- **Import side effects, in order.** Importing `sbepv.api.config` finds the repo
  root, loads `.env`, and creates the output directories. `sbepv.api.state` then
  opens and migrates the agent SQLite database. Every API module imports `config`,
  so this runs once and early — including when merely collecting tests.
- **Some imports are deliberately function-local.** `openai` in `agent/chat.py`,
  pandas/matplotlib in `api/plots.py` and `worker/run_annual.py`. Tests inject a fake
  `openai` via `sys.modules` *after* import time. Do not hoist these to the top.
- **The repo root is found by landmark, not by depth.** `sbepv.paths` walks up to the
  directory containing `pyproject.toml` and `src/sbepv/`. Do not reintroduce
  `Path(__file__).parent` for repo-relative paths.
- **`_JobCancelled` is matched by `isinstance` across a module boundary.** Define it
  once in `api/job_store.py`; a duplicate turns cancellations into hard errors.
- **`_cache_job_record` deliberately preserves `input_plots` and `traceback`.** They
  exist only in the in-memory cache, never in SQLite. Do not "clean up" that merge.
- **Two immutability triggers live in SQLite DDL**, not Python
  (`proposals_payload_is_immutable`, `job_request_is_immutable`). Changing how UPDATE
  statements are composed can surface `sqlite3.IntegrityError` instead of a clean
  domain error.
- **`app/` is the Next.js App Router directory.** No Python package can be named
  `app`; that is why the package is `sbepv`.

## What moved in the 2026-08 restructure

Everything was flat at the repo root. `app.py` was 5,276 lines; the dashboard was one
15,534-line file. Zero behaviour change — verified by an AST diff of all 333
functions against the pre-refactor originals plus a runtime comparison of the agent
contract, route table, and settings.

| Was | Now |
| --- | --- |
| `app.py` | `src/sbepv/api/` (16 modules) + `agent/` (6) + `worker/` (4) |
| `sbe_pv_model.py` | `src/sbepv/model.py` |
| `calibration_workflow.py` | `src/sbepv/calibration.py` |
| `agent_store.py` | `src/sbepv/store.py` |
| `scenario_reporting.py` | `src/sbepv/reporting.py` |
| `bazefield_historian.py` | `src/sbepv/ingest/bazefield.py` |
| `midc_stac_hourly.py` | `src/sbepv/ingest/midc.py` |
| `run_pipeline.py` | `src/run_pipeline.py` |
| single-file dashboard | `frontend/` + Python/Vite runtime assemblers |
| `uvicorn app:app` | `uvicorn sbepv.api.main:app --app-dir src` |

Test imports changed shape but not content:

```python
from sbepv.api import main as app        # was: import app
from sbepv import model                  # was: import sbe_pv_model as model
from sbepv.store import AgentStore       # was: from agent_store import AgentStore
from sbepv.api import config, state      # new: patch targets that moved out of app
```

`tests/__init__.py` puts `src/` on `sys.path`, so no install step is needed.

## Known rough edges

Pre-existing, deliberately not fixed because each changes behaviour:

- `ingest.bazefield.run_historian` calls `load_dotenv()` with a CWD-relative default
  while the API loads the same file by absolute path — a CLI run from elsewhere
  reports "No API key found" though `.env` exists.
- Run metadata still records `"script": "sbe_pv_model.py"`; it is provenance data
  compared across runs.
- `src/run_pipeline.py` has no importers and no test coverage.
- `docs/RENDER_DEPLOYMENT.md` pins Python 3.13.14; local dev here runs 3.11 and
  nothing enforces either.
