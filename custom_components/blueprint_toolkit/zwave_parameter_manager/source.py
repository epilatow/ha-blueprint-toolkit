# This is AI generated code
"""Read the live Z-Wave fleet from HA's in-process zwave_js driver.

The handler's read side. For each node the in-process zwave_js driver
knows about, assemble the resolver ``Device`` (identity + settable
params), the convergence ``ConvergenceDevice`` (name / location / wake
context), and the current value of each settable param.

Values, metadata, and identity come off ``node.values`` -- the live
driver state, not HA's cached entity states and not the on-disk cache.
``device_id`` / name / location come from the HA device + area
registries; ``device_types`` from each entity's device class (the entity
registry's value, falling back to the live state's -- zwave_js sets the
device class on the entity, not the registered entity description, so the
registry value is often unset); the last wake from the node-status
entity's recorder history.

Import contract: this module is imported by ``zwavectl`` as well as by
the handler, and the CLI runs on the Terminal & SSH add-on's
interpreter in a venv holding only ``VENV_DEPS`` -- no Home Assistant,
and so none of what Home Assistant brings with it. ``build_node_read``
and ``NodeRead`` are what the CLI takes. So nothing here may import
Home Assistant, or a module that does, at module scope: those imports
are either ``TYPE_CHECKING`` or deferred into the function that needs
them. ``tests/test_zwavectl.py`` walks this closure and fails on a
module-scope import the CLI's venv could not satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

from ..zwave.convergence import ConvergenceDevice
from .adapter import actual_values, build_device, derive_device_types
from .logic import CommandClass, Device, ParamId

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node

# The entity-registry ``platform`` the node-status entity is registered
# under.
_ZWAVE_JS_PLATFORM = "zwave_js"

# The wakeUpInterval value-id (CC 132); its live value is the device's
# wake interval, read straight out of the per-node actuals.
_WAKE_UP_INTERVAL = ParamId(CommandClass.WAKE_UP, "wakeUpInterval")

# Lookback for the node-status entity's last "awake" transition. Spans the
# fleet's longest wake interval (12h) with headroom; a device that has not
# woken within the window reads as last-awake-unknown.
_WAKE_LOOKBACK = timedelta(days=2)


@dataclass(frozen=True)
class NodeRead:
    """One node's live read.

    ``device`` feeds ``evaluate_policies``; ``convergence`` + ``actuals``
    (keyed by ParamId, the same identity ``device.params`` carry) feed the
    convergence report.
    """

    device: Device
    convergence: ConvergenceDevice
    actuals: dict[ParamId, int | None]


async def read_fleet(hass: HomeAssistant) -> list[NodeRead]:
    """Read every node the in-process zwave_js driver knows about.

    Returns an empty list when zwave_js is absent, not loaded, or
    loaded without a connected driver. The handler renders that as
    its "Z-Wave JS unavailable" notification, so every such state has
    to reach it as an empty read rather than as an exception.
    """
    # Deferred: see this module's docstring on the import contract.
    from ..helpers import zwave_js_entry

    entry = zwave_js_entry(hass)
    if entry is None:
        return []
    driver = _entry_driver(entry)
    if driver is None:
        return []
    return [
        await _read_node(hass, driver, entry.entry_id, node)
        for node in driver.controller.nodes.values()
    ]


def get_driver(hass: HomeAssistant) -> Driver | None:
    """The in-process zwave_js driver, or ``None`` without one.

    ``None`` covers every way the driver can be out of reach: no
    ``zwave_js`` entry at all, none of them loaded, or a loaded entry
    whose client has not finished connecting.
    """
    # Deferred: see this module's docstring on the import contract.
    from ..helpers import zwave_js_entry

    entry = zwave_js_entry(hass)
    return _entry_driver(entry) if entry is not None else None


def _entry_driver(entry: ConfigEntry) -> Driver | None:
    """A loaded entry's driver, or ``None`` while it is still connecting.

    Reaching through ``runtime_data`` is safe here only because the
    entry came from ``zwave_js_entry``, which hands back loaded
    entries: ``zwave_js`` publishes the attribute as it finishes
    setting one up and Home Assistant deletes it again on unload.
    ``None`` covers the window where the entry is loaded but its
    client has no driver yet, which ``read_fleet`` reports as an empty
    read -- the handler renders that as its "Z-Wave JS unavailable"
    notification, so it has to reach it as a value rather than a
    raise.
    """
    return cast("Driver | None", entry.runtime_data.client.driver)


def build_node_read(
    node: Node,
    *,
    device_id: str | None,
    name: str,
    location: str | None,
    entities: list[tuple[str, str | None]],
    last_awake: datetime | None,
) -> NodeRead:
    """Assemble a node's ``NodeRead`` from its live ``Node`` plus the HA
    context: ``device_id`` / display ``name`` / ``location``, each entity's
    ``(domain, device_class)`` (for ``derive_device_types``), and the last
    wake time.

    Pure -- no ``hass``, no driver -- so the in-process handler
    (``read_fleet``) and the standalone CLI both feed it from their own
    access layer (the in-process driver + HA registries / recorder, or a
    zwave-js-server socket + the HA API) and get an identical read.
    """

    device = build_device(
        node,
        device_id=device_id,
        device_types=derive_device_types(entities),
    )
    actuals = actual_values(node)
    convergence = ConvergenceDevice(
        node_id=node.node_id,
        name=name,
        device_id=device_id,
        location=location,
        wake_interval_seconds=actuals.get(_WAKE_UP_INTERVAL),
        last_awake_at=last_awake,
    )
    return NodeRead(device=device, convergence=convergence, actuals=actuals)


async def _read_node(
    hass: HomeAssistant, driver: Driver, entry_id: str, node: Node
) -> NodeRead:
    device_id, name, location, entities = _registry_context(
        hass, driver, entry_id, node
    )
    last_awake = (
        await _last_awake(hass, device_id) if device_id is not None else None
    )
    return build_node_read(
        node,
        device_id=device_id,
        name=name,
        location=location,
        entities=entities,
        last_awake=last_awake,
    )


def _registry_context(
    hass: HomeAssistant, driver: Driver, entry_id: str, node: Node
) -> tuple[str | None, str, str | None, list[tuple[str, str | None]]]:
    """The HA-registry view of a node: ``device_id``, display name, area,
    and each entity's ``(domain, device_class)``. Falls back to the node's
    own name when HA has no device registered for it (and then there are no
    device_id / area / entities to read)."""

    from homeassistant.components.zwave_js.helpers import get_device_id
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    dev_entry = dr.async_get(hass).async_get_device_by_identifier(
        get_device_id(driver, node), entry_id
    )
    if dev_entry is None:
        return None, node.name or "", None, []
    name = dev_entry.name_by_user or dev_entry.name or node.name or ""
    location: str | None = None
    if dev_entry.area_id is not None:
        area = ar.async_get(hass).async_get_area(dev_entry.area_id)
        location = area.name if area is not None else None
    ent_reg = er.async_get(hass)
    entities = [
        (entry.entity_id.split(".", 1)[0], _device_class(hass, entry))
        for entry in er.async_entries_for_device(ent_reg, dev_entry.id)
    ]
    return dev_entry.id, name, location, entities


def _device_class(hass: HomeAssistant, entry: RegistryEntry) -> str | None:
    """An entity's device class for device-type derivation.

    zwave_js leaves the entity registry's device class unset and only
    publishes it on the live state, so the registry value (a user override,
    then the platform default) falls back to the current state attribute.
    """

    return (
        entry.device_class
        or entry.original_device_class
        or _state_device_class(hass, entry.entity_id)
    )


def _state_device_class(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    device_class = state.attributes.get("device_class")
    return device_class if isinstance(device_class, str) else None


async def _last_awake(hass: HomeAssistant, device_id: str) -> datetime | None:
    """The node-status entity's last ``awake`` transition from the
    recorder, or ``None`` when the device has no node-status entity or has
    not woken inside the lookback window (e.g. a wake interval exceeding
    recorder retention). Best-effort: the wake context is informational, so
    an unknown last-wake just drops the expected-next-wake estimate."""

    from homeassistant.components.recorder.history import (
        state_changes_during_period,
    )
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.recorder import get_instance
    from homeassistant.util import dt as dt_util

    ent_reg = er.async_get(hass)
    status = next(
        (
            entry
            for entry in er.async_entries_for_device(ent_reg, device_id)
            if entry.translation_key == "node_status"
            and entry.platform == _ZWAVE_JS_PLATFORM
        ),
        None,
    )
    if status is None:
        return None
    now = dt_util.utcnow()
    history = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        now - _WAKE_LOOKBACK,
        now,
        status.entity_id,
    )
    awakes = [
        s for s in history.get(status.entity_id, []) if s.state == "awake"
    ]
    return awakes[-1].last_changed if awakes else None
