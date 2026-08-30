"""Deterministic manager-report snapshots, PDF rendering, and artifact verification.

Reports are derived only from immutable Decision Brief or authenticated sign-off
snapshots.  This module performs no store access and never accepts a model response.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import escape
from importlib import metadata, resources
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid
from typing import Any
import zlib


REPORT_GENERATION_CONTRACT_VERSION = "autonomy-manager-report-v1"
REPORT_SNAPSHOT_SCHEMA_VERSION = "autonomy-manager-report-snapshot-v1"
REPORT_MAX_BYTES = 10 * 1024 * 1024
REPORT_MAX_PAGES = 100
_REPORT_MEDIA_TYPE = "application/pdf"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DecisionReportError(RuntimeError):
    """Fail-closed report error with a stable public code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RenderedDecisionReport:
    pdf_bytes: bytes
    pdf_sha256: str
    byte_count: int
    page_count: int
    renderer_fingerprint: str


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise DecisionReportError(
            "report_snapshot_not_canonical",
            "The report snapshot is not finite canonical JSON.",
        ) from exc


def canonical_sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _font_identity() -> tuple[Path, str]:
    try:
        font_path = Path(str(resources.files("reportlab") / "fonts" / "Vera.ttf"))
        payload = font_path.read_bytes()
    except Exception as exc:  # pragma: no cover - dependency/runtime failure
        raise DecisionReportError(
            "report_renderer_font_unavailable",
            "The deterministic report font is unavailable.",
        ) from exc
    return font_path, sha256(payload).hexdigest()


def renderer_fingerprint() -> str:
    """Return the exact renderer/runtime identity stored with every report."""

    try:
        reportlab_version = metadata.version("reportlab")
        pypdf_version = metadata.version("pypdf")
    except metadata.PackageNotFoundError as exc:
        raise DecisionReportError(
            "report_renderer_dependency_unavailable",
            "The deterministic PDF renderer dependencies are unavailable.",
        ) from exc
    _, font_sha256 = _font_identity()
    return (
        f"reportlab={reportlab_version};pypdf={pypdf_version};"
        f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro};"
        f"zlib={zlib.ZLIB_RUNTIME_VERSION};font=Vera.ttf:{font_sha256};"
        "invariant=1;page_compression=1"
    )


