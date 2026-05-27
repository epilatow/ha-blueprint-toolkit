# This is AI generated code
"""Strict parser for the declarative ZPM policy config.

The handler reads ``/config/zwave_parameter_manager.yaml`` (I/O) and
hands the loaded object here. This module is pure: it validates the
config exhaustively against everything statically knowable -- structure,
concept (parameter) names, value types + ranges, and selector fields --
and maps it onto the logic-layer ``Policy`` / ``Selector`` /
``ParamValue`` types.

What it does NOT check is anything that needs a live device: whether a
device actually has the parameter, whether the value fits the device's
real range, and the label match all require live metadata and remain the
resolver's job (``resolve`` -> NOT_APPLICABLE / AMBIGUOUS / UNMAPPABLE).

Validation aggregates every problem into ``errors`` (never bail on the
first) so one pass surfaces them all, mirroring the argparse handlers.
Only fully-valid policies appear in ``policies``; a policy with any error
is dropped, so a caller that proceeds despite errors never applies a
half-parsed policy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .logic import (
    CATALOG,
    DeviceType,
    GenericParamNames,
    ParamValue,
    Policy,
    Power,
    Selector,
    validate_value,
)

_SELECTOR_KEYS = ("manufacturer", "model", "power", "device_type")
_POLICY_KEYS = ("name", "match", "settings", "exclude")
_CONCEPTS = {n.value: n for n in GenericParamNames}
_POWERS = {p.value: p for p in Power}
_DEVICE_TYPES = {dt.value: dt for dt in DeviceType}


@dataclass(frozen=True)
class ParsedConfig:
    """Result of ``parse_policies``.

    ``policies`` holds only fully-valid policies; ``errors`` lists every
    problem found (config-error strings, the argparse convention).
    """

    policies: tuple[Policy, ...] = ()
    errors: tuple[str, ...] = ()


def _join(items: Iterable[object]) -> str:
    return ", ".join(sorted(str(i) for i in items))


def parse_policies(raw: object) -> ParsedConfig:
    """Parse + strictly validate the loaded policy config object."""

    errors: list[str] = []
    if not isinstance(raw, Mapping):
        return ParsedConfig(errors=("config root must be a mapping",))
    extra = set(raw) - {"policies"}
    if extra:
        errors.append(f"unknown top-level key(s): {_join(extra)}")
    raw_policies = raw.get("policies")
    if not isinstance(raw_policies, list):
        errors.append("'policies' must be a list")
        return ParsedConfig(errors=tuple(errors))

    policies: list[Policy] = []
    seen_names: set[str] = set()
    for index, raw_policy in enumerate(raw_policies):
        policy = _parse_policy(raw_policy, index, seen_names, errors)
        if policy is not None:
            policies.append(policy)
    return ParsedConfig(policies=tuple(policies), errors=tuple(errors))


def _parse_policy(
    raw: object,
    index: int,
    seen_names: set[str],
    errors: list[str],
) -> Policy | None:
    where = f"policy #{index + 1}"
    if not isinstance(raw, Mapping):
        errors.append(f"{where}: must be a mapping")
        return None
    extra = set(raw) - set(_POLICY_KEYS)
    if extra:
        errors.append(f"{where}: unknown key(s): {_join(extra)}")

    name_raw = raw.get("name")
    name: str | None = None
    if not isinstance(name_raw, str) or not name_raw.strip():
        errors.append(f"{where}: 'name' must be a non-empty string")
    else:
        name = name_raw.strip()
        where = f"policy {name!r}"
        if name in seen_names:
            errors.append(f"duplicate policy name {name!r}")
            name = None
        else:
            seen_names.add(name)

    raw_match = raw.get("match")
    if raw_match is None:
        errors.append(f"{where}: 'match' is required")
        match = None
    else:
        match = _parse_selector(raw_match, f"{where} match", errors)

    settings = _parse_settings(raw.get("settings"), where, errors)
    exclude = _parse_excludes(raw.get("exclude"), where, errors)

    if name is None or match is None or settings is None or exclude is None:
        return None
    return Policy(name=name, match=match, settings=settings, exclude=exclude)


def _parse_selector(
    raw: object,
    where: str,
    errors: list[str],
) -> Selector | None:
    if not isinstance(raw, Mapping):
        errors.append(f"{where}: must be a mapping")
        return None
    extra = set(raw) - set(_SELECTOR_KEYS)
    if extra:
        errors.append(f"{where}: unknown selector key(s): {_join(extra)}")
    if not set(raw) & set(_SELECTOR_KEYS):
        errors.append(f"{where}: needs at least one of {_join(_SELECTOR_KEYS)}")
        return None

    ok = True
    power: Power | None = None
    raw_power = raw.get("power")
    if raw_power is not None:
        if isinstance(raw_power, str) and raw_power.casefold() in _POWERS:
            power = _POWERS[raw_power.casefold()]
        else:
            errors.append(f"{where}: 'power' must be one of {_join(_POWERS)}")
            ok = False

    device_type: DeviceType | None = None
    raw_type = raw.get("device_type")
    if raw_type is not None:
        if isinstance(raw_type, str) and raw_type.casefold() in _DEVICE_TYPES:
            device_type = _DEVICE_TYPES[raw_type.casefold()]
        else:
            errors.append(
                f"{where}: 'device_type' must be one of {_join(_DEVICE_TYPES)}"
            )
            ok = False

    text: dict[str, str | None] = {}
    for key in ("manufacturer", "model"):
        value = raw.get(key)
        if value is None:
            text[key] = None
        elif isinstance(value, str) and value.strip():
            text[key] = value
        else:
            errors.append(f"{where}: {key!r} must be a non-empty string")
            ok = False

    if not ok:
        return None
    return Selector(
        manufacturer=text["manufacturer"],
        model=text["model"],
        power=power,
        device_type=device_type,
    )


def _parse_settings(
    raw: object,
    where: str,
    errors: list[str],
) -> Mapping[GenericParamNames, ParamValue] | None:
    if raw is None:
        errors.append(f"{where}: 'settings' is required")
        return None
    if not isinstance(raw, Mapping):
        errors.append(f"{where}: 'settings' must be a mapping")
        return None
    if not raw:
        errors.append(f"{where}: 'settings' must not be empty")
        return None

    ok = True
    out: dict[GenericParamNames, ParamValue] = {}
    for key, value in raw.items():
        concept = _CONCEPTS.get(key) if isinstance(key, str) else None
        if concept is None:
            errors.append(f"{where}: unknown parameter {key!r}")
            ok = False
            continue
        generic_param = CATALOG[concept]
        value_errors = validate_value(generic_param, value)
        if value_errors:
            errors.extend(f"{where}: {e}" for e in value_errors)
            ok = False
            continue
        # validate_value guarantees the type; narrow it for ParamValue.
        assert isinstance(value, (bool, int, float))
        out[concept] = ParamValue.of(generic_param, value)

    if not ok:
        return None
    return out


def _parse_excludes(
    raw: object,
    where: str,
    errors: list[str],
) -> tuple[Selector, ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append(f"{where}: 'exclude' must be a list")
        return None
    ok = True
    out: list[Selector] = []
    for index, raw_selector in enumerate(raw):
        selector = _parse_selector(
            raw_selector, f"{where} exclude #{index + 1}", errors
        )
        if selector is None:
            ok = False
        else:
            out.append(selector)
    if not ok:
        return None
    return tuple(out)
