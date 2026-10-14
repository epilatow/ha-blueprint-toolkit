#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.372",
#     "zwave-js-server-python==0.73.1",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Integration tests for the in-process fleet read (source.read_fleet).

Stands up a fake zwave_js config entry whose runtime_data.client.driver
exposes one node built from a start_listening-shape state dict, plus HA
device / area / entity registries and the recorder, then asserts
read_fleet assembles the resolver Device, the ConvergenceDevice, and the
actuals the same way the live handler would.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

# Make custom_components/ importable as a top-level package; the
# uv-script env doesn't add the repo root to sys.path the way
# ``python -m pytest`` would.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# zwave_js_server and our own pure modules are safe to import at module
# scope. pytest-HACC's patch_recorder plugin refuses to load if
# homeassistant.components.recorder.util is already imported, and
# anything from pytest_homeassistant_custom_component.common pulls it in
# transitively -- so MockConfigEntry, the HA registries, and the recorder
# helper are deferred into the functions that use them.
from zwave_js_server.model.node import Node

from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (
    DeviceType,
    ParamId,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.source import (
    build_node_read,
    get_driver,
    read_fleet,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

HOME_ID = 0xC0FFEE


def _node() -> Node:
    """A sleeping Zooz ZSE11 motion sensor (node 5): a motion-sensitivity
    config param plus a wakeUpInterval."""

    data = {
        "nodeId": 5,
        "index": 0,
        "status": 1,
        "ready": True,
        "isListening": False,
        "isRouting": True,
        "isSecure": False,
        "name": "zwave node 5",
        "deviceConfig": {"manufacturer": "Zooz", "label": "ZSE11"},
        "deviceClass": {
            "basic": {"key": 3, "label": "Routing Slave"},
            "generic": {"key": 7, "label": "Notification Sensor"},
            "specific": {"key": 0, "label": "Unused"},
        },
        "endpoints": [{"nodeId": 5, "index": 0}],
        "values": [
            {
                "endpoint": 0,
                "commandClass": 112,
                "commandClassName": "Configuration",
                "property": 12,
                "propertyName": "Motion Sensor Sensitivity",
                "value": 8,
                "metadata": {
                    "type": "number",
                    "label": "Motion Sensor Sensitivity",
                    "min": 0,
                    "max": 8,
                    "states": {"0": "Disable"},
                    "writeable": True,
                },
            },
            {
                "endpoint": 0,
                "commandClass": 132,
                "commandClassName": "Wake Up",
                "property": "wakeUpInterval",
                "propertyName": "Wake-up interval",
                "value": 3600,
                "metadata": {
                    "type": "number",
                    "label": "Wake-up interval",
                    "min": 0,
                    "max": 86400,
                    "unit": "seconds",
                    "writeable": True,
                },
            },
        ],
    }
    return Node(MagicMock(), data)  # type: ignore[arg-type]


def _install_fleet(hass: HomeAssistant, node: Node) -> str:
    """Register a fake zwave_js entry + driver exposing ``node``, plus the
    device / area / entities HA would have. Returns the node-status
    entity_id (for seeding recorder history)."""

    from homeassistant.components.zwave_js.helpers import get_device_id
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    driver = MagicMock()
    driver.controller.home_id = HOME_ID
    driver.controller.nodes = {node.node_id: node}
    # The read selects LOADED entries, and a real one carries
    # ``runtime_data`` only while loaded.
    entry = MockConfigEntry(
        domain="zwave_js", data={}, state=ConfigEntryState.LOADED
    )
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.client.driver = driver
    entry.runtime_data = runtime

    area = ar.async_get(hass).async_get_or_create("Guest Bath")
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={get_device_id(driver, node)},
        name="Guest Bath Motion",
        manufacturer="Zooz",
        model="ZSE11",
    )
    dev_reg.async_update_device(device.id, area_id=area.id)

    ent_reg = er.async_get(hass)
    # zwave_js leaves the registry's device class unset and only publishes
    # it on the live state, so derive device_types off the state attribute.
    motion = ent_reg.async_get_or_create(
        "binary_sensor",
        "zwave_js",
        f"{HOME_ID}.5.motion",
        device_id=device.id,
    )
    hass.states.async_set(motion.entity_id, "off", {"device_class": "motion"})
    status = ent_reg.async_get_or_create(
        "sensor",
        "zwave_js",
        f"{HOME_ID}.5.node_status",
        device_id=device.id,
        translation_key="node_status",
        original_name="Node status",
    )
    return status.entity_id


def test_build_node_read_assembles_from_node_and_context() -> None:
    # The shared assembly is pure (no hass): a Node plus the HA-context
    # tuple the handler and the CLI each acquire on their own. Both feed it
    # here and get an identical NodeRead.
    node = _node()
    read = build_node_read(
        node,
        device_id="dev-1",
        name="Guest Bath Motion",
        location="Guest Bath",
        entities=[("binary_sensor", "motion")],
        last_awake=None,
    )
    assert read.device.node_id == 5
    assert read.device.device_types == frozenset({DeviceType.MOTION})
    assert read.device.params and {p.id for p in read.device.params} == {
        ParamId(112, 12),
        ParamId(132, "wakeUpInterval"),
    }
    assert read.convergence.name == "Guest Bath Motion"
    assert read.convergence.location == "Guest Bath"
    assert read.convergence.wake_interval_seconds == 3600
    assert read.convergence.last_awake_at is None
    assert read.actuals[ParamId(132, "wakeUpInterval")] == 3600


async def test_read_fleet_empty_without_zwave_js(hass: HomeAssistant) -> None:
    assert await read_fleet(hass) == []


async def test_read_fleet_empty_when_the_entry_is_not_loaded(
    hass: HomeAssistant,
) -> None:
    """An unloaded entry must read as empty, not raise.

    Home Assistant deletes ``runtime_data`` on unload, so reaching
    for the driver on an entry that is unloaded, retrying setup, or
    disabled would raise -- and the handler turns an empty read, not
    an exception, into its "Z-Wave JS unavailable" notification.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="zwave_js", data={})
    entry.add_to_hass(hass)

    assert not hasattr(entry, "runtime_data")
    assert await read_fleet(hass) == []


@pytest.mark.usefixtures("recorder_mock")
async def test_read_fleet_assembles_device_and_convergence(
    hass: HomeAssistant,
) -> None:
    node = _node()
    _install_fleet(hass, node)

    reads = await read_fleet(hass)
    assert len(reads) == 1
    read = reads[0]

    # resolver Device: identity off device_config, params off node.values,
    # device_types off the HA entity device_class.
    assert read.device.node_id == 5
    assert (read.device.manufacturer, read.device.model) == ("Zooz", "ZSE11")
    assert read.device.is_listening is False
    assert read.device.device_types == frozenset({DeviceType.MOTION})
    assert {p.id for p in read.device.params} == {
        ParamId(112, 12),
        ParamId(132, "wakeUpInterval"),
    }

    # ConvergenceDevice: HA registry name + area, wake interval off the node.
    conv = read.convergence
    assert conv.name == "Guest Bath Motion"
    assert conv.location == "Guest Bath"
    assert conv.device_id is not None
    assert conv.wake_interval_seconds == 3600
    # No node-status history recorded -> last wake unknown.
    assert conv.last_awake_at is None

    # actuals: current live values keyed by ParamId.
    assert read.actuals == {
        ParamId(112, 12): 8,
        ParamId(132, "wakeUpInterval"): 3600,
    }


@pytest.mark.usefixtures("recorder_mock")
async def test_read_fleet_resolves_the_device_of_its_own_entry(
    hass: HomeAssistant,
) -> None:
    """The lookup is scoped to the entry whose driver has the node.

    An identifier is unique only within a config entry, so the
    entry-scoped registry API is the supported way to resolve one.
    The decoy below registers the same identifier under a different
    entry -- which ``zwave_js``'s unique-id abort stops two LIVE
    controllers from doing, but which a stale or pre-migration entry
    can still own -- and it is registered FIRST, because an
    identifier-only search returns the earliest registration. That
    ordering is what makes these assertions fail if the lookup stops
    being scoped; with the fleet's own device first, an unscoped
    search would return it too and prove nothing.
    """

    from homeassistant.components.zwave_js.helpers import get_device_id
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    node = _node()
    dev_reg = dr.async_get(hass)

    other = MockConfigEntry(domain="zwave_js", data={})
    other.add_to_hass(hass)
    other_driver = MagicMock()
    other_driver.controller.home_id = HOME_ID
    decoy = dev_reg.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={get_device_id(other_driver, node)},
        name="Second Controller Motion",
    )

    _install_fleet(hass, node)

    reads = await read_fleet(hass)
    assert len(reads) == 1
    assert reads[0].convergence.name == "Guest Bath Motion"
    assert reads[0].convergence.device_id != decoy.id


@pytest.mark.usefixtures("recorder_mock")
async def test_read_fleet_skips_an_ignored_entry_ahead_of_the_live_one(
    hass: HomeAssistant,
) -> None:
    """An ignored discovery entry must not hide the live controller.

    Home Assistant lists ignored, disabled, and setup-retrying entries
    alongside loaded ones, and such an entry carries no driver. Taking
    the first entry regardless of state would report the fleet as
    unavailable for as long as the ignored one sorted ahead of the
    working controller, which the user cannot fix without deleting it.
    """
    from homeassistant.config_entries import SOURCE_IGNORE
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    ignored = MockConfigEntry(domain="zwave_js", data={}, source=SOURCE_IGNORE)
    ignored.add_to_hass(hass)

    _install_fleet(hass, _node())

    reads = await read_fleet(hass)
    assert len(reads) == 1
    assert reads[0].convergence.name == "Guest Bath Motion"


async def test_read_fleet_empty_while_the_driver_is_connecting(
    hass: HomeAssistant,
) -> None:
    """A loaded entry whose client has no driver yet reads as empty."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain="zwave_js", data={}, state=ConfigEntryState.LOADED
    )
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.client.driver = None
    entry.runtime_data = runtime

    assert await read_fleet(hass) == []


async def test_get_driver_returns_the_loaded_entrys_driver(
    hass: HomeAssistant,
) -> None:
    """The driver accessor the reconnect subscription arms itself from."""
    node = _node()
    _install_fleet(hass, node)

    driver = get_driver(hass)
    assert driver is not None
    assert driver.controller.nodes == {node.node_id: node}


async def test_get_driver_none_without_a_loaded_entry(
    hass: HomeAssistant,
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    assert get_driver(hass) is None

    entry = MockConfigEntry(domain="zwave_js", data={})
    entry.add_to_hass(hass)
    assert get_driver(hass) is None


@pytest.mark.usefixtures("recorder_mock")
async def test_read_fleet_last_awake_from_recorder(
    hass: HomeAssistant,
) -> None:
    from pytest_homeassistant_custom_component.components.recorder.common import (  # noqa: E501
        async_wait_recording_done,
    )

    node = _node()
    status_entity = _install_fleet(hass, node)

    hass.states.async_set(status_entity, "asleep")
    hass.states.async_set(status_entity, "awake")
    hass.states.async_set(status_entity, "asleep")
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    reads = await read_fleet(hass)
    # The node-status entity's last 'awake' transition is found + dated.
    assert reads[0].convergence.last_awake_at is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
