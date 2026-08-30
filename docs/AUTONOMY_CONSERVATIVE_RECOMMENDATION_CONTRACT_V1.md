# Autonomy Conservative Recommendation Contract

## Product contract metadata

- Status: **Approved**
- Contract version: **1.0**
- Contract identifier: **`autonomy-conservative-dominance-v1`**
- Approved direction date: **2026-08-30**
- Preserved in repository: **2026-08-30**
- Authority: deterministic recommendation, confidence, warning, and reversal
  classification for complete Autonomy comparison bundles
- Semantic policy SHA-256:
  **`b5eed8f630cdeb934b1cf5292077be19cf16f14771d4a596975c59c4b614041a`**
- Canonicalization: UTF-8 canonical JSON with sorted keys, compact separators,
  ASCII escaping, finite values only, hashed with SHA-256
- Machine authority:
  `sbepv.autonomy.recommendation.recommendation_contract_payload()`
- Calculation authority: the lifecycle outcome classes and their probabilities
  remain governed by `TECHNOECONOMIC_CALCULATION_CONTRACT.md`; this addendum does
  not change the TEA kernel, tolerances, sampling, populations, or numerical gate
- Product authority: this addendum narrows the recommendation language in
  `HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md` and
  `UNIFIED_AUTONOMY_TEA_PRODUCT_CONTRACT_V1.md`; if prose elsewhere suggests an
  agent may choose a winner or confidence, this deterministic contract controls

## 1. Purpose and authority boundary

This contract authorizes version-1 recommendation classification after the
Decision Brief comparison foundation. It replaces
`classification_pending_contract` only when one exact immutable comparison bundle
passes every gate below. Historical schema-v8 comparison bundles and unsigned brief
revisions remain immutable and are never rewritten. A historical bundle that lacks
the durable-result projection commitment remains readable but cannot receive an
available version-1 recommendation; migration never synthesizes or backfills that
authority. If a historical bundle already carries every current binding, an omitted
structural classification may be re-derived exactly from its frozen baseline and
alternative requests using the original deterministic scenario-comparison contract.
The live recommendation is stored as a new immutable record bound to the exact
bundle and policy identity.

The classifier is a pure deterministic service. It does not call an agent, read
mutable case state, query a database, read an artifact, recompute a TEA realization,
derive a sign from a rounded percentile, or choose a favorable attempt. The
Decision Agent may explain a stored recommendation but may not classify, activate,
acknowledge, sign, defer, accept, reject, report, or access signed-result payloads.

## 2. Exact input authority

Classification uses only a stored comparison bundle whose canonical SHA-256 is
recomputed and matches both the embedded and expected stored identity. The bundle
must be complete and compatible, and must contain every scenario selected by the
immutable grouped confirmation receipt in its confirmed order. Membership is exact,
scenario revision identifiers are unique, scenario ordinals are contiguous, and a
reordered or omitted scenario is a hard failure even if the bundle's self-reported
completeness counts were resealed.

For every selected scenario:

1. attempt numbers are the contiguous sequence `1..n`, the first attempt has no
   parent, each retry names the immediately preceding job, and only attempt `n` is
   selected, `done`, and reverified;
2. every earlier, failed, cancelled, interrupted, or retried attempt remains in the
   attempt history and proof set;
3. the canonical frozen request digest matches the scenario, every attempt proof,
   and result provenance; source and full-result identities match the same selected
   durable attempt;
4. the evidence-set digest is recomputed from the sorted immutable receipt identity
   tuples `(request_path, evidence_receipt_id, receipt_sha256, content_sha256)`;
5. the reporting tie-out digest is recomputed from the exact export-manifest digest
   and tie-out object, whose failed-check list is empty and whose check count and
   projected verification rows agree;
6. the selected proof carries an
   `autonomy-result-projection-commitment-v1` SHA-256 over the full projected result
   and selected durable-result digest. At store admission, the comparison verifier
   independently compares the winner-driving projected tradeoff population with
   the immutable full durable result row before accepting that commitment;
