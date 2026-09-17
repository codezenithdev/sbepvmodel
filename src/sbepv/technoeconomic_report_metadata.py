"""Display-only report metadata, kept outside immutable analysis inputs."""
from __future__ import annotations

import unicodedata


ANALYSIS_NAME_MAX_LENGTH = 120


def normalize_analysis_name(value, *, run_id=None):
    """Return a short, single-line name without changing saved analysis data."""
    if value is not None and not isinstance(value, str):
        raise ValueError("Analysis name must be text.")
    value = value or ""
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"}
           and char not in "\t\n\r" for char in value):
        raise ValueError("Analysis name cannot contain control characters.")
    normalized = " ".join(value.split())
    if len(normalized) > ANALYSIS_NAME_MAX_LENGTH:
        raise ValueError("Analysis name must be 120 characters or fewer.")
    return normalized or (f"TEA {run_id}" if run_id else "")
