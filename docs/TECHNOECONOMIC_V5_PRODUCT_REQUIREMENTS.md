# Technoeconomic v5 product requirements

Status: approved for implementation on 2026-08-31  
Scope: paired commercial Solectria and SolarEdge lifecycle LCOE in the
Technoeconomic Analysis workflow only

## Decision output

Version 5 compares two modeled commercial lifecycle LCOE distributions at one
common target capacity and rating basis:

- standalone commercial Solectria lifecycle LCOE; and
- standalone commercial SolarEdge lifecycle LCOE.

Each system is a separate headline with a full right-continuous empirical CDF and
Type-7 P10, P50, and P90. A per-realization SolarEdge-minus-Solectria LCOE delta is
an audit diagnostic, not a substitute for either headline. Results are modeled
scenarios, not validated forecasts or vendor quotes.

Version 4 remains the historical single-SolarEdge contract. Version 5 does not
rewrite, relabel, or recalculate version 1 through version 4 jobs.

## Common target and independent source bridges

The user enters one finite positive commercial target, defaulting to 100 MW. Both
systems use that exact target and its one explicit rating basis. Each technology
then scales from its own frozen Annual Simulation authority:

1. read the system's sampled AC energy for the same sampled weather year;
2. divide by that system's frozen applied source capacity;
3. multiply by the common same-rated target capacity; and
4. apply the shared degradation, project-life, and finance realization.

When the frozen Annual request enables a finite positive clipping/curtailment
limit, that limit is the AC operating capacity for both source systems. Otherwise,
each source uses its exact verified installed module nameplate and the target is
DC-rated. Neither the reviewed 125 kW limit nor any nameplate value is hardcoded.

Weather is paired within every realization: Solectria and SolarEdge use the same
frozen weather-year draw. Capacity normalization remains system-specific even when
the two applied capacities happen to have the same numeric value.

## Complete cost stacks and evidence

Each technology has its own complete commercial cost stack. Every stack requires
exactly one full initial CAPEX line and exactly one full annual O&M line, and may
include zero or more sourced scheduled replacements. Lines retain stable input and
coverage IDs, timing, distribution, constant-dollar year, occurrence years, source
evidence, and explicit acceptance where required.

The two stacks use the same timing and unit contract:

- `full_initial_capex`: `initial_t0`, constant USD per target W;
- `full_annual_om`: `annual_year_end`, constant USD per target W-year; and
- `scheduled_replacement`: `scheduled_year_end`, constant USD per target W at
  explicit project years.

Every line's constant-dollar year must equal the shared finance year. Coverage may
not overlap at the same scheduled year within one system. Input IDs are unique
across both systems so every sampled draw is auditable.

No Solectria-specific commercial price, replacement amount, or failure schedule may
be invented. A generic NREL utility-scale PV benchmark may be offered only when it
is labeled as generic, not as a Solectria or SolarEdge quote, and its evidence and
acceptance status remain visible. It cannot support a claim that one technology is
cheaper than the other. A technology-specific difference requires a documented
technology-specific source or a visibly accepted provisional assumption.

## Calculation and comparison

For technology `s` and sampled weather year `y`:

```text
q_s,y = E_source,s,y / P_source,s
E_target,s,year1,y = q_s,y * P_target
E_target,s,PV = E_target,s,year1,y * F_E(r,g,L)
E_target,s,EA = CRF(r,L) * E_target,s,PV

C_target,s,PV = initial_s
                + annual_s * AF(r,L)
                + sum(scheduled_s,t * exp(-t*log1p(r)))
C_target,s,EA = CRF(r,L) * C_target,s,PV

LCOE_s = C_target,s,PV / E_target,s,PV
       = C_target,s,EA / E_target,s,EA

Delta_LCOE = LCOE_SolarEdge - LCOE_Solectria
```

Costs are target totals after multiplying sampled intensity by target watts.
Lifecycle energy must be finite and positive for both systems. All finance,
degradation, sampling, weather-allocation, numerical-probe, percentile, and ECDF
semantics remain those of the approved calculation contract.

## Results and exports

The routine result uses schema 5 and a `paired_commercial` block with common target,
rating basis, transfer method, and constant-dollar year. Its `systems` mapping has
one Solectria and one SolarEdge record, each containing source capacity and rating
basis, capacity scale factor, headline metric and unit, P10/P50/P90, a bounded CDF
display projection, and its cost-line summaries. The signed LCOE delta is retained
as a separate diagnostic.

The sealed realization table includes the existing version-4 SolarEdge commercial
fields, mirrored Solectria target/scale/energy/cost/LCOE fields, and the signed
LCOE-delta field. Full CDF populations stay in the sealed payload and exports.

Version-5 exports use distinct manifest, CSV-bundle, and workbook schema IDs. They
include:

- both system headline and cost-line summary rows;
- both full LCOE CDF populations and an accessible two-curve comparison chart;
- a per-weather-year table with both source bridges and conditional P10/P50/P90;
- all sampled inputs and realization columns; and
- independent per-system capacity, energy, cost-timing, lifecycle, equivalent-
  annual, LCOE, percentile, CDF, and delta tie-outs.

The chart uses one shared LCOE axis and identifies systems with both color and line
style. It must not imply that unequal CDF sample values are matched quantile pairs.

## Interface requirements

The Technoeconomic tab shows both technologies together. Source and target
authority remain shared and visible; cost inputs remain separated by system. The
result order is Solectria and SolarEdge headline values, the two CDFs on a common
scale, then per-system cost summaries and provenance. Narrow layouts stack without
hiding the technology, rating basis, units, evidence status, or modeled-scenario
caveat. Tabular percentile and artifact fallbacks remain available when chart
rendering fails.

## Acceptance criteria

- The two systems use the same weather-year draw, target capacity, rating basis,
  finance realization, degradation realization, project life, and dollar year.
- Each system's energy uses its own frozen source capacity and energy, with no
  cross-system substitution.
- Each LCOE changes only with that system's energy/cost inputs and shared inputs.
- Initial, annual, and scheduled costs independently recompute for each system.
- Lifecycle and equivalent-annual LCOE ratios agree for each system within the
  calculation tolerance.
- The signed diagnostic equals SolarEdge LCOE minus Solectria LCOE realization by
  realization.
- Both full CDFs and every P10/P50/P90 recompute from sealed realizations.
- Per-weather-year counts partition the realization population exactly once.
- Version 1 through version 4 canonical request hashes, calculations, routine
  results, and export contracts remain unchanged.
- Focused kernel, API, worker, export, and frontend tests pass before handoff.
