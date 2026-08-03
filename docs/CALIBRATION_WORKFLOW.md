# Calibration workflow

The validation screen supports two paths for the exact user-selected Bazefield
period:

- an uncalibrated physics-model run; or
- an opt-in, reviewed seasonal calibration.

The **Calibrate the model** checkbox selects the path. Calibration deliberately
separates source-data review from model execution so no flagged historian data
is silently removed. An unchecked run skips factor fitting and returns the
physics-model predictions directly.

## User flow

1. The user selects the date range, interval, model efficiencies, IAM settings,
   backtracking, optional curtailment limit, and whether to calibrate.
2. When calibration is unchecked, the dashboard sends `POST /api/run` with
   `calibrate_model=false`. The job retrieves the selected Bazefield data, runs
   the physics model without fitting or applying seasonal factors, and returns
   the normal plots, statistics, and workbook.
3. When calibration is checked, `POST /api/calibration-reviews` retrieves a
   private Bazefield snapshot and profiles it without starting the PV model.
4. The dashboard reports source coverage, the meteorological seasons present,
   and every detected issue. **Show affected rows** loads hash-verified source
   rows lazily from
   `GET /api/calibration-reviews/{review_id}/rows?issue_id=...&offset=...&limit=...`.
   The table is paginated rather than placing source values in the public review
   summary.
5. Where both actions are technically valid, the recommended **Retain** or
   **Exclude** action is selected in the dropdown by default. The user can review
   the affected-row sample and change that choice. A choice applies to every
   source row affected by that issue, including rows beyond the displayed
   sample. Invalid timestamps remain a required exclusion, while gaps are
   informational because a missing row cannot itself be removed.
6. Selecting **Apply decisions & calibrate** opens the **Source-data decision
   gate**. The model is not queued until the user acknowledges that the flagged
   rows and Retain/Exclude choices were reviewed and selects **Confirm decisions
   & calibrate**.
7. `POST /api/calibration-reviews/{review_id}/run` then applies the recorded
   decisions to the hash-verified snapshot and queues the model against that
   reviewed CSV. The gate becomes a persistent receipt showing the reviewed and
   excluded row counts and the bound job ID; it remains visible while the run is
   active and when dashboard state is restored.
8. Calibrated baseline results show each final seasonal factor, reviewed sample
   coverage, confidence, before-calibration error, excluded-row audit, and
   physical-driver diagnostics. Every reviewed row in the season contributes,
   so each system's final measured and predicted energy totals reconcile within
   0.01 kWh.

Review receipts and raw snapshots expire after 24 hours. A reviewed snapshot
that is bound to a durable model job is retained for reproducible same-input
scenarios; unbound orphans are removed. All review artifacts stay under the
private output area and are not served as downloads.

`POST /api/run` is the production path for an explicitly uncalibrated request
with `calibrate_model=false`. A direct request with `calibrate_model=true` (or
with the field omitted, because the API default remains `true`) is rejected by
default so a client cannot bypass calibration review. An administrator may
temporarily permit legacy unreviewed calibration with
`PV_DASHBOARD_ENABLE_LEGACY_RUN`, but the reviewed calibration endpoints remain
the production contract. Conversely, `POST /api/calibration-reviews` accepts
only requests with calibration enabled.

## Data-quality checks

The review detects:

- missing required columns and unusable timestamps;
- duplicate timestamps, timestamps outside the end-exclusive requested window,
  gaps, and irregular cadence;
- missing or non-numeric power and weather values;
- values outside broad physical bounds;
- near-zero plant power under strong irradiance;
- plant power reported without irradiance;
- isolated local spikes using a robust rolling-median/MAD test; and
- non-trivial sensor flatlines lasting roughly four hours or longer.

Every issue has a stable ID, severity, affected columns and row count, sample
timestamps where applicable, an allowed-action list, and a recommended action.
The public report exposes only whether affected source rows are available. The
row endpoint verifies the private snapshot hash and returns bounded pages (50
rows per dashboard request, with an API maximum of 200), so large reviews do not
inflate the initial response or browser storage.
The cleaned-row counts, decisions, raw-source SHA-256, and reviewed-source
SHA-256 are carried into the result and Excel workbook for auditability.
Nonexistent or repeated `America/Denver` boundary times at daylight-saving
transitions are rejected rather than silently shifting the selected period.

