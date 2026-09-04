"""Report the deterministic TEA v6 admission envelope.

This is an analytical capacity benchmark, not a process-memory benchmark.  It
calls the same estimator used by request validation and intentionally reports
``measured_rss_bytes`` as ``None`` so estimated high-water marks cannot be
mistaken for measured resident-set size.  Run from any directory with::

    python tools/benchmark_tea_v6_admission.py --format markdown

The default matrix emphasizes a 30-year project while also showing project-life
growth and the realization-export-cell limiter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable


def _repository_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "sbepv"
        ).is_dir():
            return candidate
    raise RuntimeError("Could not locate the sbepv repository root.")


REPO_ROOT = _repository_root(Path(__file__).resolve().parent)
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sbepv import technoeconomic


DEPLOYED_SERVICE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_SCENARIOS = (
    # project life, total component classes across both systems, export columns
    (30, 0, 64),
    (30, 2, 96),
    (30, 4, 128),
    (30, 8, 192),
    (30, 16, 256),
    (30, 40, 512),
    (20, 4, 128),
    (40, 4, 128),
    (1, 0, 100),
)


def admission_benchmark_report(
    scenarios: Iterable[tuple[int, int, int]] = DEFAULT_SCENARIOS,
) -> dict[str, object]:
    """Return a JSON-serializable, deterministic analytical benchmark."""

    rows: list[dict[str, object]] = []
    for project_life_years, component_count, export_columns in scenarios:
        safe = technoeconomic.lifecycle_safe_realization_max(
            project_life_years,
            component_count,
            realization_export_columns=export_columns,
        )
        safe_n = int(safe["safe_max_realizations"])
        estimate = technoeconomic.estimate_lifecycle_memory(
            safe_n,
            project_life_years,
            component_count,
        )
        next_n = safe_n + 1
        next_estimate = technoeconomic.estimate_lifecycle_memory(
            next_n,
            project_life_years,
            component_count,
        )
        public_ceiling_estimate = technoeconomic.estimate_lifecycle_memory(
            technoeconomic.MAX_REALIZATIONS,
            project_life_years,
            component_count,
        )
        next_violations = {
            "estimated_peak_memory": (
                next_estimate["estimated_peak_bytes"]
                > technoeconomic.LIFECYCLE_MEMORY_LIMIT_BYTES
            ),
            "realization_export_cells": (
                next_n * export_columns
                > technoeconomic.LIFECYCLE_EXPORT_CELL_LIMIT
            ),
            "public_realization_ceiling": (
                next_n > technoeconomic.MAX_REALIZATIONS
            ),
        }
        rows.append(
            {
                "project_life_years": project_life_years,
                "component_count": component_count,
                "realization_export_columns": export_columns,
                **safe,
                "planned_ndarray_bytes_at_safe_max": estimate[
                    "planned_ndarray_bytes"
                ],
                "estimated_peak_bytes_at_safe_max": estimate[
                    "estimated_peak_bytes"
                ],
                "realization_export_cells_at_safe_max": safe_n * export_columns,
                "estimated_peak_bytes_at_public_ceiling": (
                    public_ceiling_estimate["estimated_peak_bytes"]
                ),
                "realization_export_cells_at_public_ceiling": (
                    technoeconomic.MAX_REALIZATIONS * export_columns
                ),
                "public_ceiling_request_admitted": (
                    public_ceiling_estimate["estimated_peak_bytes"]
                    <= technoeconomic.LIFECYCLE_MEMORY_LIMIT_BYTES
                    and technoeconomic.MAX_REALIZATIONS * export_columns
                    <= technoeconomic.LIFECYCLE_EXPORT_CELL_LIMIT
                ),
                "estimated_peak_within_limit": (
                    estimate["estimated_peak_bytes"]
                    <= technoeconomic.LIFECYCLE_MEMORY_LIMIT_BYTES
                ),
                "export_cells_within_limit": (
                    safe_n * export_columns
                    <= technoeconomic.LIFECYCLE_EXPORT_CELL_LIMIT
                ),
                "next_realization_exceeds_limiting_dimension": next_violations[
                    str(safe["limiting_dimension"])
                ],
            }
        )
    return {
        "schema_version": "tea-v6-admission-benchmark-v1",
        "measurement_kind": "analytical_estimator_only",
        "measured_rss_bytes": None,
        "measurement_note": (
            "No process RSS was measured. estimated_peak_bytes is the contract "
            "estimator (256 MiB + 2 * planned ndarray bytes), not observed memory."
        ),
        "deployed_service_memory_bytes": DEPLOYED_SERVICE_MEMORY_BYTES,
        "admission_memory_limit_bytes": technoeconomic.LIFECYCLE_MEMORY_LIMIT_BYTES,
        "admission_limit_share_of_deployed_service": (
            technoeconomic.LIFECYCLE_MEMORY_LIMIT_BYTES
            / DEPLOYED_SERVICE_MEMORY_BYTES
        ),
        "base_memory_allowance_bytes": technoeconomic.LIFECYCLE_MEMORY_BASE_BYTES,
        "realization_export_cell_limit": (
            technoeconomic.LIFECYCLE_EXPORT_CELL_LIMIT
        ),
        "public_realization_ceiling": technoeconomic.MAX_REALIZATIONS,
        "rows": rows,
    }


def _markdown(report: dict[str, object]) -> str:
    rows = report["rows"]
    assert isinstance(rows, list)
    lines = [
        "# TEA v6 analytical admission benchmark",
        "",
        str(report["measurement_note"]),
        "",
        "| Life (yr) | Components | Export columns | Safe n | Limiter | "
        "Estimated peak at safe n (bytes) | Export cells at safe n |",
        "| ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        assert isinstance(row, dict)
        lines.append(
            "| {project_life_years} | {component_count} | "
            "{realization_export_columns} | {safe_max_realizations} | "
            "{limiting_dimension} | {estimated_peak_bytes_at_safe_max} | "
            "{realization_export_cells_at_safe_max} |".format(**row)
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json).",
    )
    args = parser.parse_args()
    report = admission_benchmark_report()
    if args.format == "markdown":
        sys.stdout.write(_markdown(report))
    else:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
