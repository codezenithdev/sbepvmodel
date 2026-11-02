"""Read frozen, hash-bound calibration weather substitution evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def load_weather_evidence(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed if the persisted evidence differs from the reviewed bytes."""
    path = Path(str(metadata.get("evidence_path") or ""))
    expected = str(metadata.get("evidence_sha256") or "")
    payload = path.read_bytes()
    if len(expected) != 64 or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("The frozen MIDC replacement evidence changed or is invalid.")
    evidence = json.loads(payload)
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("Unsupported MIDC replacement evidence.")
    original = evidence.get("original_csv_text")
    if not isinstance(original, str) or hashlib.sha256(original.encode("utf-8")).hexdigest() != evidence.get("original_source_sha256"):
        raise ValueError("The original weather source evidence is invalid.")
    for snapshot in evidence.get("audit", {}).get("source_snapshots", []):
        if hashlib.sha256(snapshot["csv_text"].encode("utf-8")).hexdigest() != snapshot["sha256"]:
            raise ValueError("The frozen MIDC source snapshot is invalid.")
    return evidence
