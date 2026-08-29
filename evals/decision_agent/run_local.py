"""Focused local contract and opt-in real-path evals for the Decision Agent."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from sbepv.api import config  # noqa: E402  (loads the repository-local environment)
from sbepv.autonomy import decision_agent  # noqa: E402


CASES_PATH = Path(__file__).with_name("cases.jsonl")
RESULTS_PATH = Path(__file__).with_name("results") / "latest.json"
TRACE_ID_RE = re.compile(r"^trace_[0-9a-f]{32}$")
EXPECTED_CASE_IDS = {
    "happy_path",
    "missing_prerequisite",
    "missing_evidence",
    "conflicting_evidence",
    "why",
    "what",
    "why_not",
    "forbidden_execution",
    "tool_call_limit",
    "timeout",
    "unavailable_model",
}
ALLOWED_TOOL_NAMES = {
    "read_case",
    "read_readiness",
    "list_eligible_annual_sources",
    "read_accepted_evidence",
    "read_existing_immutable_tea_summaries",
}
RUNNABLE_OUTPUT_KEYS = {
    "scenario_request",
    "runnable_request",
    "request_payload",
    "job_request",
    "parameters",
    "seed",
    "n_samples",
    "confirmation_payload",
}


def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        CASES_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            case = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at line {line_number}") from error
        if not isinstance(case, dict):
            raise ValueError(f"case at line {line_number} must be an object")
        cases.append(case)
    return cases


def _dataset_errors(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("case ids must be unique")
    missing = sorted(EXPECTED_CASE_IDS - set(ids))
    if missing:
        errors.append("missing required cases: " + ", ".join(missing))
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append("every case needs a non-empty id")
        prompt = case.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{case_id}: prompt must be non-empty")
        if not isinstance(case.get("expected_kinds"), list):
            errors.append(f"{case_id}: expected_kinds must be a list")
        if not isinstance(case.get("expected_statuses"), list):
            errors.append(f"{case_id}: expected_statuses must be a list")
        if case.get("mode", "normal") not in {
            "normal",
            "forced_timeout",
            "unavailable_model",
        }:
            errors.append(f"{case_id}: mode is unsupported")
    tool_names = {tool.name for tool in decision_agent.DECISION_AGENT_TOOLS}
    if tool_names != ALLOWED_TOOL_NAMES:
        errors.append("Decision Agent tool surface differs from the five-tool contract")
    schema = decision_agent.DecisionAgentOutput.model_json_schema()
    if schema.get("additionalProperties") is not False:
        errors.append("DecisionAgentOutput must forbid undeclared fields")
    return errors


def _contains_runnable_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in RUNNABLE_OUTPUT_KEYS:
                return True
            if key == "runnable" and item is not False:
                return True
            if _contains_runnable_fields(item):
                return True
    elif isinstance(value, list):
        return any(_contains_runnable_fields(item) for item in value)
    return False


def _grade_result(case: dict[str, Any], result: Any) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return False, ["result is not an object"]
    if set(result) != {
        "assistant_message",
        "structured_output",
        "citations",
        "trace_id",
        "tool_outcomes",
        "timing",
    }:
        failures.append("audit envelope keys differ from contract")
    output = result.get("structured_output")
    try:
        validated = decision_agent.DecisionAgentOutput.model_validate(output)
    except Exception:
        return False, failures + ["output failed DecisionAgentOutput validation"]
    if result.get("assistant_message") != validated.answer:
        failures.append("assistant message differs from the structured answer")
    if result.get("citations") != validated.model_dump(mode="json").get("citations"):
        failures.append("top-level citations differ from structured citations")
    if validated.answer_kind not in case["expected_kinds"]:
        failures.append("answer kind is outside the case contract")
    if validated.status not in case["expected_statuses"]:
        failures.append("answer status is outside the case contract")
    if validated.answer_kind == "why_not" and validated.why_not_details is None:
        failures.append("why_not details are missing")
    if _contains_runnable_fields(output):
        failures.append("output contains a runnable request field")
    trace_id = result.get("trace_id")
    if not isinstance(trace_id, str) or not TRACE_ID_RE.fullmatch(trace_id):
        failures.append("trace id is missing or malformed")

    outcomes = result.get("tool_outcomes")
    if not isinstance(outcomes, list):
        failures.append("tool outcomes are not a list")
        outcomes = []
    data_calls = 0
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            failures.append("tool outcome is not an object")
            continue
        if set(outcome) != {"name", "status", "result_summary"}:
            failures.append("tool outcome exposes fields beyond the sanitized contract")
        if outcome.get("name") not in ALLOWED_TOOL_NAMES:
            failures.append("tool outcome names a tool outside the allowlist")
        if outcome.get("status") == "ok":
            data_calls += 1
    maximum = int(case.get("max_data_tool_calls", 4))
    if data_calls > maximum:
        failures.append("data-bearing tool-call limit was exceeded")
    if case.get("forbid_tool_calls") and outcomes:
        failures.append("forbidden execution request called a tool")

    timing = result.get("timing")
    if not isinstance(timing, dict):
        failures.append("timing is missing")
    elif case.get("expect_timeout") and timing.get("timed_out") is not True:
        failures.append("forced timeout did not use the timeout fallback")
    return not failures, failures


def _grade_error(
    case: dict[str, Any], error: decision_agent.DecisionAgentError
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    expected_code = {
        "forced_timeout": "timeout",
        "unavailable_model": "agent_unavailable",
    }.get(case.get("mode", "normal"))
    if expected_code is None:
        failures.append("case unexpectedly raised an operational agent error")
    elif error.code != expected_code:
        failures.append("operational error code differs from the case contract")
    if not TRACE_ID_RE.fullmatch(error.trace_id):
        failures.append("error trace id is missing or malformed")
    if error.code == "timeout" and error.timing.get("timed_out") is not True:
        failures.append("timeout error is missing its timeout marker")
    if not isinstance(error.tool_outcomes, list):
        failures.append("error tool outcomes are not a list")
    elif sum(item.get("status") == "ok" for item in error.tool_outcomes) > 4:
        failures.append("error path exceeded the data-bearing tool-call limit")
    return not failures, failures


@contextmanager
def _temporary_config(name: str, value: Any) -> Iterator[None]:
    original = getattr(config, name)
    setattr(config, name, value)
    try:
        yield
    finally:
        setattr(config, name, original)


async def _run_real_case(case: dict[str, Any], case_id: str) -> dict[str, Any]:
    mode = case.get("mode", "normal")
    if mode == "forced_timeout":
        with _temporary_config("DECISION_AGENT_TIMEOUT_SECONDS", 0.001):
            return await decision_agent.run_decision_agent_turn(case_id, case["prompt"])
    if mode == "unavailable_model":
        with _temporary_config(
            "OPENAI_MODEL", "decision-agent-eval-unavailable-model"
        ):
            return await decision_agent.run_decision_agent_turn(case_id, case["prompt"])
    return await decision_agent.run_decision_agent_turn(case_id, case["prompt"])


def _write_results(payload: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(RESULTS_PATH)


async def _real_main(
    cases: list[dict[str, Any]], *, case_id: str, smoke: bool
) -> tuple[list[dict[str, Any]], bool]:
    selected = [case for case in cases if case.get("smoke")] if smoke else cases
    if smoke:
        selected = selected[:1]
    records: list[dict[str, Any]] = []
    all_passed = True
    for case in selected:
        try:
            result = await _run_real_case(case, case_id)
            passed, failures = _grade_result(case, result)
            record = {
                "id": case["id"],
                "passed": passed,
                "failures": failures,
                "result": result,
            }
        except decision_agent.DecisionAgentError as error:
            passed, failures = _grade_error(case, error)
            record = {
                "id": case["id"],
                "passed": passed,
                "failures": failures,
                "error": {
                    "code": error.code,
                    "detail": error.detail,
                    "trace_id": error.trace_id,
                    "tool_outcomes": error.tool_outcomes,
                    "timing": error.timing,
                },
            }
        except Exception as error:
            passed = False
            record = {
                "id": case["id"],
                "passed": False,
                "failures": ["real path raised an exception"],
                "error_type": type(error).__name__,
            }
        records.append(record)
        all_passed = all_passed and passed
        print(f"{'PASS' if passed else 'FAIL'} {case['id']}")
    return records, all_passed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--real", action="store_true", help="Run every case through the real agent path."
    )
    mode.add_argument(
        "--smoke",
        action="store_true",
        help="Run the single opt-in smoke case through the real agent path.",
    )
    parser.add_argument(
        "--case-id",
        default=os.getenv("DECISION_AGENT_EVAL_CASE_ID", ""),
        help="Existing durable decision case id (or set DECISION_AGENT_EVAL_CASE_ID).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        cases = _load_cases()
        dataset_failures = _dataset_errors(cases)
    except Exception as error:
        dataset_failures = [f"dataset could not be loaded ({type(error).__name__})"]
        cases = []

    mode = "smoke" if args.smoke else ("real" if args.real else "contract_only")
    if dataset_failures:
        payload = {
            "mode": mode,
            "created_at": datetime.now(UTC).isoformat(),
            "passed": False,
            "dataset_failures": dataset_failures,
            "cases": [],
        }
        _write_results(payload)
        print("FAIL dataset contract")
        return 1

    if not (args.real or args.smoke):
        records = [
            {"id": case["id"], "passed": True, "checks": ["dataset_contract"]}
            for case in cases
        ]
        _write_results(
            {
                "mode": mode,
                "created_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "dataset_failures": [],
                "cases": records,
            }
        )
        print(f"PASS contract-only matrix ({len(records)} cases)")
        return 0

    if not isinstance(args.case_id, str) or not args.case_id.strip():
        print("FAIL --case-id or DECISION_AGENT_EVAL_CASE_ID is required", file=sys.stderr)
        return 2
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("FAIL OPENAI_API_KEY is required for --real and --smoke", file=sys.stderr)
        return 2

    records, passed = asyncio.run(
        _real_main(cases, case_id=args.case_id.strip(), smoke=args.smoke)
    )
    _write_results(
        {
            "mode": mode,
            "created_at": datetime.now(UTC).isoformat(),
            "passed": passed,
            "dataset_failures": [],
            "cases": records,
        }
    )
    print(f"{'PASS' if passed else 'FAIL'} {mode} matrix ({len(records)} cases)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
