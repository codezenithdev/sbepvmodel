# Codex project instructions

## Role and scope

You are the coding collaborator for this PV modelling dashboard. For every user
request, identify the intended outcome, work within its scope, preserve scientific
and data integrity, and verify the result with checks appropriate to the change.
Complete authorized work through implementation and verification when an edit is
requested. For a question, explanation, plan, or review, deliver that result
without treating it as permission to implement changes.

This file is the standing project prompt for Codex working in this repository.
Apply it alongside the current request and the host's instructions and permissions.
It does not configure the dashboard's Solar Agent or change Codex settings for
other projects. Keep these operating rules here so future tasks can load them.

Human-facing setup lives in [README.md](README.md); dashboard build details in
[frontend/README.md](frontend/README.md).

## Approval boundary

Do not design, implement, refactor, or change the behaviour of Autonomy or the
Decision Agent unless the user explicitly confirms that Cliff Ho approved that
work. A broad request to improve the application does not grant that approval.
Read-only impact checks and existing regression tests are allowed when needed to
verify that work elsewhere has not broken those areas; if a proposed non-Autonomy
change requires changing them, stop and ask for the approval confirmation.

Confirmation already supplied in the current task remains valid for the work it
covers. Do not request it again for the same scope. Shared CSS, routes, schemas,
stores, and worker code can affect these features: check the actual impact, not
just the filename. If approval is missing, pause only the dependent work and
continue independent authorized work. Name this rule and the proposed affected
behaviour when asking for confirmation.

## Workflow for every request

1. **Establish the outcome.** Interpret the request in the context of the ongoing
   task. Distinguish an explanation, investigation/review, documentation edit,
   behaviour change, refactor, and deployment. A follow-up usually refines the
   active task; retain earlier requirements and approvals unless superseded.
2. **Bound the work.** Identify the affected workflow, likely files, direct
   dependencies, and observable acceptance criteria. Check the approval boundary
   above before designing a change. Choose the smallest complete solution; a
   general improvement request does not authorize unrelated feature work.
3. **Inspect before editing.** Use the scope map below, relevant local instructions,
   and the current implementation and tests. Check existing changes with
   `git status --short --untracked-files=no` and a path-scoped diff; check untracked
   files only in the area you need. Preserve the user's unfinished work. Expand
   inspection only when evidence shows another dependency or failure path.
4. **Choose checks up front.** Match verification to the changed behaviour using
   the matrix below. For a bug, establish the failing scenario; for scientific
   work, identify the governing contract and expected numerical result; for a
   refactor, identify the behaviour that must remain equivalent.
5. **Act and communicate.** Before substantive tool work, briefly state the
   intended scope and checks. Make reasonable assumptions for routine reversible
   choices and proceed. Ask only when missing information materially changes
   correctness, scope, or authorization. Do not turn this workflow into a long
   checklist in every answer. Give concise updates during sustained work.
6. **Verify and review.** Run applicable checks, inspect the final diff for scope
   and accidental changes, and fix failures caused by this work. If evidence
   requires broader work, explain the dependency and recheck authorization before
   touching a protected area. Report unrelated failures without silently adopting
   them as new work. Do not weaken checks or contracts to obtain a passing result.
7. **Deliver the result.** State what changed or what the investigation found,
   where it matters, what checks actually ran, and any remaining limitation.
   Distinguish passing, failing, and unrun checks. Never claim a build, browser
   check, scientific validation, deployment, or approval that was not verified.

For a short question, apply the relevant scope rules and answer directly; do not
inspect files or run tests unless the answer needs them. For an implementation
request, continue beyond a proposed plan until the authorized outcome is handled
or a concrete blocker requires user input.

## Scope discipline

- Keep unrelated cleanup, dependency upgrades, formatting, and architectural
  rewrites out of the change. Update affected documentation when behaviour changes.
- Preserve equations, units, sign conventions, interval/timezone handling,
  missing-data rules, quality review gates, and provenance unless the requested
  scope explicitly includes changing them. Never present synthetic, stale, or
  unverified output as a measured or completed model result.
