"""Pure constants shared by the TEA evidence schema and its handler."""

from __future__ import annotations


TECHNOECONOMIC_EVIDENCE_TOOL_NAME = "get_technoeconomic_evidence"
TECHNOECONOMIC_EVIDENCE_SECTIONS = (
    "overview",
    "assumptions",
    "formulas",
    "metric",
    "cost_breakdown",
    "chart",
    "weather_years",
    "diagnostics",
    "source",
    "exports",
)


__all__ = [
    "TECHNOECONOMIC_EVIDENCE_SECTIONS",
    "TECHNOECONOMIC_EVIDENCE_TOOL_NAME",
]
