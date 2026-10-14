# This is AI generated code
"""Build ZPM resolver inputs from a live Z-Wave JS node.

The HA handler reads its in-process ``zwave_js`` driver; the CLI reads
the zwave-js server (3000) ``start_listening`` dump. Both yield
``zwave_js_server`` ``Node`` objects, so this maps a node's settable
parameters -- the Configuration CC (112) values plus the Wake Up CC
(132) ``wakeUpInterval`` -- onto the pure ``logic.ParamMeta`` the
resolver matches against (label / range / unit / option states).

Everything the node itself carries is assembled here: the settable
parameters as ``logic.ParamMeta`` (label / range / unit / option
states), the current values for convergence, and the resolver
``Device`` whose identity is the node's ``device_config`` (the
config-DB manufacturer / label the mapping matches on, not the
often-null ``productLabel``). The handler supplies the two
registry-derived inputs -- the HA ``device_id`` and the
``device_types`` it derives via ``derive_device_types`` over the
node's HA entities -- plus the convergence extras (location, last
wake) it reads from the registries and recorder.
"""

from __future__ import annotations

from collections.abc import Iterable

from zwave_js_server.model.node import Node
from zwave_js_server.model.value import Value, ValueMetadata

from .logic import (
    WAKE_UP_INTERVAL_VALUE,
    CommandClass,
    Device,
    DeviceType,
    FixedValueId,
    ParamId,
    ParamMeta,
    ParamRange,
)

# The settable-parameter surface: which node values become resolver
# ParamMeta. Every property of these command classes is settable...
_SETTABLE_CLASSES: frozenset[CommandClass] = frozenset(
    {CommandClass.CONFIGURATION}
)
# ...plus these individual standardized value-ids outside those classes.
_SETTABLE_VALUE_IDS: frozenset[FixedValueId] = frozenset(
    {WAKE_UP_INTERVAL_VALUE}
)
# Units the Z-Wave protocol pins for specific value-ids but zwave-js
# doesn't always carry through on the value-id's metadata (the spec
# treats them as implicit, not declared). Backfill so the resolver's
# unit-aware VALUE path doesn't UNMAPPABLE every battery device.
_PROTOCOL_UNITS: dict[FixedValueId, str] = {
    WAKE_UP_INTERVAL_VALUE: "seconds",
}


def node_param_metas(node: Node) -> tuple[ParamMeta, ...]:
    """Settable params of ``node`` as resolver ``ParamMeta``.

    Includes the Configuration CC parameters and the Wake Up interval --
    the surface ZPM concepts target. Read-only sensor values are
    excluded. Only metadata is carried (label / range / unit / option
    states); the current value is read separately for convergence.
    """

    metas: list[ParamMeta] = []
    for value in node.values.values():
        if not _is_settable_param(value):
            continue
        meta = value.metadata
        pid = _param_key(value)
        metas.append(
            ParamMeta(
                id=pid,
                label=meta.label or "",
                range=_range(meta),
                unit=meta.unit
                or _PROTOCOL_UNITS.get(
                    FixedValueId(pid.command_class, pid.property_)
                ),
                states=_states(meta),
            )
        )
    return tuple(metas)


def _is_settable_param(value: Value) -> bool:
    if value.command_class in _SETTABLE_CLASSES:
        return True
    return (
        FixedValueId(value.command_class, value.property_)
        in _SETTABLE_VALUE_IDS
    )


def _param_key(value: Value) -> ParamId:
    """A settable param's ``ParamId``.

    ``property_key`` folds to int | None (zwave-js reports an int, a str, or
    nothing). ``node_param_metas`` and ``actual_values`` both derive a
    parameter's identity through this, so the metadata and the live value
    share one key for the convergence join.
    """

    return ParamId(
        value.command_class,
        value.property_,
        value.property_key if isinstance(value.property_key, int) else None,
    )


def _range(meta: ValueMetadata) -> ParamRange | None:
    lo, hi = meta.min, meta.max
    if isinstance(lo, int) and isinstance(hi, int):
        return (lo, hi)
    return None


