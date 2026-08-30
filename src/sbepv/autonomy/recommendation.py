"""Pure conservative recommendation classification for immutable Autonomy bundles.

The Decision Agent has no role in this module.  The classifier consumes only one
canonical, hash-verified comparison bundle and the durable TEA outcome-class
probabilities already projected into that bundle.  It never recalculates a cost or
energy sign from rounded summaries, reads mutable case state, performs I/O, or
creates a scenario.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import math
import re
import secrets
from typing import Any

from sbepv import technoeconomic as technoeconomic_kernel
from sbepv.autonomy import comparison as autonomy_comparison


RECOMMENDATION_SCHEMA_VERSION = "autonomy-recommendation-v1"
RECOMMENDATION_CONTRACT_VERSION = "autonomy-conservative-dominance-v1"
WINNER_PROBABILITY_THRESHOLD = 0.90
STRONG_PROBABILITY_THRESHOLD = 0.95

SOLAREDGE_DOMINANT_CLASSES = (
    "cost_neutral_energy_gain",
    "cost_saving_energy_gain",
)
SOLECTRIA_DOMINANT_CLASSES = ("cost_increase_energy_loss",)
UNAPPROVED_HURDLE_TRADEOFF_CLASSES = (
    "cost_increase_energy_gain",
    "cost_saving_energy_loss",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SELECTION_STATES = frozenset({"solaredge", "solectria", "none"})
_COMPARISON_CLASSIFICATIONS = frozenset(
    {"baseline", "controlled", "structural"}
)
_DURABLE_ATTEMPT_STATES = frozenset(
    {"queued", "running", "done", "error", "cancelled", "interrupted"}
)


class RecommendationContractError(ValueError):
    """Raised when a purported immutable comparison identity is not trustworthy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecommendationContractError(
            "recommendation_value_not_canonical",
            "Recommendation inputs must be finite canonical JSON.",
        ) from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def recommendation_contract_payload() -> dict[str, Any]:
    """Return the exact semantic payload whose SHA-256 identifies policy v1."""

    return {
        "version": RECOMMENDATION_CONTRACT_VERSION,
        "inputs": {
            "comparison_bundle_schema": (
                autonomy_comparison.COMPARISON_BUNDLE_SCHEMA_VERSION
            ),
            "require_complete": True,
            "require_hash_verified": True,
            "require_all_selected_attempts_reverified_done": True,
            "require_compatible_results": True,
            "confirmation_membership_and_order": "exact",
            "retry_history": "contiguous_chain_with_final_attempt_selected",
            "request_binding": "canonical_request_sha256",
            "evidence_binding": "canonical_verified_receipt_identity_set",
            "reporting_binding": "manifest_and_tie_out_payload_sha256",
            "result_projection_binding": (
                autonomy_comparison.RESULT_PROJECTION_COMMITMENT_VERSION
            ),
            "probability_authority": (
                "durable_result_bound_tolerance_derived_tradeoff_classes"
            ),
            "historical_missing_comparison_classification": (
                "derive_from_frozen_requests_or_fail"
            ),
        },
        "directional_evidence": {
            "solaredge_classes": list(SOLAREDGE_DOMINANT_CLASSES),
            "solectria_classes": list(SOLECTRIA_DOMINANT_CLASSES),
            "unapproved_hurdle_tradeoff_classes": list(
                UNAPPROVED_HURDLE_TRADEOFF_CLASSES
            ),
            "winner_threshold_in_every_selected_scenario": (
                WINNER_PROBABILITY_THRESHOLD
            ),
        },
        "no_decisive_winner": {
            "confidence": "not_applicable",
            "when_neither_direction_meets_threshold_in_every_scenario": True,
            "when_selected_scenarios_imply_opposite_directions": True,
            "never_resolve_tradeoff_without_approved_hurdle": True,
        },
        "confidence": {
            "strong_threshold_in_every_selected_scenario": (
                STRONG_PROBABILITY_THRESHOLD
            ),
            "mixed": "winner_threshold_met_and_any_below_strong",
            "provisional": (
                "winner_threshold_met_with_permitted_evidence_or_"
                "convergence_warning"
            ),
        },
        "gates": {
            "evidence": {
                "documented_inputs": "pass",
                "provisional_inputs": "permitted_warning",
                "missing_unknown_or_gaps": "hard_failure",
            },
            "convergence": {
                "stable": "pass",
                "not_demonstrated_with_reasons": "permitted_warning",
                "missing_unknown_or_failed": "hard_failure",
            },
            "verification_failure": "hard_failure",
            "reporting_tieout_failure": "hard_failure",
            "incompatibility": "hard_failure",
        },
        "structural_comparisons": {
            "same_probability_policy": True,
            "retain_causal_attribution_warning": True,
            "acknowledgement_required_before_signoff": True,
        },
        "reversal_conditions": {
            "allowed_sources": [
                "completed_scenario_comparison",
                "validated_sensitivity",
            ],
            "uncalculated_break_even_thresholds_forbidden": True,
            "new_tests_return_to_controlled_scenario_draft": True,
            "brief_may_mutate_or_execute": False,
        },
    }


RECOMMENDATION_CONTRACT_DIGEST = _canonical_sha256(
    recommendation_contract_payload()
)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _finite_probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(converted) or converted < 0.0 or converted > 1.0:
        return None
    return converted


def _append_unique(rows: list[dict[str, Any]], row: Mapping[str, Any]) -> None:
    candidate = deepcopy(dict(row))
    identity = _canonical_json_text(candidate)
    if all(_canonical_json_text(existing) != identity for existing in rows):
        rows.append(candidate)


def _blocker(
    blockers: list[dict[str, Any]],
    code: str,
    *,
    scenario_revision_id: str | None = None,
    detail: Any = None,
) -> None:
    row: dict[str, Any] = {"code": code}
    if scenario_revision_id:
        row["scenario_revision_id"] = scenario_revision_id
    if detail is not None:
        row["detail"] = deepcopy(detail)
    _append_unique(blockers, row)


def _warning(
    warnings: list[dict[str, Any]],
    code: str,
    *,
    source: str,
    scenario_revision_id: str,
    detail: Any = None,
) -> None:
    row: dict[str, Any] = {
        "code": code,
        "source": source,
        "scenario_revision_id": scenario_revision_id,
    }
    if detail is not None:
        row["detail"] = deepcopy(detail)
    _append_unique(warnings, row)