- Preserve existing authentication, proposal confirmations, lease fencing,
  immutable requests, and source-integrity checks. Trace the affected guard when
  changing its caller; a UI fix can still change backend behaviour.
- Use test fixtures and temporary paths for verification. Do not overwrite real
  outputs, databases, promoted baselines, or calibration reviews to make a test
  pass. Inspect configuration side effects before importing the API in an ad hoc
  script. Keep credentials out of tracked files, logs, and responses.
- Separate preparing a change from publishing it. Commit, push, deploy, or change
  shared state only within the user's authorized scope. Documentation and Codex
  instruction edits do not require a site build or deployment just because
  `.openai/hosting.json` exists. For actual site work, use the applicable Sites
  skills and the user's delivery instructions.
- When work is blocked by a rule or tool restriction, identify the exact source,
  affected action, and required next step. Do not invent an additional approval
  requirement for routine work already authorized by the user.

## What this is

A physics-based PV performance model for the SBE Innovation Center site (SolarEdge
and Solectria arrays). Four workflows share one FastAPI backend and one dashboard:

- **Calibration / validation** — pull measured data from the Bazefield historian,
  make the user review every flagged data-quality issue, fit per-season correction
  factors, compare modelled vs measured.
- **Annual simulation** — run a full year against MIDC weather data, inheriting a
  promoted calibration baseline.
- **Technoeconomic analysis (TEA)** — a seeded Monte Carlo lifecycle cost/energy
  comparison (SolarEdge minus Solectria) built on a frozen snapshot of a completed
  calibrated Annual Simulation. Structurally isolated: its own tables, worker entry
  point, routes, and exports. Keep it isolated from generic model job mutation and
  baseline promotion; check the existing saved-result evidence integration when
  touching its Solar Agent boundary. The approved calculation contract is
  `docs/TECHNOECONOMIC_CALCULATION_CONTRACT.md`; the kernel implements it exactly
  and rejects anything it cannot prove.
- **Solar Agent** — an OpenAI-backed chat assistant that can propose and run model
  scenarios and parameter sweeps, gated by an explicit confirmation policy.

Jobs run on a background worker thread, leased through SQLite so a dead worker is
detectable and a lost lease cannot overwrite a newer attempt.

## Commands

Run commands from the repository root using a supported environment. Reuse the
existing environment; install dependencies only when the task needs them.
**Python 3.12 or newer is required** by `pyproject.toml`; prefer Python 3.13 to
match `docs/RENDER_DEPLOYMENT.md`. `requirements.txt` pins `numpy==2.5.0` and
`scipy==1.18.0`. Check the actual interpreter before running Python checks.
`package.json` requires Node.js 22.13.0 or newer.

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
```

```bash
python -m unittest -v tests.test_project_layout   # example focused check
python -m unittest discover -v                   # full Python suite
```

The suite writes into a repo-root `analysis/` directory that it does not create;
`mkdir analysis` once, or one bazefield test errors on a fresh checkout.

```bash
uvicorn sbepv.api.main:app --app-dir src --reload --port 8000
```

`python` above must resolve to the intended environment. On Windows, a virtual
environment can be invoked explicitly as `.\.venv\Scripts\python.exe`.

`npm run build` validates and builds the separate vinext/Cloudflare frontend;
`npm run typecheck` checks TypeScript. `npm run test:browser:smoke` runs the
existing bounded Playwright smoke tests when browser testing is in scope; see
[frontend/README.md](frontend/README.md) for browser setup. A successful build
alone is not proof of browser behaviour or numerical correctness.

## Layout

```
src/sbepv/
  model.py  calibration.py  store.py  reporting.py  paths.py  dashboard.py
  technoeconomic.py             pure TEA calculation kernel, no I/O of any kind
  technoeconomic_reporting.py   TEA CSV/XLSX bundles and integrity tie-outs
  ingest/   bazefield.py  midc.py
  api/      main.py config.py state.py schemas.py validation.py timewindows.py
            artifacts.py plots.py job_store.py review_store.py baselines.py
            proposals.py serializers.py security.py static_files.py
            technoeconomic.py   Annual-source verification and kernel request build
  agent/    prompts.py tool_schemas.py scenario_math.py message_guards.py
            tools.py chat.py
  worker/   loop.py run_validation.py run_annual.py run_technoeconomic.py
            completion.py
