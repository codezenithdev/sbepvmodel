"""Guards that stop the agent acting on an ambiguous instruction.

IAM is a method selection, not a scalar, so a bare number like "set IAM to 0.16"
is ambiguous and must come back as a clarifying question instead of a silent
Martin-Ruiz run.
"""

from __future__ import annotations

import re
from typing import Any

from sbepv import model


def _ambiguous_numeric_iam(message: str) -> bool:
    import re

    text = (message or "").lower()
    if "iam" not in text:
        return False
    explicit = ("martin", "ruiz", "a_r", "a-r", "coefficient", "physical")
    if any(marker in text for marker in explicit):
        return False
    number = r"(?<![\w.])-?(?:\d+(?:\.\d*)?|\.\d+)"
    relation = r"(?:value|setting|at|to|of|is|=|:)"
    patterns = (
        rf"\biam\b\s*(?:{relation}\s*)?({number})",
        rf"({number})\s*(?:{relation}\s*)?\biam\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        token = match.group(1)
        suffix = text[match.end(1) : match.end(1) + 12].lstrip()
        try:
            value = float(token)
        except ValueError:
            continue
        if suffix.startswith("%"):
            continue
        if value.is_integer() and 1900 <= value <= 2200:
            continue
        return True
    return False


def _visible_iam_selection(current_config: dict[str, Any] | None) -> dict[str, Any]:
    """Make the visible IAM choice unambiguous in the model's chat context."""
    config = current_config if isinstance(current_config, dict) else {}
    iam_model = config.get("iam_model")
    if iam_model == "physical":
        return {
            "selected": True,
            "model": "physical",
            "label": "Physical IAM",
            "martin_ruiz_selected": False,
            "iam_a_r": None,
            "iam_a_r_status": "not applicable to Physical IAM",
        }
    if iam_model == "martin_ruiz":
        return {
            "selected": True,
            "model": "martin_ruiz",
            "label": "Martin-Ruiz IAM",
            "martin_ruiz_selected": True,
            "iam_a_r": config.get("iam_a_r"),
            "iam_a_r_status": "selected Martin-Ruiz coefficient",
        }
    return {
        "selected": False,
        "model": None,
        "label": "IAM selection unavailable",
        "martin_ruiz_selected": False,
        "iam_a_r": None,
        "iam_a_r_status": "unavailable",
    }
