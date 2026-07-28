# Calibration workflow

The validation workflow calculates calibration factors for the exact
user-selected Bazefield period. It deliberately separates source-data review
from model execution so no flagged historian data is silently removed.

## User flow

1. The user selects the date range, interval, model efficiencies, IAM settings,
   backtracking, and optional curtailment limit.
2. `POST /api/calibration-reviews` retrieves a private Bazefield snapshot and
   profiles it without starting the PV model.
3. The dashboard reports the source coverage, seasons, and every detected issue.
   Where both actions are technically valid, the user explicitly chooses
   **Retain** or **Exclude** for the affected rows. Invalid timestamps are a
   required exclusion; gaps are informational because a missing row cannot
   itself be removed.
4. `POST /api/calibration-reviews/{review_id}/run` applies the recorded
   decisions to the hash-verified snapshot and queues the model against that
   reviewed CSV.
5. Results show each applied seasonal factor, valid fitting hours, confidence,
   before-calibration error, excluded-row audit, and physical-driver diagnostics.

Review receipts and raw snapshots expire after 24 hours. A reviewed snapshot
that is bound to a durable model job is retained for reproducible same-input
scenarios; unbound orphans are removed. All review artifacts stay under the
private output area and are not served as downloads.

The legacy `POST /api/run` path is disabled by default so a client cannot skip
the review. An administrator may enable it temporarily with
`PV_DASHBOARD_ENABLE_LEGACY_RUN`, but reviewed calibration endpoints are the
production contract.

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
The cleaned-row counts, decisions, raw-source SHA-256, and reviewed-source
SHA-256 are carried into the result and Excel workbook for auditability.
Nonexistent or repeated `America/Denver` boundary times at daylight-saving
transitions are rejected rather than silently shifting the selected period.

## Seasonal factor method

Meteorological seasons are used:

| Season | Months |
| --- | --- |
| Winter | December–February |
| Spring | March–May |
| Summer | June–August |
| Fall | September–November |

For each system and each season present in the selected range:

```text
factor = valid measured AC energy / uncalibrated modeled AC energy
calibrated AC power = uncalibrated modeled AC power × factor
```

Only daylight samples with `GHI >= 20 W/m²`, uncalibrated modeled power of at
least 1 kW, finite non-negative measured/model power, and a positive bounded
interval are used for fitting. When curtailment is enabled, rows whose
uncalibrated prediction is at or above 98% of the limit are excluded from the
fit so a clipped operating ceiling is not mistaken for model bias.

The factor is applied timestamp by timestamp according to the local
`America/Denver` season. A season with insufficient valid data falls back to
the overall selected-period factor for that system. If the full period is also
insufficient, a neutral factor of `1.0` is used and surfaced as a low-confidence
warning. Factors are not artificially capped; values outside the typical
`0.5–1.5` range are retained and flagged for review.

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

For periods with at least 30 valid daylight samples, the workflow estimates a
small diagnostic regression of the measured-to-uncalibrated power ratio against
available temperature, wind speed, GHI, DNI, DHI, and elapsed time. It reports
the strongest standardized associations and fit quality separately for
SolarEdge and Solectria.

These diagnostics explain residual variation but do **not** change the applied
prediction and must not be interpreted as causal. Soiling cannot be separated
reliably from correlated weather and time without dedicated soiling sensors,
rainfall history, or cleaning/maintenance records. A future adaptive-factor
model should be validated out of sample before replacing the transparent
seasonal energy-ratio factors.