7. the durable result says energy is available;
8. the evidence set has no missing required receipt or unresolved gap; and
9. the durable TEA tradeoff population ties its complete class counts and
   probabilities to one positive denominator.

A missing scenario, substituted retry, unfavorable result, partial result,
verification failure, changed identity, missing required evidence, failed reporting
tie-out, unresolved result incompatibility, or hard convergence failure makes the
recommendation unavailable. It is never downgraded to provisional.

## 3. Authoritative lifecycle outcome classes

The classifier consumes the TEA calculation contract's durable
`tradeoff_classes.probabilities` exactly. Those probabilities were already assigned
from per-realization lifecycle cost and energy values using the TEA kernel's
tolerance-derived classes. The classifier must not inspect a percentile sign or
recreate the class from displayed values.

SolarEdge directional probability is exactly the sum of:

- `cost_neutral_energy_gain`; and
- `cost_saving_energy_gain`.

Solectria directional probability is exactly:

- `cost_increase_energy_loss`.

No other class contributes to either directional probability. In particular, the
classifier does not convert either of these unapproved-hurdle tradeoffs into a
winner:

- `cost_increase_energy_gain`; or
- `cost_saving_energy_loss`.

For explanation only, a scenario is described as primarily dependent on an
unapproved cost/energy hurdle when the sum of those two tradeoff probabilities is
strictly greater than each directional probability. This explanatory plurality
does not change the winner rule.

## 4. Directional winner and no-winner policy

Let `P_SE,s` and `P_SOL,s` be the exact directional probabilities above for selected
scenario `s`.

SolarEdge is the directional winner only when:

```text
P_SE,s >= 0.90 for every selected complete scenario s
```

Solectria is the directional winner only when:

```text
P_SOL,s >= 0.90 for every selected complete scenario s
```

The comparison returns `no_decisive_winner` when neither direction satisfies its
rule in every selected scenario, when selected scenarios reach the threshold in
opposite directions, or when the evidence is chiefly a cost/energy tradeoff that
would require an unapproved willingness-to-pay, LCOE, LCOO, or other hurdle.

Threshold comparisons use the stored finite binary64 probabilities directly.
There is no rounding before comparison: `0.899999` fails and `0.90` passes.

For `no_decisive_winner`, confidence is exactly `not_applicable`. The record shows
every scenario's denominator, complete tradeoff probability map, both directional
probabilities, tradeoff probability, and exact reason. It must not invent a
confidence label.

## 5. Confidence policy

Confidence applies only after one direction reaches `0.90` in every selected
scenario and all hard gates pass.

- `strong`: the same directional probability is at least `0.95` in every selected
  scenario; all result, provenance, reporting, evidence, compatibility, and stable
  convergence gates pass; and no permitted evidence or convergence warning remains.
- `mixed`: the same direction is at least `0.90` in every selected scenario, at
  least one selected scenario is below `0.95`, and no permitted evidence or
  convergence warning remains.
- `provisional`: the same direction is at least `0.90` in every selected scenario
  and core verification passes, but one or more explicitly permitted warnings in
  Section 6 remain.

Again, `0.949999` is mixed and `0.95` satisfies the strong threshold. A provisional
record lists every warning separately. Sign-off requires an explicit additional
acknowledgement of every recorded warning; a blanket hidden acknowledgement is not
sufficient.

## 6. Evidence and convergence gates

### 6.1 Evidence

- `documented_inputs` with no gaps passes.
- `provisional_inputs` with no gaps is an explicitly permitted evidence warning and
  makes a directional recommendation provisional.
- A missing or unknown evidence status, changed evidence-set identity, unaccepted or
  missing required evidence, or any recorded evidence gap is a hard failure.

Provisional evidence remains visible by scenario and retains its accepted receipt
and immutable content identity. The warning cannot be removed by agent prose.

### 6.2 Convergence

