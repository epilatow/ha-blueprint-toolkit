#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Verify a fleet YAML is fully covered by a mapping.json.

The fleet YAML is a one-shot offline snapshot of the user's HA fleet
(captured ahead of time, never queried by this script). For each
device + each catalog concept this script runs the live resolver's
matching logic and classifies the outcome:

    RESOLVED        the locator found exactly one matching param.
    NOT_APPLICABLE  no param on this device matches the locator.
                    (Expected when the device doesn't carry the
                    concept's surface -- a motion sensor has no
                    humidity_report_threshold.)
    AMBIGUOUS       multiple params matched. Always a mapping bug.
    UNMAPPABLE      no locator for this concept in mapping.json, or
                    the locator matched but the device's metadata
                    won't yield a writable raw value (e.g. a BOOL
                    with no on/off label and no range).

Exits non-zero only on AMBIGUOUS. Everything else is reported so the
operator can spot coverage holes (a concept that should resolve on
this device but didn't) and unmapped params (settable params on the
device that no concept's locator captures -- the heuristic for "labels
we might be missing").
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    CATALOG,
    Device,
    FixedValueId,
    GenericParamNames,
    LabelMatch,
    Locator,
    MappingTable,
    ParamId,
    ParamMeta,
    ParamValue,
    ResolutionStatus,
    resolve,
)

_DEFAULT_MAPPING = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "zwave_parameter_manager"
    / "mapping.json"
)
# A safe placeholder per ParamType -- resolution status (RESOLVED vs
# AMBIGUOUS vs NOT_APPLICABLE) is what verify cares about; the value
# itself never gets written.
_DUMMY_VALUE: dict[str, bool | int | float] = {
    "bool": True,
    "range": 5,
    "value": 1,
}


@dataclass
class _ConceptOutcome:
    concept: GenericParamNames
    status: ResolutionStatus
    matched_label: str | None
    reason: str | None


@dataclass
class _DeviceReport:
    name: str
    node_id: int
    manufacturer: str
    model: str
    outcomes: list[_ConceptOutcome]
    unmapped_params: list[ParamMeta]


def _load_mapping(path: Path) -> MappingTable:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    return MappingTable.from_dict(raw)