def _validate_bundle_identity(
    bundle: Mapping[str, Any],
    *,
    expected_bundle_sha256: str | None,
) -> str:
    embedded = bundle.get("bundle_hash")
    if not _valid_digest(embedded):
        raise RecommendationContractError(
            "comparison_bundle_hash_missing",
            "The comparison bundle has no valid canonical SHA-256.",
        )
    calculated = autonomy_comparison.canonical_comparison_bundle_sha256(bundle)
    if not secrets.compare_digest(str(embedded), calculated):
        raise RecommendationContractError(
            "comparison_bundle_hash_mismatch",
            "The comparison bundle changed after its canonical hash was recorded.",
        )
    if expected_bundle_sha256 is not None:
        if not _valid_digest(expected_bundle_sha256):
            raise RecommendationContractError(
                "expected_comparison_bundle_hash_invalid",
                "The expected comparison bundle SHA-256 is invalid.",
            )
        if not secrets.compare_digest(str(embedded), expected_bundle_sha256):
            raise RecommendationContractError(
                "comparison_bundle_identity_mismatch",
                "The selected stored bundle differs from the expected identity.",
            )
    return str(embedded)


def _validate_confirmation_binding(
    *,
    bundle: Mapping[str, Any],
    scenarios: Sequence[Any],
    blockers: list[dict[str, Any]],
) -> None:
    """Prove that the classifier sees the exact confirmed scenario sequence."""

    if (
        bundle.get("selection_contract")
        != autonomy_comparison.ATTEMPT_SELECTION_CONTRACT_VERSION
    ):
        _blocker(blockers, "attempt_selection_contract_unsupported")

    confirmation = bundle.get("confirmation")
    if not isinstance(confirmation, Mapping):
        _blocker(blockers, "confirmation_projection_missing")
        return
    if not str(confirmation.get("confirmation_id") or "").strip():
        _blocker(blockers, "confirmation_identity_invalid")
    for field in ("receipt_sha256", "confirmation_request_sha256"):
        if not _valid_digest(confirmation.get(field)):
            _blocker(
                blockers,
                "confirmation_digest_invalid",
                detail={"field": field},
            )

    ordered = confirmation.get("ordered_scenario_revision_ids")
    if not _is_sequence(ordered):
        _blocker(blockers, "confirmation_scenario_membership_mismatch")
        return
    ordered_ids = [str(value or "") for value in ordered]
    scenario_ids = [
        str(scenario.get("scenario_revision_id") or "")
        if isinstance(scenario, Mapping)
        else ""
        for scenario in scenarios
    ]
    if (
        not ordered_ids
        or any(not value for value in ordered_ids)
        or len(set(ordered_ids)) != len(ordered_ids)
        or any(not value for value in scenario_ids)
        or len(set(scenario_ids)) != len(scenario_ids)
        or len(ordered_ids) != len(scenario_ids)
        or set(ordered_ids) != set(scenario_ids)
    ):
        _blocker(blockers, "confirmation_scenario_membership_mismatch")
    elif ordered_ids != scenario_ids:
        _blocker(blockers, "confirmation_scenario_order_mismatch")

    for index, raw_scenario in enumerate(scenarios):
        if not isinstance(raw_scenario, Mapping):
            continue
        if raw_scenario.get("ordinal") != index:
            _blocker(
                blockers,
                "confirmation_scenario_order_mismatch",
                scenario_revision_id=str(
                    raw_scenario.get("scenario_revision_id") or ""
                ),
            )


