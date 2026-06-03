#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.357",
#     "zwave-js-server-python==0.73.0",
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

import pytest  # noqa: E402

# zwave_js_server and our own pure modules are safe to import at module
# scope. pytest-HACC's patch_recorder plugin refuses to load if
# homeassistant.components.recorder.util is already imported, and
# anything from pytest_homeassistant_custom_component.common pulls it in
# transitively -- so MockConfigEntry, the HA registries, and the recorder
# helper are deferred into the functions that use them.
from zwave_js_server.model.node import Node  # noqa: E402

from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    DeviceType,
    ParamId,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.source import (  # noqa: E402, E501
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
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    driver = MagicMock()
    driver.controller.home_id = HOME_ID
    driver.controller.nodes = {node.node_id: node}
    entry = MockConfigEntry(domain="zwave_js", data={})
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


async def test_read_fleet_empty_without_zwave_js(hass: HomeAssistant) -> None:
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