## Seasonal factor method

Meteorological seasons are assigned in `America/Denver` local civil time:

| Season | Months |
| --- | --- |
| Winter | December–February |
| Spring | March–May |
| Summer | June–August |
| Fall | September–November |

These are the standard DJF/MAM/JJA/SON groupings. The selected range is not
expanded automatically to a complete three-month season: a partial-season
request uses only the timestamps in that exact range, while a range crossing a
boundary calculates an independent factor for each season present.

After the review decisions have been applied, each system and season uses every
remaining reviewed row to calculate one auditable energy-ratio factor:

```text
applied factor = measured AC energy / uncalibrated modeled AC energy
```

When curtailment is enabled, direct division alone would not account for the
clipped operating ceiling. The workflow therefore solves the equivalent
whole-season equation:

```text
sum(final predicted AC power × interval) = sum(measured AC power × interval)
final predicted AC power = min(uncalibrated AC power × applied factor, curtailment limit)
```

Without curtailment this reduces to the direct all-row measured/model energy
ratio. With curtailment, the workflow solves the monotonic clipped-energy
equation. Calibration stops with an actionable error if the measured target is
physically unreachable under the selected cap or the model produces no positive
energy. The result records the final factor, reviewed sample and hour coverage,
target energy, predicted energy, and residual.

The factor is applied timestamp by timestamp according to the local
`America/Denver` season. There is no daylight-only sample filter or cross-season
fallback: retained nighttime, low-output, and weather-fallback rows contribute
to the same seasonal energy calculation as every other reviewed row.
Factors are not artificially capped; values outside the typical `0.5–1.5`
range are retained and flagged for review.

Energy integration is bounded to the requested sampling interval. Therefore an
excluded row or source gap cannot cause the following row to represent several
missing hours.

### Scenario integrity

The reviewed baseline stores the exact floating-point factor applied for every
season and system, together with its source hash and review lineage. A
same-input scenario reuses that immutable profile instead of fitting against
the measurements again. This preserves the effect of efficiency, IAM,
backtracking, or other model changes; recalculating the factor for every
candidate would otherwise cancel much of the requested change. A scenario must
contain every local season required by its frozen profile, and no candidate
measurement is used to derive a replacement factor.

An uncalibrated `calibrate_model=false` validation job provides direct model
results but does not create or qualify as a reviewed calibration baseline.
Calibration promotion and same-input calibration scenarios therefore remain
limited to jobs carrying the hash-verified review lineage described above.

Solar Agent can queue only these reviewed, same-input scenarios. A request that
changes the calibration date, time, interval, or source is a new data period,
so Solar Agent does not fetch it, create a proposal, or start a model job. It
hands the user back to the visible Calibration form to retrieve Bazefield data,
review the detected irregularities, record every Retain/Exclude decision, and
apply the reviewed run. The same handoff applies when no reviewed calibration
baseline exists.

Confirmation and promotion endpoints enforce the same lineage rule as a
backstop: a validation candidate must carry data-quality provenance whose
reviewed-source SHA-256 matches the job source. Thus a legacy or cross-run
candidate cannot be promoted into the active calibration baseline without
first passing through the visible review workflow.

## Data-driven diagnostic extension

For periods with at least 30 comparable measured/model samples, the workflow
estimates a small diagnostic regression of the measured-to-uncalibrated power
ratio against available temperature, wind speed, GHI, DNI, DHI, and elapsed
time. It reports the strongest standardized associations and fit quality
separately for SolarEdge and Solectria.

These diagnostics explain residual variation but do **not** change the applied
prediction and must not be interpreted as causal. Soiling cannot be separated
reliably from correlated weather and time without dedicated soiling sensors,
rainfall history, or cleaning/maintenance records. A future adaptive-factor
model should be validated out of sample before replacing the transparent
seasonal energy-ratio factors.