def _validate_attempt_coverage(
    *,
    scenarios: Sequence[Any],
    proofs: Sequence[Any],
    blockers: list[dict[str, Any]],
) -> None:
    proof_by_key: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for raw_proof in proofs:
        if not isinstance(raw_proof, Mapping):
            _blocker(blockers, "attempt_proof_invalid")
            continue
        revision_id = str(raw_proof.get("scenario_revision_id") or "")
        tea_job_id = str(raw_proof.get("tea_job_id") or "")
        attempt_number = raw_proof.get("attempt_number")
        item_index = raw_proof.get("item_index")
        if (
            not revision_id
            or not tea_job_id
            or isinstance(attempt_number, bool)
            or not isinstance(attempt_number, int)
            or attempt_number <= 0
            or isinstance(item_index, bool)
            or not isinstance(item_index, int)
            or item_index < 0
            or not str(raw_proof.get("scenario_id") or "")
            or raw_proof.get("state") not in _DURABLE_ATTEMPT_STATES
        ):
            _blocker(blockers, "attempt_proof_identity_invalid")
            continue
        key = (revision_id, tea_job_id, attempt_number)
        if key in proof_by_key:
            _blocker(
                blockers,
                "attempt_proof_duplicate",
                scenario_revision_id=revision_id,
            )
            continue
        proof_by_key[key] = raw_proof

    seen_history_keys: set[tuple[str, str, int]] = set()
    selected_job_ids: set[str] = set()
    for scenario_index, raw_scenario in enumerate(scenarios):
        if not isinstance(raw_scenario, Mapping):
            _blocker(blockers, "scenario_projection_invalid")
            continue
        revision_id = str(raw_scenario.get("scenario_revision_id") or "")
        scenario_id = str(raw_scenario.get("scenario_id") or "")
        history = raw_scenario.get("attempt_history")
        if not revision_id or not _is_sequence(history) or not history:
            _blocker(
                blockers,
                "attempt_history_missing",
                scenario_revision_id=revision_id or None,
            )
            continue
        request = raw_scenario.get("request")
        request_sha256 = raw_scenario.get("request_sha256")
        if not isinstance(request, Mapping) or not _valid_digest(request_sha256):
            _blocker(
                blockers,
                "scenario_request_digest_mismatch",
                scenario_revision_id=revision_id,
            )
        elif not secrets.compare_digest(
            str(request_sha256), _canonical_sha256(request)
        ):
            _blocker(
                blockers,
                "scenario_request_digest_mismatch",
                scenario_revision_id=revision_id,
            )
        source = raw_scenario.get("source")
        source = source if isinstance(source, Mapping) else {}
        source_snapshot_sha256 = source.get("source_snapshot_sha256")
        if not _valid_digest(source_snapshot_sha256):
            _blocker(
                blockers,
                "scenario_source_digest_invalid",
                scenario_revision_id=revision_id,
            )

        selected_history: list[Mapping[str, Any]] = []
        previous_job_id: str | None = None
        history_job_ids: set[str] = set()
        for expected_attempt_number, raw_history in enumerate(history, start=1):
            if not isinstance(raw_history, Mapping):
                _blocker(
                    blockers,
                    "attempt_history_invalid",
                    scenario_revision_id=revision_id,
                )
                continue
            tea_job_id = str(raw_history.get("tea_job_id") or "")
            attempt_number = raw_history.get("attempt_number")
            if (
                not tea_job_id
                or isinstance(attempt_number, bool)
                or not isinstance(attempt_number, int)
                or attempt_number <= 0
            ):
                _blocker(
                    blockers,
                    "attempt_history_identity_invalid",
                    scenario_revision_id=revision_id,
                )
                continue
            if (
                attempt_number != expected_attempt_number
                or tea_job_id in history_job_ids
                or (
                    expected_attempt_number == 1
                    and raw_history.get("retry_of_job_id") is not None
                )
                or (
                    expected_attempt_number > 1
                    and raw_history.get("retry_of_job_id") != previous_job_id
                )
            ):
                _blocker(
                    blockers,
                    "attempt_chain_not_contiguous",
                    scenario_revision_id=revision_id,
                )
            history_job_ids.add(tea_job_id)
            previous_job_id = tea_job_id
            if raw_history.get("state") not in _DURABLE_ATTEMPT_STATES:
                _blocker(
                    blockers,
                    "attempt_history_state_invalid",
                    scenario_revision_id=revision_id,
                    detail={"tea_job_id": tea_job_id},
                )
            key = (revision_id, tea_job_id, attempt_number)
            if key in seen_history_keys:
                _blocker(
                    blockers,
                    "attempt_history_duplicate",
                    scenario_revision_id=revision_id,
                    detail={"tea_job_id": tea_job_id},
                )
            seen_history_keys.add(key)
            proof = proof_by_key.get(key)
            if proof is None:
                _blocker(
                    blockers,
                    "attempt_proof_missing",
                    scenario_revision_id=revision_id,
                    detail={"tea_job_id": tea_job_id},
                )
                continue
            for field in (
                "retry_of_job_id",
                "state",
                "selected_for_comparison",
                "request_sha256",
                "source_snapshot_sha256",
                "result_sha256",
                "result_provenance_sha256",
            ):
                if proof.get(field) != raw_history.get(field):
                    _blocker(
                        blockers,
                        "attempt_proof_history_mismatch",
                        scenario_revision_id=revision_id,
                        detail={"tea_job_id": tea_job_id, "field": field},
                    )
            for field, expected_value in (
                ("item_index", scenario_index),
                ("scenario_id", scenario_id),
            ):
                if proof.get(field) != expected_value:
                    _blocker(
                        blockers,
                        "attempt_proof_scenario_mismatch",
                        scenario_revision_id=revision_id,
                        detail={"tea_job_id": tea_job_id, "field": field},
                    )
            if (
                raw_history.get("request_sha256") != request_sha256
                or raw_history.get("source_snapshot_sha256")
                != source_snapshot_sha256
            ):
                _blocker(
                    blockers,
                    "attempt_request_or_source_mismatch",
                    scenario_revision_id=revision_id,
                    detail={"tea_job_id": tea_job_id},
                )
            if raw_history.get("selected_for_comparison") is not True and (
                proof.get("verification_status") != "not_applicable"
                or proof.get("result_projection_sha256") is not None
            ):
                _blocker(
                    blockers,
                    "nonselected_attempt_authority_invalid",
                    scenario_revision_id=revision_id,
                    detail={"tea_job_id": tea_job_id},
                )
            if raw_history.get("selected_for_comparison") is True:
                selected_history.append(raw_history)
        if len(selected_history) != 1:
            _blocker(
                blockers,
                "selected_attempt_cardinality_invalid",
                scenario_revision_id=revision_id,
            )
            continue
        selected = selected_history[0]
        if selected is not history[-1]:
            _blocker(
                blockers,
                "selected_attempt_not_chain_endpoint",
                scenario_revision_id=revision_id,
            )
        selected_key = (
            revision_id,
            str(selected.get("tea_job_id") or ""),
            int(selected.get("attempt_number") or 0),
        )
        selected_proof = proof_by_key.get(selected_key)
        attempt = raw_scenario.get("attempt")
        attempt = attempt if isinstance(attempt, Mapping) else {}
        verification = raw_scenario.get("verification")
        verification = verification if isinstance(verification, Mapping) else {}
        if (
            selected_proof is None
            or selected_proof.get("selected_for_comparison") is not True
            or selected_proof.get("state") != "done"
            or selected_proof.get("verification_status") != "verified"
            or attempt.get("tea_job_id") != selected.get("tea_job_id")
            or attempt.get("attempt_number") != selected.get("attempt_number")
            or attempt.get("retry_of_job_id") != selected.get("retry_of_job_id")
            or attempt.get("durable_state") != "done"
            or attempt.get("display_status") != "done"
            or attempt.get("terminal") is not True
            or attempt.get("selected_by_explicit_link") is not True
            or verification.get("status") != "verified"
            or bool(verification.get("failures"))
            or raw_scenario.get("request_sha256")
            != selected.get("request_sha256")
            or (
                (raw_scenario.get("source") or {}).get(
                    "source_snapshot_sha256"
                )
                if isinstance(raw_scenario.get("source"), Mapping)
                else None
            )
            != selected.get("source_snapshot_sha256")
        ):
            _blocker(
                blockers,
                "selected_attempt_not_reverified_done",
                scenario_revision_id=revision_id,
            )
        selected_job_id = str(selected.get("tea_job_id") or "")
        if selected_job_id in selected_job_ids:
            _blocker(
                blockers,
                "selected_attempt_reused_across_scenarios",
                scenario_revision_id=revision_id,
            )
        selected_job_ids.add(selected_job_id)
        checks = verification.get("checks")
        if not _is_sequence(checks) or not checks:
            _blocker(
                blockers,
                "result_verification_checks_missing",
                scenario_revision_id=revision_id,
            )
        elif any(
            not isinstance(check, Mapping) or check.get("status") != "passed"
            for check in checks
        ):
            _blocker(
                blockers,
                "result_verification_check_failed",
                scenario_revision_id=revision_id,
            )
        if selected_proof is not None:
            for field in (
                "request_sha256",
                "source_snapshot_sha256",
                "result_sha256",
                "result_provenance_sha256",
                "result_projection_sha256",
                "evidence_set_sha256",
                "reporting_tieout_sha256",
            ):
                if not _valid_digest(selected_proof.get(field)):
                    _blocker(
                        blockers,
                        "selected_attempt_digest_invalid",
                        scenario_revision_id=revision_id,
                        detail={"field": field},
                    )

            result_projection = raw_scenario.get("result")
            commitment = selected_proof.get("result_projection_sha256")
            if isinstance(result_projection, Mapping) and _valid_digest(
                selected_proof.get("result_sha256")
            ) and _valid_digest(commitment):
                expected_commitment = (
                    autonomy_comparison.result_projection_commitment_sha256(
                        durable_result_sha256=str(
                            selected_proof["result_sha256"]
                        ),
                        result_projection=result_projection,
                    )
                )
                if not secrets.compare_digest(str(commitment), expected_commitment):
                    _blocker(
                        blockers,
                        "result_projection_digest_mismatch",
                        scenario_revision_id=revision_id,
                    )
            else:
                _blocker(
                    blockers,
                    "result_projection_digest_mismatch",
                    scenario_revision_id=revision_id,
                )

            provenance = raw_scenario.get("provenance")
            provenance = provenance if isinstance(provenance, Mapping) else {}
            if any(
                (
                    provenance.get("request_sha256") != request_sha256,
                    provenance.get("source_snapshot_sha256")
                    != source_snapshot_sha256,
                    provenance.get("routine_result_sha256")
                    != selected_proof.get("result_sha256"),
                )
            ):
                _blocker(
                    blockers,
                    "selected_result_identity_mismatch",
                    scenario_revision_id=revision_id,
                )

    for key in sorted(set(proof_by_key) - seen_history_keys):
        _blocker(
            blockers,
            "attempt_history_omits_proof",
            scenario_revision_id=key[0],
            detail={"tea_job_id": key[1]},
        )


