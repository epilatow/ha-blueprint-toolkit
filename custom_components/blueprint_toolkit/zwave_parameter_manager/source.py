# This is AI generated code
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest-homeassistant-custom-component==0.13.357",
#     "zwave-js-server-python==0.73.0",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
"""Read the live Z-Wave fleet from HA's in-process zwave_js driver.

The handler's read side. For each node the in-process zwave_js driver
knows about, assemble the resolver ``Device`` (identity + settable
params), the convergence ``ConvergenceDevice`` (name / location / wake
context), and the current value of each settable param.

Values, metadata, and identity come off ``node.values`` -- the live
driver state, not HA's cached entity states and not the on-disk cache.
``device_id`` / name / location come from the HA device + area
registries; ``device_types`` from the entity registry's device-class
attributes; the last wake from the node-status entity's recorder history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

from ..zwave.convergence import ConvergenceDevice
from .adapter import actual_values, build_device, derive_device_types
from .logic import CommandClass, Device, ParamId

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node

_ZWAVE_JS_DOMAIN = "zwave_js"

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

    Returns an empty list when zwave_js is not loaded.
    """

    driver = get_driver(hass)
    if driver is None:
        return []
    return [
        await _read_node(hass, driver, node)
        for node in driver.controller.nodes.values()
    ]


def get_driver(hass: HomeAssistant) -> Driver | None:
    """The in-process zwave_js driver, or ``None`` when it is not loaded."""
    entries = hass.config_entries.async_entries(_ZWAVE_JS_DOMAIN)
    if not entries:
        return None
    return cast("Driver | None", entries[0].runtime_data.client.driver)


async def _read_node(
    hass: HomeAssistant, driver: Driver, node: Node
) -> NodeRead:
    device_id, name, location, entities = _registry_context(hass, driver, node)
    device = build_device(
        node,
        device_id=device_id,
        device_types=derive_device_types(entities),
    )
    actuals = actual_values(node)
    last_awake = (
        await _last_awake(hass, device_id) if device_id is not None else None
    )
    convergence = ConvergenceDevice(
        node_id=node.node_id,
        name=name,
        device_id=device_id,
        location=location,
        wake_interval_seconds=actuals.get(_WAKE_UP_INTERVAL),
        last_awake_at=last_awake,
    )
    return NodeRead(device=device, convergence=convergence, actuals=actuals)


def _registry_context(
    hass: HomeAssistant, driver: Driver, node: Node
) -> tuple[str | None, str, str | None, list[tuple[str, str | None]]]:
    """The HA-registry view of a node: ``device_id``, display name, area,
    and each entity's ``(domain, device_class)``. Falls back to the node's
    own name when HA has no device registered for it (and then there are no
    device_id / area / entities to read)."""

    from homeassistant.components.zwave_js.helpers import get_device_id
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    dev_entry = dr.async_get(hass).async_get_device(
        identifiers={get_device_id(driver, node)}
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
        (
            entry.entity_id.split(".", 1)[0],
            entry.device_class or entry.original_device_class,
        )
        for entry in er.async_entries_for_device(ent_reg, dev_entry.id)
    ]
    return dev_entry.id, name, location, entities


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
            and entry.platform == _ZWAVE_JS_DOMAIN
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
