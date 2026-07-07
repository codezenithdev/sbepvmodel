# Render Deployment Checklist

## Upload to GitHub

Create a private GitHub repository in the browser and upload only these project files:

- `app.py`
- `bazefield_historian.py`
- `sbe_pv_model.py`
- `run_pipeline.py`
- `test_chat_backend.py`
- `requirements.txt`
- `env.example`
- `.gitignore`
- `DEPLOYMENT_REVIEW.md`
- `RENDER_DEPLOYMENT.md`
- `sb_energy_dashboard_modern.html`
- `sb_energy_dashboard.html`
- `sb_energy_dashboard_legacy.html`

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

## Smoke Test

After the first deploy succeeds:

1. Open `https://<service>.onrender.com/healthz` and confirm it returns `{"status":"ok"}`.
2. Open `https://<service>.onrender.com/` and confirm the browser asks for the shared username and password.
3. Run a short known-good analysis window and confirm progress, plots, stats, and CSV/XLSX downloads.
4. Ask one dashboard chat question and confirm the response is grounded in the run context.
5. Share Cliff only the Render URL and dashboard password, never API keys.

