"""The OpenAI request/response cycle behind the dashboard chat.

Builds the grounded run context, decides whether web search is permitted, calls
the Responses API, and normalises tool calls out of the reply. ``openai`` is
imported inside the call so the dependency is only needed when chat is used.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from time import perf_counter

from sbepv.agent.message_guards import _ambiguous_numeric_iam, _visible_iam_selection
from sbepv.agent.prompts import SOLAR_AGENT_INSTRUCTIONS, SOLAR_MODEL_KNOWLEDGE
from sbepv.agent.scenario_math import _normalise_config_keys
from sbepv.agent.tool_schemas import (
    MAX_PARAMETER_SWEEP_VALUES,
    PARAMETER_SWEEP_TOOL,
    SCENARIO_TOOL,
)
from sbepv.agent import tools as agent_tools
from sbepv.api import config, job_store, serializers, state
from sbepv.api.schemas import ChatMessage, ChatRequest

logger = logging.getLogger(__name__)


def _clean_chat_history(
    history: list[ChatMessage], *, current_message: str | None = None
) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history[-8:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = (item.content or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:1400]})
    if (
        cleaned
        and cleaned[-1]["role"] == "user"
        and current_message
        and cleaned[-1]["content"] == current_message.strip()[:1400]
    ):
        cleaned.pop()
    return cleaned


def _deduplicated_job_context(job: dict[str, Any]) -> dict[str, Any]:
    """Keep trusted fields while removing large values repeated in nested sections."""

    result = serializers._public_value(job.get("result") or {})
    if not isinstance(result, dict):
        result = {}
    stats = result.get("stats")
    if isinstance(stats, dict):
        stats = deepcopy(stats)
        for key in (
            "calibration_factors",
            "factor_driver_diagnostics",
            "data_quality",
            "data_quality_review",
            "data_quality_warnings",
        ):
            if key in result and stats.get(key) == result.get(key):
                stats.pop(key, None)
        result["stats"] = stats

    provenance = serializers._public_value(job.get("provenance") or {})
    if isinstance(provenance, dict):
        if provenance.get("data_quality") == result.get("data_quality"):
            provenance.pop("data_quality", None)

    artifacts = serializers._public_value(job.get("artifacts") or {})
    if isinstance(artifacts, dict):
        workbook = artifacts.get("model_workbook")
        if isinstance(workbook, dict) and workbook.get("url") == result.get("excel"):
            artifacts.pop("model_workbook", None)
        if artifacts.get("input_plots") == result.get("input_plots"):
            artifacts.pop("input_plots", None)

    return {
        "result": result,
        "provenance": provenance,
        "artifacts": artifacts,
    }


def _chat_run_context(
    job_id: str | None, active_mode: str | None = None
) -> tuple[str | None, dict]:
    resolved_job_id = job_id or job_store._latest_completed_job_id(active_mode)
    if not resolved_job_id:
        return None, {
            "state": "missing",
            "message": "No completed dashboard run is available yet.",
        }

    job_record = job_store._get_job_record(resolved_job_id)
    job = None if job_record is None else {**job_record, **state.JOBS.get(resolved_job_id, {})}
    if job is None:
        return resolved_job_id, {
            "job_id": resolved_job_id,
            "state": "missing",
            "message": (
                "The browser had a cached job id, but this FastAPI process does "
                "not have that job in memory. Ask the user to rerun analysis for "
                "grounded run-specific answers."
            ),
        }

    context = {
        "job_id": resolved_job_id,
        "mode": job.get("mode", "validation"),
        "state": job.get("state"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
    }
    if "request" in job:
        context["request"] = serializers._public_value(job["request"])
    if job.get("state") == "done":
        compact = _deduplicated_job_context(job)
        context["result"] = compact["result"]
        if job.get("comparison"):
            context["comparison"] = serializers._public_value(job["comparison"])
        if compact["provenance"]:
            context["provenance"] = compact["provenance"]
        if compact["artifacts"]:
            context["artifacts"] = compact["artifacts"]
    elif job.get("state") == "error":
        context["error"] = serializers._public_error(job.get("error"))
    return resolved_job_id, context


def _recent_run_context(
    active_mode: str | None,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return a small durable run index for history-aware questions.

    Full results stay attached only to the selected run.  This index is deliberately
    compact so the agent can resolve references such as "the previous annual run"
    without repeating large workbooks, plots, or diagnostic payloads.
    """

    activity_limit = max(0, min(int(limit), 10))
    snapshot = state.AGENT_STORE.snapshot_state(
        mode=None,
        recent_limit=activity_limit * MAX_PARAMETER_SWEEP_VALUES,
    )
    request_fields = {
        "years",
        "from_date",
        "from_time",
        "to_date",
        "to_time",
        "interval_value",
        "interval_unit",
        "calibrate_model",
        "backtrack",
        "iam_model",
        "iam_a_r",
        "curtailment_enabled",
        "curtailment_limit_kw",
        "solaredge_inverter_efficiency",
        "solaredge_bos_efficiency",
        "solectria_inverter_efficiency",
        "solectria_bos_efficiency",
    }
    def sweep_metadata(job: dict[str, Any]) -> dict[str, Any] | None:
        provenance = job.get("provenance")
        metadata = (
            provenance.get("scenario_sweep")
            if isinstance(provenance, dict)
            else None
        )
        if (
            isinstance(metadata, dict)
            and metadata.get("type") == "parameter_sweep"
            and str(metadata.get("sweep_id") or "").strip()
        ):
            return metadata
        return None

    def activity_key(job: dict[str, Any]) -> tuple[str, str]:
        metadata = sweep_metadata(job)
        if metadata is not None:
            return "sweep", str(metadata["sweep_id"])
        return "job", str(job.get("id") or "")

    def compact_job(job: dict[str, Any]) -> dict[str, Any]:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        annual_rows = stats.get("annual_energy_by_year")
        request = job.get("request") if isinstance(job.get("request"), dict) else {}
        return {
            "job_id": job.get("id"),
            "kind": job.get("kind"),
            "mode": job.get("mode"),
            "state": job.get("state"),
            "origin": "Solar Agent" if job.get("proposal_id") else "Dashboard",
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
            "request": {
                key: value for key, value in request.items() if key in request_fields
            },
            "metrics": {
                "solaredge_predicted_kwh": stats.get("se_predicted_kwh"),
                "solectria_predicted_kwh": stats.get("sol_predicted_kwh"),
                "solaredge_model_delta_pct": stats.get("se_pct"),
                "solectria_model_delta_pct": stats.get("sol_pct"),
                "year_count": (
                    len(annual_rows) if isinstance(annual_rows, list) else None
                ),
                "full_year_count": (
                    sum(
                        1
                        for row in annual_rows
                        if isinstance(row, dict)
                        and (
                            row.get("coverage") in {"complete", "full"}
                            or row.get("is_complete_year") is True
                            or row.get("coverage_status") == "complete"
                            or row.get("complete_calendar_year") is True
                            or row.get("cdf_eligible") is True
                        )
                    )
                    if isinstance(annual_rows, list)
                    else None
                ),
            },
        }

    terminal_jobs = snapshot["recent_jobs"]
    selected_keys: list[tuple[str, str]] = []
    for job in terminal_jobs:
        key = activity_key(job)
        if key not in selected_keys:
            if len(selected_keys) >= activity_limit:
                break
            selected_keys.append(key)

    selected_sweep_ids = [key for kind, key in selected_keys if kind == "sweep"]
    if selected_sweep_ids:
        jobs_by_id = {str(job["id"]): job for job in terminal_jobs}
        for job in state.AGENT_STORE.list_parameter_sweep_jobs(selected_sweep_ids):
            jobs_by_id.setdefault(str(job["id"]), job)
        terminal_jobs = list(jobs_by_id.values())

    summaries: list[dict[str, Any]] = []
    for key in selected_keys:
        members = [job for job in terminal_jobs if activity_key(job) == key]
        if key[0] != "sweep":
            summaries.append(compact_job(members[0]))
            continue
        metadata = sweep_metadata(members[0]) or {}
        ordered_members = sorted(
            members,
            key=lambda job: int((sweep_metadata(job) or {}).get("index", 0)),
        )
        summaries.append(
            {
                "activity_type": "parameter_sweep",
                "sweep_id": key[1],
                "mode": members[0].get("mode"),
                "state": (
                    "done"
                    if all(job.get("state") == "done" for job in members)
                    and len(members) >= int(metadata.get("candidate_count") or 0)
                    else "incomplete"
                ),
                "parameter": metadata.get("parameter"),
                "candidate_count": metadata.get("candidate_count"),
                "loaded_member_count": len(members),
                "completed_at": max(
                    (str(job.get("completed_at") or "") for job in members),
                    default="",
                ),
                "members": [
                    {
                        "index": (sweep_metadata(job) or {}).get("index"),
                        "value": (sweep_metadata(job) or {}).get("value"),
                        **compact_job(job),
                    }
                    for job in ordered_members
                ],
            }
        )
    return summaries


