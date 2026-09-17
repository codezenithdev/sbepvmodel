"""GDP-deflator conversion before the v5 kernel consumes constant-dollar costs.

The indexed values are frozen locally. Conversion copies only declared monetary
fields; it never samples, reads a saved job, changes energy, or opens a database.
Original prices are user-declared evidence, not independently verified quotes.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path


METHOD = "gdp_deflator_v1"
_CATALOG_FILES = ("gdp_deflator_2026_09_17.json",)
_DISTRIBUTION_PARAMETERS = {
    "fixed": ("value",),
    "uniform": ("low", "high"),
    "triangular": ("low", "mode", "high"),
    "bounded_normal": ("low", "high", "mean", "sd"),
}
_RECEIPT_FIELDS = {
    "method", "source_year", "target_year", "index_snapshot_id",
    "source_index", "target_index", "factor", "source_provisional",
    "target_provisional", "original_money",
}


@lru_cache(maxsize=1)
def _index_catalogs():
    catalogs = {}
    for filename in _CATALOG_FILES:
        catalog = json.loads((Path(__file__).with_name("data") / filename).read_text(encoding="utf-8"))
        catalogs[catalog["snapshot_id"]] = catalog
    return catalogs


def get_index_catalog(snapshot_id=None):
    """Return a detached published snapshot, never a mutable shared catalog."""
    catalogs = _index_catalogs()
    identifier = snapshot_id or next(reversed(catalogs))
    if identifier not in catalogs:
        raise ValueError("The GDP-deflator snapshot is not supported.")
    return deepcopy(catalogs[identifier])


def _year_record(catalog, year):
    if type(year) is not int:
        raise ValueError("Cost years must be integers.")
    record = catalog["years"].get(str(year))
    if record is None:
        raise ValueError(f"No GDP-deflator value is available for {year} in this snapshot.")
    _finite(record["value"], positive=True)
    if type(record["provisional"]) is not bool:
        raise ValueError("The GDP-deflator snapshot has an invalid provisional flag.")
    return record


def _finite(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Cost conversion requires finite numeric values.")
    if positive and value <= 0:
        raise ValueError("GDP-deflator values and conversion factors must be positive.")
    return float(value)


def _money_slots(request):
    paired = request.get("paired_commercial")
    if not isinstance(paired, Mapping) or request.get("calculation_contract_version") not in (None, "tea-calculation-v5"):
        raise ValueError("Cost-year adjustment is supported only for paired commercial v5 analyses.")
    slots = []
    shared = paired.get("shared_initial_capex")
    if shared is not None:
        prefix = "paired_commercial.shared_initial_capex."
        for key in ("common_capex_wdc", "optimizer_installation_wdc", "optimizer_unit_price_usd"):
            slots.append((prefix + key, shared, key))
        allocations = (shared.get("report_context") or {}).get("component_allocations") or []
        for index, allocation in enumerate(allocations):
            for key in ("midpoint_wdc", "low_wdc", "high_wdc"):
                slots.append((prefix + f"report_context.component_allocations.{index}." + key, allocation, key))
    for system in paired["systems"]:
        for line in system["cost_lines"]:
            slots.append((f"paired_commercial.systems.{system['technology']}.cost_lines.{line['input_id']}.distribution", line, "distribution"))
    if len({path for path, _, _ in slots}) != len(slots):
        raise ValueError("Cost conversion requires unique monetary field identifiers.")
    return slots


def collect_money(request):
    """Collect canonical prices and distributions by stable presentation-free path."""
    return {path: deepcopy(container[key]) for path, container, key in _money_slots(request)}


def _scale_money(value, factor):
    if isinstance(value, Mapping):
        family = value.get("family")
        parameters = _DISTRIBUTION_PARAMETERS.get(family)
        if parameters is None or set(value) != {"family", *parameters}:
            raise ValueError("Original cost distributions must contain only their canonical parameters.")
        result = {"family": family}
        for parameter in parameters:
            result[parameter] = _finite(_finite(value[parameter]) * factor)
        return result
    original = _finite(value)
    if original < 0:
        raise ValueError("Original scalar costs cannot be negative.")
    return _finite(original * factor)


def _money_equal(actual, expected):
    if isinstance(expected, Mapping):
        return (isinstance(actual, Mapping) and set(actual) == set(expected)
                and actual.get("family") == expected.get("family")
                and all(_money_equal(actual[key], expected[key]) for key in expected if key != "family"))
    _finite(actual)
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def validate_cost_year_adjustment(request):
    """Tie a receipt to the frozen index snapshot and every submitted money field."""
    receipt = request.get("cost_year_adjustment")
    if receipt is None:
        return None
    if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS or receipt.get("method") != METHOD:
        raise ValueError("The cost-year adjustment receipt has an unsupported shape or method.")
    money = collect_money(request)
    catalog = get_index_catalog(receipt["index_snapshot_id"])
    source = _year_record(catalog, receipt["source_year"])
    target = _year_record(catalog, receipt["target_year"])
    factor = target["value"] / source["value"]
    for key, expected in (("source_index", source["value"]), ("target_index", target["value"]), ("factor", factor)):
        _finite(receipt[key], positive=True)
        if receipt[key] != expected:
            raise ValueError(f"Cost-year adjustment {key} does not match the frozen GDP-deflator snapshot.")
    for key, expected in (("source_provisional", source["provisional"]), ("target_provisional", target["provisional"])):
        if type(receipt[key]) is not bool or receipt[key] is not expected:
            raise ValueError("Cost-year adjustment provisional flags do not match the frozen snapshot.")
    if request["finance"]["constant_dollar_cost_year"] != receipt["target_year"]:
        raise ValueError("Cost-year adjustment target must equal the finance constant-dollar year.")
    for system in request["paired_commercial"]["systems"]:
        for line in system["cost_lines"]:
            if line["constant_dollar_cost_year"] != receipt["target_year"]:
                raise ValueError("Every converted cost line must use the receipt target year.")
    original = receipt["original_money"]
    if not isinstance(original, Mapping) or set(original) != set(money):
        raise ValueError("The cost-year adjustment must retain originals for exactly every monetary field.")
    for path, submitted in money.items():
        expected = _scale_money(original[path], factor)
        if not _money_equal(submitted, expected):
            raise ValueError("Converted cost does not equal its recorded original times the GDP-deflator factor: " + path)
    return deepcopy(dict(receipt))


def build_cost_year_adjustment_receipt(request):
    """Freeze index provenance beside the submitted conversion arithmetic."""
    receipt = validate_cost_year_adjustment(request)
    if receipt is None:
        return None
    catalog = get_index_catalog(receipt['index_snapshot_id'])
    canonical = json.dumps(catalog, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    metadata = {key: deepcopy(value) for key, value in catalog.items() if key not in {'years', 'sources'}}
    metadata['sources'] = {
        name: {key: deepcopy(value) for key, value in source.items() if key != 'raw_csv'}
        for name, source in catalog['sources'].items()
    }
    metadata['source_observation'] = deepcopy(catalog['years'][str(receipt['source_year'])])
    metadata['target_observation'] = deepcopy(catalog['years'][str(receipt['target_year'])])
    metadata['catalog_sha256'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return {**receipt, 'index_metadata': metadata}


def convert_cost_year(request, target_year):
    """Return a converted copy, retaining original prices across year round trips."""
    result = deepcopy(dict(request))
    prior = validate_cost_year_adjustment(result)
    source_year = prior["source_year"] if prior else result["finance"]["constant_dollar_cost_year"]
    if not prior:
        for system in result["paired_commercial"]["systems"]:
            for line in system["cost_lines"]:
                if line.get("constant_dollar_cost_year") != source_year:
                    raise ValueError("Every original cost line must use the declared source dollar year before conversion")
    catalog = get_index_catalog(prior["index_snapshot_id"] if prior else None)
    source = _year_record(catalog, source_year)
    target = _year_record(catalog, target_year)
    factor = target["value"] / source["value"]
    original = deepcopy(prior["original_money"]) if prior else collect_money(result)
    for path, container, key in _money_slots(result):
        container[key] = _scale_money(original[path], factor)
    result["finance"]["constant_dollar_cost_year"] = target_year
    for system in result["paired_commercial"]["systems"]:
        for line in system["cost_lines"]:
            line["constant_dollar_cost_year"] = target_year
    result["cost_year_adjustment"] = {
        "method": METHOD, "source_year": source_year, "target_year": target_year,
        "index_snapshot_id": catalog["snapshot_id"], "source_index": source["value"],
        "target_index": target["value"], "factor": factor,
        "source_provisional": source["provisional"], "target_provisional": target["provisional"],
        "original_money": original,
    }
    validate_cost_year_adjustment(result)
    return result
