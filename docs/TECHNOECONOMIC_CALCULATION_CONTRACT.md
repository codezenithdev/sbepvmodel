# Probabilistic Technoeconomic Analysis: Phase 0 Contract

Status: **proposed for approval**

Phase: **0 (inspection and design only)**

Date: **2026-08-13**

Revision: **Phase 0.2 — Cliff shared-chat lifecycle/Wdc reconciliation**

This document defines the calculation and architecture contract for replacing the
dashboard's deterministic, browser-only Technoeconomic Analysis (TEA) with a
durable probabilistic job. It incorporates the Phase 0 repository inspection and the
2026-08-13 review of Cliff's shared ChatGPT conversation. It records what the
repository currently does, the proposed formulas and data rules, a hand-calculated
golden example, the likely file impact, the implementation sequence, and the
decisions that still need product confirmation.

No production code was changed in Phase 0.

## 1. Plain-language summary

The new TEA will not rerun the PV physics model. The user will select a completed,
calibration-adjusted Annual Simulation. At the moment the TEA is submitted, the
server will freeze a copy of every eligible full-weather-year row. Each row already
contains the Solectria and SolarEdge energy from the **same weather year**, so that
pair must remain together.

For every stored calculation and display, **Solectria is the baseline (`SOL`) and
SolarEdge is the optimized case (`SE`)**. Every delta is explicitly
`SolarEdge minus Solectria`; a positive cost delta means SolarEdge costs more, and a
positive energy delta means SolarEdge produces more.

For each realization, the job will:

1. draw one value for each uncertain cost or finance input using seeded Latin
   Hypercube Sampling (LHS);
2. select one eligible paired weather-year row, with equal probability by year;
3. use the frozen module-DC-nameplate capacities to normalize each system in Wdc;
4. build separate Solectria and SolarEdge lifecycle cost streams from system-only
   and shared cost items under exactly one declared cost basis;
5. turn the sampled paired annual energy into discounted lifecycle energy streams
   using source-backed degradation assumptions;
6. calculate discounted lifecycle LCOEs, SolarEdge-minus-Solectria cost and energy
   deltas, Cliff's all-in marginal LCOO, and their mathematically equivalent
   CRF-annualized values;
7. retain every realization, including years in which SolarEdge produces the same
   or less energy than Solectria; and
8. summarize the ensemble with empirical CDFs, percentiles, weather-year summaries,
   sensitivity rankings, convergence checks, and reproducible exports.

The job will use its frozen source snapshot throughout execution and retry. It will
never follow a later annual promotion, reread a changed source job, or enter Annual
Simulation baseline, promotion, proposal, or comparison logic.

## 2. Current behavior being replaced

The current implementation is entirely in canonical frontend sources. It accepts
two nonnegative **already annualized** scalar costs and reads one aggregate
Solectria/SolarEdge energy pair from the latest browser-held Annual Simulation
result. It calculates:

```text
baseline LCOE = baseline annualized cost / Solectria annual energy
current LCOO  = (optimized annualized cost - baseline annualized cost)
                / (SolarEdge annual energy - Solectria annual energy)
```

It supports exactly one eligible calendar-year row, suppresses LCOO whenever the
energy change is zero or negative, and has no backend request, durable record,
worker, source snapshot, probabilistic sampling, optimized LCOE, export, sensitivity,
or convergence result.

The relevant current sources are:

- `frontend/html/50-technoeconomic.html`
- `frontend/js/06-technoeconomic.js`
- `frontend/css/04-technoeconomic.css`
- supporting bindings and saved browser-form state in the other canonical
  `frontend/` partials

## 3. Methodological basis

The requested Cliff/Ho workflow is interpreted as the probabilistic method described
by Clifford K. Ho and Gregory J. Kolb:

- represent uncertain inputs with explicit probability distributions;
- sample the distributions with stratified Latin Hypercube Sampling;
- run a set of equally weighted realizations;
- express output uncertainty with cumulative probability distributions; and
- use forward stepwise linear rank regression to rank inputs by incremental
  coefficient of determination (delta R-squared), also reporting standardized
  regression coefficients and their signs.

References:

1. C. K. Ho and G. J. Kolb, *Incorporating Uncertainty Into Probabilistic
   Performance Models of Concentrating Solar Power Plants*, Journal of Solar Energy
   Engineering 132(3), 2010, DOI `10.1115/1.4001468`.
2. C. W. Hansen and C. E. Martin, *Photovoltaic System Modeling: Uncertainty and
   Sensitivity Analyses*, SAND2015-6700, 2015.

These sources define the probabilistic and sensitivity method. They do not define
this application's term "all-in LCOO."

### 3.1 Cliff shared-chat review

