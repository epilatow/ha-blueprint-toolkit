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
"""Integration-level tests for the ZPM handler.

Boots the integration in-process (pytest-HACC) and drives the
``blueprint_toolkit.zwave_parameter_manager`` service against a fake
``zwave_js`` config entry whose driver exposes one battery node. Covers
the full reconcile path the unit tests skip: argparse, the policy-file
read + parse, the live fleet read off the driver, the plan, and the
dispatch of a real write through the ``zwave_js`` services. Plus the
config-error and Z-Wave-JS-unavailable terminal paths and the shared
restart/reload recovery wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from conftest import RecoveryEventsIntegrationBase

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

DOMAIN = "blueprint_toolkit"
SERVICE = "zwave_parameter_manager"
HOME_ID = 0xC0FFEE

_WAKE_POLICY = """
policies:
  - name: wake fast
    match:
      power: battery
    settings:
      wake_up_interval: 3600
"""

_UNUSED_POLICY = """
policies:
  - name: ghost
    match:
      manufacturer: Nonexistent Inc.
    settings:
      wake_up_interval: 3600
"""


@pytest.fixture(autouse=True)
def install_our_integration(
    # Both requested for their side effect; pytest resolves fixtures by name
    # so they can't be ``_``-prefixed, and ``usefixtures`` has no effect on a
    # fixture function.
    recorder_mock: object,  # noqa: ARG001
    hass: HomeAssistant,
    enable_custom_integrations: None,  # noqa: ARG001
) -> Generator[None]:
    """Symlink our integration into pytest-HACC's config_dir.

    Depends on ``recorder_mock`` first so the recorder DB is set up before
    ``hass`` -- ``source.read_fleet`` reads the recorder for last-wake, and
    pytest-HACC refuses to attach the recorder once ``hass`` is already up.
    """
    import shutil

    src = (
        Path(__file__).parent.parent / "custom_components" / "blueprint_toolkit"
    )
    cc = Path(hass.config.config_dir) / "custom_components"
    cc.mkdir(exist_ok=True)
    dst = cc / "blueprint_toolkit"
    if dst.is_symlink() or dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    dst.symlink_to(src)
    from homeassistant.loader import DATA_CUSTOM_COMPONENTS

    hass.data.pop(DATA_CUSTOM_COMPONENTS, None)
    yield
    if dst.is_symlink():
        dst.unlink()


def _mock_config_entry(**kwargs: Any) -> Any:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(**kwargs)


async def _setup_integration(hass: Any) -> Any:
    """Create + load the blueprint_toolkit entry; return it."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "persistent_notification", {})
    entry = _mock_config_entry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _node(wake_value: int) -> Any:
    """A sleeping node with a wakeUpInterval at ``wake_value`` seconds."""
    from zwave_js_server.model.node import Node

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
                "commandClass": 132,
                "commandClassName": "Wake Up",
                "property": "wakeUpInterval",
                "propertyName": "Wake-up interval",
                "value": wake_value,
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


def _install_zwave_js(hass: Any) -> str:
    """Register a fake zwave_js entry + driver + the node's HA device.

    Returns the HA device_id the write must target.
    """
    from homeassistant.components.zwave_js.helpers import get_device_id
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    node = _node(1800)
    driver = MagicMock()
    driver.controller.home_id = HOME_ID
    driver.controller.nodes = {node.node_id: node}
    # Controller-statistics counters the driver-session monitor + the handler
    # sample to detect a driver restart (a drop below the stored value).
    driver.controller.statistics.messages_rx = 1000
    driver.controller.statistics.messages_tx = 500
    # The read selects LOADED entries, and a real one carries
    # ``runtime_data`` only while loaded.
    entry = MockConfigEntry(
        domain="zwave_js", data={}, state=ConfigEntryState.LOADED
    )
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.client.driver = driver
    entry.runtime_data = runtime

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={get_device_id(driver, node)},
        name="Guest Bath Motion",
        manufacturer="Zooz",
        model="ZSE11",
    )
    return device.id