The existing TEA result has two valid convergence states:

- `stable` with no reasons passes; and
- `not_demonstrated` with at least one machine-readable reason is an explicitly
  permitted convergence warning and makes a directional recommendation provisional.

A missing, unknown, contradictory, invalid, or explicit failed convergence state is
a hard failure. The classifier does not reinterpret the convergence checkpoints or
weaken their thresholds.

### 6.3 Other result warnings

Sensitivity warnings and structural-comparison limitations remain visible but do
not by themselves change the confidence label. They cannot erase an evidence or
convergence warning. Reporting tie-out, numerical provenance, verification, and
compatibility failures are always hard failures.

## 7. Structural comparisons

A selected structural scenario uses the same probability policy and participates in
the every-scenario thresholds. Its result is never omitted because structure
changed. The recommendation record also retains the existing warning:

```text
structural_comparison_causal_attribution_limited
```

This warning means baseline-relative causal attribution is limited; it does not
change the already calculated directional probabilities. Because the frozen
scenario contract marks this limitation as acknowledgement-required, sign-off
must include the exact server-issued acknowledgement identity even when the
directional confidence is otherwise `strong`.

## 8. Reversal conditions and controlled follow-up

A reversal condition may be recorded only from:

1. a completed selected scenario comparison whose stored probabilities demonstrate
   a different direction; or
2. a reverified sensitivity model whose status is `available`, whose sample count
   meets its recorded minimum, and whose deterministic step is structurally valid.

A sensitivity row is only a candidate for a controlled follow-up test. It does not
claim the input will reverse the decision. Every such row stores
`break_even_threshold = null` and `threshold_status = not_calculated` unless a later
completed calculation supplies an approved threshold.

Any new test returns the user to Investigation / Compare scenarios with a
`create_controlled_scenario_draft` action tied to the source scenario and predictor.
The Decision Brief action has `mutates_from_brief = false` and `executes = false`.
It cannot alter a confirmed request or queue a TEA job.

Unavailable or malformed sensitivity output produces no reversal claim. Agent
interpretation, a rounded percentile, or an unsimulated break-even value is never a
reversal source.

## 9. Immutable recommendation output

Every available or unavailable classification record stores at least:

- recommendation schema version;
- state and eligibility;
- classification and confidence;
- recommendation contract version and semantic SHA-256;
- exact comparison-bundle SHA-256;
- classification-input SHA-256;
- exact per-scenario probabilities and denominators;
- blockers, reasons, evidence/convergence warnings, and required acknowledgements;
- structural/model limitations and evidence gaps;
- validated major drivers and reversal conditions; and
- a deterministic plain-language conditional statement.

The exact contract version and digest must flow unchanged into every subsequent
brief overlay, sign-off snapshot, and report snapshot. A changed bundle, policy
digest, classification, confidence, warning set, or acknowledgement set creates a
new immutable record; it never mutates an existing brief or signed snapshot.

## 10. Acceptance matrix

Contract tests must cover, at minimum:

- `0.899999`, `0.90`, `0.949999`, and `0.95` for both directions;
- every selected scenario participating, including unfavorable results and retry
  history;
- exact confirmation membership and order, contiguous retry ancestry, final-attempt
  selection, canonical request binding, and complete proof coverage;
- evidence-receipt and reporting-manifest/tie-out digest recomputation;
- rejection of a resealed projected tradeoff population that differs from the
  immutable full durable result;
- cross-scenario directional conflict;
- unapproved-hurdle tradeoffs and no-winner confidence;
- provisional and missing evidence;
- stable, not-demonstrated, and hard-failed convergence;
- verification, provenance, reporting tie-out, compatibility, and bundle-hash
  failures;
- malformed class denominators, counts, probabilities, and population tie-outs;
- structural warnings without probability-policy exceptions, including exact
  acknowledgement enforcement before sign-off; and
- completed-scenario and validated-sensitivity reversal sources with no fabricated
  break-even threshold or direct execution.
