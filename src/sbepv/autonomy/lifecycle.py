"""Deterministic Autonomy case lifecycle and action policy.

The model may explain these rules, but it never supplies or changes them.  The
complete approved state vocabulary is retained so durable rows remain forwards
compatible. Scenario construction and execution are deterministic human-owned
actions; recommendation, sign-off, and report generation remain unavailable.
"""

from __future__ import annotations

from collections.abc import Iterable


CASE_STATES = frozenset(
    {
        "draft",
        "evidence_needed",
        "blocked",
        "ready_to_run",
        "running",
        "results_ready",
        "decision_ready",
        "signed",
        "archived",
    }
)

CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"evidence_needed", "blocked", "archived"}),
    "evidence_needed": frozenset({"blocked", "ready_to_run", "archived"}),
    "blocked": frozenset({"evidence_needed", "ready_to_run", "archived"}),
    "ready_to_run": frozenset({"evidence_needed", "blocked", "running", "archived"}),
    "running": frozenset({"results_ready"}),
    "results_ready": frozenset({"decision_ready"}),
    "decision_ready": frozenset({"signed"}),
    "signed": frozenset({"archived"}),
    "archived": frozenset(),
}

EVIDENCE_CLASSES = frozenset(
    {
        "project_actual",
        "direct_quote_or_primary_document",
        "public_market_proxy_or_benchmark",
        "engineering_judgment",
        "secondary_synthesis",
    }
)
PROVISIONAL_EVIDENCE_CLASSES = frozenset(
    {"engineering_judgment", "secondary_synthesis"}
)
EVIDENCE_REVIEW_STATES = frozenset({"pending", "accepted", "rejected", "deleted"})

# These are the only case actions exposed through the Scenarios + Execution phase.
# There is intentionally no recommendation, sign, or report action.
_PHASE_ACTIONS_BY_STATE: dict[str, tuple[str, ...]] = {
    "draft": (
        "edit_case",
        "lock_case_basis",
        "upload_evidence",
        "review_evidence",
        "create_scenario",
        "compare_scenarios",
        "ask_decision_agent",
        "view_history",
        "archive_case",
    ),
    "evidence_needed": (
        "edit_case",
        "lock_case_basis",
        "upload_evidence",
        "review_evidence",
        "create_scenario",
        "compare_scenarios",
        "ask_decision_agent",
        "view_history",
        "archive_case",
    ),
    "blocked": (
        "edit_case",
        "lock_case_basis",
        "upload_evidence",
        "review_evidence",
        "create_scenario",
        "compare_scenarios",
        "ask_decision_agent",
        "view_history",
        "archive_case",
    ),
    "ready_to_run": (
        "upload_evidence",
        "review_evidence",
        "create_scenario",
        "compare_scenarios",
        "confirm_scenarios",
        "ask_decision_agent",
        "view_history",
        "archive_case",
    ),
    "running": (
        "monitor_execution",
        "retry_failed_execution",
        "cancel_execution",
        "ask_decision_agent",
        "view_history",
    ),
    "results_ready": (
        "monitor_execution",
        "compare_scenarios",
        "ask_decision_agent",
        "view_history",
        "archive_case",
    ),
    "decision_ready": ("ask_decision_agent", "view_history", "archive_case"),
    "signed": ("view_history", "archive_case"),
    "archived": ("view_history",),
}

ACTION_LABELS = {
    "edit_case": "Edit case definition",
    "lock_case_basis": "Select and lock an eligible Annual source",
    "upload_evidence": "Upload evidence",
    "review_evidence": "Review extracted evidence",
    "create_scenario": "Create a scenario draft",
    "compare_scenarios": "Compare scenario inputs",
    "confirm_scenarios": "Review and confirm selected TEA runs",
    "monitor_execution": "Monitor confirmed TEA runs",
    "retry_failed_execution": "Retry an eligible TEA attempt",
    "cancel_execution": "Cancel eligible TEA work",
    "ask_decision_agent": "Ask the Decision Agent",
    "view_history": "View case history",
    "archive_case": "Archive case",
}


class LifecycleRuleError(ValueError):
    """Raised when a requested state/action is outside deterministic policy."""


def validate_case_state(value: object) -> str:
    state_name = str(value or "").strip()
    if state_name not in CASE_STATES:
        raise LifecycleRuleError("Unsupported decision-case state.")
    return state_name


def transition_is_allowed(current: object, requested: object) -> bool:
    current_state = validate_case_state(current)
    requested_state = validate_case_state(requested)
    return requested_state == current_state or requested_state in CASE_TRANSITIONS[current_state]


def require_transition(current: object, requested: object) -> str:
    requested_state = validate_case_state(requested)
    if not transition_is_allowed(current, requested_state):
        raise LifecycleRuleError(
            f"Decision case cannot transition from {current!s} to {requested_state}."
        )
    return requested_state


def phase_actions_for_state(
    state_name: object,
    *,
    source_locked: bool = False,
    has_pending_evidence: bool = False,
    has_validated_scenarios: bool = False,
    has_retryable_execution: bool = False,
    has_cancellable_execution: bool = False,
    agent_available: bool = True,
    extra_disabled: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Return the server-owned action allowlist with explicit disabled reasons."""

    canonical = validate_case_state(state_name)
    disabled = set(extra_disabled)
    actions: list[dict[str, object]] = []
    for action_id in _PHASE_ACTIONS_BY_STATE[canonical]:
        reason: str | None = None
        enabled = action_id not in disabled
        if action_id == "lock_case_basis" and source_locked:
            enabled = False
            reason = "The immutable case basis is already locked."
        elif action_id == "review_evidence" and not has_pending_evidence:
            enabled = False
            reason = "No evidence candidates are awaiting human review."
        elif (
            action_id in {"create_scenario", "compare_scenarios"}
            and not source_locked
        ):
            enabled = False
            reason = "Lock an eligible Annual source and analysis basis first."
        elif action_id == "confirm_scenarios" and not has_validated_scenarios:
            enabled = False
            reason = "At least one current validated scenario is required."
        elif action_id == "retry_failed_execution" and not has_retryable_execution:
            enabled = False
            reason = "No linked TEA attempt is eligible for retry."
        elif action_id == "cancel_execution" and not has_cancellable_execution:
            enabled = False
            reason = "No linked queued or running TEA attempt can be cancelled."
        elif action_id == "ask_decision_agent" and not agent_available:
            enabled = False
            reason = "The Decision Agent is unavailable; deterministic readiness remains available."
        if action_id in disabled and reason is None:
            reason = "This action is not currently supported by deterministic case state."
        actions.append(
            {
                "id": action_id,
                "label": ACTION_LABELS[action_id],
                "enabled": enabled,
                "disabled_reason": reason,
            }
        )
    return actions


def evidence_class_requires_rationale(evidence_class: object) -> bool:
    canonical = str(evidence_class or "").strip()
    if canonical not in EVIDENCE_CLASSES:
        raise LifecycleRuleError("Unsupported evidence class.")
    return canonical in PROVISIONAL_EVIDENCE_CLASSES