def _capture_zwave_services(hass: Any) -> list[tuple[str, dict[str, Any]]]:
    """Register stand-in zwave_js apply services that record their calls."""
    from homeassistant.core import ServiceCall

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _record(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("zwave_js", "set_config_parameter", _record)
    hass.services.async_register("zwave_js", "set_value", _record)
    return calls


def _payload(
    config_file_path: str = "zwave_parameter_manager.yaml",
    *,
    pending_report_interval_hours: int = 24,
) -> dict[str, Any]:
    return {
        "instance_id": "automation.zpm_test",
        "trigger_id": "manual",
        "config_file_path": config_file_path,
        "reconcile_interval_minutes_raw": 5,
        "pending_report_interval_hours_raw": pending_report_interval_hours,
        "debug_logging_raw": False,
    }


def _write_policy(hass: Any, text: str) -> None:
    path = Path(hass.config.config_dir) / "zwave_parameter_manager.yaml"
    path.write_text(text, encoding="utf-8")


def _zpm_state(hass: Any) -> Any:
    for eid in hass.states.async_entity_ids():
        if eid.startswith("blueprint_toolkit.zpm_"):
            return hass.states.get(eid)
    return None


async def test_reconcile_dispatches_wake_interval_write(hass: Any) -> None:
    _write_policy(hass, _WAKE_POLICY)
    device_id = _install_zwave_js(hass)
    calls = _capture_zwave_services(hass)
    await _setup_integration(hass)

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()

    # The policy's wake interval (3600) differs from the node's live value
    # (1800), so the reconcile issues a set_value to converge it.
    set_values = [data for service, data in calls if service == "set_value"]
    assert any(
        data["device_id"] == device_id
        and data["command_class"] == 132
        and data["property"] == "wakeUpInterval"
        and data["value"] == 3600
        for data in set_values
    ), set_values

    state = _zpm_state(hass)
    assert state is not None
    assert state.attributes["writes_issued"] == 1
    assert state.attributes["devices"] == 1


async def test_pending_notification_dismisses_on_convergence(
    hass: Any,
) -> None:
    # The pending notification appears as soon as a write is unconverged, and
    # is dismissed once the device applies the write rather than being left
    # stuck on the panel -- convergence dismisses regardless of the interval.
    _write_policy(hass, _WAKE_POLICY)
    _install_zwave_js(hass)
    _capture_zwave_services(hass)
    await _setup_integration(hass)

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    notifs = _async_get_or_create_notifications(hass)
    assert any(nid.endswith("__pending") for nid in notifs), list(notifs)

    # Simulate the sleeping device waking and applying the write: swap in a
    # node already at the policy's target, so the next reconcile sees it
    # converged -- the pending set empties and the notification is dismissed.
    driver = hass.config_entries.async_entries("zwave_js")[
        0
    ].runtime_data.client.driver
    converged = _node(3600)
    driver.controller.nodes = {converged.node_id: converged}

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    notifs = _async_get_or_create_notifications(hass)
    assert not any(nid.endswith("__pending") for nid in notifs), list(notifs)


async def test_pending_report_disabled_when_interval_zero(hass: Any) -> None:
    # A pending-report interval of 0 turns the report off: an unconverged
    # write still dispatches, but no pending notification is published.
    _write_policy(hass, _WAKE_POLICY)
    _install_zwave_js(hass)
    _capture_zwave_services(hass)
    await _setup_integration(hass)

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE,
        _payload(pending_report_interval_hours=0),
        blocking=True,
    )
    await hass.async_block_till_done()
    notifs = _async_get_or_create_notifications(hass)
    assert not any(nid.endswith("__pending") for nid in notifs), list(notifs)


async def test_stale_pending_dismissed_after_state_reset(hass: Any) -> None:
    # A pending report published before an entry reload must be dismissed on
    # the first reconcile after the reload if the fleet converged during the
    # gap. In-memory state is volatile across a reload, so a fresh instance has
    # no memory that it published (``last_pending_publish_dt is None``) -- the
    # reconcile must still clear the stale notification rather than gate the
    # dismiss on having published it in this process.
    from custom_components.blueprint_toolkit.zwave_parameter_manager import (
        handler,
    )

    _write_policy(hass, _WAKE_POLICY)
    _install_zwave_js(hass)
    _capture_zwave_services(hass)
    await _setup_integration(hass)

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    notifs = _async_get_or_create_notifications(hass)
    assert any(nid.endswith("__pending") for nid in notifs), list(notifs)

    # Reproduce the post-reload fresh-instance condition without tearing down
    # the timer: clear the "we published" memory, then converge the fleet.
    (state,) = handler._instances(hass).values()
    state.last_pending_publish_dt = None
    driver = hass.config_entries.async_entries("zwave_js")[
        0
    ].runtime_data.client.driver
    converged = _node(3600)
    driver.controller.nodes = {converged.node_id: converged}

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    notifs = _async_get_or_create_notifications(hass)
    assert not any(nid.endswith("__pending") for nid in notifs), list(notifs)


async def test_invalid_policy_emits_config_error(hass: Any) -> None:
    _write_policy(hass, "policies: not-a-list\n")
    _install_zwave_js(hass)
    await _setup_integration(hass)

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    notifs = _async_get_or_create_notifications(hass)
    assert any("config_error" in nid for nid in notifs), list(notifs)


async def test_unused_policy_emits_notification(hass: Any) -> None:
    # A policy whose selector matches no installed device lands on
    # nothing, so the reconcile fires the unused-config notification on
    # its first (config-change) pass.
    _write_policy(hass, _UNUSED_POLICY)
    _install_zwave_js(hass)
    await _setup_integration(hass)

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    notifs = _async_get_or_create_notifications(hass)
    assert any("unused" in nid for nid in notifs), list(notifs)


async def test_no_zwave_js_emits_unavailable(hass: Any) -> None:
    _write_policy(hass, _WAKE_POLICY)
    # No zwave_js entry installed -> read_fleet returns [].
    await _setup_integration(hass)

    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()

    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    notifs = _async_get_or_create_notifications(hass)
    assert any("unavailable" in nid for nid in notifs), list(notifs)


async def test_driver_restart_reissues(hass: Any) -> None:
    _write_policy(hass, _WAKE_POLICY)
    _install_zwave_js(hass)
    calls = _capture_zwave_services(hass)
    await _setup_integration(hass)

    def _set_value_count() -> int:
        return len([d for s, d in calls if s == "set_value"])

    driver = hass.config_entries.async_entries("zwave_js")[
        0
    ].runtime_data.client.driver

    # First reconcile issues the write and records it in zpm_pending.json.
    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    assert _set_value_count() == 1

    # A second reconcile suppresses the re-issue (still queued, no restart).
    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    assert _set_value_count() == 1

    # Simulate a driver / add-on restart: the controller-statistics counters
    # reset to near-zero. The next reconcile refreshes the driver-session
    # record, sees the drop, treats the pending set as flushed, and re-issues.
    driver.controller.statistics.messages_rx = 5
    driver.controller.statistics.messages_tx = 3
    await hass.services.async_call(DOMAIN, SERVICE, _payload(), blocking=True)
    await hass.async_block_till_done()
    assert _set_value_count() == 2


class TestRecovery(RecoveryEventsIntegrationBase):
    service_tag = "ZPM"
    setup_integration = staticmethod(_setup_integration)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
