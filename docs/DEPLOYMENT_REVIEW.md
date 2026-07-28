
# Deployment Review

Date: 2026-07-06

## Summary

This project is not deployable to Sites as-is. Sites hosts Cloudflare Worker-compatible JavaScript/TypeScript deployments that build to ESM Worker output. The current dashboard is a FastAPI Python application with scientific Python dependencies, background jobs, generated filesystem outputs, and external API calls.

The Python app validated locally, but there is no Sites-compatible build artifact to save or deploy without changing the backend architecture.

## Current project structure

- `app.py`: FastAPI backend, static HTML serving, job orchestration, OpenAI chat endpoint.
- `sb_energy_dashboard_modern.html`: active dashboard frontend served at `/`.
- `sb_energy_dashboard.html` and `sb_energy_dashboard_legacy.html`: alternate dashboard HTML files.
- `bazefield_historian.py`: Bazefield API client and CSV generation.
- `sbe_pv_model.py`: PV modeling using pandas, pvlib, pvmismatch, matplotlib, and openpyxl.
- `requirements.txt`: Python dependencies.
- `test_chat_backend.py`: Python unit tests for chat context and plot rendering.
- `outputs/`: generated CSV, XLSX, PNG, and log files.

## Sites compatibility

Blockers for direct Sites hosting:

- Runtime is Python/FastAPI, not Cloudflare Worker-compatible JS/TS ESM.
- Backend depends on Python packages that are not available in a Worker runtime: `pandas`, `numpy`, `matplotlib`, `openpyxl`, `pvlib`, and `pvmismatch`.
- `/api/run` starts a long-running background thread and stores job state in process memory.
- The app writes generated CSV, XLSX, and PNG files to local disk under `outputs/`.
- The frontend fetches same-origin API routes: `/api/session`, `/api/run`, `/api/status/{job_id}`, and `/api/chat`.

Because of these blockers, a frontend-only Sites deployment would break existing functionality unless a compatible backend URL and API routing plan are added first.

## Recommended architecture

Best option: deploy the frontend on Sites and host the Python backend separately.

Use Sites for the HTML/CSS/JS frontend after making API base URL configurable. Host the Python API on a platform that supports long-running Python workloads and filesystem or object-storage outputs, such as Render, AWS App Runner/ECS, Google Cloud Run, Azure Container Apps, or a VM. Store generated artifacts in durable storage for production rather than relying only on local disk.

Alternative: deploy the full app on a Python-capable host.

This is the fastest production path with the least risk. Serve the existing HTML from FastAPI and run the whole app on Render, AWS, Cloud Run, Azure, or similar. This preserves current behavior with minimal code movement.

Not recommended now: convert the backend to a Sites-compatible JS/TS backend.

The PV modeling path depends on Python scientific and PV libraries. Rewriting that in JS/TS would be a significant port and validation effort, with high risk of model drift.

## Runtime configuration

Required secrets:

- `BAZEFIELD_API_KEY`: required for `/api/run`.
- `OPENAI_API_KEY`: required for `/api/chat`.

Optional configuration:

- `BAZEFIELD_BASE_URL`: defaults to `https://bazefield.sbenergy-us.com/Bazefield.Services/api/`.
- `OPENAI_MODEL`: defaults in `app.py` if omitted.

Production should not commit real `.env` values. Configure these through the selected host's secret manager.

## Validation run

Passed:

- `python -m unittest -v`
- `python -m py_compile app.py bazefield_historian.py sbe_pv_model.py run_pipeline.py test_chat_backend.py`

Not run:

- Sites build/deploy build, because the repo has no `package.json`, no Worker build path, and no `.openai/hosting.json`.

## Deployment gate

No Sites version was saved and no deployment was performed. The app is not eligible for Sites deployment until one of these is true:

- A separate deployed Python backend URL exists and the frontend is adapted to call it; or
- The backend is ported to a Cloudflare Worker-compatible JS/TS implementation; or
- The full app is deployed to a Python-capable hosting platform instead of Sites.