def _resolved_comparison_classifications(
    scenarios: Sequence[Any],
    *,
    blockers: list[dict[str, Any]],
) -> dict[str, str]:
    """Resolve v8 projections without changing their canonical bundle bytes.

    New bundles project the immutable stored classification directly.  Historical
    schema-v8 bundles predate that projection, so an absent alternative value is
    re-derived from the two frozen requests with the original deterministic
    scenario helpers.  Any ambiguity fails closed.
    """

    resolved: dict[str, str] = {}
    missing_alternatives: list[Mapping[str, Any]] = []
    baselines: list[Mapping[str, Any]] = []
    for raw_scenario in scenarios:
        if not isinstance(raw_scenario, Mapping):
            continue
        revision_id = str(raw_scenario.get("scenario_revision_id") or "")
        kind = raw_scenario.get("kind")
        classification = raw_scenario.get("comparison_classification")
        if kind == "baseline":
            baselines.append(raw_scenario)
            if classification in (None, "baseline"):
                resolved[revision_id] = "baseline"
            else:
                resolved[revision_id] = str(classification)
        elif classification in {"controlled", "structural"}:
            resolved[revision_id] = str(classification)
        elif classification is None:
            missing_alternatives.append(raw_scenario)
        else:
            resolved[revision_id] = str(classification)

    if not missing_alternatives:
        return resolved
    if len(baselines) != 1 or not isinstance(baselines[0].get("request"), Mapping):
        for scenario in missing_alternatives:
            _blocker(
                blockers,
                "historical_comparison_classification_unprovable",
                scenario_revision_id=str(
                    scenario.get("scenario_revision_id") or ""
                ),
                detail={"reason": "exactly_one_frozen_baseline_required"},
            )
        return resolved

    # Function-local by design: the fallback is needed only for immutable bundles
    # created before comparison classification was projected.  These helpers are
    # pure and are the original authority used when the scenario was validated.
    from sbepv.autonomy import scenarios as autonomy_scenarios

    baseline_request = baselines[0]["request"]
    for scenario in missing_alternatives:
        revision_id = str(scenario.get("scenario_revision_id") or "")
        scenario_request = scenario.get("request")
        if not isinstance(scenario_request, Mapping):
            _blocker(
                blockers,
                "historical_comparison_classification_unprovable",
                scenario_revision_id=revision_id,
                detail={"reason": "frozen_request_missing"},
            )
            continue
        try:
            differences = autonomy_scenarios.json_pointer_leaf_diff(
                baseline_request,
                scenario_request,
            )
            derived = autonomy_scenarios.classify_comparison(
                baseline_request,
                scenario_request,
                differences,
            )
        except (TypeError, ValueError) as exc:
            _blocker(
                blockers,
                "historical_comparison_classification_unprovable",
                scenario_revision_id=revision_id,
                detail={"reason": type(exc).__name__},
            )
            continue
        if derived not in {"controlled", "structural"}:
            _blocker(
                blockers,
                "historical_comparison_classification_unprovable",
                scenario_revision_id=revision_id,
                detail={"reason": "unsupported_derived_classification"},
            )
            continue
        resolved[revision_id] = derived
    return resolved


