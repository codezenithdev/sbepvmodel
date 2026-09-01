# Technoeconomic v4 product requirements

Status: approved for implementation on 2026-08-31  
Scope: Technoeconomic Analysis tab and its calculation, provenance, artifacts, and
exports only

## Decision output

The primary result is the probabilistic **standalone commercial SolarEdge LCOE**,
shown as a complete cumulative distribution function (CDF) in real USD/MWh_AC.
P10, P50, and P90 are visible secondary checks. The result is a modeled scenario,
not a validated forecast.

The former commercial SolarEdge-minus-Solectria marginal LCOO remains available
only for historical version-3 jobs. It is not the version-4 headline and is not
relabeled as standalone LCOE.

## Source-to-target calculation bridge

The tab must make the calculation legible in five steps:

1. read sampled SolarEdge AC energy from a verified completed Annual Simulation;
2. divide by the frozen SolarEdge source capacity to obtain specific energy;
3. multiply by the editable same-basis commercial target capacity;
4. calculate discounted lifecycle cost and energy for every realization; and
5. present the standalone commercial SolarEdge LCOE CDF.

The source-capacity rule is authoritative and shared by the backend, provenance,
exports, and UI:

- when the frozen Annual request enables a finite positive clipping/curtailment
  limit, use that value as the AC operating limit (125 kWac in the reviewed case);
- otherwise use the exact verified SolarEdge installed module nameplate
  (currently 139.1808 kWdc), not a rounded “140 kW” value.

The target default is 100 MW. Its AC/DC suffix and rating basis inherit from the
selected source. No source capacity is hardcoded.

## Cost and finance assumptions

The version-4 input is a standalone SolarEdge commercial cost stack. Each line is
editable, probabilistic, evidenced, and one of:

- initial cost at `t=0`, in real USD per target W;
- annual recurring cost at each year-end, in real USD per target W-year; or
- a scheduled replacement cost at explicit year-end occurrence years, in real USD
  per target W.

Supported distributions are Fixed, Uniform, Triangular, and Normal (bounded).
Project life, real discount rate, shared module degradation, constant-dollar year,
sample count, and seed remain explicit and frozen with the job.

The initial benchmark preset is the NREL 2024 Annual Technology Baseline
utility-scale PV base-year benchmark, clearly labeled as a generic utility-scale PV
benchmark rather than a SolarEdge quote:

- AC basis: 1.56 USD/Wac initial CAPEX and 0.022 USD/Wac-year fixed O&M;
- DC basis: 1.17 USD/Wdc initial CAPEX and 0.01658 USD/Wdc-year fixed O&M;
- real-dollar year: 2022; and
- project life: 30 years.

Source: <https://data.openei.org/submissions/6006> (DOI: 10.25984/2377191)

No optimizer replacement amount is invented. The scenario must say that a
replacement is not included until the user adds a sourced scheduled line. All
benchmarks, judgments, and user-entered values retain evidence and acceptance
records.

## Results-first interface

The selected desktop direction is the “calculation bridge” design:

- existing SB Energy shell, navigation, typography, and tokens;
- always-visible five-step bridge above the result;
- large CDF card first in reading and keyboard order;
- interpretation and accessible P10/P50/P90 table beside or below the chart;
- compact scenario-input rail with target, life, model, currency year, discount
  rate, and P50 cost totals;
- **Edit assumptions** opens and focuses the native assumptions section;
- **Calculate/Recalculate** uses the existing review, confirmation, queue, polling,
  and artifact-verification workflow; and
- CSV/XLSX/chart export identities remain compatible.

At narrower widths, the CDF remains before the scenario rail and the bridge stacks
without losing source, unit, evidence, or caveat text. Chart failure must leave the
interpretation and percentile table usable. Controls meet the existing keyboard,
focus, forced-colors, reduced-motion, and touch-target requirements.

## Explicitly out of scope

- changes to collection, calibration, or Annual Simulation behavior;
- Solar Agent or Autonomy changes;
- relabeling or rewriting historical v1-v3 jobs;
- a Solectria benchmark in the v4 headline view;
- taxes, incentives, financing structure, escalation, salvage, or decommissioning;
- invented SolarEdge vendor pricing, optimizer failure rates, or replacement cost;
  and
- deployment or publishing.

## Acceptance criteria

- Changing Solectria energy or cost cannot change a v4 commercial SolarEdge LCOE.
- A clipped Annual source uses its frozen positive limit; an unclipped source uses
  exact verified installed Wdc.
- Source and target rating bases must match or submission fails before enqueue.
- Initial, recurring, and scheduled cost timing independently tie out in exports.
- Lifecycle and equivalent-annual LCOE ratios are equal within the calculation
  contract tolerance.
- The full empirical CDF and Type-7 P10/P50/P90 recompute from sealed realizations.
- v1-v3 canonical request hashes, calculations, and artifacts remain unchanged.
- Focused Python/frontend tests, the full Python suite, frontend build, and
  same-viewport visual comparison all pass before handoff.