def _states(meta: ValueMetadata) -> dict[int, str]:
    """Option states keyed by int (zwave-js reports str keys)."""

    out: dict[int, str] = {}
    for raw, label in (meta.states or {}).items():
        try:
            out[int(raw)] = str(label)
        except TypeError, ValueError:
            continue
    return out


# -- device_types derivation -------------------------------------

# HA entity device_class -> DeviceType. ``contact`` collapses HA's
# window / door / garage_door (open-close sensors share their config).
_CLASS_TO_TYPE: dict[str, DeviceType] = {
    "motion": DeviceType.MOTION,
    "humidity": DeviceType.HUMIDITY,
    "temperature": DeviceType.TEMPERATURE,
    "illuminance": DeviceType.ILLUMINANCE,
    "moisture": DeviceType.MOISTURE,
    "smoke": DeviceType.SMOKE,
    "carbon_monoxide": DeviceType.CARBON_MONOXIDE,
    "window": DeviceType.CONTACT,
    "door": DeviceType.CONTACT,
    "garage_door": DeviceType.CONTACT,
}

# HA entity domain -> DeviceType, for the types HA carries as a domain
# rather than a sensor device_class.
_DOMAIN_TO_TYPE: dict[str, DeviceType] = {
    "lock": DeviceType.LOCK,
    "siren": DeviceType.SIREN,
}


def derive_device_types(
    entities: Iterable[tuple[str, str | None]],
) -> frozenset[DeviceType]:
    """Map a device's HA entities onto its ``DeviceType`` tags.

    ``entities`` is each entity's ``(domain, device_class)``. A device is
    tagged from its sensor ``device_class`` attributes and from the
    presence of the ``lock`` / ``siren`` domains. Anything unrecognised
    -- diagnostic classes (battery, firmware, tamper, ...) and unrelated
    domains -- is ignored, so the closed enum is itself the filter.
    """

    found: set[DeviceType] = set()
    for domain, device_class in entities:
        by_domain = _DOMAIN_TO_TYPE.get(domain)
        if by_domain is not None:
            found.add(by_domain)
        if device_class is not None:
            by_class = _CLASS_TO_TYPE.get(device_class)
            if by_class is not None:
                found.add(by_class)
    return frozenset(found)


# -- Device assembly + actual values -----------------------------


def build_device(
    node: Node,
    *,
    device_id: str | None,
    device_types: frozenset[DeviceType],
) -> Device:
    """Assemble the resolver ``Device`` from a live node.

    Identity comes off the node's ``device_config`` -- the config-DB
    manufacturer / label the mapping's selectors + per-model quirks match
    on (the wire ``productLabel`` is often null). The handler resolves
    ``device_id`` from the HA device registry and ``device_types`` via
    ``derive_device_types`` over the node's HA entities and passes both
    in; everything else is read from the node.
    """

    config = node.device_config
    return Device(
        node_id=node.node_id,
        name=node.name or "",
        manufacturer=config.manufacturer or "",
        model=config.label or "",
        is_listening=bool(node.is_listening),
        device_id=device_id,
        device_types=device_types,
        params=node_param_metas(node),
    )


def actual_values(node: Node) -> dict[ParamId, int | None]:
    """Current live value of each settable param, keyed by ``ParamId``.

    The same identity ``node_param_metas`` emits, so the convergence
    computation joins a planned write to its live value. ``None`` when the
    device has not reported a value (unread), which the report renders as
    such; read-only sensor readings (excluded from ``node_param_metas``) are
    excluded here too.
    """

    out: dict[ParamId, int | None] = {}
    for value in node.values.values():
        if not _is_settable_param(value):
            continue
        raw = value.value
        # A boolean-type config param reports a Python bool; fold it to the
        # int form so it compares against the resolver's int target.
        out[_param_key(value)] = int(raw) if isinstance(raw, bool) else raw
    return out