def _load_fleet(path: Path) -> list[Device]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    devices_raw = raw.get("devices")
    if not isinstance(devices_raw, list):
        raise ValueError(f"{path}: 'devices' must be a list")
    out: list[Device] = []
    for index, entry in enumerate(devices_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: devices[{index}] must be a mapping")
        out.append(_build_device(entry, index, path))
    return out


def _build_device(entry: dict[str, Any], index: int, where: Path) -> Device:
    def req(field: str) -> Any:
        if field not in entry:
            raise ValueError(
                f"{where}: devices[{index}] missing required {field!r}"
            )
        return entry[field]

    params_raw = entry.get("params") or []
    if not isinstance(params_raw, list):
        raise ValueError(f"{where}: devices[{index}].params must be a list")
    params = tuple(
        _build_param(p, index, j, where) for j, p in enumerate(params_raw)
    )
    return Device(
        node_id=int(req("node_id")),
        name=str(req("name")),
        manufacturer=str(req("manufacturer")),
        model=str(req("model")),
        is_listening=bool(entry.get("is_listening", False)),
        params=params,
    )


def _build_param(
    raw: Any, device_index: int, param_index: int, where: Path
) -> ParamMeta:
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}: devices[{device_index}].params[{param_index}] "
            f"must be a mapping"
        )
    cc = raw.get("command_class")
    prop = raw.get("property")
    label = raw.get("label", "")
    if not isinstance(cc, int):
        raise ValueError(
            f"{where}: devices[{device_index}].params[{param_index}]"
            f": command_class must be an int"
        )
    if not isinstance(prop, (int, str)):
        raise ValueError(
            f"{where}: devices[{device_index}].params[{param_index}]"
            f": property must be int or str"
        )
    lo = raw.get("min")
    hi = raw.get("max")
    rng: tuple[int, int] | None = None
    if isinstance(lo, int) and isinstance(hi, int):
        rng = (lo, hi)
    states_raw = raw.get("states") or {}
    states: dict[int, str] = {}
    if isinstance(states_raw, dict):
        for k, v in states_raw.items():
            try:
                states[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
    unit_raw = raw.get("unit")
    unit = unit_raw if isinstance(unit_raw, str) else None
    return ParamMeta(
        id=ParamId(cc, prop),
        label=str(label),
        range=rng,
        unit=unit,
        states=states,
    )


def _locator_matches(locator: Locator, device: Device) -> list[ParamMeta]:
    """Params on ``device`` captured by ``locator``, regardless of
    whether the eventual ``resolve`` produces a value. Used for the
    unmapped-params rollup so AMBIGUOUS / value-production failures
    don't surface as "labels we might be missing"."""

    if isinstance(locator, LabelMatch):
        wanted = {label.casefold() for label in locator.labels}
        return [p for p in device.params if p.label.casefold() in wanted]
    if isinstance(locator, FixedValueId):
        return [
            p
            for p in device.params
            if p.id.command_class == locator.command_class
            and p.id.property_ == locator.property_
        ]
    return []


def _classify_device(device: Device, mapping: MappingTable) -> _DeviceReport:
    outcomes: list[_ConceptOutcome] = []
    matched_param_ids: set[tuple[int, int | str]] = set()
    for concept_name in GenericParamNames:
        gp = CATALOG[concept_name]
        locator = mapping.locators.get(concept_name)
        if locator is not None:
            # Tracking matches at the locator level (not just on
            # RESOLVED) keeps AMBIGUOUS labels out of the unmapped
            # summary -- the mapping already captures them.
            for pm in _locator_matches(locator, device):
                matched_param_ids.add((pm.id.command_class, pm.id.property_))
        dummy = ParamValue.of(gp, _DUMMY_VALUE[gp.param_type.value])
        res = resolve(device, gp, mapping, dummy)
        matched_label: str | None = None
        if res.status is ResolutionStatus.RESOLVED:
            for pm in device.params:
                if pm.id == res.id:
                    matched_label = pm.label
                    break
        outcomes.append(
            _ConceptOutcome(
                concept=concept_name,
                status=res.status,
                matched_label=matched_label,
                reason=res.reason,
            )
        )
    unmapped = [
        p
        for p in device.params
        if (p.id.command_class, p.id.property_) not in matched_param_ids
    ]
    return _DeviceReport(
        name=device.name,
        node_id=device.node_id,
        manufacturer=device.manufacturer,
        model=device.model,
        outcomes=outcomes,
        unmapped_params=unmapped,
    )


def _print_report(reports: list[_DeviceReport]) -> int:
    ambiguous = 0
    print(
        f"{'node_id':>7}  {'name':<25}  {'mfg/model':<25}  "
        f"concept                          status"
    )
    print("-" * 110)
    for r in reports:
        mfg_model = f"{r.manufacturer}/{r.model}"
        for outcome in r.outcomes:
            label = outcome.matched_label or ""
            if outcome.status is ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            extra = f"  -> {label}" if label else ""
            print(
                f"{r.node_id:>7}  {r.name[:25]:<25}  "
                f"{mfg_model[:25]:<25}  "
                f"{outcome.concept.value:<30}  "
                f"{outcome.status.name}{extra}"
            )

    # Unmapped-params summary -- the candidates the LLM-suggester
    # would consider for new concept labels.
    unmapped_counts: dict[str, int] = defaultdict(int)
    for r in reports:
        for p in r.unmapped_params:
            unmapped_counts[p.label] += 1
    if unmapped_counts:
        print()
        print("Unmapped param labels (across all devices):")
        for label, count in sorted(
            unmapped_counts.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            print(f"  {count:>3}  {label}")
    print()
    print(f"AMBIGUOUS: {ambiguous}")
    return 1 if ambiguous else 0


def main() -> int:
    summary = (__doc__ or "").strip().split("\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument(
        "--mapping",
        type=Path,
        default=_DEFAULT_MAPPING,
        help="Path to mapping.json.",
    )
    parser.add_argument(
        "--fleet",
        type=Path,
        required=True,
        help="Path to fleet.yaml (HA-side snapshot, never queried live).",
    )
    args = parser.parse_args()

    mapping = _load_mapping(args.mapping)
    fleet = _load_fleet(args.fleet)
    reports = [_classify_device(d, mapping) for d in fleet]
    return _print_report(reports)


if __name__ == "__main__":
    sys.exit(main())