def _technical_exports(brief: Mapping[str, Any]) -> list[dict[str, str]]:
    bundle = brief.get("comparison_bundle")
    scenarios = bundle.get("scenarios") if isinstance(bundle, Mapping) else None
    result: list[dict[str, str]] = []
    if not isinstance(scenarios, Sequence) or isinstance(scenarios, (str, bytes)):
        return result
    for scenario in scenarios[:4]:
        if not isinstance(scenario, Mapping):
            continue
        attempt = scenario.get("attempt")
        attempt = attempt if isinstance(attempt, Mapping) else {}
        job_id = str(attempt.get("tea_job_id") or "").strip()
        if not job_id:
            continue
        label = str(scenario.get("label") or scenario.get("scenario_id") or "Scenario")
        for export_format, media_type in (
            ("csv", "application/zip"),
            (
                "xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ):
            result.append(
                {
                    "scenario_revision_id": str(
                        scenario.get("scenario_revision_id") or ""
                    ),
                    "label": f"{label} {export_format.upper()}",
                    "url": f"/api/technoeconomic/jobs/{job_id}/exports/{export_format}",
                    "media_type": media_type,
                }
            )
    return result


def prepare_report_snapshot(
    *,
    report_kind: str,
    case: Mapping[str, Any],
    brief: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    signoff: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Freeze one deterministic report snapshot and content-derived report ID."""

    kind = str(report_kind).strip().lower()
    if kind not in {"draft", "final"}:
        raise DecisionReportError(
            "report_kind_invalid", "Report kind must be draft or final."
        )
    if (kind == "final") != (signoff is not None):
        raise DecisionReportError(
            "report_signoff_mismatch",
            "Final reports require an exact sign-off; draft reports must be unsigned.",
        )
    case_payload = deepcopy(dict(case))
    brief_payload = deepcopy(dict(brief))
    recommendation_payload = deepcopy(dict(recommendation))
    case_id = str(case_payload.get("case_id") or "")
    case_revision = case_payload.get("revision")
    brief_revision_id = str(brief_payload.get("brief_revision_id") or "")
    brief_revision = brief_payload.get("revision")
    if (
        not case_id.startswith("case_")
        or isinstance(case_revision, bool)
        or not isinstance(case_revision, int)
        or case_revision <= 0
        or not brief_revision_id.startswith("dbr_")
        or isinstance(brief_revision, bool)
        or not isinstance(brief_revision, int)
        or brief_revision <= 0
    ):
        raise DecisionReportError(
            "report_source_identity_invalid",
            "The report source is missing its immutable case or brief identity.",
        )
    contract_version = str(recommendation_payload.get("contract_version") or "")
    contract_digest = str(recommendation_payload.get("contract_digest") or "")
    if not contract_version or not _SHA256_RE.fullmatch(contract_digest):
        raise DecisionReportError(
            "report_recommendation_contract_invalid",
            "The report source has no approved recommendation contract identity.",
        )
    source_identity: dict[str, Any] = {
        "kind": kind,
        "case_id": case_id,
        "case_revision": case_revision,
        "brief_revision_id": brief_revision_id,
        "comparison_bundle_sha256": brief_payload.get(
            "comparison_bundle_sha256"
        ),
        "provenance_sha256": brief_payload.get("provenance_sha256"),
        "recommendation_contract_version": contract_version,
        "recommendation_contract_digest": contract_digest,
        "generation_contract_version": REPORT_GENERATION_CONTRACT_VERSION,
        "renderer_fingerprint": renderer_fingerprint(),
    }
    if signoff is not None:
        source_identity["signoff_id"] = signoff.get("signoff_id") or signoff.get("id")
        source_identity["decision_snapshot_sha256"] = signoff.get(
            "decision_snapshot_sha256"
        )
    report_identity_sha256 = canonical_sha256(source_identity)
    report_id = f"drpt_{report_identity_sha256[:32]}"
    technical_exports = _technical_exports(brief_payload)
    snapshot = {
        "schema_version": REPORT_SNAPSHOT_SCHEMA_VERSION,
        "case": case_payload,
        "brief": brief_payload,
        "recommendation": recommendation_payload,
        "signoff": deepcopy(dict(signoff)) if signoff is not None else None,
        "technical_exports": technical_exports,
        "report": {
            "report_id": report_id,
            "revision": brief_revision,
            "kind": kind,
            "watermark": "DRAFT - UNSIGNED" if kind == "draft" else None,
            "generation_contract_version": REPORT_GENERATION_CONTRACT_VERSION,
            "renderer_fingerprint": source_identity["renderer_fingerprint"],
            "report_identity_sha256": report_identity_sha256,
            "recommendation_contract_version": contract_version,
            "recommendation_contract_digest": contract_digest,
            "chart_contracts": [
                {
                    "id": "directional-outcome-probabilities",
                    "question": "How much probability supports each decision direction?",
                    "family": "composition",
                    "variant": "horizontal_stacked_bar",
                    "palette_policy": "hard_two_root_cap_plus_neutral",
                    "non_color_encoding": "direct_labels_and_table_fallback",
                    "population": "all durable TEA realizations per selected scenario",
                }
            ],
        },
    }
    # Validate once here so rendering and persistence consume the same exact shape.
    _canonical_json(snapshot)
    return snapshot


def _plain(value: Any, *, maximum: int = 4_000) -> str:
    if value is None:
        return "Not available"
    text = str(value).replace("\x00", "").strip()
    return text[:maximum] if text else "Not available"


def _paragraph_text(value: Any, *, maximum: int = 4_000) -> str:
    return escape(_plain(value, maximum=maximum)).replace("\n", "<br/>")


def _exact_number(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        try:
            return json.dumps(value, allow_nan=False, separators=(",", ":"))
        except ValueError:
            return "Not available"
    return _plain(value, maximum=200)


def _friendly_metric(metric_id: str) -> str:
    known = {
        "LifecycleLCOE_SOL": "Solectria lifecycle LCOE",
        "LifecycleLCOE_SE": "SolarEdge lifecycle LCOE",
        "headline_positive_gain_lcoo": "All-in LCOO (positive lifecycle gain)",
        "signed_nonzero_lcoo": "Signed all-in LCOO",
    }
    if metric_id in known:
        return known[metric_id]
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", metric_id)
    return text.replace("_", " ").strip()


def _scenario_rows(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    brief = snapshot.get("brief")
    bundle = brief.get("comparison_bundle") if isinstance(brief, Mapping) else None
    scenarios = bundle.get("scenarios") if isinstance(bundle, Mapping) else None
    if not isinstance(scenarios, Sequence) or isinstance(scenarios, (str, bytes)):
        return []
    return [item for item in scenarios[:4] if isinstance(item, Mapping)]


def _tradeoff_probability_rows(
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in _scenario_rows(snapshot):
        result = scenario.get("result")
        outcomes = result.get("joint_outcomes") if isinstance(result, Mapping) else None
        tradeoffs = outcomes.get("tradeoff_classes") if isinstance(outcomes, Mapping) else None
        probabilities = tradeoffs.get("probabilities") if isinstance(tradeoffs, Mapping) else None
        if not isinstance(probabilities, Mapping):
            continue
        try:
            se_probability = Decimal(
                str(probabilities.get("cost_neutral_energy_gain", 0.0) or 0.0)
            ) + Decimal(
                str(probabilities.get("cost_saving_energy_gain", 0.0) or 0.0)
            )
            sol_probability = Decimal(
                str(probabilities.get("cost_increase_energy_loss", 0.0) or 0.0)
            )
        except InvalidOperation:
            continue
        other_probability = max(
            Decimal("0"),
            min(Decimal("1"), Decimal("1") - se_probability - sol_probability),
        )
        rows.append(
            {
                "label": _plain(
                    scenario.get("label") or scenario.get("scenario_revision_id"),
                    maximum=80,
                ),
                "scenario_revision_id": _plain(
                    scenario.get("scenario_revision_id"), maximum=128
                ),
                "denominator": tradeoffs.get("denominator"),
                "solaredge_dominant": se_probability,
                "solectria_dominant": sol_probability,
                "tradeoff_or_other": other_probability,
            }
        )
    return rows


def render_manager_pdf(snapshot: Mapping[str, Any]) -> RenderedDecisionReport:
    """Render one bounded answer-first stakeholder PDF deterministically."""

    try:
        from pypdf import PdfReader
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        from reportlab.platypus import (
            Flowable,
            Paragraph,
            SimpleDocTemplate,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - dependency/runtime failure
        raise DecisionReportError(
            "report_renderer_dependency_unavailable",
            "The deterministic PDF renderer dependencies are unavailable.",
        ) from exc

    snapshot_payload = deepcopy(dict(snapshot))
    report = snapshot_payload.get("report")
    case = snapshot_payload.get("case")
    brief = snapshot_payload.get("brief")
    recommendation = snapshot_payload.get("recommendation")
    if not all(
        isinstance(item, Mapping) for item in (report, case, brief, recommendation)
    ):
        raise DecisionReportError(
            "report_snapshot_invalid", "The stored report snapshot is incomplete."
        )
    kind = str(report.get("kind") or "")
    if kind not in {"draft", "final"}:
        raise DecisionReportError(
            "report_snapshot_invalid", "The report snapshot kind is invalid."
        )
    current_fingerprint = renderer_fingerprint()
    if (
        report.get("generation_contract_version")
        != REPORT_GENERATION_CONTRACT_VERSION
        or report.get("renderer_fingerprint") != current_fingerprint
    ):
        raise DecisionReportError(
            "report_renderer_identity_mismatch",
            "The report snapshot does not match the active deterministic renderer.",
        )

    font_path, _ = _font_identity()
    if "SBEVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SBEVera", str(font_path)))
    buffer = io.BytesIO()

    class InvariantCanvas(canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["invariant"] = 1
            kwargs["pageCompression"] = 1
            super().__init__(*args, **kwargs)
            self.setTitle("PV Decision Report")
            self.setSubject("Immutable Autonomy decision snapshot")
            self.setAuthor("SBE PV Operations Dashboard")
            self.setCreator(REPORT_GENERATION_CONTRACT_VERSION)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.52 * inch,
        leftMargin=0.52 * inch,
        topMargin=0.68 * inch,
        bottomMargin=0.62 * inch,
        title="PV Decision Report",
        author="SBE PV Operations Dashboard",
        subject="Immutable Autonomy decision snapshot",
        creator=REPORT_GENERATION_CONTRACT_VERSION,
    )
    styles = getSampleStyleSheet()
    ink = colors.HexColor("#183234")
    teal = colors.HexColor("#087E80")
    teal_open = colors.HexColor("#D9EEEE")
    gold = colors.HexColor("#C48A20")
    neutral = colors.HexColor("#D9E0E0")
    pale = colors.HexColor("#F4F8F7")
    warning = colors.HexColor("#9A6500")
    styles.add(
        ParagraphStyle(
            name="SBEReportTitle",
            parent=styles["Title"],
            fontName="SBEVera",
            fontSize=20,
            leading=24,
            textColor=ink,
            alignment=TA_LEFT,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SBEHeading",
            parent=styles["Heading2"],
            fontName="SBEVera",
            fontSize=12.5,
            leading=15,
            textColor=ink,
            spaceBefore=10,
            spaceAfter=6,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SBEBody",
            parent=styles["BodyText"],
            fontName="SBEVera",
            fontSize=8.4,
            leading=11.3,
            textColor=ink,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SBESmall",
            parent=styles["BodyText"],
            fontName="SBEVera",
            fontSize=6.5,
            leading=8.2,
            textColor=ink,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SBECallout",
            parent=styles["BodyText"],
            fontName="SBEVera",
            fontSize=9,
            leading=12,
            textColor=ink,
            backColor=teal_open,
            borderColor=teal,
            borderWidth=0.6,
            borderPadding=7,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SBEWarning",
            parent=styles["BodyText"],
            fontName="SBEVera",
            fontSize=8,
            leading=10.5,
            textColor=warning,
            backColor=colors.HexColor("#FFF5DC"),
            borderColor=gold,
            borderWidth=0.5,
            borderPadding=6,
            spaceAfter=6,
        )
    )

    def p(value: Any, style: str = "SBEBody") -> Any:
        return Paragraph(_paragraph_text(value), styles[style])

    def heading(value: str) -> Any:
        return Paragraph(escape(value), styles["SBEHeading"])

    def cell(value: Any, *, bold: bool = False) -> Any:
        text = _paragraph_text(value, maximum=1_000)
        if bold:
            text = f"<b>{text}</b>"
        return Paragraph(text, styles["SBESmall"])

    def table(data: list[list[Any]], widths: list[float], *, repeat: int = 1) -> Any:
        output = Table(data, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
        output.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), teal),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), "SBEVera"),
                    ("FONTSIZE", (0, 0), (-1, -1), 6.3),
                    ("LEADING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#AEBDBD")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]),
                ]
            )
        )
        return output

    class OutcomeChart(Flowable):
        def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
            super().__init__()
            self.rows = list(rows)
            self.width = 7.1 * inch
            self.height = max(1.0 * inch, (0.34 * len(self.rows) + 0.55) * inch)

        def draw(self) -> None:
            drawing = self.canv
            label_width = 1.8 * inch
            bar_width = self.width - label_width - 0.25 * inch
            bar_height = 0.17 * inch
            y = self.height - 0.32 * inch
            drawing.setFont("SBEVera", 6.5)
            drawing.setFillColor(ink)
            drawing.drawString(label_width, self.height - 0.12 * inch, "0%")
            drawing.drawRightString(self.width - 0.05 * inch, self.height - 0.12 * inch, "100%")
            for row in self.rows:
                drawing.setFillColor(ink)
                drawing.drawRightString(label_width - 0.08 * inch, y + 2, _plain(row["label"], maximum=28))
                x = label_width
                values = (
                    (float(row["solaredge_dominant"]), teal, "SE"),
                    (float(row["solectria_dominant"]), gold, "SOL"),
                    (float(row["tradeoff_or_other"]), neutral, "Other"),
                )
                for value, color, label in values:
                    segment = max(0.0, min(1.0, value)) * bar_width
                    drawing.setFillColor(color)
                    drawing.setStrokeColor(colors.white)
                    drawing.rect(x, y, segment, bar_height, fill=1, stroke=1)
                    if segment >= 0.42 * inch:
                        drawing.setFillColor(ink if color == neutral else colors.white)
                        drawing.setFont("SBEVera", 5.5)
                        drawing.drawCentredString(
                            x + segment / 2,
                            y + 3.1,
                            f"{label} {value * 100:.1f}%",
                        )
                    x += segment
                y -= 0.34 * inch
            drawing.setFillColor(ink)
            drawing.setFont("SBEVera", 5.7)
            drawing.drawString(
                label_width,
                0.04 * inch,
                "Direct labels and the exact table below provide non-color equivalents.",
            )

    def on_page(canv: Any, document: Any) -> None:
        canv.saveState()
        width, height = letter
        if kind == "draft":
            canv.setFillColor(colors.HexColor("#DDE6E6"))
            canv.setFont("SBEVera", 42)
            canv.translate(width / 2, height / 2)
            canv.rotate(35)
            canv.drawCentredString(0, 0, "DRAFT - UNSIGNED")
            canv.rotate(-35)
            canv.translate(-width / 2, -height / 2)
        canv.setStrokeColor(colors.HexColor("#B9C8C8"))
        canv.setLineWidth(0.4)
        canv.line(doc.leftMargin, 0.48 * inch, width - doc.rightMargin, 0.48 * inch)
        canv.setFillColor(ink)
        canv.setFont("SBEVera", 6.5)
        canv.drawString(doc.leftMargin, 0.29 * inch, _plain(report.get("report_id"), maximum=80))
        canv.drawRightString(
            width - doc.rightMargin,
            0.29 * inch,
            f"Page {document.page}",
        )
        canv.restoreState()

    story: list[Any] = []
    story.append(Paragraph("PV Decision Report", styles["SBEReportTitle"]))
    if kind == "draft":
        story.append(
            Paragraph(
                "<b>DRAFT - UNSIGNED.</b> This report is derived from a verified unsigned brief and is not an authenticated application sign-off.",
                styles["SBEWarning"],
            )
        )
    story.append(heading("Executive Summary"))
    question = case.get("question") or case.get("original_question")
    classification = recommendation.get("classification")
    confidence = recommendation.get("confidence")
    disposition = (
        (snapshot_payload.get("signoff") or {}).get("disposition")
        if isinstance(snapshot_payload.get("signoff"), Mapping)
        else "Unsigned"
    )
    summary_parts = [
        f"<b>Decision question.</b> {_paragraph_text(question)}",
        (
            f"<b>Outcome.</b> {_paragraph_text(classification)}; confidence "
            f"{_paragraph_text(confidence)}; disposition {_paragraph_text(disposition)}."
        ),
    ]
    reasons = recommendation.get("reasons") or recommendation.get("exact_reasons")
    if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)) and reasons:
        summary_parts.append(
            "<b>Why.</b> "
            + "; ".join(_paragraph_text(item, maximum=600) for item in reasons[:3])
        )
    warnings = recommendation.get("warnings") or recommendation.get("provisional_warnings")
    if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)) and warnings:
        summary_parts.append(
            f"<b>Decision condition.</b> {len(warnings)} stored warning(s) require attention; exact details are retained below."
        )
    for item in summary_parts[:4]:
        story.append(Paragraph(item, styles["SBECallout"]))

    story.append(heading("Decision authority"))
    authority_rows = [
        [cell("Field", bold=True), cell("Stored value", bold=True)],
        [cell("Question"), cell(question)],
        [cell("Recommendation"), cell(classification)],
        [cell("Confidence"), cell(confidence)],
        [cell("Disposition"), cell(disposition)],
    ]
    signoff_record = snapshot_payload.get("signoff")
    if isinstance(signoff_record, Mapping):
        authority_rows.extend(
            [
                [cell("Decision owner"), cell(signoff_record.get("decision_owner_name"))],
                [cell("Rationale"), cell(signoff_record.get("rationale"))],
                [cell("Acknowledgement version"), cell(signoff_record.get("acknowledgement_version"))],
                [cell("Signed at"), cell(signoff_record.get("signed_at"))],
                [
                    cell("Signature meaning"),
                    cell(
                        "Authenticated application sign-off; not a cryptographic or legal digital signature."
                    ),
                ],
            ]
        )
    story.append(table(authority_rows, [1.45 * inch, 5.65 * inch]))

    story.append(heading("Baseline and alternatives"))
    story.append(
        p(
            "Each row preserves its server-supplied unit, type-7 percentile definition, population, and selected TEA attempt. Positive deltas are SolarEdge minus Solectria."
        )
    )
    metric_rows: list[list[Any]] = [
        [
            cell("Scenario", bold=True),
            cell("Metric and population", bold=True),
            cell("P5", bold=True),
            cell("P50", bold=True),
            cell("P95", bold=True),
            cell("Unit", bold=True),
        ]
    ]
    for scenario in _scenario_rows(snapshot_payload):
        result = scenario.get("result")
        metrics = result.get("metrics") if isinstance(result, Mapping) else None
        if not isinstance(metrics, Mapping):
            metric_rows.append(
                [
                    cell(scenario.get("label")),
                    cell("Verified metrics unavailable"),
                    cell("-"), cell("-"), cell("-"), cell("-"),
                ]
            )
            continue
        for metric_id, metric in metrics.items():
            if not isinstance(metric, Mapping):
                continue
            percentiles = metric.get("percentiles")
            percentiles = percentiles if isinstance(percentiles, Mapping) else {}
            metric_label = (
                f"{_friendly_metric(str(metric_id))}\n"
                f"ID: {metric_id}; population: {metric.get('population_semantics')}; "
                f"n={metric.get('count')}"
            )
            metric_rows.append(
                [
                    cell(
                        f"{scenario.get('label')} ({scenario.get('kind')})\n"
                        f"{scenario.get('scenario_revision_id')}"
                    ),
                    cell(metric_label),
                    cell(_exact_number(percentiles.get("p5"))),
                    cell(_exact_number(percentiles.get("p50"))),
                    cell(_exact_number(percentiles.get("p95"))),
                    cell(metric.get("unit")),
                ]
            )
    story.append(
        table(
            metric_rows,
            [1.05 * inch, 2.65 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 1.3 * inch],
        )
    )

    probability_rows = _tradeoff_probability_rows(snapshot_payload)
    story.append(heading("Directional outcome probabilities"))
    story.append(
        p(
            "The chart separates only the approved SolarEdge-dominant and SolarEdge-dominated classes. Cost/energy tradeoffs remain neutral rather than being converted into a winner."
        )
    )
    if probability_rows:
        story.append(OutcomeChart(probability_rows))
        exact_probability_table: list[list[Any]] = [
            [
                cell("Scenario", bold=True),
                cell("Denominator", bold=True),
                cell("SolarEdge dominant", bold=True),
                cell("Solectria dominant", bold=True),
                cell("Tradeoff/other", bold=True),
            ]
        ]
        for row in probability_rows:
            exact_probability_table.append(
                [
                    cell(f"{row['label']}\n{row['scenario_revision_id']}"),
                    cell(_exact_number(row["denominator"])),
                    cell(_exact_number(row["solaredge_dominant"])),
                    cell(_exact_number(row["solectria_dominant"])),
                    cell(_exact_number(row["tradeoff_or_other"])),
                ]
            )
        story.append(
            table(
                exact_probability_table,
                [1.8 * inch, 0.85 * inch, 1.45 * inch, 1.45 * inch, 1.45 * inch],
            )
        )
        story.append(
            p(
                f"Interpretation: the stored recommendation is {classification}. Read each bar against the exact realization denominator and probabilities in the adjacent table; neutral segments include tradeoffs that require no unapproved willingness-to-pay assumption."
            )
        )
    else:
        story.append(p("No verified directional probability population is stored."))

    story.append(heading("Sensitivity and convergence quality"))
    sensitivity_rows: list[list[Any]] = [
        [
            cell("Scenario", bold=True),
            cell("Response", bold=True),
            cell("Driver", bold=True),
            cell("Entry delta R-squared", bold=True),
            cell("Beta/sign", bold=True),
        ]
    ]
    convergence_rows: list[list[Any]] = [
        [cell("Scenario", bold=True), cell("Status", bold=True), cell("Stored reasons", bold=True)]
    ]
    for scenario in _scenario_rows(snapshot_payload):
        result = scenario.get("result")
        if not isinstance(result, Mapping):
            continue
        sensitivity = result.get("sensitivity")
        if isinstance(sensitivity, Mapping):
            for response_id, model in sensitivity.items():
                if not isinstance(model, Mapping):
                    continue
                steps = model.get("steps")
                if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
                    for step in steps[:3]:
                        if not isinstance(step, Mapping):
                            continue
                        sensitivity_rows.append(
                            [
                                cell(scenario.get("label")),
                                cell(response_id),
                                cell(step.get("predictor_id")),
                                cell(_exact_number(step.get("incremental_r_squared"))),
                                cell(
                                    f"{_exact_number(step.get('standardized_beta'))} / "
                                    f"{_plain(step.get('sign'), maximum=20)}"
                                ),
                            ]
                        )
        convergence = result.get("convergence")
        convergence = convergence if isinstance(convergence, Mapping) else {}
        convergence_rows.append(
            [
                cell(scenario.get("label")),
                cell(convergence.get("status")),
                cell(", ".join(str(item) for item in (convergence.get("reasons") or [])[:8]) or "None"),
            ]
        )
    if len(sensitivity_rows) == 1:
        sensitivity_rows.append(
            [cell("All"), cell("Unavailable"), cell("-"), cell("-"), cell("-")]
        )
    story.append(table(sensitivity_rows, [1.2 * inch, 2.0 * inch, 1.7 * inch, 1.2 * inch, 1.0 * inch]))
    story.append(
        p(
            "Interpretation: sensitivity entries rank association within the stored simulation, not causal effects. Convergence status below is a quality gate and remains visible when stability was not demonstrated."
        )
    )
    story.append(table(convergence_rows, [1.5 * inch, 1.25 * inch, 4.35 * inch]))

    story.append(heading("What could change the decision"))
    reversal_conditions = recommendation.get("reversal_conditions")
    if not isinstance(reversal_conditions, Sequence) or isinstance(
        reversal_conditions, (str, bytes)
    ):
        reversal_conditions = brief.get("reversal_conditions")
    if isinstance(reversal_conditions, Sequence) and not isinstance(
        reversal_conditions, (str, bytes)
    ) and reversal_conditions:
        reversal_table: list[list[Any]] = [
            [cell("Condition", bold=True), cell("Evidence and controlled next action", bold=True)]
        ]
        for item in reversal_conditions[:20]:
            if isinstance(item, Mapping):
                label = item.get("label") or item.get("condition") or item.get("code")
                details = _canonical_json(item)
            else:
                label = item
                details = item
            reversal_table.append([cell(label), cell(details)])
        story.append(table(reversal_table, [2.2 * inch, 4.9 * inch]))
    else:
        story.append(
            p(
                "No completed scenario comparison or validated sensitivity result supplies a calculated reversal condition. No break-even threshold has been fabricated."
            )
        )

    story.append(heading("Evidence, warnings, caveats, and limitations"))
    caveat_rows: list[list[Any]] = [
        [cell("Type", bold=True), cell("Stored detail", bold=True)]
    ]
    for label, values in (
        ("Recommendation warning", warnings),
        ("Brief caveat", brief.get("caveats")),
        ("Model limitation", recommendation.get("model_limitations")),
        ("Evidence gap", recommendation.get("evidence_gaps")),
    ):
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            for item in values[:30]:
                caveat_rows.append(
                    [cell(label), cell(_canonical_json(item) if isinstance(item, Mapping) else item)]
                )
    if len(caveat_rows) == 1:
        caveat_rows.append([cell("Status"), cell("No stored caveats or warnings.")])
    story.append(table(caveat_rows, [1.6 * inch, 5.5 * inch]))

    story.append(heading("Recommended next step"))
    next_actions = recommendation.get("next_actions") or recommendation.get("recommended_next_steps")
    if isinstance(next_actions, Sequence) and not isinstance(next_actions, (str, bytes)) and next_actions:
        for index, item in enumerate(next_actions[:10], start=1):
            story.append(p(f"{index}. {_plain(item, maximum=1_000)}"))
    elif classification == "no_decisive_winner":
        story.append(
            p(
                "Defer a directional choice or run a controlled, evidence-backed follow-up scenario that addresses the stored uncertainty. Do not infer a willingness-to-pay threshold that was not modeled."
            )
        )
    else:
        story.append(
            p(
                "Apply the recorded disposition and monitor the listed convergence, evidence, and reversal conditions. Create a new controlled case revision if any source or assumption changes."
            )
        )

    story.append(heading("Further questions"))
    further_questions = recommendation.get("further_questions")
    if isinstance(further_questions, Sequence) and not isinstance(
        further_questions, (str, bytes)
    ) and further_questions:
        for item in further_questions[:10]:
            story.append(p(f"- {_plain(item, maximum=1_000)}"))
    else:
        story.append(
            p(
                "Would new accepted evidence, a failed convergence gate, or a completed controlled reversal scenario change the disposition?"
            )
        )

    story.append(heading("Readable audit trail"))
    bundle = brief.get("comparison_bundle")
    bundle = bundle if isinstance(bundle, Mapping) else {}
    confirmation = bundle.get("confirmation")
    confirmation = confirmation if isinstance(confirmation, Mapping) else {}
    basis_lock = case.get("basis_lock") or case.get("source_lock")
    basis_lock = basis_lock if isinstance(basis_lock, Mapping) else {}
    audit_rows: list[list[Any]] = [
        [cell("Record", bold=True), cell("Identifier", bold=True), cell("Hash or version", bold=True)]
    ]
    audit_items = [
        ("Case", case.get("case_id"), f"revision {case.get('revision')}"),
        ("Calibration", basis_lock.get("calibration_job_id"), basis_lock.get("calibration_promoted_at")),
        ("Annual source", basis_lock.get("source_annual_job_id") or basis_lock.get("annual_job_id"), basis_lock.get("source_snapshot_sha256")),
        ("Scenario confirmation", confirmation.get("confirmation_id"), confirmation.get("receipt_sha256")),
        ("Comparison bundle", brief.get("comparison_bundle_id"), brief.get("comparison_bundle_sha256")),
        ("Decision Brief", brief.get("brief_revision_id"), brief.get("provenance_sha256")),
        ("Recommendation contract", recommendation.get("contract_version"), recommendation.get("contract_digest")),
        ("Sign-off", (signoff_record or {}).get("signoff_id") if isinstance(signoff_record, Mapping) else "Unsigned", (signoff_record or {}).get("decision_snapshot_sha256") if isinstance(signoff_record, Mapping) else "Not applicable"),
        ("Report", report.get("report_id"), f"revision {report.get('revision')}; {report.get('report_identity_sha256')}"),
        ("Report generation", report.get("generation_contract_version"), report.get("renderer_fingerprint")),
    ]
    for label, identifier, digest in audit_items:
        audit_rows.append([cell(label), cell(identifier), cell(digest)])
    for scenario in _scenario_rows(snapshot_payload):
        attempt = scenario.get("attempt")
        attempt = attempt if isinstance(attempt, Mapping) else {}
        provenance = scenario.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        evidence = scenario.get("evidence")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        audit_rows.extend(
            [
                [cell("Scenario revision"), cell(scenario.get("scenario_revision_id")), cell(scenario.get("request_sha256"))],
                [cell("TEA attempt"), cell(attempt.get("tea_job_id")), cell(f"attempt {attempt.get('attempt_number')}; retry_of={attempt.get('retry_of_job_id')}")],
                [cell("TEA result/provenance"), cell(provenance.get("routine_result_sha256")), cell(provenance.get("sealed_calculation_sha256"))],
                [cell("Evidence set"), cell(evidence.get("evidence_set_sha256")), cell(provenance.get("reporting_tieout_sha256"))],
            ]
        )
    story.append(table(audit_rows, [1.35 * inch, 2.55 * inch, 3.2 * inch]))

    story.append(heading("Technical export references"))
    export_rows: list[list[Any]] = [
        [cell("Scenario export", bold=True), cell("Verified API reference", bold=True), cell("Media type", bold=True)]
    ]
    for item in snapshot_payload.get("technical_exports") or []:
        if isinstance(item, Mapping):
            export_rows.append(
                [cell(item.get("label")), cell(item.get("url")), cell(item.get("media_type"))]
            )
    if len(export_rows) == 1:
        export_rows.append([cell("None"), cell("No verified export reference stored."), cell("-")])
    story.append(table(export_rows, [2.0 * inch, 3.65 * inch, 1.45 * inch]))

    doc.build(
        story,
        onFirstPage=on_page,
        onLaterPages=on_page,
        canvasmaker=InvariantCanvas,
    )
    payload = buffer.getvalue()
    if not payload.startswith(b"%PDF-") or len(payload) > REPORT_MAX_BYTES:
        raise DecisionReportError(
            "report_pdf_invalid", "The generated report PDF is invalid or too large."
        )
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        page_count = len(reader.pages)
    except Exception as exc:
        raise DecisionReportError(
            "report_pdf_reopen_failed", "The generated report PDF could not be reopened."
        ) from exc
    if not 1 <= page_count <= REPORT_MAX_PAGES:
        raise DecisionReportError(
            "report_page_count_invalid", "The generated report page count is invalid."
        )
    return RenderedDecisionReport(
        pdf_bytes=payload,
        pdf_sha256=sha256(payload).hexdigest(),
        byte_count=len(payload),
        page_count=page_count,
        renderer_fingerprint=current_fingerprint,
    )


def report_storage_key(pdf_sha256: str) -> str:
    digest = str(pdf_sha256).strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise DecisionReportError(
            "report_pdf_digest_invalid", "The report PDF digest is invalid."
        )
    return f"sha256/{digest[:2]}/{digest}.pdf"


def _confined_report_path(root: Path, storage_key: str) -> Path:
    supplied_root = Path(root)
    if supplied_root.is_symlink():
        raise DecisionReportError(
            "report_root_symlink", "The private report root must not be a symlink."
        )
    root_path = supplied_root.resolve()
    key = str(storage_key).replace("\\", "/")
    if not re.fullmatch(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}\.pdf", key):
        raise DecisionReportError(
            "report_storage_key_invalid", "The report storage identity is invalid."
        )
    relative = Path(key)
    current = root_path
    for component in relative.parts[:-1]:
        current = current / component
        if current.is_symlink():
            raise DecisionReportError(
                "report_path_symlink",
                "The report artifact path must not traverse a symlink.",
            )
    candidate = (root_path / relative).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise DecisionReportError(
            "report_path_escape", "The report path escapes its private root."
        ) from exc
    return candidate


def publish_report_pdf(root: Path, rendered: RenderedDecisionReport) -> str:
    """Publish bytes under a private content-addressed root with symlink guards."""

    payload = rendered.pdf_bytes
    if (
        not isinstance(payload, bytes)
        or not payload.startswith(b"%PDF-")
        or not 0 < len(payload) <= REPORT_MAX_BYTES
        or len(payload) != rendered.byte_count
        or sha256(payload).hexdigest() != rendered.pdf_sha256
        or not 1 <= rendered.page_count <= REPORT_MAX_PAGES
        or rendered.renderer_fingerprint != renderer_fingerprint()
    ):
        raise DecisionReportError(
            "report_rendered_artifact_invalid",
            "The rendered report failed pre-publication integrity checks.",
        )
    try:
        from pypdf import PdfReader

        actual_page_count = len(PdfReader(io.BytesIO(payload), strict=True).pages)
    except Exception as exc:
        raise DecisionReportError(
            "report_rendered_artifact_invalid",
            "The rendered report failed strict pre-publication parsing.",
        ) from exc
    if actual_page_count != rendered.page_count:
        raise DecisionReportError(
            "report_rendered_artifact_invalid",
            "The rendered report page count does not match the parsed artifact.",
        )
    storage_key = report_storage_key(rendered.pdf_sha256)
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    if root_path.is_symlink():
        raise DecisionReportError(
            "report_root_symlink", "The private report root must not be a symlink."
        )
    target = _confined_report_path(root_path, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise DecisionReportError(
            "report_path_symlink", "The report artifact path must not be a symlink."
        )
    if target.exists():
        details = target.stat(follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode) or details.st_size > REPORT_MAX_BYTES:
            raise DecisionReportError(
                "report_content_address_collision",
                "Existing report content is not a bounded regular file.",
            )
        existing = target.read_bytes()
        if not (
            len(existing) == rendered.byte_count
            and sha256(existing).hexdigest() == rendered.pdf_sha256
        ):
            raise DecisionReportError(
                "report_content_address_collision",
                "Existing report bytes do not match their content address.",
            )
        return storage_key
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink():
            raise DecisionReportError(
                "report_path_symlink", "The pending report path became a symlink."
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return storage_key


def verified_report_pdf(
    root: Path,
    record: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Reverify the stored snapshot and PDF bytes on every access."""

    snapshot = record.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise DecisionReportError(
            "report_snapshot_missing", "The stored report snapshot is missing."
        )
    expected_snapshot_sha256 = str(record.get("snapshot_sha256") or "")
    if not _SHA256_RE.fullmatch(expected_snapshot_sha256) or not secrets_compare(
        canonical_sha256(snapshot), expected_snapshot_sha256
    ):
        raise DecisionReportError(
            "report_snapshot_tampered", "The stored report snapshot failed verification."
        )
    storage_key = str(record.get("storage_key") or "")
    target = _confined_report_path(Path(root), storage_key)
    if target.is_symlink():
        raise DecisionReportError(
            "report_artifact_symlink", "The report artifact must not be a symlink."
        )
    try:
        details = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise DecisionReportError(
            "report_artifact_missing", "The report artifact is unavailable."
        ) from exc
    if not stat.S_ISREG(details.st_mode):
        raise DecisionReportError(
            "report_artifact_not_regular", "The report artifact is not a regular file."
        )
    expected_bytes = int(record.get("byte_count") or 0)
    if details.st_size != expected_bytes or expected_bytes > REPORT_MAX_BYTES:
        raise DecisionReportError(
            "report_artifact_size_mismatch", "The report artifact size changed."
        )
    payload = target.read_bytes()
    expected_pdf_sha256 = str(record.get("pdf_sha256") or "")
    if storage_key != report_storage_key(expected_pdf_sha256):
        raise DecisionReportError(
            "report_storage_identity_mismatch",
            "The report storage key does not match its PDF content address.",
        )
    if (
        not payload.startswith(b"%PDF-")
        or not _SHA256_RE.fullmatch(expected_pdf_sha256)
        or not secrets_compare(sha256(payload).hexdigest(), expected_pdf_sha256)
    ):
        raise DecisionReportError(
            "report_artifact_tampered", "The report PDF failed integrity verification."
        )
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload), strict=True)
        page_count = len(reader.pages)
        metadata_record = dict(reader.metadata or {})
    except Exception as exc:
        raise DecisionReportError(
            "report_artifact_reopen_failed", "The report PDF could not be reopened."
        ) from exc
    if page_count != int(record.get("page_count") or 0):
        raise DecisionReportError(
            "report_page_count_mismatch", "The report PDF page count changed."
        )
    return payload, {
        "status": "verified",
        "media_type": _REPORT_MEDIA_TYPE,
        "pdf_sha256": expected_pdf_sha256,
        "byte_count": expected_bytes,
        "page_count": page_count,
        "snapshot_sha256": expected_snapshot_sha256,
        "metadata": metadata_record,
    }


def secrets_compare(left: str, right: str) -> bool:
    # Local import keeps the public surface small and avoids accidental shadowing.
    import secrets

    return secrets.compare_digest(str(left), str(right))


__all__ = [
    "DecisionReportError",
    "REPORT_GENERATION_CONTRACT_VERSION",
    "REPORT_MAX_BYTES",
    "REPORT_MAX_PAGES",
    "REPORT_SNAPSHOT_SCHEMA_VERSION",
    "RenderedDecisionReport",
    "canonical_sha256",
    "prepare_report_snapshot",
    "publish_report_pdf",
    "render_manager_pdf",
    "renderer_fingerprint",
    "report_storage_key",
    "verified_report_pdf",
]
