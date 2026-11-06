#!/usr/bin/env -S uv run --script --exact
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.375",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Integration-level tests for the BW handler.

Drives ``blueprint_toolkit.battery_watchdog`` against a real
in-process HA (pytest-HACC): the live schema + argparse, the
battery read off the state machine and the entity / device /
area registries, the notification dispatch, and the
diagnostic state entity.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Make custom_components/ importable as a top-level package.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from conftest import RecoveryEventsIntegrationBase

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = (
    REPO_ROOT / "custom_components" / "blueprint_toolkit" / "battery_watchdog"
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

DOMAIN = "blueprint_toolkit"
SERVICE = "battery_watchdog"
INSTANCE = "automation.bw_test"
LOW_ID = f"blueprint_toolkit_battery_watchdog__{INSTANCE}__low_batteries"


@pytest.fixture(autouse=True)
def install_our_integration(
    hass: HomeAssistant,
    # Requested for its side effect; pytest resolves fixtures by name
    # so it can't be ``_``-prefixed, and ``usefixtures`` has no effect
    # on a fixture function.
    enable_custom_integrations: None,  # noqa: ARG001
) -> Generator[None]:
    """Symlink our integration into pytest-HACC's config_dir."""
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


def _mock_config_entry(**kwargs: Any) -> MockConfigEntry:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    return MockConfigEntry(**kwargs)


async def _setup_integration(hass: Any) -> Any:
    """Create + load a config entry; return it."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "persistent_notification", {})
    entry = _mock_config_entry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _payload(
    *,
    warning_level: int = 25,
    include_integrations: list[str] | None = None,
    exclude_integrations: list[str] | None = None,
    exclude_device_name_regex: str = "",
    include_entities: list[str] | None = None,
    exclude_entities: list[str] | None = None,
    exclude_entity_id_regex: str = "",
    exclude_entity_name_regex: str = "",
    validate_includes_excludes: bool = True,
) -> dict[str, Any]:
    return {
        "instance_id": INSTANCE,
        "trigger_id": "manual",
        "battery_warning_level_raw": warning_level,
        "include_integrations_raw": include_integrations or [],
        "exclude_integrations_raw": exclude_integrations or [],
        "exclude_device_name_regex_raw": exclude_device_name_regex,
        "include_entities_raw": include_entities or [],
        "exclude_entities_raw": exclude_entities or [],
        "exclude_entity_id_regex_raw": exclude_entity_id_regex,
        "exclude_entity_name_regex_raw": exclude_entity_name_regex,
        "check_interval_minutes_raw": 5,
        "validate_includes_excludes_raw": validate_includes_excludes,
        "debug_logging_raw": False,
    }


async def _scan(hass: HomeAssistant, **kwargs: Any) -> dict[str, Any]:
    """Run one scan; return the live notifications."""
    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    await hass.services.async_call(
        DOMAIN, SERVICE, _payload(**kwargs), blocking=True
    )
    await hass.async_block_till_done()
    notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
    return notifs


def _plant_battery(
    hass: HomeAssistant,
    *,
    unique_id: str,
    state: str,
    name: str = "Battery",
    device_name: str | None = "Window",
    device_area: str | None = "Kitchen",
    entity_area: str | None = None,
    domain: str = "sensor",
    platform: str = "zwave_js",
) -> tuple[str, str | None]:
    """Register a battery entity (and device); return (entity_id, device_id)."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    config_entry = _mock_config_entry(domain=platform)
    config_entry.add_to_hass(hass)
    area_reg = ar.async_get(hass)
    device_id: str | None = None
    if device_name is not None:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(platform, unique_id)},
            name=device_name,
        )
        if device_area is not None:
            area = area_reg.async_get_or_create(device_area)
            dev_reg.async_update_device(device.id, area_id=area.id)
        device_id = device.id
    entry = er.async_get(hass).async_get_or_create(
        domain=domain,
        platform=platform,
        unique_id=unique_id,
        device_id=device_id,
        config_entry=config_entry,
    )
    if entity_area is not None:
        # HA only lets an entity with a name of its own take an
        # area of its own.
        area = area_reg.async_get_or_create(entity_area)
        er.async_get(hass).async_update_entity(
            entry.entity_id, name=name, area_id=area.id
        )
    hass.states.async_set(
        entry.entity_id,
        state,
        {"device_class": "battery", "friendly_name": name},
    )
    return entry.entity_id, device_id


