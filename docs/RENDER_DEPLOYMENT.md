# Render Deployment Checklist

## Upload to GitHub

Create a private GitHub repository in the browser and upload only these project files:

- `app.py`
- `agent_store.py`
- `bazefield_historian.py`
- `calibration_workflow.py`
- `scenario_reporting.py`
- `sbe_pv_model.py`
- `run_pipeline.py`
- `requirements.txt`
- `env.example`
- `.gitignore`
- `docs/`
- `sb_energy_dashboard_modern.html`
- `tests/`

Do not upload `.env`, `outputs/`, `__pycache__/`, generated `.csv` / `.xlsx` / `.png` files, or log files.

## Render Web Service

Create a new Render Web Service from the private GitHub repo.

- Name: `sb-energy-dashboard`
- Runtime: `Python 3`
- Region: Oregon / US West
- Instance type: paid Starter or higher
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Health check path: `/healthz`

Attach a persistent disk:

- Mount path: `/var/data`
- Size: smallest available size that fits expected generated outputs

## Environment Variables

Set these in Render, not in the GitHub repo:

- `PYTHON_VERSION=3.13.14`
- `BAZEFIELD_API_KEY=<real key>`
- `OPENAI_API_KEY=<real key>`
- `DASHBOARD_BASIC_USER=<shared username>`
- `DASHBOARD_BASIC_PASSWORD=<strong shared password>`
- `PV_DASHBOARD_OUTPUT_DIR=/var/data/outputs`

Leave `OPENAI_MODEL` unset initially. Add it only if the deployed chat smoke test returns a model-access error.
Leave `PV_DASHBOARD_ENABLE_LEGACY_RUN` unset so all calibration runs must pass
through the data-quality review.

## Smoke Test

After the first deploy succeeds:

1. Open `https://<service>.onrender.com/healthz` and confirm it returns `{"status":"ok"}`.
2. Open `https://<service>.onrender.com/` and confirm the browser asks for the shared username and password.
3. Select a short known-good calibration window, retrieve its Bazefield review,
   inspect the detected issues, make each Retain/Exclude choice, and apply it.
4. Confirm seasonal factors, review provenance, plots, stats, and CSV/XLSX
   downloads are present.
5. Ask one dashboard chat question and confirm the response is grounded in the run context.
6. Share Cliff only the Render URL and dashboard password, never API keys.