frontend/   dashboard.ts  css/ html/ js/   canonical dashboard sources
app/ lib/ worker/ build/      TypeScript frontend (vinext on Cloudflare Workers)
```

## Map the request to files

These are starting points, not a requirement to read every listed file. Follow
the affected symbols into direct callers, shared helpers, and tests as needed.
Shortened Python paths in this table are relative to `src/sbepv/`.

| Request area | Start here | Boundaries to check |
| --- | --- | --- |
| Codex instructions or documentation | `AGENTS.md`, the named document, referenced commands/files | Instruction consistency, approval rules, valid paths; no runtime change implied |
| Dashboard appearance or interaction | Relevant `frontend/html/`, `frontend/css/`, `frontend/js/` partials | Shared selectors/globals, protected views, both assemblers, affected workflow tests |
| Calibration or data ingestion | `src/sbepv/calibration.py`, `ingest/`, `api/validation.py`, `api/review_store.py`, `worker/run_validation.py` | Quality review, intervals/units, measured inputs, seasonal factors, baseline promotion |
| PV physics or annual simulation | `src/sbepv/model.py`, `api/baselines.py`, `worker/run_annual.py` | Physical assumptions, calibration inheritance, weather inputs, output/provenance consumers |
| TEA | Calculation contract, `src/sbepv/technoeconomic.py`, `api/technoeconomic.py`, `worker/run_technoeconomic.py`, `technoeconomic_reporting.py` | Frozen Annual source, numerical probes, seed determinism, isolation, export tie-outs |
| Solar Agent | Affected files in `src/sbepv/agent/`, `api/proposals.py` | Tool schema/handler agreement, request validation, confirmation policy, protected-feature overlap |
| API, persistence, or background jobs | Affected route and schema, `api/job_store.py`, `store.py`, `worker/loop.py`, `worker/completion.py` | Auth, request immutability, migrations, cancellation, retries, stale leases, response compatibility |
| Frontend hosting or deployment | Relevant `app/`, `lib/`, `worker/`, `build/` files, package scripts, deployment documentation | Distinguish Python `src/sbepv/worker/` from TypeScript `worker/`; preserve both front doors |
| Autonomy or Decision Agent | Approval boundary above, then only the authorized area | Read-only impact checks and existing regressions are allowed; design/implementation needs confirmed Cliff Ho approval |

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

## Verification matched to scope

Select checks from the actual diff and affected behaviour. Test modules below are
starting points, not an exhaustive list or a substitute for inspecting the case.

| Change | Required verification for that scope |
| --- | --- |
| Documentation or instructions only | Review the diff, verify referenced paths/commands and rule consistency, run `git diff --check`. Do not run application suites or builds for prose alone. |
| Dashboard partials or assembly | `tests.test_dashboard_build`, relevant workflow UI/frontend tests, and `npm run build`. Include `tests.test_project_layout` when imports, paths, or assembly structure change. |
| TypeScript behaviour or frontend plumbing | `npm run typecheck`, `npm run build`, and relevant existing tests. Use bounded browser tests when requested or otherwise required by applicable instructions; report when interaction was not exercised. |
| Calibration/ingestion | Relevant cases in `tests.test_calibration_workflow`, `tests.test_calibration_api`, and the affected ingestion tests; cover review gates and interval/quality handling affected by the change. |
| Physics or Annual Simulation | Relevant cases in `tests.test_annual_simulation`, `tests.test_annual_calibration_model`, `tests.test_annual_calibration_api`, plus tests of the changed model function; verify units, inherited baseline, and expected numerical behaviour. |
| TEA calculations, source, storage, or exports | Relevant `tests/test_technoeconomic*.py` modules for the changed layer; include affected numerical, source-integrity, isolation, and export checks. For agent evidence changes, inspect `tests.test_technoeconomic_agent_evidence` as well. |
| Solar Agent or proposal handling | Relevant `tests.test_agent_backend`, `tests.test_agent_store`, `tests.test_agent_interval_contract`, and frontend tests when applicable; verify validation and confirmation paths. |
| Shared Python imports, paths, state, stores, or worker lifecycle | `tests.test_project_layout` plus direct regression tests for changed persistence/lease/cancellation behaviour and affected workflow boundaries. |
| Broad Python changes spanning workflows, Python runtime/dependency changes, or an explicit full-suite request | Full Python suite; add TypeScript checks/build for frontend impact. Frontend-only dependency changes use the TypeScript row. Existing protected-area regression tests may run without authorizing edits there. |

- Add or update a focused regression test for a meaningful bug or changed contract
  when existing coverage does not exercise it. Do not add tests that merely restate
  the implementation or assert the wording of this guide.
- For deterministic scientific calculations, use the approved contract's reference
  results and tolerances. Do not change expected values, seeds, probes, digests, or
  tolerances simply to match a new result.
- Confirm that patched settings and stores resolve to temporary test locations.
  Before the full suite, create the ignored repo-root `analysis/` directory if it
  is missing, as described below. Keep generated test artifacts out of the diff.
- After applicable checks pass, avoid repeated or broader runs unless a new edit,
  failure, or unresolved dependency justifies them. Record actual commands and
  outcomes; historical test counts in documentation are not current test evidence.

## Invariants

Violating these rules can silently invalidate test isolation or break runtime
behaviour. Check the ones touched by the diff. `tests/test_project_layout.py`
contains guards for imports, paths, state patching, and the plotting backend.

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
contract, and `npm run build` exercises the Vite contract. Regression assertions
match the assembled text, including indentation and element ordering.

Load order inside `frontend/` is filename order and is load-bearing:
`13-agent-drawer-base.css` must precede `14-agent-drawer-redesign.css` (equal
specificity override), and the JS partials are one classic script sharing globals,
not ES modules.

## Other things that will surprise you

- **The TEA kernel gates on numerical behaviour, not on version strings.**
  `technoeconomic.validate_runtime_versions()` runs at the top of `generate_lhs`,
  `allocate_weather_years`, and `validate_request`, and fails closed unless four
  probe groups — the `PCG64DXSM`/`SeedSequence` bit stream, `truncnorm.ppf` across
  ordinary and far-tail intervals, the type-7 quantile rule, and `log1p`/`expm1` —
  each digest to `NUMERICAL_PROBE_DIGESTS` at twelve significant decimal digits.
  It replaced an exact `numpy == 2.5.0 and scipy == 1.18.0` check on 2026-08-15;
  that check had disabled the whole feature on any other runtime, including ones
  whose numbers were identical. Two consequences worth knowing:
  - **Changing a probe changes the contract.** Editing `_NUMERICAL_PROBES` or the
    digests is a calculation-contract decision (§5.6), not a refactor. Regenerate
    with `technoeconomic.numerical_fingerprint()` and get the change approved.
  - **Bit-exactness is reported, not enforced.** Provenance carries
    `numerics.exactness_digest` and `numerics.bit_identical_to_reference` so two
    completed jobs can be compared. SciPy 1.17.1 and 1.18.0 pass the same gate but
    differ by three ULP on one near-bound `truncnorm.ppf` case, so they are within
    contract tolerance without being bit-comparable. Do not "fix" that by
    tightening the gate to the exactness digest; it would re-break the feature on
    every runtime but one.
  - Deliberately unprobed: `matrix_rank` and `lstsq` reach LAPACK, so their
    trailing bits follow the local BLAS build, not the NumPy release.
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
- `docs/RENDER_DEPLOYMENT.md` pins Python 3.13.14; nothing enforces that locally
  beyond the `requires-python = ">=3.12"` floor in `pyproject.toml`.
- `tests/test_bazefield_quality_factor_comparison.py:115` writes into a repo-root
  `analysis/` directory that it does not create and that `.gitignore` excludes, so
  `test_analysis_directory_supports_the_temporary_csv_workflow` errors with
  `FileNotFoundError` on a fresh checkout without that directory. `mkdir analysis`
  clears that prerequisite; verify current suite results rather than relying on
  historical test counts. This directory issue has been observed on both 3.11
  and 3.13; use the supported Python version for current work.
