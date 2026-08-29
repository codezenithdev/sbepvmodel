"""Durable Autonomy decision-case services.

This package is deliberately isolated from the existing Solar Agent and from TEA
calculation formulas. Modules expose read-only Decision Agent capabilities plus
human-controlled evidence review and deterministic scenario construction. Confirmed
scenarios enter only the existing durable TEA job and leased-worker path.
"""

from __future__ import annotations