def _tradeoff_evidence(
    scenario: Mapping[str, Any],
    *,
    comparison_classification: str | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    revision_id = str(scenario.get("scenario_revision_id") or "")
    result = scenario.get("result")
    if not isinstance(result, Mapping):
        _blocker(
            blockers,
            "selected_scenario_result_missing",
            scenario_revision_id=revision_id or None,
        )
        return None
    if result.get("energy_available") is not True:
        _blocker(
            blockers,
            "selected_scenario_energy_unavailable",
            scenario_revision_id=revision_id,
        )
        return None
    joint = result.get("joint_outcomes")
    tradeoff = joint.get("tradeoff_classes") if isinstance(joint, Mapping) else None
    if not isinstance(tradeoff, Mapping):
        _blocker(
            blockers,
            "tradeoff_class_summary_missing",
            scenario_revision_id=revision_id,
        )
        return None
    denominator = tradeoff.get("denominator")
    counts = tradeoff.get("counts")
    probabilities = tradeoff.get("probabilities")
    expected_classes = set(technoeconomic_kernel.TRADEOFF_CLASSES)
    if (
        isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or denominator <= 0
        or not isinstance(counts, Mapping)
        or not isinstance(probabilities, Mapping)
        or set(counts) != expected_classes
        or set(probabilities) != expected_classes
    ):
        _blocker(
            blockers,
            "tradeoff_class_summary_invalid",
            scenario_revision_id=revision_id,
        )
        return None
    normalized: dict[str, float] = {}
    count_total = 0
    for class_id in technoeconomic_kernel.TRADEOFF_CLASSES:
        count = counts.get(class_id)
        probability = _finite_probability(probabilities.get(class_id))
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or probability is None
        ):
            _blocker(
                blockers,
                "tradeoff_class_value_invalid",
                scenario_revision_id=revision_id,
                detail={"class_id": class_id},
            )
            return None
        expected_probability = count / denominator
        if not math.isclose(
            probability,
            expected_probability,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            _blocker(
                blockers,
                "tradeoff_probability_count_mismatch",
                scenario_revision_id=revision_id,
                detail={"class_id": class_id},
            )
            return None
        normalized[class_id] = probability
        count_total += count
    if count_total != denominator or not math.isclose(
        math.fsum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-12
    ):
        _blocker(
            blockers,
            "tradeoff_population_tieout_failed",
            scenario_revision_id=revision_id,
        )
        return None

    solaredge_probability = math.fsum(
        normalized[class_id] for class_id in SOLAREDGE_DOMINANT_CLASSES
    )
    solectria_probability = math.fsum(
        normalized[class_id] for class_id in SOLECTRIA_DOMINANT_CLASSES
    )
    hurdle_probability = math.fsum(
        normalized[class_id]
        for class_id in UNAPPROVED_HURDLE_TRADEOFF_CLASSES
    )
    direction = "none"
    if solaredge_probability >= WINNER_PROBABILITY_THRESHOLD:
        direction = "solaredge"
    elif solectria_probability >= WINNER_PROBABILITY_THRESHOLD:
        direction = "solectria"
    assert direction in _SELECTION_STATES
    return {
        "scenario_revision_id": revision_id,
        "scenario_id": scenario.get("scenario_id"),
        "label": scenario.get("label"),
        "kind": scenario.get("kind"),
        "comparison_classification": comparison_classification,
        "denominator": denominator,
        "tradeoff_probabilities": normalized,
        "solaredge_dominant_probability": solaredge_probability,
        "solectria_dominant_probability": solectria_probability,
        "unapproved_hurdle_tradeoff_probability": hurdle_probability,
        "direction_at_approved_threshold": direction,
        "winner_threshold": WINNER_PROBABILITY_THRESHOLD,
        "strong_threshold": STRONG_PROBABILITY_THRESHOLD,
    }


def _validate_scenario_gates(
    scenario: Mapping[str, Any],
    *,
    comparison_classification: str | None,
    selected_proof: Mapping[str, Any] | None,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    evidence_gaps: list[dict[str, Any]],
    model_limitations: list[dict[str, Any]],
) -> None:
    revision_id = str(scenario.get("scenario_revision_id") or "")
    result = scenario.get("result")
    result = result if isinstance(result, Mapping) else {}
    evidence = scenario.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    provenance = scenario.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}

    if comparison_classification not in _COMPARISON_CLASSIFICATIONS:
        _blocker(
            blockers,
            "scenario_comparison_classification_missing",
            scenario_revision_id=revision_id,
        )
    elif (
        scenario.get("kind") == "baseline"
        and comparison_classification != "baseline"
    ) or (
        scenario.get("kind") == "alternative"
        and comparison_classification == "baseline"
    ):
        _blocker(
            blockers,
            "scenario_comparison_classification_invalid",
            scenario_revision_id=revision_id,
        )
    elif comparison_classification == "structural":
        _append_unique(
            model_limitations,
            {
                "code": "structural_comparison_causal_attribution_limited",
                "scenario_revision_id": revision_id,
                "message": (
                    "This structural comparison changes request structure; "
                    "baseline-relative differences cannot isolate a single "
                    "causal effect."
                ),
                "acknowledgement_required": True,
            },
        )

    input_status = evidence.get("status")
    if input_status != result.get("input_status"):
        _blocker(
            blockers,
            "evidence_status_result_mismatch",
            scenario_revision_id=revision_id,
        )
    if input_status == "provisional_inputs":
        _warning(
            warnings,
            "provisional_inputs",
            source="evidence",
            scenario_revision_id=revision_id,
        )
    elif input_status != "documented_inputs":
        _blocker(
            blockers,
            "required_evidence_status_invalid",
            scenario_revision_id=revision_id,
        )
    gaps = evidence.get("gaps")
    if not _is_sequence(gaps):
        _blocker(
            blockers,
            "evidence_gaps_invalid",
            scenario_revision_id=revision_id,
        )
    elif gaps:
        for gap in gaps:
            row = {
                "scenario_revision_id": revision_id,
                "gap": deepcopy(gap),
            }
            _append_unique(evidence_gaps, row)
        _blocker(
            blockers,
            "required_evidence_gap",
            scenario_revision_id=revision_id,
        )

    receipts = evidence.get("receipts")
    evidence_identities: list[dict[str, Any]] = []
    seen_receipt_keys: set[tuple[str, str]] = set()
    receipt_set_valid = _is_sequence(receipts)
    if receipt_set_valid:
        for raw_receipt in receipts:
            if not isinstance(raw_receipt, Mapping):
                receipt_set_valid = False
                continue
            request_path = str(raw_receipt.get("request_path") or "")
            receipt_id = str(raw_receipt.get("evidence_receipt_id") or "")
            receipt_sha256 = raw_receipt.get("receipt_sha256")
            content_sha256 = raw_receipt.get("content_sha256")
            key = (request_path, receipt_id)
            if (
                not request_path
                or not receipt_id
                or not _valid_digest(receipt_sha256)
                or not _valid_digest(content_sha256)
                or key in seen_receipt_keys
            ):
                receipt_set_valid = False
            seen_receipt_keys.add(key)
            evidence_identities.append(
                {
                    "request_path": raw_receipt.get("request_path"),
                    "evidence_receipt_id": raw_receipt.get(
                        "evidence_receipt_id"
                    ),
                    "receipt_sha256": receipt_sha256,
                    "content_sha256": content_sha256,
                }
            )
        evidence_identities.sort(
            key=lambda item: (
                str(item.get("request_path") or ""),
                str(item.get("evidence_receipt_id") or ""),
            )
        )
    if not receipt_set_valid:
        _blocker(
            blockers,
            "evidence_receipt_identity_invalid",
            scenario_revision_id=revision_id,
        )

    evidence_digest = evidence.get("evidence_set_sha256")
    expected_evidence_digest = _canonical_sha256(evidence_identities)
    if not _valid_digest(evidence_digest):
        _blocker(
            blockers,
            "evidence_set_digest_invalid",
            scenario_revision_id=revision_id,
        )
    elif (
        not receipt_set_valid
        or not secrets.compare_digest(
            str(evidence_digest), expected_evidence_digest
        )
        or selected_proof is None
        or evidence_digest != selected_proof.get("evidence_set_sha256")
        or evidence_digest != provenance.get("evidence_set_sha256")
    ):
        _blocker(
            blockers,
            "evidence_set_digest_mismatch",
            scenario_revision_id=revision_id,
        )

    quality = result.get("quality")
    quality = quality if isinstance(quality, Mapping) else {}
    tie_outs = quality.get("reporting_tie_outs")
    reporting_checks = quality.get("reporting_checks")
    tie_outs_valid = bool(
        isinstance(tie_outs, Mapping)
        and tie_outs.get("status") == "passed"
        and tie_outs.get("failed_check_ids") == []
        and _is_sequence(reporting_checks)
        and tie_outs.get("check_count") == len(reporting_checks)
        and all(
            isinstance(check, Mapping)
            and check.get("status_authority") == "OK"
            for check in reporting_checks
        )
    )
    if not tie_outs_valid:
        _blocker(
            blockers,
            "reporting_tieout_failed",
            scenario_revision_id=revision_id,
        )

    export_manifest_sha256 = provenance.get("export_manifest_sha256")
    provenance_exports = provenance.get("exports")
    provenance_tie_outs = provenance.get("reporting_tie_outs")
    expected_tieout_sha256 = (
        _canonical_sha256(
            {
                "manifest_sha256": export_manifest_sha256,
                "tie_outs": dict(tie_outs),
            }
        )
        if isinstance(tie_outs, Mapping)
        and _valid_digest(export_manifest_sha256)
        else None
    )
    if (
        expected_tieout_sha256 is None
        or not isinstance(provenance_exports, Mapping)
        or provenance_exports.get("manifest_sha256")
        != export_manifest_sha256
        or provenance_tie_outs != tie_outs
        or selected_proof is None
        or selected_proof.get("reporting_tieout_sha256")
        != expected_tieout_sha256
        or provenance.get("reporting_tieout_sha256")
        != expected_tieout_sha256
    ):
        _blocker(
            blockers,
            "reporting_tieout_digest_mismatch",
            scenario_revision_id=revision_id,
        )

    numerics = quality.get("numerical_provenance")
    if (
        not isinstance(numerics, Mapping)
        or not str(numerics.get("contract_version") or "")
        or not isinstance(numerics.get("probe_digests"), Mapping)
    ):
        _blocker(
            blockers,
            "numerical_provenance_missing",
            scenario_revision_id=revision_id,
        )
    else:
        kernel = provenance.get("kernel")
        kernel_numerics = provenance.get("kernel_numerics")
        if (
            not isinstance(kernel, Mapping)
            or kernel.get("numerics") != numerics
            or kernel_numerics != numerics
            or kernel.get("calculation_contract_version")
            != result.get("calculation_contract_version")
            or kernel.get("sampling_version") != result.get("sampling_version")
        ):
            _blocker(
                blockers,
                "numerical_provenance_mismatch",
                scenario_revision_id=revision_id,
            )

    required_provenance_digests = (
        "request_sha256",
        "source_snapshot_sha256",
        "submission_provenance_sha256",
        "validated_kernel_request_sha256",
        "routine_result_sha256",
        "sealed_calculation_sha256",
        "export_manifest_sha256",
        "reporting_tieout_sha256",
        "evidence_set_sha256",
    )
    for field in required_provenance_digests:
        if not _valid_digest(provenance.get(field)):
            _blocker(
                blockers,
                "result_provenance_digest_invalid",
                scenario_revision_id=revision_id,
                detail={"field": field},
            )

    convergence = result.get("convergence")
    if not isinstance(convergence, Mapping):
        _blocker(
            blockers,
            "hard_convergence_gate_failed",
            scenario_revision_id=revision_id,
            detail={"status": "missing"},
        )
    else:
        convergence_status = convergence.get("status")
        reasons = convergence.get("reasons")
        if convergence_status == "stable" and (
            not _is_sequence(reasons) or len(reasons) != 0
        ):
            _blocker(
                blockers,
                "convergence_status_contradictory",
                scenario_revision_id=revision_id,
            )
        elif convergence_status == "not_demonstrated":
            if not _is_sequence(reasons) or not reasons:
                _blocker(
                    blockers,
                    "hard_convergence_gate_failed",
                    scenario_revision_id=revision_id,
                    detail={"status": convergence_status},
                )
            else:
                for reason in reasons:
                    _warning(
                        warnings,
                        "convergence_not_demonstrated",
                        source="convergence",
                        scenario_revision_id=revision_id,
                        detail={"reason": str(reason)},
                    )
        elif convergence_status != "stable":
            _blocker(
                blockers,
                "hard_convergence_gate_failed",
                scenario_revision_id=revision_id,
                detail={"status": convergence_status},
            )


