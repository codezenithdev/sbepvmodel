"""Task-scoped application facts. Update with the corresponding UI/API contract."""
import re


SECTIONS = {
    'workflow': {
        'match': r'workflow|application|app\b|start|steps|report|guide|how.*use',
        'text': 'Data Collection downloads source measurements and CSV/XLSX without running or calibrating a model. Model Calibration separately retrieves data, requires decisions on every flagged quality issue, fits seasonal factors, and may promote a reviewed baseline. Annual Simulation uses historical MIDC weather with that baseline, or explicitly physics-only settings. TEA v5 requires eligible frozen completed calibrated Annual evidence and computes standalone lifecycle LCOE for each system. Reports export saved verified results. TEA v6, Autonomy and Decision Agent are retired. Calibration fit is not independent predictive validation; historical weather simulation is not a validated long-range forecast.',
        'source': 'README.md; docs/TECHNOECONOMIC_CALCULATION_CONTRACT.md',
    },
    'collection': {
        'match': r'collect|download|csv|xlsx|bazefield|historian|timezone|\bdst\b|end.*date|interval',
        'text': 'Standalone Data Collection does not initiate calibration review or execute physics. It has its own request, status, files and bounded queue. Collection dates use an exclusive end; include the next midnight for an inclusive last day. Use the displayed timezone and source interval rules; MIDC is MST UTC-7 while local historian windows require timezone/DST handling. CSV is retained if optional plots or XLSX generation fail. An error or empty download is not measured zero energy. API /api/data-collections is separate from calibration reviews and model jobs.',
        'source': 'src/sbepv/api/collect_data.py; frontend/js/07-collect-data.js',
    },
    'saved_results': {
        'match': r'sav|bookmark|pin|history|oldest|recent|restart|browser|local|persist|delete|remov|lost|missing|share|team',
        'text': 'Analysis library searches shared Calibration, Annual and TEA history by name/ID, workflow and status; its metadata marks bookmarks and current promoted baselines. Opening a completed library result preserves the input draft and is blocked if it would replace active-job polling. Saved results remains a quick-access server-side SQLite bookmark drawer for completed Calibration and Annual jobs, shared across this workspace, capped at ten total bookmarks, not ten per user. It is not the recent-ten-run index and that limit does not mean only ten jobs persist. Removing a bookmark does not delete its underlying job; permanent job deletion is separate with guards. Browser localStorage contains drafts/cache, not authoritative completed evidence. Restart persistence requires both database and artifacts on durable storage; a recent index is not an indefinite retention promise. Promoting calibration selects a scientific baseline and is not a bookmark. TEA is discoverable in Analysis library but has separate storage/mutation routes, not generic Saved results bookmarks. Open/select existing evidence before suggesting a rerun. Never claim oldest saved from recent_runs: use saved_results_index timestamps and disclose the indexed scope.',
        'source': 'src/sbepv/store.py; frontend/js/20-saved-results.js',
    },
    'tea': {
        'match': r'tea|lcoe|cost|dollar|inflation|deflator|index|economic|converg|numerical|runtime|gate|capacity|scal',
        'text': 'TEA v5 uses frozen eligible complete paired Annual weather-year rows; partial years are not accepted as full-year peers. Capacity normalization follows calculation contract section 18.1: when the frozen Annual clipping/curtailment limit is enabled, finite and positive, each source capacity is limit_kW * 1000 and both source and commercial target use rating_basis=ac_operating_limit (Wac or MWac). Otherwise each system uses its own verified installed_wdc and both source and commercial target use rating_basis=dc_installed_nameplate (Wdc or MWdc). The predicted energy remains AC energy in either branch. Divide each system source AC energy by its own authoritative source capacity, then multiply by the common target capacity expressed in matching units and rating basis. Never substitute one system capacity for the other, or assume AC normalization without the frozen source evidence. A separately declared DC rating for cost normalization does not supply an extra energy multiplier. If no source is selected, explain both supported capacity branches rather than assuming the current preset applies. Discount lifecycle costs and AC energy within each paired realization, calculate its ratio, then summarize that distribution. Do not divide independent P50 cost and energy. Shared weather year and shared uncertain inputs preserve pairing; calibration/measurement uncertainty is not automatically included. Current user-cost-basis-2026-v1 preset uses 2026 dollars and 96,000 optimizers; historical thursday-2026-09-17-v1 preserves 2024 dollars and 103,077 optimizers. Cost-year changes use the UI preview then explicit apply, with a frozen US BEA GDP price-index snapshot; the 2026 value is a provisional 2026 Q2 proxy, not a finalized full-year observation. Use index metadata for exact values, dates and ratios. Old saved jobs are never rebased automatically. Numerical gate failures require checking the supported runtime and numerical probes; rerunning unchanged inputs is not a fix and reference digests/tolerances must not be bypassed. Convergence describes sampling stability, not validity of assumptions or commercial transfer.',
        'source': 'docs/TECHNOECONOMIC_CALCULATION_CONTRACT.md; README.md#technoeconomic-analysis',
    },
    'recovery': {
        'match': r'fail|error|cancel|retry|recover|missing|unavailable|timeout|stuck|not.*work',
        'text': 'Use the job identifier and authoritative status to distinguish queued, running, failed, canceled and interrupted work. Model/TEA retry and cancel use their own lifecycle controls and do not grant permission to alter scientific evidence. Missing context or artifacts should trigger selection/storage/access diagnosis; do not assert a run was lost from process memory or automatically rerun it. Numerical-gate failures are runtime/probe compatibility issues. If a provider or research service fails, explain which evidence is unavailable and what the user can retry. Never invent a completed result to cover a failure.',
        'source': 'src/sbepv/api/job_store.py; src/sbepv/worker/loop.py',
    },
}


def relevant_sections(question: str) -> dict:
    selected = {'workflow': SECTIONS['workflow']}
    for name, section in SECTIONS.items():
        if re.search(section['match'], question, re.IGNORECASE):
            selected[name] = section
    return {name: {'text': section['text'], 'source': section['source']} for name, section in selected.items()}