class TestConfigErrors:
    async def test_schema_rejection_creates_notification(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN, SERVICE, {"instance_id": INSTANCE}, blocking=True
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs = _async_get_or_create_notifications(hass)
        notif_id = (
            f"blueprint_toolkit_battery_watchdog__{INSTANCE}__config_error"
        )
        assert notif_id in notifs
        assert "schema:" in notifs[notif_id]["message"]

    async def test_include_entities_with_an_exclude_is_an_error(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        notifs = await _scan(
            hass,
            include_entities=["sensor.window_battery"],
            exclude_entities=["sensor.phone_battery"],
        )

        notif_id = (
            f"blueprint_toolkit_battery_watchdog__{INSTANCE}__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "include_entities" in msg
        assert "exclude_entities" in msg

    async def test_successful_scan_dismisses_prior_config_error(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN, SERVICE, {"instance_id": INSTANCE}, blocking=True
        )
        notifs = await _scan(hass)

        assert not [n for n in notifs if n.endswith("__config_error")]


class TestLowBatteryNotification:
    async def test_lists_a_low_battery_with_links(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        hass.states.async_set(
            INSTANCE, "on", {"friendly_name": "Battery Watchdog", "id": "42"}
        )
        entity_id, device_id = _plant_battery(
            hass, unique_id="window", state="20"
        )

        notifs = await _scan(hass)

        assert LOW_ID in notifs
        assert notifs[LOW_ID]["title"] == "Battery Watchdog: 1 low battery"
        body: str = notifs[LOW_ID]["message"]
        assert body.startswith(
            "Automation: [Battery Watchdog](/config/automation/edit/42)\n"
        )
        assert body.endswith(
            f"- Kitchen -> [Window](/config/devices/device/{device_id}): "
            f"[20%](/history?entity_id={entity_id})"
        )

    async def test_level_at_the_warning_level_is_listed(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        _plant_battery(hass, unique_id="window", state="25")

        notifs = await _scan(hass, warning_level=25)

        assert LOW_ID in notifs

    async def test_level_above_warning_is_not_listed(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        _plant_battery(hass, unique_id="window", state="26")

        notifs = await _scan(hass, warning_level=25)

        assert LOW_ID not in notifs

    async def test_entity_area_overrides_device_area(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        _plant_battery(
            hass,
            unique_id="remote",
            state="10",
            device_name="Remote",
            device_area="Kitchen",
            entity_area="Den",
        )

        notifs = await _scan(hass)

        assert "- Den -> [Remote]" in notifs[LOW_ID]["message"]

    async def test_binary_battery_reads_low(self, hass: HomeAssistant) -> None:
        await _setup_integration(hass)
        entity_id, _ = _plant_battery(
            hass,
            unique_id="lock",
            state="on",
            device_name="Lock",
            domain="binary_sensor",
        )

        notifs = await _scan(hass)

        assert notifs[LOW_ID]["message"].endswith(
            f": [low](/history?entity_id={entity_id})"
        )

    async def test_deviceless_battery_shows_its_name(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        hass.states.async_set(
            "sensor.spare_battery",
            "5",
            {"device_class": "battery", "friendly_name": "Spare"},
        )

        notifs = await _scan(hass)

        assert notifs[LOW_ID]["message"] == (
            "- Spare: [5%](/history?entity_id=sensor.spare_battery)"
        )

    async def test_user_text_is_escaped(self, hass: HomeAssistant) -> None:
        await _setup_integration(hass)
        _plant_battery(
            hass,
            unique_id="lamp",
            state="10",
            device_name="Lamp [old]",
            device_area="[Den]",
        )

        notifs = await _scan(hass)

        assert r"- \[Den\] -> [Lamp \[old\]](" in notifs[LOW_ID]["message"]

    async def test_recovery_dismisses_the_notification(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        entity_id, _ = _plant_battery(hass, unique_id="window", state="20")
        assert LOW_ID in await _scan(hass)

        hass.states.async_set(
            entity_id,
            "100",
            {"device_class": "battery", "friendly_name": "Battery"},
        )

        assert LOW_ID not in await _scan(hass)

    async def test_level_change_updates_the_notification(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        entity_id, _ = _plant_battery(hass, unique_id="window", state="20")
        before = (await _scan(hass))[LOW_ID]

        hass.states.async_set(
            entity_id,
            "10",
            {"device_class": "battery", "friendly_name": "Battery"},
        )
        after = (await _scan(hass))[LOW_ID]

        assert "[20%]" in before["message"]
        assert "[10%]" in after["message"]
        assert after["created_at"] >= before["created_at"]

    async def test_unchanged_level_leaves_the_notification_alone(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        _plant_battery(hass, unique_id="window", state="20")
        before = (await _scan(hass))[LOW_ID]

        after = (await _scan(hass))[LOW_ID]

        assert after["created_at"] == before["created_at"]


class TestExclusions:
    async def test_exclude_entities_drops_a_battery(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        entity_id, _ = _plant_battery(hass, unique_id="phone", state="5")

        notifs = await _scan(hass, exclude_entities=[entity_id])

        assert LOW_ID not in notifs

    async def test_excluded_integration_drops_the_whole_device(
        self, hass: HomeAssistant
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        _, device_id = _plant_battery(hass, unique_id="fan", state="5")
        er.async_get(hass).async_get_or_create(
            domain="fan",
            platform="switch_as_x",
            unique_id="fan",
            device_id=device_id,
        )

        assert LOW_ID in await _scan(hass)
        assert LOW_ID not in await _scan(
            hass, exclude_integrations=["switch_as_x"]
        )

    async def test_include_entities_watches_only_those(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        kept, _ = _plant_battery(hass, unique_id="window", state="5")
        _plant_battery(hass, unique_id="door", state="5", device_name="Door")

        notifs = await _scan(hass, include_entities=[kept])

        body: str = notifs[LOW_ID]["message"]
        assert "[Window]" in body
        assert "[Door]" not in body


class TestUnmatchedDirectives:
    async def test_non_battery_entity_is_flagged(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        _plant_battery(hass, unique_id="window", state="80")
        hass.states.async_set("sensor.temperature", "21")

        notifs = await _scan(hass, exclude_entities=["sensor.temperature"])

        notif_id = (
            f"blueprint_toolkit_battery_watchdog__{INSTANCE}"
            "__unmatched_directives"
        )
        assert notif_id in notifs
        assert "sensor.temperature" in notifs[notif_id]["message"]


class TestDiagnosticState:
    async def test_scan_writes_the_state_entity(
        self, hass: HomeAssistant
    ) -> None:
        await _setup_integration(hass)
        entity_id, _ = _plant_battery(hass, unique_id="window", state="20")
        _plant_battery(hass, unique_id="door", state="90", device_name="Door")

        await _scan(hass)

        state = hass.states.get("blueprint_toolkit.bw_bw_test_state")
        assert state is not None
        assert state.state == "ok"
        attrs = state.attributes
        assert attrs["instance_id"] == INSTANCE
        assert "last_run" in attrs
        assert "runtime" in attrs
        assert attrs["last_trigger"] == "manual"
        assert attrs["batteries"] == 2
        assert attrs["batteries_excluded"] == 0
        assert attrs["low_batteries"] == 1
        assert attrs["low_battery_entities"] == [entity_id]
        assert attrs["unmatched_directives"] == 0


class TestRecoveryEvents(RecoveryEventsIntegrationBase):
    service_tag = "BW"
    setup_integration = staticmethod(_setup_integration)


if __name__ == "__main__":
    from conftest import run_tests

    run_tests(__file__, _SCRIPT_PATH, REPO_ROOT)