def _validated_sensitivity_rows(
    scenario: Mapping[str, Any],
    *,
    model_limitations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    revision_id = str(scenario.get("scenario_revision_id") or "")
    result = scenario.get("result")
    sensitivity = (
        result.get("sensitivity") if isinstance(result, Mapping) else None
    )
    if not isinstance(sensitivity, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for response_id in sorted(sensitivity):
        model = sensitivity.get(response_id)
        if not isinstance(model, Mapping) or model.get("status") != "available":
            continue
        sample_count = model.get("sample_count")
        minimum = model.get("minimum_sample_count")
        steps = model.get("steps")
        valid_header = (
            isinstance(sample_count, int)
            and not isinstance(sample_count, bool)
            and isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and sample_count >= minimum >= 1
            and _is_sequence(steps)
            and bool(steps)
        )
        if not valid_header:
            _append_unique(
                model_limitations,
                {
                    "code": "sensitivity_data_not_usable_for_reversal",
                    "scenario_revision_id": revision_id,
                    "response_id": str(response_id),
                },
            )
            continue
        for raw_step in steps:
            if not isinstance(raw_step, Mapping):
                continue
            predictor_id = str(raw_step.get("predictor_id") or "")
            entry_order = raw_step.get("entry_order")
            incremental = raw_step.get("incremental_r_squared")
            beta = raw_step.get("standardized_beta")
            sign = raw_step.get("sign")
            if (
                not predictor_id
                or isinstance(entry_order, bool)
                or not isinstance(entry_order, int)
                or entry_order <= 0
                or _finite_probability(incremental) is None
                or isinstance(beta, bool)
                or not isinstance(beta, (int, float))
                or not math.isfinite(float(beta))
                or sign not in {"positive", "negative", "zero"}
            ):
                continue
            rows.append(
                {
                    "scenario_revision_id": revision_id,
                    "response_id": str(response_id),
                    "predictor_id": predictor_id,
                    "entry_order": entry_order,
                    "incremental_r_squared": float(incremental),
                    "standardized_beta": float(beta),
                    "sign": sign,
                }
            )
    return rows


def _reversal_conditions(
    *,
    case_id: str,
    classification: str,
    scenario_evidence: Sequence[Mapping[str, Any]],
    sensitivity_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    directions = {
        str(item.get("direction_at_approved_threshold"))
        for item in scenario_evidence
    }
    if classification == "no_decisive_winner" and {
        "solaredge",
        "solectria",
    }.issubset(directions):
        for item in scenario_evidence:
            if item.get("direction_at_approved_threshold") == "none":
                continue
            rows.append(
                {
                    "source": "completed_scenario_comparison",
                    "scenario_revision_id": item.get("scenario_revision_id"),
                    "observed_direction": item.get(
                        "direction_at_approved_threshold"
                    ),
                    "solaredge_dominant_probability": item.get(
                        "solaredge_dominant_probability"
                    ),
                    "solectria_dominant_probability": item.get(
                        "solectria_dominant_probability"
                    ),
                    "break_even_threshold": None,
                    "threshold_status": "not_calculated",
                    "calculation_status": "completed_scenario",
                }
            )

    for item in sorted(
        sensitivity_rows,
        key=lambda row: (
            -float(row.get("incremental_r_squared") or 0.0),
            str(row.get("scenario_revision_id") or ""),
            str(row.get("response_id") or ""),
            int(row.get("entry_order") or 0),
            str(row.get("predictor_id") or ""),
        ),
    )[:3]:
        rows.append(
            {
                "source": "validated_sensitivity",
                "scenario_revision_id": item.get("scenario_revision_id"),
                "response_id": item.get("response_id"),
                "predictor_id": item.get("predictor_id"),
                "observed_standardized_beta": item.get("standardized_beta"),
                "observed_sign": item.get("sign"),
                "incremental_r_squared": item.get("incremental_r_squared"),
                "break_even_threshold": None,
                "threshold_status": "not_calculated",
                "calculation_status": "candidate_for_controlled_test",
                "draft_deep_link": {
                    "target": "investigation_compare_scenarios",
                    "action": "create_controlled_scenario_draft",
                    "case_id": case_id,
                    "source_scenario_revision_id": item.get(
                        "scenario_revision_id"
                    ),
                    "predictor_id": item.get("predictor_id"),
                    "mutates_from_brief": False,
                    "executes": False,
                },
            }
        )
    return rows


def _unavailable_result(
    *,
    bundle_sha256: str,
    blockers: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    scenario_evidence: Sequence[Mapping[str, Any]],
    evidence_gaps: Sequence[Mapping[str, Any]],
    model_limitations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    classification_basis = {
        "comparison_bundle_sha256": bundle_sha256,
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "contract_digest": RECOMMENDATION_CONTRACT_DIGEST,
        "scenario_evidence": list(scenario_evidence),
        "blockers": list(blockers),
        "warnings": list(warnings),
    }
    return {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "state": "unavailable",
        "recommendation_eligible": False,
        "classification": None,
        "confidence": None,
        "conditional_statement": (
            "A final recommendation is unavailable until every hard contract "
            "gate passes."
        ),
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "contract_digest": RECOMMENDATION_CONTRACT_DIGEST,
        "comparison_bundle_sha256": bundle_sha256,
        "classification_input_sha256": _canonical_sha256(classification_basis),
        "blockers": deepcopy(list(blockers)),
        "reasons": [],
        "warnings": deepcopy(list(warnings)),
        "required_acknowledgements": [],
        "scenario_evidence": deepcopy(list(scenario_evidence)),
        "decisive_evidence": [],
        "major_drivers": [],
        "important_uncertainty": deepcopy(list(warnings)),
        "evidence_gaps": deepcopy(list(evidence_gaps)),
        "model_limitations": deepcopy(list(model_limitations)),
        "reversal_conditions": [],
    }


def classify_comparison_bundle(
    bundle: Mapping[str, Any],
    *,
    expected_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    """Classify one exact immutable comparison bundle under policy v1.

    Identity/hash failures raise :class:`RecommendationContractError`; ordinary
    incomplete or failed contract gates return a structured unavailable result.
    The returned object is pure canonical JSON and includes the policy version and
    digest required for immutable recommendation, sign-off, and report snapshots.
    """

    if not isinstance(bundle, Mapping):
        raise RecommendationContractError(
            "comparison_bundle_invalid",
            "The recommendation input must be a comparison-bundle object.",
        )
    bundle_sha256 = _validate_bundle_identity(
        bundle, expected_bundle_sha256=expected_bundle_sha256
    )
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence_gaps: list[dict[str, Any]] = []
    model_limitations: list[dict[str, Any]] = []

    if (
        bundle.get("schema_version")
        != autonomy_comparison.COMPARISON_BUNDLE_SCHEMA_VERSION
    ):
        _blocker(blockers, "comparison_bundle_schema_unsupported")
    if bundle.get("is_complete") is not True:
        _blocker(blockers, "comparison_bundle_incomplete")
    completeness = bundle.get("completeness")
    completeness = completeness if isinstance(completeness, Mapping) else {}
    scenarios = bundle.get("scenarios")
    scenarios = scenarios if _is_sequence(scenarios) else []
    proofs = bundle.get("attempt_proofs")
    proofs = proofs if _is_sequence(proofs) else []
    _validate_confirmation_binding(
        bundle=bundle,
        scenarios=scenarios,
        blockers=blockers,
    )
    if not scenarios:
        _blocker(blockers, "selected_scenarios_missing")
    if (
        completeness.get("status") != "complete"
        or completeness.get("blockers") not in ([], ())
        or completeness.get("selected_count") != len(scenarios)
        or completeness.get("verified_done_count") != len(scenarios)
    ):
        _blocker(blockers, "comparison_completeness_proof_invalid")
    comparison = bundle.get("comparison")
    compatibility = (
        comparison.get("compatibility")
        if isinstance(comparison, Mapping)
        else None
    )
    if (
        not isinstance(compatibility, Mapping)
        or compatibility.get("status") != "compatible"
        or compatibility.get("blockers") not in ([], ())
    ):
        _blocker(blockers, "comparison_results_incompatible")

    _validate_attempt_coverage(
        scenarios=scenarios,
        proofs=proofs,
        blockers=blockers,
    )
    selected_proofs = {
        str(proof.get("scenario_revision_id") or ""): proof
        for proof in proofs
        if isinstance(proof, Mapping)
        and proof.get("selected_for_comparison") is True
    }
    resolved_comparisons = _resolved_comparison_classifications(
        scenarios,
        blockers=blockers,
    )

    scenario_evidence: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    seen_revision_ids: set[str] = set()
    for raw_scenario in scenarios:
        if not isinstance(raw_scenario, Mapping):
            continue
        revision_id = str(raw_scenario.get("scenario_revision_id") or "")
        if not revision_id or revision_id in seen_revision_ids:
            _blocker(
                blockers,
                "scenario_revision_identity_invalid",
                scenario_revision_id=revision_id or None,
            )
            continue
        seen_revision_ids.add(revision_id)
        _validate_scenario_gates(
            raw_scenario,
            comparison_classification=resolved_comparisons.get(revision_id),
            selected_proof=selected_proofs.get(revision_id),
            blockers=blockers,
            warnings=warnings,
            evidence_gaps=evidence_gaps,
            model_limitations=model_limitations,
        )
        evidence_row = _tradeoff_evidence(
            raw_scenario,
            comparison_classification=resolved_comparisons.get(revision_id),
            blockers=blockers,
        )
        if evidence_row is not None:
            scenario_evidence.append(evidence_row)
        sensitivity_rows.extend(
            _validated_sensitivity_rows(
                raw_scenario,
                model_limitations=model_limitations,
            )
        )

    if len(scenario_evidence) != len(scenarios):
        _blocker(blockers, "all_selected_scenarios_not_classifiable")
    if blockers:
        return _unavailable_result(
            bundle_sha256=bundle_sha256,
            blockers=blockers,
            warnings=warnings,
            scenario_evidence=scenario_evidence,
            evidence_gaps=evidence_gaps,
            model_limitations=model_limitations,
        )

    directions = {
        str(item["direction_at_approved_threshold"])
        for item in scenario_evidence
    }
    if directions == {"solaredge"}:
        classification = "solaredge"
    elif directions == {"solectria"}:
        classification = "solectria"
    else:
        classification = "no_decisive_winner"

    reasons: list[dict[str, Any]] = []
    if classification in {"solaredge", "solectria"}:
        _append_unique(
            reasons,
            {
                "code": "direction_threshold_met_in_every_selected_scenario",
                "direction": classification,
                "threshold": WINNER_PROBABILITY_THRESHOLD,
            },
        )
    else:
        if {"solaredge", "solectria"}.issubset(directions):
            _append_unique(
                reasons,
                {
                    "code": "cross_scenario_direction_conflict",
                    "threshold": WINNER_PROBABILITY_THRESHOLD,
                },
            )
        for evidence_row in scenario_evidence:
            if evidence_row["direction_at_approved_threshold"] == "none":
                _append_unique(
                    reasons,
                    {
                        "code": "direction_threshold_not_met",
                        "scenario_revision_id": evidence_row[
                            "scenario_revision_id"
                        ],
                        "solaredge_dominant_probability": evidence_row[
                            "solaredge_dominant_probability"
                        ],
                        "solectria_dominant_probability": evidence_row[
                            "solectria_dominant_probability"
                        ],
                        "threshold": WINNER_PROBABILITY_THRESHOLD,
                    },
                )
            hurdle = float(
                evidence_row["unapproved_hurdle_tradeoff_probability"]
            )
            if hurdle > max(
                float(evidence_row["solaredge_dominant_probability"]),
                float(evidence_row["solectria_dominant_probability"]),
            ):
                _append_unique(
                    reasons,
                    {
                        "code": "cost_energy_tradeoff_requires_unapproved_hurdle",
                        "scenario_revision_id": evidence_row[
                            "scenario_revision_id"
                        ],
                        "tradeoff_probability": hurdle,
                    },
                )

    if classification == "no_decisive_winner":
        confidence = "not_applicable"
    elif warnings:
        confidence = "provisional"
    else:
        directional_key = f"{classification}_dominant_probability"
        minimum_probability = min(
            float(item[directional_key]) for item in scenario_evidence
        )
        confidence = (
            "strong"
            if minimum_probability >= STRONG_PROBABILITY_THRESHOLD
            else "mixed"
        )

    major_drivers = sorted(
        sensitivity_rows,
        key=lambda row: (
            -float(row.get("incremental_r_squared") or 0.0),
            str(row.get("scenario_revision_id") or ""),
            str(row.get("response_id") or ""),
            int(row.get("entry_order") or 0),
            str(row.get("predictor_id") or ""),
        ),
    )[:5]
    case = bundle.get("case")
    case_id = str(case.get("case_id") or "") if isinstance(case, Mapping) else ""
    reversals = _reversal_conditions(
        case_id=case_id,
        classification=classification,
        scenario_evidence=scenario_evidence,
        sensitivity_rows=sensitivity_rows,
    )
    required_acknowledgements = [
        {
            "code": "acknowledge_recommendation_warning",
            "warning": deepcopy(item),
        }
        for item in warnings
    ] if confidence == "provisional" else []
    required_acknowledgements.extend(
        {
            "code": "acknowledge_model_limitation",
            "model_limitation": deepcopy(item),
        }
        for item in model_limitations
        if item.get("acknowledgement_required") is True
    )
    statements = {
        "solaredge": (
            "SolarEdge is the directional winner under every selected complete "
            "scenario using the approved conservative-dominance policy."
        ),
        "solectria": (
            "Solectria is the directional winner under every selected complete "
            "scenario using the approved conservative-dominance policy."
        ),
        "no_decisive_winner": (
            "No decisive winner meets the approved conservative-dominance policy "
            "across every selected complete scenario."
        ),
    }
    classification_basis = {
        "comparison_bundle_sha256": bundle_sha256,
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "contract_digest": RECOMMENDATION_CONTRACT_DIGEST,
        "scenario_evidence": scenario_evidence,
        "warnings": warnings,
        "model_limitations": model_limitations,
    }
    result = {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "state": "available",
        "recommendation_eligible": True,
        "classification": classification,
        "confidence": confidence,
        "conditional_statement": statements[classification],
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "contract_digest": RECOMMENDATION_CONTRACT_DIGEST,
        "comparison_bundle_sha256": bundle_sha256,
        "classification_input_sha256": _canonical_sha256(classification_basis),
        "blockers": [],
        "reasons": reasons,
        "warnings": warnings,
        "required_acknowledgements": required_acknowledgements,
        "scenario_evidence": scenario_evidence,
        "decisive_evidence": deepcopy(scenario_evidence),
        "major_drivers": major_drivers,
        "important_uncertainty": deepcopy(warnings),
        "evidence_gaps": evidence_gaps,
        "model_limitations": model_limitations,
        "reversal_conditions": reversals,
    }
    # Defense in depth: ensure callers can hash/store the output without lossy
    # normalization or a late non-finite value.
    _canonical_json_text(result)
    return result


__all__ = [
    "RECOMMENDATION_CONTRACT_DIGEST",
    "RECOMMENDATION_CONTRACT_VERSION",
    "RECOMMENDATION_SCHEMA_VERSION",
    "SOLECTRIA_DOMINANT_CLASSES",
    "SOLAREDGE_DOMINANT_CLASSES",
    "STRONG_PROBABILITY_THRESHOLD",
    "UNAPPROVED_HURDLE_TRADEOFF_CLASSES",
    "WINNER_PROBABILITY_THRESHOLD",
    "RecommendationContractError",
    "classify_comparison_bundle",
    "recommendation_contract_payload",
]
