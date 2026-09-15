"""On-demand, read-only full reports from a completed job's sealed evidence.

Rendering never runs a model, consults today's baseline, or changes a job/manifests.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import base64
import hashlib
from io import BytesIO
import math
import re

import numpy as np

from sbepv import technoeconomic_reporting as reporting
from sbepv.technoeconomic_report import REPORT_VERSION
from sbepv.api import artifacts, technoeconomic as tea_api

class FullReportError(ValueError):
    """Frozen evidence cannot support a full report."""


def verified_report_evidence(job):
    if job.get("state") != "done":
        raise FullReportError("A full report requires a completed TEA.")
    for field in ("source_snapshot", "submission_provenance"):
        if tea_api.canonical_json_sha256(job.get(field)) != job.get(field + "_sha256"):
            raise FullReportError(f"Frozen {field} digest mismatch.")
    routine = dict(job.get("result") or {})
    if tea_api.canonical_json_sha256(routine) != (job.get("result_provenance") or {}).get("routine_result_sha256"):
        raise FullReportError("Saved result digest mismatch.")
    csv_path, _ = artifacts._verified_technoeconomic_artifact(job, "csv")
    sealed = job["artifacts"]["sealed_calculation"]
    from sbepv.worker import run_technoeconomic
    run_technoeconomic._verify_sealed_calculation_artifact(job["id"], csv_path.parent.name, sealed)
    routine.pop("exports", None)
    calculation = reporting._load_sealed_calculation(
        attempt_directory=csv_path.parent,
        sealed_calculation_path=csv_path.parent / sealed["filename"],
        sealed_calculation_artifact=sealed,
        request_payload=job["request"], source_snapshot=job["source_snapshot"],
        submission_provenance=job["submission_provenance"],
    )
    reporting._verify_routine_result(
        metadata=calculation.metadata, routine_result=routine,
        request_payload=job["request"], source_snapshot=job["source_snapshot"],
        submission_provenance=job["submission_provenance"], sealed_calculation_artifact=sealed,
    )
    checks = reporting._build_checks(calculation, job["source_snapshot"], job["submission_provenance"], routine)
    # Independent direct annual sums, not the production log1p/expm1 formulas.
    rate = np.asarray(calculation.by_name["SampledInput::finance.discount-rate"])
    degradation = np.asarray(calculation.by_name["SampledInput::energy.shared-degradation"])
    life = int(job["request"]["finance"]["project_life_years"])
    direct_annuity = np.zeros(calculation.row_count)
    direct_energy = np.zeros(calculation.row_count)
    for year in range(1, life + 1):
        discount = (1.0 + rate) ** -year
        direct_annuity += discount
        direct_energy += (1.0 - degradation) ** (year - 1) * discount
    for name, expected in (("AnnuityFactor_years", direct_annuity), ("LifecycleEnergyFactor_years", direct_energy)):
        actual = np.asarray(calculation.by_name[name])
        tolerance = max(1e-10, float(np.max(np.abs(expected))) * 1e-11)
        difference = float(np.max(np.abs(actual - expected)))
        checks.append(("independent_direct_sum_" + name, difference, 0, difference, tolerance,
                       "OK" if difference <= tolerance else "FAIL", "Year-by-year direct powers for every saved realization."))
    if not checks or any(row[5] != "OK" for row in checks):
        raise FullReportError("Saved numerical results failed export tie-outs.")
    lineage = job["source_snapshot"].get("calibration_lineage") or {}
    origin = lineage.get("origin_validation_job") or {}
    annual = job["source_snapshot"].get("source_annual_job") or {}
    if not origin.get("result") or not annual.get("result") or not lineage.get("resolved_profile"):
        raise FullReportError("Full calibration/annual lineage is unavailable in this historical record.")
    return calculation, routine, checks


def independent_reference_checks():
    """Decimal year-by-year sums, independent of the kernel's closed-form helpers."""
    with localcontext() as context:
        context.prec = 48
        D = Decimal
        r, g = D(".06"), D(".005")
        af = sum((1 + r) ** -year for year in range(1, 31))
        ef = sum((1 - g) ** (year - 1) / (1 + r) ** year for year in range(1, 31))
        base = D("1.12") * D(134_000_000)
        hardware = D(103_077) * D("37.75")
        se = base + hardware + D(".007") * D(134_000_000)
        sol_lcoe = (base + D(1_407_000) * af) / (D(200_000_000) * ef)
        se_lcoe = (se + D(2_010_000) * af) / (D(210_000_000) * ef)
        references = [
            ("Optimizer hardware USD", float(hardware), 3_891_156.75),
            ("Solectria deterministic midpoint USD", float(base), 150_080_000.0),
            ("SolarEdge deterministic midpoint USD", float(se), 154_909_156.75),
            ("30-year annuity factor, r=6%", float(af), 13.764831151489424),
            ("Discounted energy factor, r=6%, g=0.5%", float(ef), 13.079975318650642),
            ("Synthetic Solectria LCOE USD/kWh", float(sol_lcoe), .06477348515655538),
            ("Synthetic SolarEdge LCOE USD/kWh", float(se_lcoe), .06646891360070414),
            ("Zero-rate, zero-degradation energy factor", float(sum(D(1) for _ in range(30))), 30.0),
            ("Clipped calibration example kWh: min(.95x100,125)+min(.95x150,125)", min(.95*100,125)+min(.95*150,125), 220.0),
        ]
    if any(not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12) for _, actual, expected in references):
        raise FullReportError("Independent reference checks failed.")
    return references


def prepare_report(job, *, generated_at=None):
    from sbepv import technoeconomic_report
    from PIL import Image
    calculation, routine, checks = verified_report_evidence(job)
    independent_reference_checks()
    chart_path, chart_record = artifacts._verified_technoeconomic_artifact(job, "cdf_plot")
    chart_bytes = chart_path.read_bytes()
    if len(chart_bytes) != chart_record["byte_count"] or hashlib.sha256(chart_bytes).hexdigest() != chart_record["sha256"]:
        raise FullReportError("The saved LCOE chart changed during report preparation.")
    with Image.open(BytesIO(chart_bytes)) as chart_image:
        width, height = chart_image.size
    saved_chart = {"image": base64.b64encode(chart_bytes).decode("ascii"),
                   "height": 522 * height / width, "source_sha256": chart_record["sha256"]}
    return technoeconomic_report.build_report(job, calculation, routine, checks, generated_at=generated_at, lifecycle_chart=saved_chart)


def report_filename(report, extension):
    if extension == "pdf":
        return "LCOE_comparsion.pdf"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", report["run_id"])[:100]
    return f"PV_Comparison_{report['generated_at'][:10]}_v{report['version']}_{safe_id}.{extension}"


def build_pdf(job, *, generated_at=None):
    from sbepv import technoeconomic_pdf_layout
    report = prepare_report(job, generated_at=generated_at)
    return technoeconomic_pdf_layout.render_pdf(report), report_filename(report, "pdf")