def _should_allow_web_search(message: str) -> bool:
    import re

    text = (message or "").lower()
    explicit_external_intent = re.search(
        r"\b(?:web|internet|online|sources?|citations?|references?|external|research|search)\b"
        r"|\blook\s+up\b",
        text,
    )
    if explicit_external_intent:
        return True
    if re.search(r"\b(?:weather|forecast|nrel|pvlib|pvmismatch)\b", text):
        return True
    current_external_topic = re.search(
        r"\b(?:latest|current|today|recent)\b.*"
        r"\b(?:news|version|release|documentation|standard|specification|policy|law|price)\b"
        r"|\b(?:news|version|release|documentation|standard|specification|policy|law|price)\b.*"
        r"\b(?:latest|current|today|recent)\b",
        text,
    )
    return current_external_topic is not None


def _extract_response_text(response) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    output = getattr(response, "output", None) or []
    parts: list[str] = []
    for item in output:
        content = getattr(item, "content", None) or []
        for block in content:
            block_text = getattr(block, "text", None)
            if block_text:
                parts.append(block_text)
    return "\n".join(parts).strip()


def _extract_web_sources(response: Any) -> list[dict[str, str]]:
    """Extract URL citations without mixing them into trusted model evidence."""
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in (getattr(response, "output", None) or []):
        for block in (_response_item_value(item, "content", []) or []):
            for annotation in (_response_item_value(block, "annotations", []) or []):
                citation = _response_item_value(annotation, "url_citation", annotation)
                url = _response_item_value(citation, "url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                title = _response_item_value(citation, "title") or "External source"
                sources.append({"title": str(title)[:200], "url": url})
    return sources


def _response_item_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _scenario_tool_calls(response: Any) -> list[Any]:
    supported_tools = {
        "propose_model_scenario",
        "run_model_parameter_sweep",
        "run_iam_ar_sweep",
    }
    return [
        item
        for item in (getattr(response, "output", None) or [])
        if _response_item_value(item, "type") == "function_call"
        and _response_item_value(item, "name") in supported_tools
    ]


def _openai_agent_response(req: ChatRequest) -> dict[str, Any]:
    if not (req.message or "").strip():
        raise HTTPException(status_code=422, detail="Message is required.")
    if len(req.message) > 4000:
        raise HTTPException(
            status_code=422, detail="Message must be 4,000 characters or fewer."
        )

    resolved_job_id, run_context = _chat_run_context(req.job_id, req.active_mode)
    gpt_seconds = 0.0
    if _ambiguous_numeric_iam(req.message):
        result = {
            "reply": (
                "**IAM clarification**\n\nYour model supports **Physical IAM** or "
                "**Martin-Ruiz IAM** with an `a_r` coefficient. Is your numeric "
                "value intended to be the Martin-Ruiz `a_r`, or do you want to "
                "keep Physical IAM? "
                "I will not start a run until that is explicit."
            ),
            "job_id": resolved_job_id,
            "web_search_enabled": False,
            "action": None,
        }
        result["timing"] = serializers._chat_timing(
            gpt_seconds=gpt_seconds, model_job_id=resolved_job_id
        )
        return result

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The OpenAI Python package is not installed. Install the project "
                "dependencies from requirements.txt, then restart the server."
            ),
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not available to the server process.",
        )

    allow_web = _should_allow_web_search(req.message)
    tools: list[dict[str, Any]] = (
        [SCENARIO_TOOL, PARAMETER_SWEEP_TOOL]
        if req.allow_scenario_actions
        else []
    )
    if allow_web:
        tools.append({"type": "web_search"})
    payload = {
        "question": req.message.strip(),
        "context_generated_at": datetime.now(config.LOCAL_TZ).isoformat(),
        "dashboard_timezone": str(config.LOCAL_TZ),
        "dashboard_run_context": run_context,
        "active_mode": req.active_mode,
        "visible_dashboard_configuration": _normalise_config_keys(
            req.current_config
        ),
        "visible_iam_selection": _visible_iam_selection(req.current_config),
        "model_knowledge": SOLAR_MODEL_KNOWLEDGE,
        "recent_runs": _recent_run_context(req.active_mode),
        "recent_chat_history": _clean_chat_history(
            req.history, current_message=req.message
        ),
    }
    user_input = {
        "role": "user",
        "content": (
            "Answer the user's question using this JSON context. Prefer dashboard "
            "context over external sources for run-specific facts.\n\n"
            + json.dumps(payload, indent=2, default=str)
        ),
    }

    try:
        client = OpenAI(
            timeout=config.OPENAI_TIMEOUT_SECONDS,
            max_retries=config.OPENAI_MAX_RETRIES,
        )
    except TypeError:
        # Lightweight test doubles and older compatible clients may not expose
        # constructor options. The supported production SDK does.
        client = OpenAI()
    gpt_started = perf_counter()
    try:
        request_options: dict[str, Any] = {}
        if req.allow_scenario_actions:
            request_options.update(
                {"max_tool_calls": 1, "parallel_tool_calls": False}
            )
        response = client.responses.create(
            model=config.OPENAI_MODEL,
            instructions=SOLAR_AGENT_INSTRUCTIONS,
            input=[user_input],
            tools=tools,
            store=False,
            max_output_tokens=1_200,
            reasoning={"effort": config.OPENAI_REASONING_EFFORT},
            text={"verbosity": "low"},
            **request_options,
        )
    except Exception as exc:
        logger.error(
            "OpenAI request failed: type=%s status=%s request_id=%s",
            exc.__class__.__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "request_id", None),
        )
        raise HTTPException(
            status_code=502,
            detail="Solar Agent is temporarily unavailable. Please retry.",
        ) from exc
    finally:
        gpt_seconds += perf_counter() - gpt_started

    web_sources = _extract_web_sources(response)
    action: dict[str, Any] | None = None
    deterministic_reply: str | None = None
    tool_calls = _scenario_tool_calls(response) if req.allow_scenario_actions else []
    if len(tool_calls) > 1:
        deterministic_reply = (
            "I did not start a run because more than one scenario action was "
            "requested in the same response. Please ask for one scenario or one "
            "parameter sweep at a time."
        )
        tool_calls = []
    if tool_calls:
        tool_call = tool_calls[0]
        try:
            arguments = json.loads(_response_item_value(tool_call, "arguments", "{}"))
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            tool_name = _response_item_value(tool_call, "name")
            if tool_name == "run_model_parameter_sweep":
                tool_result, action = agent_tools._handle_parameter_sweep_tool(req, arguments)
            elif tool_name == "run_iam_ar_sweep":
                tool_result, action = agent_tools._handle_iam_ar_sweep_tool(req, arguments)
            else:
                tool_result, action = agent_tools._handle_scenario_tool(req, arguments)
        except HTTPException as exc:
            tool_result = {"status": "rejected", "message": str(exc.detail)}
            action = None
        except (TypeError, ValueError, json.JSONDecodeError):
            tool_result = {
                "status": "rejected",
                "message": "The requested scenario settings were invalid.",
            }
            action = None
        deterministic_reply = str(
            tool_result.get("message") or "Scenario request prepared."
        )

    reply = deterministic_reply or _extract_response_text(response)
    if not reply:
        reply = "I could not generate a response from the model for this question."
    result = {
        "reply": reply,
        "job_id": resolved_job_id,
        "web_search_enabled": allow_web,
        "web_sources": web_sources,
        "action": action,
    }
    timing_job_id = resolved_job_id
    if action:
        if action.get("type") == "job_started":
            timing_job_id = (action.get("job") or {}).get("job_id")
        elif action.get("type") == "job_batch_started":
            jobs = action.get("jobs") or []
            timing_job_id = jobs[0].get("job_id") if jobs else None
        elif action.get("type") in {"proposal", "proposal_batch"}:
            timing_job_id = None
    result["timing"] = serializers._chat_timing(
        gpt_seconds=gpt_seconds, model_job_id=timing_job_id
    )
    return result


def _openai_chat_response(req: ChatRequest) -> tuple[str, str | None, bool]:
    """Backward-compatible helper used by the existing unit tests."""
    result = _openai_agent_response(req)
    return result["reply"], result["job_id"], result["web_search_enabled"]