Phase 0 also reviewed *SolarEdge Solectria Cost Comparison*, Cliff's shared ChatGPT
conversation at [the supplied shared-chat URL](https://chatgpt.com/share/e/6a7dfea2-bec0-8327-9d00-7bdab0aa099c),
accessed 2026-08-13. The conversation supplies the project-specific intent that was
missing from the repository:

- every marginal quantity is SolarEdge minus Solectria;
- costs and energy should be compared over a discounted lifecycle, not by dividing
  lifecycle cost by only one year's energy;
- both systems should be normalized by installed module DC nameplate Wdc;
- SolarTAC/as-built economics and a commercially representative cost design are
  different bases and must not be blended;
- truly common cost streams cancel from the marginal numerator; and
- transferring SolarTAC specific-energy differences to a commercial design requires
  explicit mechanism-by-mechanism assumptions.

The chat is **secondary synthesis**, not a primary cost source. Its numeric estimates,
its interpretation of drawings, and links to other pages may be frozen as rationale,
but none may become a runnable numeric default. An underlying invoice, purchase
order, quote, as-built BOM/drawing, manufacturer document, market listing, or
benchmark must be captured and independently verified before receiving its own
evidence classification.

Provisional figures inventoried from the chat include a SolarTAC differential central
estimate of about `+$6,500` (`+$0.046/Wdc`) and a commercially representative central
estimate of `+$0.035/Wdc`. The chat's commercial component endpoints independently
sum to approximately `+$0.012` to `+$0.063/Wdc`, which is wider than its separately
stated aggregate `+$0.02` to `+$0.05/Wdc` range. The aggregate and component ranges
must never both be sampled because that would double-count the same uncertainty.
These figures are examples awaiting evidence and explicit user entry, not defaults or
validated bounds.

The chat cites manufacturer manuals/warranty material, DOE and NLR benchmarks,
O*NET/BLS-derived wages, reseller listings, and an industrial transformer-pricing
guide. This inventory helps locate candidate evidence; it does not validate the
applicability, price date, quoted scope, or SolarTAC procurement value of any cited
page. Each underlying source must pass the evidence checks in Section 5.5 before use.

There is also an unresolved equipment-record discrepancy. The chat discusses an
inferred `244 x 575 W` array, a 330 kW SolarEdge unit, and a 200 kW Solectria unit.
The inspected production model uses `240 x 579.92 W` for each array, identifies the
Solectria inverter as an XGI 1500-250 at 250 kW AC, and does not store a SolarEdge AC
nameplate/clipping parameter. The TEA must not promote either description to
authoritative equipment metadata until the BOM/one-line and model are reconciled.

## 4. Source Annual Simulation contract

### 4.1 Eligible source job

A source is eligible only when all of the following are true at TEA submission time:

- it is a durable `done` Annual Simulation job;
- its annual temporal-semantics version/fingerprint is current;
- calibration was enabled and the result says calibration was applied;
- its durable calibration profile and application provenance are complete and
  internally hash-consistent;
- its origin validation job, reviewed data-quality decision record, and recorded
  calibration promotion can still be resolved and verified against the origin
  source SHA-256;
- its recorded MIDC source file still matches the recorded SHA-256 and, under the
  recommended retention policy, resolves to the matching immutable content-addressed
  artifact identity/byte count;
- `annual_source_audit.source_sha256` equals the job's source SHA-256, the audit
  interval equals the canonical request/window interval, and audited period coverage
  agrees with the result window and annual-energy rows;
- the top-level and `stats` copies of `annual_energy_by_year` agree; and
- at least one row satisfies every row rule below.

Physics-only annual runs and unverifiable legacy annual runs are rejected. A
completed run with an explicitly recorded and verified Spring-to-Fall calibration
substitution remains eligible because the substitution was already approved before
that Annual Simulation ran.

### 4.2 Eligible paired row

The authoritative population is `annual_energy_by_year`, not the separately sorted
Annual Simulation CDF series. A row is included only when:

```text
complete_calendar_year is true
source_complete is true
cdf_eligible is true
year, period_start, and period_end are valid
sol_predicted_kwh is finite and greater than zero
se_predicted_kwh is finite and greater than zero
```

The frozen energy row contains at least:

```text
year
period_start
period_end
row_count
coverage_status
source expected/covered interval counts and coverage percentages
sol_predicted_kwh          # baseline Solectria AC energy
se_predicted_kwh           # optimized SolarEdge AC energy
combined_predicted_kwh
optional physics-only energy fields, retained as provenance but not sampled
```

The two predicted-energy values stay paired. The job must never independently sort,
resample, or join the Solectria and SolarEdge energy series.

### 4.3 Frozen provenance

Submission freezes a canonical, versioned snapshot containing:

- source annual job ID, kind, state, timestamps, and immutable request;
- every eligible paired annual-energy row and every excluded annual row with reason;
- annual result/window and current temporal-semantics identity;
- MIDC source path identity, SHA-256, source audit, interval convention, quality,
  warnings, and per-period coverage;
- immutable Annual-owned content-addressed MIDC artifact identity, media type, byte
  count, storage key, and verified SHA-256, or the explicitly approved weaker
  retention policy/status;
- full origin/resolved calibration profiles, their SHA-256 values, calibration
  baseline and review IDs, seasonal factors, settings deltas, substitution and
  explicit consent records;
- the resolved origin validation job's immutable request, source SHA-256, reviewed
  `data_quality` provenance and decisions, calibration fit metadata/diagnostics, and
  matching historical promotion receipt;
- application/model contract version and relevant software/version identity; and
- snapshot schema version plus SHA-256 of the canonical snapshot JSON.

For this contract, "all calibration provenance" means both the evidence embedded in
the completed Annual Simulation and the resolvable origin validation/review/promotion
records named by that evidence. A source Annual Simulation is ineligible if those
origin records have already been deleted or no longer cross-check; the TEA must not
silently downgrade to the embedded profile alone.

Private filesystem paths and other internal-only fields remain in durable evidence
but are removed from public API projections.

### 4.4 Frozen Wdc capacity manifest

`Wdc` means installed **module DC nameplate power at STC**. It never means inverter
AC nameplate, optimizer nameplate, modeled AC output, or a rounded drawing capacity.
The source snapshot stores separate Solectria and SolarEdge capacity records:

```text
rating_basis = module_dc_nameplate_at_stc
module model and STC watts per module
strings, bays per string, modules per bay, and total module count
installed_wdc = module_count * module_stc_wdc
calibration-physics version and fingerprint
capacity-manifest schema version and canonical SHA-256
```

Validation requires every value to be finite and positive, the topology product to
equal module count, the multiplication to equal `installed_wdc`, and the fingerprint
to match both the Annual result and applied calibration profile.

The current production physics has 240 modules per system at 579.92 Wdc, or exactly
`139,180.8 Wdc` per system. Annual result JSON currently stores the committing
calibration-physics fingerprint but not the manifest values themselves. For a legacy
Annual job, reconstruction is permitted only if its stored full calibration-physics
fingerprint exactly equals the current manifest; otherwise the source must be rerun.
Whether to allow that exact-fingerprint legacy path is a confirmation decision.

Canonical calculations divide by capacity in **Wdc**, so energy intensity is labeled
`kWh_AC/Wdc-year` and cost intensity is `USD/Wdc` or `USD/Wdc-year`. User-facing
displays may additionally show per-kWdc values only through the explicit conversions
`kWh_AC/kWdc = 1,000 * kWh_AC/Wdc` and `USD/kWdc = 1,000 * USD/Wdc`.
The numerator is modeled calibrated AC energy while the capacity denominator is
module DC STC nameplate; units may never be relabeled without that factor. LCOO uses
cost and energy on the same Wdc or kWdc basis, so the common factor cancels.

## 5. Cost-input and analysis-basis contract

### 5.1 Explicit sign convention

The technology names, not generic baseline/optimized aliases, are authoritative:

```text
SOL = Solectria baseline
SE  = SolarEdge optimized
DeltaX_se_minus_sol = X_SE - X_SOL
```

This order is used in formulas, API fields, CSV/XLSX columns, CDF labels, tooltips,
accessible text, and narrative interpretation. A bare `delta_cost` or `delta_energy`
field is not allowed in a durable schema.

### 5.2 Separate SolarTAC and commercial bases

Every TEA job selects exactly one named analysis basis:

- `solartac_site`: project-specific installed totals in constant USD and USD/year,
  divided by the frozen as-modeled capacity of each system; or
- `commercial_representative`: separately sourced, representative commercial costs
  expressed as USD/Wdc and USD/Wdc-year, with its own target design record.

One job never blends the bases. A commercial design record freezes target/reference
Wdc, module and optimizer quantities, DC/AC ratio and inverter loading, inverter and
transformer topology/count, BOS scope, labor productivity/rates, commissioning scope,
currency year, and every normalization derivation. SolarTAC inverter, transformer,
or installation totals are never silently divided by a hypothetical commercial Wdc.
The same Annual energy snapshot may support separate site and commercial jobs, but
the resulting distributions remain separate result families.

### 5.3 Cost ownership, timing, and completeness

Each line item has one ownership scope:

- `solectria_only`;
- `solaredge_only`; or
- `paired_shared`, sampled once and applied to both systems. Its comparison treatment
  is separately classified as `common_cancelled` or `shared_non_cancelling` after
  normalization and timing checks.

Each line item also has one version-1 timing/type:

- initial CAPEX at `t=0`;
- initial installation labor at `t=0`;
- recurring labor at each year-end `t=1..L`;
- recurring O&M at each year-end `t=1..L`; or
- recurring maintenance at each year-end `t=1..L`.

Recurring values are level real annual amounts or intensities. A source-derived
expected annual maintenance value may include replacement parts and truck rolls only
when its derivation prevents double counting. Discrete failure/replacement-event
schedules are outside the recommended version-1 scope and are a confirmation
decision.

Version 1 otherwise excludes inflation/escalation within a constant-real-dollar job,
taxes and tax credits, financing structure, residual/salvage value, decommissioning,
and component-specific service lives. Adding any of these changes the lifecycle
stream contract and requires an explicit later version.

Accordingly, the version-1 kernel accepts exactly one calculation-treatment key for
both systems: `constant-real-v1`. An unknown key is rejected even when both sides use
the same text; a label cannot claim timing or escalation arithmetic that the kernel
does not implement. A genuinely different system treatment must be normalized into
the supported constant-real basis and represented by disjoint system-owned lines,
or wait for a later contract version that defines its arithmetic.

A `full_system` cost stack includes all system-only and shared/common streams needed
for standalone SolarEdge and Solectria LCOEs. A `differential_only` stack may omit
verified common streams and supports marginal cost/LCOO only; it cannot call its
partial ratios full-system LCOE. Because the original requested output includes both
standalone LCOEs, the recommended production flow requires `full_system`.

Every line item also freezes an inclusion/exclusion scope and stable component IDs.
The server rejects overlaps before enqueueing: an inclusive installed-cost total or
all-in benchmark cannot be summed with equipment, labor, BOS, warranty, replacement,
or O&M items already contained in it. Equipment-only plus installation labor is
allowed only when source scope proves they are disjoint. Aggregate differential
inputs and their component lines are mutually exclusive, as are annual expected-
maintenance allowances and any replacement/truck-roll amounts already inside them.
The immutable validation receipt records the overlap graph and decision for every
potentially overlapping pair.

### 5.4 Exact common-cost cancellation

Paired/shared never means merely similar, unpriced, or placed in the same category;
nor does it by itself promise cancellation. A paired stream is classified
`common_cancelled` only when its sampled normalized intensity, normalization
basis/method, timing, escalation/discount treatment, and every other calculation
treatment are identical for SolarEdge and Solectria. Native Wdc values may differ;
the resulting per-Wdc intensities must be identical. Only those eligible streams
must have an exact zero SolarEdge-minus-Solectria contribution. The engine includes
every paired stream in each standalone full-system LCOE and exports the two normalized
values, derived delta, eligibility checks, treatment, and reason. A paired stream
that fails any check is retained as `shared_non_cancelling`; its derived delta is not
discarded, provided both sides use a calculation treatment implemented by this
contract. Unsupported or genuinely different treatment keys are rejected rather
than merely relabeled.

The kernel accumulates SolarEdge-minus-Solectria marginal contributions line by line
and forces each verified `common_cancelled` contribution to exact zero. It does not
derive the authoritative marginal value by subtracting two potentially huge system
totals, so common-cost cancellation remains numerically invariant at every scale.

Modules, trackers/racking, piles, common civil work, common DC wiring,
interconnection, and common plant O&M are candidates only after explicit
classification. SolarEdge optimizers/transformer, topology-specific BOS/labor,
control or meter differences, commissioning differences, replacements, truck rolls,
and availability consequences do not cancel by default. If native capacities differ,
equal total dollars do not cancel per Wdc; the normalized intensities must be equal.

### 5.5 Source evidence and quality

Every input line item freezes:

```text
input ID and label
analysis basis, ownership scope, cost type, and completeness scope
distribution family and parameters
original units, normalized units, quantity/capacity denominator, and derivation
constant-dollar cost year
source title/organization and URL or stable local reference
source publication/as-of and access dates
source excerpt or derivation note
evidence class
user-entered rationale/acceptance for judgment or secondary values
evidence attachment/content SHA-256 when bytes are available
```

Evidence class is one of:

1. `project_actual`: invoice, purchase order, as-built BOM, timecard, or maintenance
   record;
2. `direct_quote_or_primary_document`: attached vendor quote or manufacturer source;
3. `public_market_proxy_or_benchmark`: reseller listing or public benchmark;
4. `engineering_judgment`; or
5. `secondary_synthesis`, including Cliff's shared chat.

A value is not promoted merely because secondary synthesis links to another page.
The underlying evidence must be captured and independently checked. The shared-chat
figures may appear only after explicit user entry/acceptance as provisional
assumptions; they never prepopulate runnable numeric defaults. Source evidence is
immutable after submission. A URL or local path alone is not immutable evidence:
uploaded/retrieved evidence bytes are stored in confined content-addressed storage
and hashed when licensing/access permits; otherwise the frozen provenance must say
that only metadata/excerpt/hash supplied by the user was preserved.

### 5.6 Supported distributions

Each distribution has finite, closed mathematical support, and its parameters use
the same physical units as the input. Routine LHS generation uses uniforms strictly
inside `(0, 1)`, so a nondegenerate distribution's exact endpoints are part of its
support but are not ordinarily drawn. Degenerate inputs can equal their endpoint.

Version 1 applies role-specific validation:

- every fixed value and the full support of every cost input is nonnegative;
- real discount-rate support is greater than `-1`;
- degradation support satisfies `0 <= g < 1`;
- transfer inputs follow the approved transfer policy; and
- project life follows Section 5.7.

Signed *derived* SolarEdge-minus-Solectria cost is valid; a signed user-entered
aggregate cost delta is not allowed in the recommended paired itemized model.

Validation is support-wide, not limited to individual parameters. Before a durable
job may be accepted, conservative closed-support endpoint bounds must prove that all
required binary64 realization fields remain finite: system and marginal lifecycle
and equivalent-annual costs and energies, LCOEs, every reportable signed LCOO, and
applicable SolarTAC or commercial-reference raw totals. This includes multipliers,
summed lines, annuity/lifecycle factors, Wdc scaling, and transfer factors. A request
that would inevitably overflow is a validation error, not a later worker failure.
Runtime finite-value checks remain defense in depth.

#### Fixed

```text
X = value
requirements: value is finite
```

Fixed inputs consume no LHS dimension and are omitted from sensitivity predictors.

#### Uniform

```text
X = low + U * (high - low)
requirements: low <= high
```

If `low == high`, it normalizes to fixed.

#### Triangular

For `low <= mode <= high`, with `c = (mode - low)/(high - low)`:

```text
if U < c:
    X = low + sqrt(U * (high - low) * (mode - low))
else:
    X = high - sqrt((1 - U) * (high - low) * (high - mode))
```

Equal bounds normalize to fixed.

#### Bounded normal

This is a truncated normal, not clipping/censoring an ordinary normal:

```text
a = (low - mean) / sd
b = (high - mean) / sd
X = mean + sd * Phi^-1(Phi(a) + U * (Phi(b) - Phi(a)))
```

Requirements: `sd > 0`, `low < high`, all parameters finite, and a nonempty
truncated probability interval. The mean need not be centered in the bounds.

Version 1 evaluates this inverse CDF with `scipy.stats.truncnorm.ppf`, authored
against SciPy 1.18.0. This is deliberate: ordinary binary64 normal-CDF
subtraction collapses legitimate far-tail intervals (for example, 10 to 11 standard
deviations) to zero probability. A result that rounds onto a bound is moved one
binary64 value toward the interior; an interval with no representable interior
binary64 value is rejected. The SciPy version is stored with the sampling
provenance.

The dependency is on this *behavior*, not on a version string, and the runtime
gate says so directly. `technoeconomic.validate_runtime_versions` evaluates four
probe groups at every entry point — the `PCG64DXSM`/`SeedSequence` bit stream,
`truncnorm.ppf` across ordinary, 10-to-11 and 37-to-38 standard-deviation
intervals, the type-7 quantile rule, and the `log1p`/`expm1` pair behind the
annuity and lifecycle-energy factors — and refuses to run unless each digest
matches `NUMERICAL_PROBE_DIGESTS` to twelve significant decimal digits.
`matrix_rank` and `lstsq` are excluded on purpose: they reach LAPACK, so their
trailing bits track the local BLAS build rather than the NumPy release.

Twelve digits absorbs last-bit refinement between releases — SciPy 1.17.1 and
1.18.0 differ by three ULP on one near-bound case while agreeing everywhere the
contract depends on them — and still rejects every failure mode that matters,
each of which moves far more than one part in `1e12`. Bit-level identity is
reported rather than enforced: provenance carries an `exactness_digest` and a
`bit_identical_to_reference` flag, so a reviewer comparing two completed jobs
can tell whether they are bit-comparable or merely both within contract
tolerance. Re-approving `NUMERICAL_PROBE_DIGESTS` is a contract decision.

### 5.7 Finance and degradation inputs

The real annual discount rate `r`, project life `L`, and degradation assumptions are
source-backed. The recommended version-1 policy lets `r` use any supported
distribution and requires a fixed integer `L >= 1`.

The sampled paired Annual row is year-one energy. Degradation begins after year one.
The recommended matched-system model uses one shared sampled module-degradation rate
because the production systems use the same module model, unless source evidence
justifies separate `g_SOL` and `g_SE`. Separate degradation distributions require an
approved correlation/pairing rule; silently sampling them independently is not
allowed.

All money uses one declared constant-dollar cost year. Inputs from another year must
be normalized before submission, with the index/source and derivation recorded.

## 6. Seeded Latin Hypercube Sampling contract

Let `n` be the user-specified realization count and `d` the number of non-fixed
uncertain dimensions, including costs, finance, degradation, and approved energy-
transfer inputs. The implementation stores the named/versioned pseudorandom-number
generator and LHS algorithm.

The proposed `tea-lhs-v1` sampling version pins:

- NumPy `PCG64DXSM` as the bit generator, authored against NumPy 2.5.0 and
  verified at runtime by the Section 5.6 `pcg64dxsm_stream` probe;
- a user seed integer in `0..2^64-1`;
- canonical uncertain-dimension order by server-assigned stable ASCII input ID
  matching `[a-z0-9._:-]+`, followed by reserved IDs for approved dependence groups
  and weather allocation;
- one domain-separated substream per purpose/dimension, initialized from the SHA-256
  digest of `"sbepv-tea-lhs-v1\0" + uint64_seed_big_endian + "\0" + purpose + "\0" + stable_id`; purpose and ID are UTF-8 and forbidden to contain NUL. The
  32-byte digest is split into exactly eight big-endian unsigned 32-bit words and
  passed, in order, as NumPy `SeedSequence(entropy=words)` before constructing
  `PCG64DXSM`;
- open-interval binary64 jitter: draw a raw `uint64`, set `k = word >> 11`, reject
  and redraw only when `k == 0`, then use the exactly representable
  `jitter = k / 2^53`. Thus `2^-53 <= jitter <= 1-2^-53`; rounding can never produce
  zero or one; and
- a versioned Fisher-Yates permutation. For `i = length-1 .. 1`, compute in an
  unbounded integer `m=i+1` and `limit=2^64-(2^64 mod m)`; draw raw `uint64` words
  until `word < limit`; set `j=word mod m`; then swap positions `i` and `j`. This
  rejection/modulo rule is used for every cost/LHS and weather permutation, so
  results never depend on an undocumented library shuffle.

The exact version-1 domain-purpose strings are `lhs-jitter`, `lhs-permutation`,
`weather-extra-permutation`, and `weather-assignment-permutation`; the reserved
weather stable ID is `weather.year`. After evaluating `(k + jitter) / n`, binary64
rounding is checked against the exact stratum bounds `k/n` and `(k+1)/n`. A value on
or outside either bound is moved with `nextafter` to the nearest representable value
strictly inside that stratum. This repair is part of `tea-lhs-v1`, because open
jitter alone does not prevent the final division from rounding to a boundary.

The canonical request stores sampling version and NumPy version. Python/dictionary
iteration order never determines streams. A future PRNG, dependency, seed rule, or
permutation is a new sampling version, never a silent change.

Proposed guardrails are integer `1 <= n <= 100,000`, with `10,000` as the UI default.
Small jobs remain valid for golden checks, but sensitivity or convergence reports
`unavailable`/`not demonstrated` when its evidence threshold is unmet. The server
owns the bounds; the browser never silently changes `n`.

For each uncertain dimension `j`:

1. Divide `(0, 1)` into `n` equal-probability strata.
2. Draw seeded jitter strictly inside each stratum:
   `u[k,j] = (k + jitter[k,j]) / n`, for `k = 0..n-1`.
3. Apply an independently seeded permutation to that dimension's values.
4. Transform values through the input's inverse CDF.

The RNG adapter guarantees `0 < jitter < 1`; `U == 0` and `U == 1` are forbidden.
Inputs are independent except for explicitly shared draws and any approved,
versioned degradation/transfer pairing rule. No unrecorded correlation is allowed.

Weather year is a discrete paired input sampled with a versioned balanced categorical
algorithm rather than a continuous inverse-CDF transform:

1. Give every one of `Y` ascending source years `floor(n/Y)` realizations.
2. Select the `n mod Y` years that receive one extra realization using a seeded
   permutation of the year IDs.
3. Construct the resulting `n`-element multiset as ascending-year count blocks, then
   seed-shuffle it and assign it to realization rows.

Counts therefore differ by at most one for every positive `n` and `Y`, while the
identity and order of extra assignments remain seed-dependent. Solectria and
SolarEdge values from an assigned row are never resampled independently.

Identical canonical request, source snapshot, seed, algorithms, and contract version
produce identical numeric values, classes, and summaries. Canonical table hashes use
stable row/column order and versioned JSON with shortest round-trip finite decimals.
CSV uses stable order, UTF-8, LF, and versioned formatting. XLSX package bytes need
not match because metadata can vary; cell values, schemas, checks, and content hashes
must match.

## 7. Discounted lifecycle calculation contract

### 7.1 Timing and first-year normalized energy

For realization `i`, initial costs occur at `t=0`. Recurring cost and energy occur at
each year-end `t=1..L`; there is no `t=0` energy.

For the sampled paired Annual row:

```text
Y_SOL,1 = E_SOL,1_kWh_AC / Pdc_SOL_W       [kWh_AC/Wdc-year]
Y_SE,1  = E_SE,1_kWh_AC  / Pdc_SE_W        [kWh_AC/Wdc-year]
Year1DeltaSpecificEnergy_se_minus_sol = Y_SE,1 - Y_SOL,1

Y_j,t = Y_j,1 * (1 - g_j)^(t-1), j in {SOL, SE}
```

Each system is normalized before differencing. This is essential if capacities ever
differ. The current equal capacities make normalized and raw-total ordering agree,
but the durable contract does not rely on that accident.

### 7.2 Discount factors, annuity factor, and CRF

```text
DF_t    = 1 / (1 + r)^t
AF(r,L) = sum(t=1..L, DF_t)
CRF     = 1 / AF
```

Equivalently, for `r != 0`:

```text
CRF = r * (1 + r)^L / ((1 + r)^L - 1)
```

When `r == 0`, `AF=L` and `CRF=1/L`. Stable `log1p`/`expm1` implementations may be
used, but every realization must produce finite positive `AF` and `CRF`.

### 7.3 Lifecycle cost intensity

For SolarTAC totals, normalize sampled costs by that system's frozen Wdc. Commercial
inputs are already separately sourced per-Wdc intensities:

```text
i_j = (initial CAPEX_j + initial installation labor_j) / Pdc_j
rho_j = (recurring labor_j + recurring O&M_j
         + recurring maintenance_j) / Pdc_j
```

For commercial inputs, the divisions above mean the already normalized equivalents.
Then:

```text
PVCostIntensity_j = i_j + sum(t=1..L, rho_j * DF_t)
                  = i_j + rho_j * AF                 # level real recurring stream

EquivalentAnnualCostIntensity_j = CRF * PVCostIntensity_j
                                = CRF * i_j + rho_j
```

This explicitly preserves the original requirement to annualize initial CAPEX and
installation labor with CRF and add recurring labor/O&M/maintenance. The lifecycle
PV and equivalent-annual forms are exact transforms of the same cost stream.

### 7.4 Lifecycle energy intensity

```text
PVEnergyIntensity_j = sum(t=1..L, Y_j,t * DF_t)
EquivalentAnnualEnergyIntensity_j = CRF * PVEnergyIntensity_j
```

The Annual row is the first-year basis, not a lifetime denominator by itself.
Different degradation rates can make the sign of the lifecycle delta differ from the
year-one delta, so both are retained.

### 7.5 LCOEs, deltas, and Cliff's all-in LCOO

```text
LifecycleLCOE_SOL = PVCostIntensity_SOL / PVEnergyIntensity_SOL
LifecycleLCOE_SE  = PVCostIntensity_SE  / PVEnergyIntensity_SE

DeltaLifecycleCostPerWdc_se_minus_sol =
    PVCostIntensity_SE - PVCostIntensity_SOL

DeltaLifecycleEnergyPerWdc_se_minus_sol =
    PVEnergyIntensity_SE - PVEnergyIntensity_SOL

DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol =
    CRF * DeltaLifecycleCostPerWdc_se_minus_sol

DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol =
    CRF * DeltaLifecycleEnergyPerWdc_se_minus_sol
```

Cliff's all-in marginal LCOO is:

```text
AllInLCOO_se_minus_sol = DeltaLifecycleCostPerWdc_se_minus_sol
                         / DeltaLifecycleEnergyPerWdc_se_minus_sol

                       = DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol
                         / DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol
```

The equality is exact because the same CRF multiplies both deltas. When both systems
have equal Wdc, it also equals raw `PV(C_SE-C_SOL) / PV(E_SE-E_SOL)`. With unequal
Wdc, normalize each system first; raw project totals would conflate scale and
technology.

For the `solartac_site` basis, raw totals are also retained as explicit secondary
fields—`PVCost_SOL_USD`, `PVCost_SE_USD`,
`DeltaPVCostUSD_se_minus_sol`, `PVEnergy_SOL_kWh_AC`,
`PVEnergy_SE_kWh_AC`, and `DeltaPVEnergyKWhAC_se_minus_sol`. They are exported and
may be displayed as site diagnostics, but the normalized fields above are the
cross-capacity comparison authority. A commercial per-Wdc input has no invented raw
total unless the commercial design supplies an explicit reference Wdc.

### 7.6 Commercial-energy transferability

SolarTAC results need no commercial transfer claim. A `commercial_representative`
job may calculate commercial energy/LCOE/LCOO only from either a separately modeled,
eligible representative energy source or an immutable approved transfer record.

The proposed explicit transfer parameterization is:

```text
Y_SOL,1_commercial = T_baseline * Y_SOL,1_solartac
DeltaY_1_commercial = T_incremental *
                      (Y_SE,1_solartac - Y_SOL,1_solartac)
Y_SE,1_commercial = Y_SOL,1_commercial + DeltaY_1_commercial
```

`T_baseline=1` or `T_incremental=1` is a strong explicit assumption, never a default.
The record identifies target design and the evidence/rationale/status for climate and
irradiance, module/string/optimizer topology, mismatch mechanism, shading, row and
tracker geometry, conversion/temperature behavior, DC/AC ratio and clipping,
availability/outages, curtailment, soiling, weather representativeness, degradation,
and size independence. Mismatch and conversion effects may be candidates for
transfer; shading, geometry/tracker behavior, clipping, availability, curtailment,
soiling, and site weather do not transfer automatically.

Request validation evaluates distribution support against every eligible source
year and must prove `Y_SOL,1_commercial > 0` and `Y_SE,1_commercial > 0` for every
possible supported combination. `T_baseline > 0` and `T_incremental >= 0` are
necessary but not sufficient when a source year's SolarEdge-minus-Solectria delta is
negative. A request that cannot prove both positive yields is rejected before
enqueueing; individual invalid realizations are never dropped or clamped.

Without an approved transfer or representative source, commercial cost and
`DeltaLifecycleCostPerWdc_se_minus_sol` distributions may be produced, but
commercial LCOEs, lifecycle energy delta, and LCOO are explicitly unavailable. A single
incremental factor is insufficient for standalone LCOEs; both absolute baseline and
incremental energy must be defined.

### 7.7 Lifecycle outcome classification

Classification uses the durable
`DeltaLifecycleEnergyPerWdc_se_minus_sol` lifecycle normalized energy, not the
sampled year-one raw delta. Below, `DeltaE` is shorthand only for that durable field,
and `DeltaC` is shorthand only for `DeltaLifecycleCostPerWdc_se_minus_sol`.
Numerical zero means:

```text
abs(DeltaLifecycleEnergyPerWdc_se_minus_sol) <=
    max(1e-9 kWh_AC/Wdc,
        1e-12 * max(abs(PVEnergyIntensity_SE),
                    abs(PVEnergyIntensity_SOL)))
```

Every realization is retained and assigned an energy class plus a cost/energy
tradeoff class. The table uses the tolerance-derived energy class and cost class,
not the unrounded raw sign, so a within-tolerance value cannot receive a contradictory
tradeoff:

```text
positive_lifecycle_gain  when DeltaE > tolerance
zero_lifecycle_gain      when abs(DeltaE) <= tolerance
negative_lifecycle_gain  when DeltaE < -tolerance

cost_increase + positive_lifecycle_gain: cost increase / energy gain
cost_neutral  + positive_lifecycle_gain: SolarEdge dominant, cost-neutral gain
cost_saving   + positive_lifecycle_gain: SolarEdge dominant, saving and gain
cost_increase + negative_lifecycle_gain: SolarEdge dominated
cost_neutral  + negative_lifecycle_gain: energy loss at neutral cost
cost_saving   + negative_lifecycle_gain: lower-cost / lower-energy tradeoff
cost_increase + zero_lifecycle_gain: cost increase / no lifecycle energy change
cost_neutral  + zero_lifecycle_gain: lifecycle-equivalent within tolerances
cost_saving   + zero_lifecycle_gain: saving / no lifecycle energy change
```

Cost-zero classification uses the same form as energy zero, in USD/Wdc:
`max(1e-12 USD/Wdc, 1e-12 * max(abs(PVCostIntensity_SE), abs(PVCostIntensity_SOL)))`; values above/below that tolerance become
`cost_increase`/`cost_saving`, and values within it become `cost_neutral`.

Nonzero negative-energy rows retain signed LCOO arithmetic; a positive ratio made by
two negative deltas is never presented as favorable. Zero-energy rows retain every
other value but set LCOO null with `zero_lifecycle_delta_energy`. The recommended
headline LCOO CDF/P5/P50/P95 population remains conditional on positive lifecycle
gain, with negative/zero probabilities and tradeoff summaries shown separately.

## 8. Statistical summaries and diagnostics

### 8.1 Empirical CDF and percentiles

For each finite output population, sort values ascending. Equal values share the
same right-continuous empirical cumulative probability `P(X <= x) = max_rank / m`,
matching the Annual Simulation ECDF convention.

Report P5, P50, and P95 using one fixed, documented quantile definition. Proposed:
NumPy's default linear method (Hyndman-Fan type 7), because it is explicit,
widely reproducible, and matches common spreadsheet inclusive percentiles.

Required output summaries:

- lifecycle Solectria LCOE and SolarEdge LCOE: all realizations when the cost/energy
  basis is complete;
- `DeltaLifecycleCostPerWdc_se_minus_sol`: all realizations;
- `DeltaLifecycleEnergyPerWdc_se_minus_sol`: all realizations with commercial
  energy available;
- equivalent-annual cost and energy deltas: the same populations;
- all-in LCOO: positive-lifecycle-gain headline population plus separate signed
  diagnostic summaries; and
- lifecycle energy classes and cost/energy tradeoff counts and probabilities.

CDF plots must state the population and denominator in their subtitle/metadata.

### 8.2 Per-weather-year summaries

For every eligible source year, report:

- source Solectria and SolarEdge AC energy, each frozen Wdc, both first-year specific
  energies, and explicit SolarEdge-minus-Solectria first-year specific-energy delta;
- realization count and share;
- P5/P50/P95 for both lifecycle LCOEs, lifecycle and equivalent-annual cost/energy
  deltas, and any defined LCOO;
- energy-class counts; and
- an explicit note when no finite LCOO exists for the year.

If balanced allocation gives a source year zero realizations (possible when `n < Y`),
the year still appears with its frozen energy/capacity data, count/share zero, null
simulation percentiles, and reason `no_realizations_assigned`; it is never omitted.

First-year source energy is fixed within a source year, but sampled degradation,
discount rate, or commercial-transfer inputs can vary its lifecycle value. Per-year
rows are descriptive conditional summaries, not independent evidence.

### 8.3 Ho-style forward stepwise rank regression

Run sensitivity separately for these responses where finite and sufficiently
variable:

- lifecycle Solectria LCOE;
- lifecycle SolarEdge LCOE;
- lifecycle cost delta per Wdc;
- lifecycle energy delta per Wdc; and
- approved LCOO reporting population.

Candidate predictors are non-fixed exogenous inputs with a structural path to the
response. A response is never also used as its own predictor. The response-specific
sets are:

- Solectria LCOE: applicable Solectria/shared costs, finance, `g_SOL`, normalized
  first-year Solectria energy, and applicable baseline transfer input;
- SolarEdge LCOE: applicable SolarEdge/shared costs, finance, `g_SE`, normalized
  SolarEdge source energy, and applicable transfer inputs. The normalized Solectria
  source energy enters only when the commercial transfer equation constructs
  SolarEdge energy from baseline plus incremental yield;
- lifecycle cost delta: non-cancelled costs and finance, with no energy/degradation
  predictor;
- lifecycle energy delta: finance, degradation, both normalized first-year source
  energies, and applicable transfer inputs, with no cost predictor; and
- LCOO: every non-fixed input with a structural path to either approved delta.

Inputs that cancel algebraically from a response are excluded with reason
`no_structural_effect`. Raw calendar year is not treated as continuous. Per-year
summaries separately show the deterministic categorical weather-row relationship.
Perfectly constant and duplicate-rank predictors are excluded with recorded reasons.

Proposed deterministic algorithm:

1. Convert each response and predictor to midranks (average ranks for ties).
2. Standardize each rank column to zero mean and unit sample standard deviation.
3. Start with an intercept-only ordinary least-squares model (`R^2 = 0`).
4. At each step, tentatively add every remaining predictor and calculate the
   ordinary `R^2` improvement.
5. Add the predictor with the largest positive incremental delta R-squared.
   Treat candidate improvements within `1e-12` as tied and resolve them by stable
   input ID.
6. Stop when no remaining predictor improves `R^2` by at least `1e-6`, the residual
   degrees of freedom would be less than 1, or every eligible predictor is entered.
7. Refit the final standardized rank model and report entry order, incremental and
   cumulative R-squared, standardized beta and sign, sample count, exclusions, and
   final model R-squared.

Preprocessing retains the lexicographically first exact rank-duplicate predictor and
records later duplicates as `duplicate_rank`. Before each candidate fit, the design
matrix must gain one numerical rank under NumPy's matrix-rank rule; otherwise
the candidate is recorded as `rank_singular`. Ordinary R-squared is clamped only for
roundoff to `[0, 1]`. These policies prevent an arbitrary least-squares solution from
changing entry order when predictors are algebraically redundant.

This is a deterministic, application-specific convention consistent with Ho's
high-level description of stepwise rank regression, incremental R-squared, and
standardized beta. Ho does not specify this exact entry threshold or tie rule. The
convention intentionally avoids inventing a p-value, AIC, or BIC rule, and its
approval is requested in Section 12.

Sensitivity is marked unavailable, not fabricated, when the response has fewer than
the minimum usable observations, no variance, insufficient residual degrees of
freedom, or severe rank singularity. Proposed minimum: `max(20, 2p + 2)` rows for
`p` eligible predictors; below that threshold the job still succeeds but explains
why sensitivity is not reported.

### 8.4 Convergence diagnostics

The realization table is generated in deterministic LHS order. Evaluate cumulative
checkpoints at ascending unique sizes from this set after clamping each value to
`1..n`:

```text
min(n, 20), ceil(0.10*n), ceil(0.25*n), ceil(0.50*n), ceil(0.75*n), n
```

At each checkpoint report, for every primary metric:

- P5, P50, and P95;
- absolute and relative change from the preceding checkpoint;
- lifecycle energy-class and cost/energy-tradeoff proportions; and
- cumulative representation of each weather year.

The diagnostic is evidence, not a promise of mathematical convergence. It is
`not demonstrated` when fewer than two unique checkpoints exist. Otherwise the
proposed status is `stable` only when the final two checkpoints satisfy all of:

- for P5/P50/P95 of both LCOEs, lifecycle cost/energy deltas, and every defined
  headline-LCOO quantile, the symmetric relative change
  `abs(new-old) / max(abs(new), abs(old))` is at most `1%` when that denominator is
  at least 100 times that metric's absolute tolerance;
- otherwise the absolute change is at most `$0.0001/kWh` for LCOE/LCOO,
  `$0.0001/Wdc` for lifecycle cost intensity, or `0.0001 kWh_AC/Wdc` for lifecycle
  energy intensity;
- every lifecycle class/tradeoff probability changes by at most `0.001` (0.1
  percentage point);
- neither compared quantile is undefined; and
- every eligible weather year has at least one realization at both checkpoints.

If any condition fails, the status is `not demonstrated` with a machine-readable
reason. The thresholds and units are stored in the result provenance.

## 9. Durable job and API architecture

### 9.1 Structural isolation

Use a sibling `technoeconomic_jobs` table in the existing SQLite database rather
than encoding TEA as `jobs.mode = 'annual'` or overloading `baseline_id`.

Reasons:

- current model jobs permit only validation/annual modes;
- the current worker dispatch treats anything non-annual as validation;
- `baseline_id` triggers model-workbook comparison generation;
- baseline/manual completion can auto-promote;
- model promotion currently accepts any completed model job; and
- histories, current baselines, proposals, comparisons, and Solar Agent context are
  mode-oriented around validation/annual.

A separate table provides the primary structural isolation. The reserved `tea_` ID
namespace, model-job prefix rejection, dedicated route lookups, and explicit model
promotion/comparison guards complete the boundary; the table alone would not prevent
an accidental cross-table ID collision.

### 9.2 Proposed table contract

The table should contain:

```text
tea_job_id, state, request_json
source_annual_job_id
source_artifact_storage_key, source_artifact_sha256, source_artifact_bytes
source_snapshot_json, source_snapshot_sha256
submission_provenance_json, submission_provenance_sha256
result_json, result_provenance_json, artifacts_json
progress, stage, error, cancellation fields
worker_id, lease_token, heartbeat timestamps
created/queued/started/completed/updated timestamps
```

Database constraints/triggers should make these immutable after insertion:

- `request_json`;
- `source_annual_job_id`;
- source artifact identity, SHA-256, and byte count;
- `source_snapshot_json` and its SHA-256; and
- submission provenance JSON and its SHA-256, including analysis basis, capacity
  manifests, cost evidence, degradation, and any commercial-transfer attestation.

After a job becomes terminal, database triggers should prevent rewriting its result,
provenance, and artifact manifest. Retry should create a new job ID referencing the
same frozen request/snapshot, with lineage to the earlier attempt, rather than
mutating a completed record.

If the recommended source-retention decision is approved, `source_annual_job_id` is
a restrictive foreign key plus a friendly domain-level delete check, and the Annual
source points to an immutable content-addressed MIDC artifact whose bytes are verified
at TEA submission and remain available while referenced. The foreign key alone is
not a raw-byte retention mechanism. If TEA-owned copying is approved instead, the
source ID remains immutable historical text (never `ON DELETE SET NULL`) after Annual
deletion, and the TEA-owned verified blob/hash become the re-verification authority.

### 9.3 Lifecycle

The TEA lifecycle mirrors safe model-job concepts—queued, leased running work,
heartbeats, cooperative cancellation, fenced completion, interruption recovery,
retry, confined artifact cleanup—but uses dedicated store methods and explicit
worker dispatch.

The worker receives only the persisted request and source snapshot. It never reads
the live source Annual Simulation. TEA jobs share the application's overall
single-running-job/queue capacity policy unless later performance testing supports a
separate concurrency limit. Claiming must therefore be one atomic transaction across
both model and TEA tables: it checks for a running row in either table, selects the
oldest queued row across both, returns an explicit workflow discriminator, and counts
both tables when enforcing queue capacity. A second independent TEA claimer would
break the current one-job-at-a-time guarantee.

TEA identifiers use a reserved `tea_` prefix that model-job creation rejects. This
avoids ambiguous IDs across sibling tables at generic status or mutation boundaries.

Snapshot creation must also close the read/insert race. The server first verifies
the MIDC bytes and builds a candidate snapshot. Inside one write transaction it then
re-reads the Annual Simulation and every referenced calibration, review, and
promotion record, and inserts the TEA only if their canonical request, result,
provenance, and source hashes still match the candidate. Any change or deletion
returns a conflict and requires a fresh submission.

### 9.4 Proposed API surface

Exact paths can follow repository conventions, but the functional surface is:

```text
GET    eligible completed calibrated annual sources
POST   create TEA job (source ID + basis + n + seed + cost/finance/degradation/
       transfer specs)
GET    TEA job status/result
POST   cancel queued/running TEA job
POST   retry terminal retryable TEA job from frozen request/snapshot
DELETE delete TEA job and its confined artifacts
GET    CSV export
GET    XLSX export
```

No TEA endpoint promotes, compares, proposes, or changes current baselines. Calling
the existing model promotion route with a TEA ID must return not found; defensive
kind guards should also be added to model promotion/comparison code.

## 10. Outputs, exports, and immutable evidence

### 10.1 Result/API payload

The result includes:

- calculation-contract and sampling algorithm versions;
- realization count, seed, analysis basis, eligible years, both frozen Wdc values,
  and source-snapshot SHA-256;
- cost-stack completeness, evidence-class counts, commercial-transfer status, and
  exact common-cost cancellation audit;
- metric percentiles/CDF data and class probabilities;
- per-year summaries;
- sensitivity models and exclusions;
- convergence checkpoints/status; and
- safe public provenance and artifact URLs.

Large realization arrays should live in artifacts rather than inflate routine status
polls. The durable result contains summaries plus hashes/row counts for each export.

### 10.2 CSV

At minimum produce UTF-8 CSV files for:

- all realizations, including every sampled input, lifecycle and equivalent-annual
  subtotal, normalized/raw energy, explicitly signed metric, lifecycle energy class,
  and cost/energy tradeoff;
- input specifications and source citations;
- eligible/excluded energy rows, capacity manifests, and source lineage;
- cost-basis/design records, common-cost cancellation audit, and any commercial-
  transfer assumptions/mechanism checklist;
- percentiles/CDF points;
- per-year summaries;
- sensitivity steps; and
- convergence checkpoints.

If the product needs one-click CSV, package these into a ZIP; otherwise expose each
as a named download. This packaging choice does not change calculations.

### 10.3 XLSX

The workbook should contain equivalent sheets, a readable summary, formulas as
display aids where useful, and frozen numeric values as the authority. Suggested
sheets:

```text
Summary
Realizations
Input Specifications
Energy Snapshot
Capacity and Basis
Common-Cost Audit
Commercial Transfer
Metric CDFs
Per-Year Summary
Sensitivity
Convergence
Provenance
Checks
```

### 10.4 Integrity

Every artifact is written to an attempt-specific path, hashed with SHA-256, then
published only after the worker confirms it still owns the lease. The final immutable
manifest records filename, media type, bytes, SHA-256, row/sheet counts, and schema
version. Export checks tie all realization counts and headline statistics back to the
durable result.

## 11. Hand-calculated lifecycle golden example

This fixed-input example validates lifecycle discounting, CRF equivalence, Wdc
normalization, common-cost cancellation, degradation, sign convention, and edge
classes independently of random sampling. The costs, energies, and degradation rates
are synthetic test fixtures, not recommended defaults. The capacity uses the
currently inspected model manifest solely to exercise its exact denominator.

### 11.1 Inputs

```text
Project life L                       = 20 years
Real discount rate r                 = 5% = 0.05/year

Pdc_SOL = Pdc_SE = 240 * 579.92      = 139,180.8 Wdc

Solectria-only initial CAPEX         = $100,000
Solectria-only installation labor    = $20,000
SolarEdge-only initial CAPEX         = $130,000
SolarEdge-only installation labor    = $20,000
Shared initial CAPEX                 = $10,000
Shared installation labor            = $5,000

Solectria-only recurring labor       = $1,000/year
Solectria-only recurring O&M         = $2,000/year
Solectria-only recurring maintenance = $500/year
SolarEdge-only recurring labor       = $1,100/year
SolarEdge-only recurring O&M         = $2,100/year
SolarEdge-only recurring maintenance = $500/year
Shared recurring labor               = $200/year
Shared recurring O&M                 = $300/year
Shared recurring maintenance         = $100/year

Paired weather year                  = 2021
E_SOL,1                              = 200,000.0 kWh_AC
E_SE,1                               = 215,000.0 kWh_AC
g_SOL = g_SE                         = 0.005/year (one shared draw)
```

### 11.2 Annuity factor and CRF

```text
AF  = sum(t=1..20, 1/1.05^t)
    = 12.4622103425400

CRF = 1/AF
    = 0.0802425871907/year
```

For the required zero-rate branch, `r=0` gives `AF=20` and `CRF=0.05/year`.

### 11.3 Lifecycle costs and common-cost audit

```text
Initial_SOL   = 100,000 + 20,000 + 10,000 + 5,000 = $135,000
Recurring_SOL = 1,000 + 2,000 + 500 + 200 + 300 + 100
              = $4,100/year

Initial_SE    = 130,000 + 20,000 + 10,000 + 5,000 = $165,000
Recurring_SE  = 1,100 + 2,100 + 500 + 200 + 300 + 100
              = $4,300/year

PVCost_SOL = 135,000 + 4,100 * AF = $186,095.0624
PVCost_SE  = 165,000 + 4,300 * AF = $218,587.5045
DeltaPVCost_se_minus_sol           =  $32,492.4421
```

The shared lifecycle stream is present in both standalone costs:

```text
PVShared_SOL = PVShared_SE = 15,000 + 600 * AF
                             = $22,477.3262
DeltaPVShared_se_minus_sol   = exactly $0
```

The equivalent-annual tie-out preserves the original CRF requirement:

```text
EACost_SOL = CRF * 135,000 + 4,100 = $14,932.7493/year
EACost_SE  = CRF * 165,000 + 4,300 = $17,540.0269/year
DeltaEACost_se_minus_sol             =  $2,607.2776/year
```

### 11.4 Discounted lifecycle energy

Degradation starts after year one:

```text
F_shared = sum(t=1..20, 0.995^(t-1)/1.05^t) = 11.9829422525

PVEnergy_SOL = 200,000 * F_shared = 2,396,588.4505 kWh_AC
PVEnergy_SE  = 215,000 * F_shared = 2,576,332.5843 kWh_AC
DeltaPVEnergy_se_minus_sol        =   179,744.1338 kWh_AC

EAEnergy_SOL = CRF * PVEnergy_SOL = 192,308.4577 kWh_AC/year
EAEnergy_SE  = CRF * PVEnergy_SE  = 206,731.5920 kWh_AC/year
DeltaEAEnergy_se_minus_sol         =  14,423.1343 kWh_AC/year
```

### 11.5 LCOEs, normalized deltas, and all-in LCOO

```text
LifecycleLCOE_SOL = 186,095.0624 / 2,396,588.4505
                  = $0.0776499872/kWh_AC

LifecycleLCOE_SE  = 218,587.5045 / 2,576,332.5843
                  = $0.0848444435/kWh_AC

DeltaLifecycleCostPerWdc_se_minus_sol
    = 32,492.4421 / 139,180.8
    = $0.2334549167/Wdc

DeltaLifecycleEnergyPerWdc_se_minus_sol
    = 179,744.1338 / 139,180.8
    = 1.2914434591 kWh_AC/Wdc

AllInLCOO_se_minus_sol = 0.2334549167 / 1.2914434591
                       = 32,492.4421 / 179,744.1338
                       = 2,607.2776 / 14,423.1343
                       = $0.1807705285/kWh_AC
                       = $180.7705/MWh_AC
```

Equivalent-annual normalized deltas are `$0.0187330265/Wdc-year` and
`0.1036287644 kWh_AC/Wdc-year`; their ratio is identical.

### 11.6 Lifecycle zero and negative edge rows

Holding costs, Solectria energy, and degradation assumptions fixed:

```text
E_SE,1 = 200,000.0 kWh_AC:
DeltaPVEnergy is exactly zero before floating-point tolerance
class = zero_lifecycle_gain
AllInLCOO_se_minus_sol = null
reason = zero_lifecycle_delta_energy

E_SE,1 = 190,000.0 kWh_AC:
DeltaPVEnergy = -119,829.4225 kWh_AC
class = negative_lifecycle_gain
tradeoff = SolarEdge dominated (cost increase / energy loss)
signed AllInLCOO_se_minus_sol = -$0.2711557928/kWh_AC
```

The negative signed ratio is arithmetic evidence, not a favorable result; the
energy class and tradeoff class control interpretation.

### 11.7 Unequal-Wdc normalize-before-difference fixture

This compact synthetic fixture catches an implementation that subtracts raw project
totals before normalizing:

```text
Pdc_SOL = 100,000 Wdc       Pdc_SE = 200,000 Wdc
PVCost_SOL = $100,000       PVCost_SE = $180,000
PVEnergy_SOL = 1,000,000    PVEnergy_SE = 1,800,000 kWh_AC

raw DeltaPVCost = +$80,000
raw DeltaPVEnergy = +800,000 kWh_AC

PVCostIntensity_SOL = $1.00/Wdc
PVCostIntensity_SE  = $0.90/Wdc
DeltaLifecycleCostPerWdc_se_minus_sol = -$0.10/Wdc

PVEnergyIntensity_SOL = 10.0 kWh_AC/Wdc
PVEnergyIntensity_SE  =  9.0 kWh_AC/Wdc
DeltaLifecycleEnergyPerWdc_se_minus_sol = -1.0 kWh_AC/Wdc
```

The normalized signs are both negative despite positive raw-total deltas, proving
that scale and technology cannot be mixed. The signed ratio is `+$0.10/kWh_AC`, but
the tradeoff is lower cost/lower energy, not a positive-gain result.

For common-cost behavior at these capacities:

```text
$20,000 applied to each system -> $0.20/Wdc versus $0.10/Wdc
                               -> shared_non_cancelling, delta -$0.10/Wdc

$0.20/Wdc applied to each system -> $20,000 versus $40,000 raw totals
                                  -> common_cancelled, normalized delta exactly zero
```

### 11.8 Commercial-transfer fixture

This synthetic unit check exercises both transfer parameters:

```text
Y_SOL,1_solartac = 1.40 kWh_AC/Wdc-year
Y_SE,1_solartac  = 1.50 kWh_AC/Wdc-year
T_baseline       = 0.90
T_incremental    = 0.50

Y_SOL,1_commercial = 0.90 * 1.40 = 1.26 kWh_AC/Wdc-year
DeltaY_1_commercial = 0.50 * (1.50 - 1.40) = 0.05 kWh_AC/Wdc-year
Y_SE,1_commercial = 1.26 + 0.05 = 1.31 kWh_AC/Wdc-year
```

This fixture proves the absolute-baseline and incremental mechanisms remain
separate. A second test uses a negative source delta and rejects any supported factor
combination that could make either commercial absolute yield nonpositive.

### 11.9 Provisional commercial arithmetic illustration—not a default

The shared chat illustrates scale cancellation with a provisional commercial
**initial installed CAPEX** delta of `$0.035/Wdc`. If, solely for this arithmetic
illustration, that amount occurs at `t=0`, the recurring differential is zero, and
the hypothetical discounted lifecycle energy delta is `0.50 kWh_AC/Wdc`:

```text
$0.035/Wdc / 0.50 kWh_AC/Wdc = $0.070/kWh_AC
```

This division is correct, but neither input is an approved golden fixture or numeric
default. A runnable commercial case still needs the complete source-backed cost and
energy-transfer records defined above.

## 12. Approved decisions

The user approved all fifteen recommended choices on 2026-08-13. They are normative
for implementation; the alternatives remain below only as the decision record.

### 12.1 Revised calculation and scope decisions

1. **Lifecycle time basis and headline deltas — required.**

   - **Recommended:** approve Section 7: initial costs at `t=0`; recurring costs and
     energy at year-end; discounted PV cost/energy per Wdc as the primary deltas;
     equivalent-annual CRF values alongside; and their exact-ratio all-in LCOO.
   - Alternative: specify different timing or discount treatment. Dividing lifecycle
     cost by only the sampled first-year energy is no longer proposed.
   - Cliff's chat resolves the former numerator ambiguity: the proposed numerator is
     lifecycle SolarEdge-minus-Solectria cost, not total SolarEdge cost.
2. **Degradation model and dependence — required.**

   - **Recommended:** one source-backed shared module-degradation distribution in
     version 1 because both modeled systems use the same module; represent documented
     architecture-specific availability effects separately rather than silently
     assigning independent degradation.
   - Alternative: separate `g_SOL` and `g_SE`, but supply the desired correlation or
     pairing rule and evidence. Independent LHS draws are not assumed.
3. **Commercial cost representation and job granularity — required for commercial
   results.**

   - **Recommended:** one basis per durable job; commercial jobs use paired itemized
     Solectria/SolarEdge/shared per-Wdc cost stacks and a fully specified target
     design. Never combine an aggregate signed delta distribution with its component
     distributions.
   - Alternative: allow an aggregate signed commercial-delta-only mode. It can
     support marginal cost/LCOO but cannot produce the requested standalone LCOEs.
4. **Cost-stack completeness and standalone LCOEs — required.**

   - **Recommended:** require `full_system` costs, including sampled paired streams,
     for production TEA so both standalone LCOEs and marginal LCOO are available.
     Only streams validated as `common_cancelled` cancel exactly; paired
     `shared_non_cancelling` streams remain visible in both LCOEs and in the marginal
     delta, which is essential when capacities or quantities differ.
   - Alternative: permit a visibly labeled `differential_only` job with standalone
     LCOEs unavailable. Cliff's provisional cost estimates currently support only
     this narrower scope.
5. **Commercial energy transfer — required for commercial LCOE/LCOO.**

   - **Recommended:** implement the fail-closed transfer gate and the explicit
     baseline-plus-incremental parameterization in Section 7.6. A commercial job
     without an approved transfer/representative source returns cost and
     `DeltaLifecycleCostPerWdc_se_minus_sol` only. Require `T_baseline > 0` and
     `T_incremental >= 0`; sign reversal requires a
     direct representative energy specification rather than a negative multiplier.
   - Alternative: version 1 exposes only SolarTAC energy/LCOE/LCOO and commercial
     cost distributions until a representative commercial energy model exists.
   - Alternative: permit signed transfer factors; this needs explicit UI warnings and
     additional energy-sign semantics.
6. **Recurring expected maintenance versus discrete lifecycle events.**

   - **Recommended:** version 1 uses level real recurring labor/O&M/maintenance;
     expected replacements/truck rolls may be included only through a documented
     annual derivation. Do not add discrete event/failure schedules yet.
   - Alternative: add event year, replacement quantities, and failure/replacement
     sampling now, which materially expands the calculation and UI.
7. **Equipment-loading discrepancy and authoritative design record — required before
   SolarTAC-derived commercial defaults.**

   - **Recommended:** use the fingerprint-verified model capacity manifest for
     SolarTAC energy normalization, label the chat's 244-module/200-kW/330-kW values
     provisional, and never inherit either description into a commercial design.
     SolarTAC-derived commercial loading fields remain blank until the as-built BOM,
     one-line, and model discrepancy are reconciled; a separately evidenced
     commercial target design may proceed independently.
   - Alternative: provide and approve the authoritative module counts/ratings and
     both inverter nameplates now, with supporting records.
8. **Legacy Annual capacity reconstruction.**

   - **Recommended:** allow reconstruction only when the stored full calibration-
     physics fingerprint exactly matches the current capacity manifest, then freeze
     the explicit manifest in TEA provenance.
   - Alternative: only newly rerun Annual Simulations containing an explicit capacity
     manifest are eligible.
9. **Non-positive lifecycle-energy policy — required.**

   - **Recommended:** approve Section 7.7's deterministic near-zero tolerance;
     retain signed LCOO for negative nonzero rows, null only at zero, classify every
     cost/energy tradeoff, and calculate headline LCOO CDF/Pxx conditional on
     positive lifecycle gain.
   - Alternative: leave LCOO null for every non-positive-energy row while preserving
     all rows and classifications.
10. **Stepwise rank-regression rule — required.**

    - **Recommended:** approve Section 8.3's deterministic convention: average ranks,
      standardized ranks, greedy maximum incremental ordinary R-squared, `1e-6`
      threshold, stable-ID ties, and delta R-squared plus standardized beta.
    - Alternative: supply Cliff/Ho code or a required p-value/AIC/BIC entry/removal
      rule. Ho's cited paper does not specify this exact rule.

### 12.2 Carried-forward architecture and guardrail decisions

11. **Eligible Annual-source scope.**

    - **Recommended:** any explicitly selected completed calibrated Annual Simulation
      that passes the strict validator, including an eligible Solar Agent candidate.
    - Alternative: only manual jobs or only the promoted annual baseline.
12. **Source retention after snapshot.**

    - **Recommended:** prevent deletion of a referenced Annual Simulation while a TEA
      job exists **and** require its MIDC source to be an immutable content-addressed
      Annual-owned artifact whose bytes still verify against the frozen hash. A
      restrictive foreign key alone protects only the database row, not source bytes.
    - Alternative: copy verified raw source bytes into TEA-owned content-addressed
      storage at snapshot time, then allow Annual deletion under a clear policy.
    - Alternative: preserve metadata/hash only; this reproduces calculations from the
      frozen paired rows but cannot promise later raw-source re-verification.
13. **Project life and realization guardrails.**

    - **Recommended:** fixed integer project life in version 1; probabilistic discount
      rate; server-enforced `1 <= n <= 100,000`; UI default `10,000`.
    - Alternative: specify probabilistic integer life or different `n` bounds/default.
14. **Evidence sufficiency for runnable jobs.**

    - **Recommended:** allow `engineering_judgment` and `secondary_synthesis` inputs
      only after explicit per-line user acceptance, immutable rationale, and a
      prominent `provisional_inputs` result status. They remain excluded from numeric
      defaults and procurement-grade claims.
    - Alternative: make these evidence classes citation-only and require project,
      primary, or independently verified public evidence for every runnable value.
15. **Sampling and published-statistics conventions.**

    - **Recommended:** approve the balanced categorical weather sampler, type-7
      quantiles, sensitivity minimum `max(20, 2p+2)`, checkpoint/tolerance rules in
      Section 8, and the exact `tea-lhs-v1` PCG64DXSM/seed/substream/permutation
      contract in Section 6.
    - Alternative: specify another quantile, categorical allocation, minimum-sample,
      convergence, or PRNG/substream convention now.

The user's instruction resolves one prior issue without another decision: Cliff's
chat and prior workbook may provide blank citation templates and provisional rationale
only. Their numeric values, Beta-PERT parameters, and engineering ranges are not
primary-source defaults and never prepopulate a runnable job.

These approvals unblock the calculation contract. Decision 7 still bars numeric
SolarTAC-derived commercial design defaults until the discrepancy is reconciled, but
an independently sourced commercial design may proceed without inheriting either
disputed SolarTAC description.

## 13. Affected-file map

This is the expected map, not a promise that every listed file must change.

### New focused backend modules

| Proposed file                              | Responsibility                                                                                                                                                                          |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sbepv/technoeconomic.py`            | Distribution validation/inverse CDFs, seeded LHS, Wdc normalization, lifecycle/CRF calculations, basis/transfer rules, ECDF/quantiles, per-year summaries, rank regression, convergence |
| `src/sbepv/technoeconomic_reporting.py`  | CDF/diagnostic figures, CSV tables, XLSX workbook, integrity manifest and export tie-outs                                                                                               |
| `src/sbepv/api/technoeconomic.py`        | Source verification/snapshot construction, TEA route helpers and public result shaping                                                                                                  |
| `src/sbepv/worker/run_technoeconomic.py` | Lease-fenced execution, progress, cancellation, artifact generation and completion                                                                                                      |

### Existing backend files

| File                                  | Expected change                                                                                                                     |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `src/sbepv/store.py`                | Schema v5 sibling TEA table, immutability triggers, dedicated lifecycle/lease/cancel/retry/delete queries                           |
| `src/sbepv/model.py`                | Add a separately versioned explicit capacity-manifest helper without silently changing the existing calibration-physics fingerprint |
| `src/sbepv/worker/run_annual.py`    | Persist/expose explicit per-system Wdc manifest with future Annual results and provenance                                           |
| `src/sbepv/api/schemas.py`          | Strict basis, distribution, cost/evidence, finance, degradation, commercial-transfer, and TEA submission schemas                    |
| `src/sbepv/api/main.py`             | Mount TEA endpoints and defensive model promotion/comparison isolation guards                                                       |
| `src/sbepv/api/job_store.py`        | Audit/gate generic model job lookup, cancellation, and retry helpers; retain the single shared`_JobCancelled` type                |
| `src/sbepv/api/state.py`            | TEA worker/orchestration state if not shared through the current loop                                                               |
| `src/sbepv/worker/loop.py`          | Explicit safe dispatch/claim coordination or dedicated sibling runner startup                                                       |
| `src/sbepv/worker/completion.py`    | Defensive assertion that model completion/comparison/promotion accepts model jobs only                                              |
| `src/sbepv/api/artifacts.py`        | Confined TEA paths, publication and cleanup                                                                                         |
| `src/sbepv/api/serializers.py`      | Safe TEA public projection; keep private source audit/path data private                                                             |
| `src/sbepv/api/config.py`           | Only if TEA limits/defaults need environment-backed configuration                                                                   |
| `src/sbepv/api/baselines.py`        | Prefer reusable read-only verification helper; do not inherit annual-scenario substitution rejection                                |
| `README.md`, `frontend/README.md` | Document the durable TEA workflow, canonical frontend responsibilities, analysis bases, and verification commands                   |
| `requirements.txt`                  | Only if the reviewed implementation truly needs a new statistics dependency; NumPy/openpyxl/matplotlib already exist                |
| `lib/render-proxy.ts`               | Allow only the dedicated TEA API paths through the Vinext/Render proxy                                                              |

### Canonical frontend sources

| File/group                                                                                   | Expected change                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/html/50-technoeconomic.html`                                                     | Replace deterministic UI with source/basis picker, itemized cost/evidence editor, Wdc/design and transfer disclosures, lifecycle controls, job progress, results, diagnostics and downloads |
| `frontend/js/06-technoeconomic.js`                                                         | Replace browser calculation with strict form serialization, API lifecycle, result rendering, plots/tables and export links                                                                  |
| `frontend/css/04-technoeconomic.css`                                                       | Replace/adapt TEA layout, responsive tables/cards, state and chart styles                                                                                                                   |
| `frontend/js/00-help-tips-and-elements.js`                                                 | New TEA DOM bindings                                                                                                                                                                        |
| `frontend/js/03-form-reading-and-plots.js`                                                 | New TEA form/state and Solar Agent safe context                                                                                                                                             |
| `frontend/js/08-dashboard-state.js`                                                        | Persist draft inputs/source selection only, never authoritative results                                                                                                                     |
| `frontend/js/10-annual-run.js`                                                             | Replace immediate deterministic listeners with TEA source/run wiring                                                                                                                        |
| `frontend/js/19-chat-send-and-cache.js`                                                    | Restore versioned TEA draft state safely                                                                                                                                                    |
| `frontend/js/07-annual-results.js`                                                         | Refresh TEA source eligibility after annual completion, not calculate TEA                                                                                                                   |
| `frontend/js/13-chat-message-rendering.js`, `14-agent-state.js`, `18-agent-actions.js` | Update TEA prompts/status/reset integration while leaving Solar Agent action mode annual/validation only                                                                                    |
| `frontend/js/16-proposal-and-job-cards.js`, `20-saved-results.js`                        | Audit model-only promotion/delete/history/saved-result UI paths and add explicit TEA isolation guards only if needed                                                                        |
| `frontend/css/03-workspace-and-header.css`, `13-agent-drawer-base.css`                   | Responsive/support selectors as required                                                                                                                                                    |
| `frontend/html/20-header-and-tabs.html`                                                    | Help copy only; tab mechanics can remain                                                                                                                                                    |

No generated dashboard HTML will be edited. `frontend/` remains the only source of
truth and both Python/Vite assemblers must remain equivalent.

### Tests

| Proposed/existing test                       | Coverage                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| new`tests/test_technoeconomic.py`          | Four distributions, pinned LHS/seed and balanced categorical weather, lifecycle discounting/CRF equivalence, Wdc/kWdc 1,000x conversion, unequal-Wdc normalize-before-difference, sign/tolerance/tradeoff matrix, cancelling/non-cancelling paired streams, overlap rejection, golden formulas, transfer positivity/gating, ECDF/quantiles, per-year zero allocations, sensitivity, convergence |
| new`tests/test_technoeconomic_api.py`      | Source/capacity/raw-byte eligibility and tamper rejection, exact-fingerprint legacy path, basis-mixing and cost-overlap rejection, provisional evidence/default gating, transfer support/positivity attestations, snapshot hashes, lifecycle/status/cancel/retry/delete/export, safe serialization, promotion/comparison rejection                                                              |
| new`tests/test_technoeconomic_worker.py`   | Lease fencing, cancellation, interruption/retry, frozen-source use, terminal immutability, artifact publication/cleanup                                                                                                                                                                                                                                                                         |
| new`tests/test_technoeconomic_exports.py`  | CSV/XLSX schemas, lifecycle/raw/normalized tie-outs, capacity/basis/transfer provenance, common-cancellation audit, row/count/stat/hash tie-outs, zero/negative retention, workbook formats                                                                                                                                                                                                     |
| new`tests/test_technoeconomic_frontend.py` | Source/basis picker, evidence and distribution editor, Wdc/design/transfer warnings, lifecycle validation, job polling, explicit SE-minus-SOL rendering, tradeoff classifications, downloads, draft restore, accessibility/responsiveness                                                                                                                                                       |
| `tests/test_model_runtime.py`              | Exact per-system capacity-manifest values, topology multiplication, and independent denominators                                                                                                                                                                                                                                                                                                |
| `tests/test_agent_store.py`                | Schema migration, constraints/triggers, queue coordination and isolation                                                                                                                                                                                                                                                                                                                        |
| `tests/test_annual_simulation.py`          | Paired-row/source-provenance contract and regression safety                                                                                                                                                                                                                                                                                                                                     |
| `tests/test_agent_backend.py`              | No TEA promotion/proposal/comparison/history contamination                                                                                                                                                                                                                                                                                                                                      |
| `tests/test_annual_calibration_ui.py`      | Remove deterministic assertions; preserve annual source-coverage UI contract                                                                                                                                                                                                                                                                                                                    |
| `tests/test_saved_results_frontend.py`     | Proxy allowlist and model-saved-result isolation regression coverage                                                                                                                                                                                                                                                                                                                            |
| `tests/test_dashboard_build.py`            | Python canonical assembly contract                                                                                                                                                                                                                                                                                                                                                              |
| `tests/test_project_layout.py`             | Module qualification/shadowing/source-layout invariants                                                                                                                                                                                                                                                                                                                                         |

## 14. Phased implementation checklist

### Phase 0 — contract and architecture (this phase)

- [X] Read `AGENTS.md` and canonical frontend build guidance.
- [X] Inspect Annual Simulation validation, paired energy rows, source audit,
  calibration provenance, durable jobs, worker, promotion/comparison boundaries,
  and tests.
- [X] Inspect deterministic TEA frontend, state, formulas, and tests.
- [X] Locate and assess local Cliff/Ho material and the prior probabilistic workbook.
- [X] Review Cliff's shared chat and classify its estimates as secondary/provisional.
- [X] Reconcile lifecycle discounting, SE-minus-SOL signs, Wdc normalization, isolated
  SolarTAC/commercial bases, common-cost cancellation, and commercial transferability.
- [X] Write the proposed calculation contract and hand-calculated golden example.
- [X] Map affected files, phases, tests, and genuine decisions.
- [X] Receive user approval and decisions before production implementation.

### Phase 1 — pure calculation kernel and contract tests

- [X] Freeze approved contract/schema versions.
- [X] Implement distribution validation and inverse CDFs.
- [X] Implement seeded/versioned LHS and balanced paired-year sampling.
- [X] Implement capacity validation, basis isolation, lifecycle PV/CRF equivalence,
  degradation/transfer rules, exact common-cost audit, explicitly signed LCOEs,
  deltas, LCOO, and tradeoff classification.
- [X] Implement ECDF/P5/P50/P95, per-year summaries, sensitivity, convergence.
- [X] Add golden, seed reproducibility, invariance, degenerate/edge, and statistical
  contract tests.
- [X] Run the focused calculation test file and report results for approval.

### Phase 2 — durable persistence and immutable source snapshot

- [X] Add schema-v5 sibling TEA job table and migration tests.
- [X] Add source eligibility verification and canonical snapshot/hash construction.
- [X] Freeze per-system Wdc manifests, cost/design basis, evidence, degradation, and
  any commercial-transfer declaration atomically with the source snapshot.
- [X] Add immutability triggers and terminal write protection.
- [X] Add create/read/claim/heartbeat/cancel/interruption/retry/delete methods.
- [X] Make global capacity and oldest-first claiming atomic across model and TEA
  tables; reserve the `tea_` identifier namespace.
- [X] Prove TEA IDs cannot enter current baselines, promotions, proposals,
  comparisons, saved model results, or Solar Agent model history.
- [X] Run persistence/source tests and report results for approval.

### Phase 3 — API and worker

- [X] Add strict request schemas and eligible-source endpoint.
- [X] Add create/status/cancel/retry/delete endpoints and safe serialization.
- [X] Add explicitly dispatched TEA worker with progress and cancellation checks.
- [X] Consume only the frozen source snapshot.
- [X] Add lease-loss, cancellation, restart/interruption, tamper, queue-capacity, and
  API error tests.
- [X] Run focused API/worker tests and report results for approval.

### Phase 4 — artifacts, CDF plots, and exports

- [X] Generate result CDF and sensitivity/convergence plots with the non-GUI backend.
- [X] Generate complete CSV set and XLSX workbook.
- [X] Hash and publish artifacts only after lease ownership verification.
- [X] Add export tie-outs, safe filenames, cleanup, cancellation and tamper tests.
- [X] Visually inspect plots/workbook and report results for approval.

### Phase 5 — canonical frontend replacement

- [X] Replace only canonical `frontend/` TEA sources and necessary shared partials.
- [X] Build accessible source selection, distribution/citation editing, n/seed
  controls, basis/Wdc/design and transfer disclosures, lifecycle assumptions,
  submission/confirmation, durable progress/cancel/retry, summaries, CDFs, per-year
  table, sensitivity, convergence, tradeoff classifications and downloads.
- [X] Keep draft form state local but all job results server-authoritative.
- [X] Keep Solar Agent action modes and model promotion/comparison separate.
- [X] Add Node/assembled-dashboard frontend tests and responsive/accessibility checks.
- [X] Run focused frontend tests and `npm run build`; visually inspect the dashboard;
  report results for approval.

### Phase 6 — integration and full verification

- [X] Run all focused TEA suites together.
- [X] Run `python -m unittest discover -v` from repository root.
- [X] Run `npm run build`.
- [X] Recheck project-layout invariants, clean source/output boundaries, immutable
  provenance, API safety, and unrelated workspace changes.
- [X] Report exact test/build counts and any remaining caveats.

## 15. Version 2 addendum — SolarTAC applied-capacity normalization

Contract `tea-calculation-v2` changes only the `solartac_site` normalization
denominator. It does not add commercial target scaling or a marginal-cost workflow.
Commercial-representative requests remain on `tea-calculation-v1`.

For each frozen Annual source, the applied capacity is selected deterministically:

```text
if curtailment_enabled is true and curtailment_limit_kw is finite and positive:
    P_applied_SOL = P_applied_SE = 1,000 * curtailment_limit_kw
    rating_basis = ac_operating_limit
else:
    P_applied_system = installed_wdc_system
    rating_basis = dc_installed_nameplate
```

Version 2 divides each SolarTAC system's source energy and entered project-total
cost by its own `P_applied_system` before differencing. Authoritative intensity
units are therefore `kWh_AC/applied_W-year`, `USD/applied_W`, and
`USD/applied_W-year`. Lifecycle LCOE and LCOO remain `USD/kWh_AC`; their formulas,
discounting, degradation, sign convention, sampling, and classification semantics
are otherwise unchanged.

The immutable receipt records `applied_capacity_w`, `rating_basis`, selection
method, and source field for both systems. Installed module DC-STC capacities remain
separately preserved as physics/nameplate evidence and are never relabeled as AC
operating limits.

Literal version-1 requests, results, exports, and kernel-request hashes retain their
historical field shapes and Wdc semantics. Version-2 routine results, manifests,
tabular bundles, and workbook exports use distinct schema versions and explicit
`per_applied_W` field names so the two authorities cannot be silently mixed. The
unchanged PNG rendering contract and XLSX logical-row hash algorithm retain their
algorithm-version identifiers.
