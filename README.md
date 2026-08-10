# SB Energy PV Operations Dashboard

A physics-based PV performance model for the SBE Innovation Center site (SolarEdge
and Solectria arrays), with a calibration workflow over Bazefield measured data, an
annual simulation over MIDC weather data, and a browser dashboard with an embedded
analyst agent.

## Layout

```
src/sbepv/            the Python package
  model.py            PV physics: pvlib ModelChain + pvmismatch string mismatch
  calibration.py      historian data-quality review and seasonal factor fitting
  store.py            SQLite: proposals, jobs, worker leases, promoted baselines
  reporting.py        scenario comparison, Excel workbooks, comparison charts
  paths.py            repository-root discovery shared by everything below
  ingest/
    bazefield.py      Bazefield REST puller (stdlib only) + CLI
    midc.py           MIDC hourly weather puller + CLI
  api/                the FastAPI application
    main.py           app construction, auth middleware, HTTP routes
    config.py         env-derived settings and paths  (import side effects, see below)
    state.py          process-wide singletons: job cache, agent store, worker events
    schemas.py        Pydantic request bodies
    validation.py     request validation (all 422s originate here)
    timewindows.py    DST-aware Mountain <-> UTC conversion
    artifacts.py      output-file naming, URLs, and cleanup
    plots.py          input-data charts rendered before the model runs
    job_store.py      read-through cache over the durable job registry
    review_store.py   on-disk pending calibration reviews
    baselines.py      which calibration baseline a run may inherit
    proposals.py      what the agent may run, and what needs confirmation
    serializers.py    internal records -> HTTP response shapes
    security.py       HTTP Basic auth
    static_files.py   the /outputs allowlist
  agent/              the Solar Agent chat assistant
    prompts.py        system instructions and static model notes
    tool_schemas.py   the tool contract the model sees
    scenario_math.py  tool arguments -> a concrete model request
    message_guards.py refuses to act on an ambiguous instruction
    tools.py          tool handlers
    chat.py           the OpenAI request/response cycle
  worker/             background job execution
    loop.py           the worker thread: lease, heartbeat, dispatch
    run_validation.py one calibration run
    run_annual.py     one annual simulation
    completion.py     recording success or failure, lease-fenced
  dashboard.py        assembles frontend/ for the Render fallback
src/run_pipeline.py   standalone batch driver (no importers)

frontend/             sole dashboard source -- see frontend/README.md
  dashboard.ts        Vite assembler for the Sites frontend

app/ lib/ worker/ build/          vinext frontend on Cloudflare Workers (TypeScript)
public/                           static assets, served by BOTH front doors
deploy/render.yaml                Render service definition
docs/                             deployment, calibration workflow, design QA
tests/                            272 tests, stdlib unittest
```

## Running it

```bash
pip install -r requirements.txt
```

```bash
uvicorn sbepv.api.main:app --app-dir src --reload --port 8000
```

Then open <http://127.0.0.1:8000>. Copy `env.example` to `.env` and fill in
`BAZEFIELD_API_KEY` and `OPENAI_API_KEY` first; without them the dashboard loads but
Bazefield retrieval and chat fail.

`--app-dir src` puts the package on `sys.path`. `pip install -e .` also works and
makes the flag unnecessary.

## Tests

```bash
python -m unittest discover -v
```

272 tests, one skipped (it needs MIDC reconciliation fixtures that are not in the
repo). Run from the repository root.

## Editing the dashboard

Edit the partials in `frontend/`; there is no generated HTML file to rebuild or
commit. FastAPI assembles them for the Render fallback, and Vite assembles them for
Sites. Run the Python tests and `npm run build` before committing. See
[frontend/README.md](frontend/README.md) for the shared assembly contract and why
file order matters.

## Things worth knowing before you change something

**Importing `sbepv.api.config` has side effects, in order.** It finds the repository
root, loads `.env`, and creates the output directories. `sbepv.api.state` then opens
and migrates the agent SQLite database. Every API module imports `config`, so that
sequence runs once, early, whether you are starting the server or collecting tests.

**Reach settings and singletons through their module.** Write `config.OUTPUT_DIR` and
`state.AGENT_STORE`, not `from .config import OUTPUT_DIR`. The test suite redirects
both at temporary locations by assigning to the module attribute; a value import
captures the original and the tests then quietly exercise — and write to — the real
output directory. `tests/test_project_layout.py` guards this.

**Never shadow a module import with a local name.** Late binding is what keeps those
patches working, so a route named `chat` or a local list named `tools` breaks it at
runtime rather than at import. There is a test for this too.

**matplotlib is pinned to `Agg` transitively.** `sbepv.model` and `sbepv.reporting`
set it at import time; `api/plots.py` imports pyplot lazily and relies on that having
already happened. Break the chain and the worker thread picks a GUI backend and hangs.

**The repository root is found by landmark, not by depth.** `sbepv.paths` walks up to
the directory containing `pyproject.toml` and `src/sbepv/`, so `.env`, `outputs/`,
`public/`, and `frontend/` resolve correctly regardless of where a module sits.

## Deployment

FastAPI runs on Render; a separate vinext/Cloudflare Worker frontend serves the same
dashboard and proxies `/api/*` to it. See [docs/RENDER_DEPLOYMENT.md](docs/RENDER_DEPLOYMENT.md)
and [deploy/render.yaml](deploy/render.yaml).

## Known rough edges

Not introduced by the current layout, and each worth its own change:

- `sbepv.ingest.bazefield.run_historian` calls `load_dotenv()` with a CWD-relative
  default, while the API loads the same file by absolute path. A CLI run from another
  directory reports "No API key found" even though `.env` exists.
- The run metadata written into workbooks still records `"script": "sbe_pv_model.py"`.
  It is provenance data compared across runs, so it was left alone deliberately.
- `docs/RENDER_DEPLOYMENT.md` pins `PYTHON_VERSION=3.13.14`; local development here
  runs 3.11. No `.python-version` is committed, so nothing enforces either.
- `src/run_pipeline.py` has no importers and no test coverage.
