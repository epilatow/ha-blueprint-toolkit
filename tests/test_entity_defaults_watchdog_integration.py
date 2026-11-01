#!/usr/bin/env -S uv run --script
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
"""Integration-level tests for the EDW handler.

Exercises the parts the in-process unit tests
(``tests/test_entity_defaults_watchdog_handler.py``)
deliberately don't cover: the live ``probatio.Schema`` argparse,
the helper-driven multi-line regex validation, the full
``_async_service_layer`` build-and-apply loop against
``hass.states`` / ``hass.config_entries.async_entries`` /
the entity + device registries (truth-set assembly +
executor offload of ``run_evaluation`` + sweep dispatch +
``update_instance_state``), and the
automation-link-prefix-on-notification-body invariant the
plan flags as a P1 regression. Same pytest-HACC harness
as ``test_integration.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

# Make custom_components/ importable as a top-level package;
# the uv-script env doesn't add the repo root to sys.path
# the way ``python -m pytest`` would.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from conftest import (
    RecoveryEventsIntegrationBase,
    WatchdogFindingLifecycleBase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

# pytest-HACC's plugins refuse to load if any
# homeassistant.components.* module is already in
# sys.modules. Defer imports until inside the tests.
DOMAIN = "blueprint_toolkit"
SERVICE = "entity_defaults_watchdog"


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
    """Lazy-import wrapper for MockConfigEntry."""
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    return MockConfigEntry(**kwargs)


async def _setup_integration(hass: Any) -> Any:
    """Create + load a config entry; return it.

    Also explicitly sets up ``persistent_notification`` so
    the argparse-error code path can dispatch to it. The
    pytest-HACC harness doesn't auto-load it.
    """
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "persistent_notification", {})
    entry = _mock_config_entry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _valid_payload(
    *,
    instance_id: str = "automation.edw_test",
    drift_checks: list[str] | None = None,
    include_integrations: list[str] | None = None,
    exclude_integrations: list[str] | None = None,
    exclude_device_name_regex: str = "",
    exclude_entities: list[str] | None = None,
    exclude_entity_id_regex: str = "",
    exclude_entity_name_regex: str = "",
    check_interval_minutes: int = 60,
    max_device_notifications: int = 0,
    create_repairs: bool = False,
    max_repairs: int = 5,
    validate_includes_excludes: bool = True,
) -> dict[str, Any]:
    """Build a fully-populated EDW service-call payload."""
    return {
        "instance_id": instance_id,
        "trigger_id": "manual",
        "drift_checks_raw": drift_checks or [],
        "include_integrations_raw": include_integrations or [],
        "exclude_integrations_raw": exclude_integrations or [],
        "exclude_device_name_regex_raw": exclude_device_name_regex,
        "exclude_entities_raw": exclude_entities or [],
        "exclude_entity_id_regex_raw": exclude_entity_id_regex,
        "exclude_entity_name_regex_raw": exclude_entity_name_regex,
        "check_interval_minutes_raw": check_interval_minutes,
        "max_device_notifications_raw": max_device_notifications,
        "create_repairs_raw": create_repairs,
        "max_repairs_raw": max_repairs,
        "validate_includes_excludes_raw": validate_includes_excludes,
        "debug_logging_raw": False,
    }


# --------------------------------------------------------
# Argparse / config-error notification path
# --------------------------------------------------------


class TestArgparseEmitsConfigErrorNotification:
    async def test_missing_required_keys_create_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A bad call must show up as a persistent notification."""
        await _setup_integration(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.edw_bad_call"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_bad_call__config_error"
        )
        assert notif_id in notifs, "config-error notification was not emitted"
        assert "schema:" in notifs[notif_id]["message"]

    async def test_unknown_drift_check_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Cross-validation rejects values not in CHECK_ALL."""
        await _setup_integration(hass)

        payload = _valid_payload(
            instance_id="automation.edw_bad_check",
            drift_checks=["device-entity-id", "bogus-check"],
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_bad_check__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "drift_checks" in msg
        assert "bogus-check" in msg

    async def test_invalid_regex_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A bad regex line in any of the three regex fields
        surfaces as a per-line config error.
        """
        await _setup_integration(hass)

        payload = _valid_payload(
            instance_id="automation.edw_bad_regex",
            exclude_entity_id_regex="[unclosed",
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_bad_regex__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "[unclosed" in msg
        assert "exclude_entity_id_regex" in msg

    async def test_match_all_regex_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """``.*`` matches every entity; the helper rejects
        it with a ``"matches empty string"`` error.
        """
        await _setup_integration(hass)

        payload = _valid_payload(
            instance_id="automation.edw_match_all",
            exclude_device_name_regex=".*",
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_match_all__config_error"
        )
        assert notif_id in notifs
        assert "matches empty string" in notifs[notif_id]["message"]

    async def test_notification_includes_automation_link_when_known(
        self,
        hass: HomeAssistant,
    ) -> None:
        """When the automation entity is registered, the
        config-error body starts with the
        ``Automation: [name](link)`` header.
        """
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.edw_link",
            "on",
            {"friendly_name": "EDW: Linked", "id": "1234"},
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.edw_link"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_link__config_error"
        )
        assert notif_id in notifs
        body: str = notifs[notif_id]["message"]
        assert body.startswith(
            "Automation: [EDW: Linked](/config/automation/edit/1234)\n",
        )

    async def test_successful_call_dismisses_prior_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        # Bad call first.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.edw_dismiss"},
            blocking=True,
        )
        # Then a good call with the same instance_id.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.edw_dismiss"),
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_dismiss__config_error"
        )
        assert notif_id not in notifs


class TestServiceLayerScan:
    async def test_successful_scan_creates_diagnostic_state(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A successful scan populates the diagnostic state
        entity at
        ``blueprint_toolkit.edw_<slug>_state``
        with the common attrs (``instance_id``, ``last_run``,
        ``runtime``) plus the per-port stat extras.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.edw_scan"),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_scan_state",
        )
        assert state is not None, "diagnostic state entity not created"
        assert state.state == "ok"
        attrs = state.attributes
        # Common attrs.
        assert attrs["instance_id"] == "automation.edw_scan"
        assert "last_run" in attrs
        assert "runtime" in attrs
        # Per-port stat extras (subset; full list in the
        # handler).
        for key in (
            "integrations",
            "integrations_excluded",
            "devices",
            "devices_excluded",
            "entities",
            "entities_excluded",
            "device_issues",
            "entity_issues",
            "entity_name_issues",
            "entity_id_issues",
            "deviceless_entities",
            "deviceless_excluded",
            "deviceless_drift",
            "deviceless_stale",
        ):
            assert key in attrs, f"missing diagnostic attr: {key}"
        # Trigger label propagates from the payload.
        assert attrs["last_trigger"] == "manual"

    async def test_deviceless_notification_carries_automation_link(
        self,
        hass: HomeAssistant,
    ) -> None:
        """EDW's deviceless aggregate notification must carry
        the ``Automation: [name](link)`` prefix. Regression
        guard for the same plan-flagged P1 RW caught: a
        ``PersistentNotification`` constructed without
        ``instance_id`` silently loses the click-through
        link, and the dispatcher's gate makes that
        invisible at code-review time.

        Trigger a deviceless finding by pre-seeding a state-
        only entity in a ``DEVICELESS_DOMAINS`` whose
        ``friendly_name`` doesn't match its slugified
        ``object_id`` -- ``EDW``'s state-only safety net
        path picks it up without needing a registry entry.
        """
        await _setup_integration(hass)
        # Register the automation entity so the dispatcher
        # can find a friendly name + YAML id to build the
        # link.
        hass.states.async_set(
            "automation.edw_finding",
            "on",
            {"friendly_name": "EDW: Finding", "id": "9999"},
        )
        # Plant a state-only entity whose effective name's
        # slugified form doesn't match its object_id. The
        # logic module's deviceless evaluator flags this as
        # drift and emits the deviceless aggregate
        # notification.
        hass.states.async_set(
            "input_text.legacy_object_id",
            "value",
            {"friendly_name": "Brand New Name"},
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.edw_finding"),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_finding__deviceless"
        )
        assert notif_id in notifs, (
            f"expected deviceless notification; got {sorted(notifs.keys())}"
        )
        body: str = notifs[notif_id]["message"]
        # Critical assertion: the dispatcher prepended the
        # automation-link header. Without ``instance_id`` on
        # the underlying ``PersistentNotification`` spec, the
        # body would start with the per-category content
        # directly.
        assert body.startswith(
            "Automation: [EDW: Finding](/config/automation/edit/9999)\n",
        ), f"missing automation-link prefix; body was: {body[:200]!r}"


class TestDeviceAttachedDisabledEntityFilter:
    async def test_disabled_entity_excluded_from_device_scan(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Disabled entities on the device-attached scan
        path must not contribute to drift findings. Parity
        regression: the deviceless path already filters
        ``disabled_by`` but the device-attached path used to
        scan disabled entities, producing noisy drift on
        entities the user had explicitly disabled.

        Plant a device with one enabled entity and one
        disabled entity under the same fake integration;
        verify the diagnostic state's ``entities`` count is
        1 (post-fix), not 2 (pre-fix).
        """
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)

        # The watchdog scan groups entities by their entity-
        # registry ``platform``. Mock a config entry plus a
        # registry entry whose ``platform="fake_integration"``
        # so the scan picks up our planted entities.
        fake_entry = _mock_config_entry(
            domain="fake_integration",
            title="fake_integration",
        )
        fake_entry.add_to_hass(hass)

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        device = dev_reg.async_get_or_create(
            config_entry_id=fake_entry.entry_id,
            identifiers={("fake_integration", "device-1")},
            name="Test Device",
        )

        ent_reg.async_get_or_create(
            domain="light",
            platform="fake_integration",
            unique_id="enabled-1",
            device_id=device.id,
            config_entry=fake_entry,
            original_name="enabled",
        )
        ent_reg.async_get_or_create(
            domain="light",
            platform="fake_integration",
            unique_id="disabled-1",
            device_id=device.id,
            config_entry=fake_entry,
            disabled_by=er.RegistryEntryDisabler.USER,
            original_name="disabled",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_disabled_test",
                include_integrations=["fake_integration"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_disabled_test_state",
        )
        assert state is not None
        assert state.attributes["entities"] == 1, (
            f"expected 1 enabled entity scanned; got "
            f"{state.attributes['entities']}"
        )


class TestUnmatchedDirectives:
    """End-to-end coverage of the unmatched-directives
    notification surface added by the
    ``validate_includes_excludes`` toggle.
    """

    async def test_excluding_state_only_entity_is_not_unmatched(
        self,
        hass: HomeAssistant,
    ) -> None:
        """An exclude that clears a state-only finding did match
        something, though the entity has no registry row.
        """
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        hass.states.async_set(
            "input_text.legacy_object_id",
            "value",
            {"friendly_name": "Brand New Name"},
        )

        def _repairs() -> list[str]:
            return [
                i.issue_id
                for i in ir.async_get(hass).issues.values()
                if i.domain == DOMAIN and "__repair_" in i.issue_id
            ]

        for overrides, expected_repairs in (
            ({}, 1),
            ({"exclude_entities": ["input_text.legacy_object_id"]}, 0),
            ({"exclude_entity_id_regex": "legacy_object_id"}, 0),
            ({"exclude_entity_name_regex": "Brand New Name"}, 0),
        ):
            await hass.services.async_call(
                DOMAIN,
                SERVICE,
                _valid_payload(
                    instance_id="automation.edw_state_only",
                    drift_checks=["entity-id"],
                    create_repairs=True,
                    **overrides,
                ),
                blocking=True,
            )
            await hass.async_block_till_done()

            assert len(_repairs()) == expected_repairs, overrides
            assert not [
                notification_id
                for notification_id in _async_get_or_create_notifications(hass)
                if "unmatched_directives" in notification_id
            ], overrides

    async def test_typoed_integration_fires_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_unmatched",
                exclude_integrations=["typoed_integration"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_unmatched__unmatched_directives"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id in notifs
        body: str = notifs[notif_id]["message"]
        assert "typoed_integration" in body
        assert "exclude_integrations" in body
        assert "unknown integration" in body

    async def test_toggle_off_dismisses_prior_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_toggle",
                exclude_integrations=["typoed_integration"],
                validate_includes_excludes=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_toggle__unmatched_directives"
        )
        assert notif_id in _async_get_or_create_notifications(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_toggle",
                exclude_integrations=["typoed_integration"],
                validate_includes_excludes=False,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()
        assert notif_id not in _async_get_or_create_notifications(hass)

    async def test_each_directive_category_surfaces_end_to_end(
        self,
        hass: HomeAssistant,
    ) -> None:
        """One representative bullet per directive category
        in a single notification body so a refactor that
        drops a category from ``_validate_edw_directives``
        fails CI rather than silently shipping.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_categories",
                exclude_integrations=["typoed_integration"],
                exclude_entities=["sensor.does_not_exist"],
                exclude_device_name_regex="^xyz_no_device_matches$",
                exclude_entity_id_regex="^xyz_no_entity_matches$",
                exclude_entity_name_regex="^xyz_no_name_matches$",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_categories__unmatched_directives"
        )
        body = _async_get_or_create_notifications(hass)[notif_id]["message"]
        for fragment in (
            "exclude_integrations",
            "exclude_entities",
            "exclude_device_name_regex",
            "exclude_entity_id_regex",
            "exclude_entity_name_regex",
            "typoed_integration",
            "sensor.does_not_exist",
            "xyz_no_device_matches",
            "xyz_no_entity_matches",
            "xyz_no_name_matches",
        ):
            assert fragment in body, (
                f"missing {fragment!r} in unmatched-directives body: {body!r}"
            )

    async def test_cap_bypass_unmatched_directives_always_surfaces(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The unmatched-directives notification rides outside the
        per-device cap.

        Regression guard: the cap-bypass is structural -- the
        unmatched spec is appended to the dispatch list AFTER
        ``prepare_notifications`` already trimmed the per-device
        results. Plant two devices with name-override drift (so
        cap=1 engages) plus a typo'd directive; assert the
        cap-summary AND the unmatched-directives notification
        both fire.
        """
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        hass.states.async_set(
            "automation.edw_capbypass",
            "on",
            {"friendly_name": "EDW: CapBypass", "id": "8989"},
        )
        fake_entry = _mock_config_entry(
            domain="fake_edw_capbypass",
            title="fake_edw_capbypass",
        )
        fake_entry.add_to_hass(hass)
        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        # Plant two devices each with a name-override that
        # diverges from the integration's original_name --
        # triggers name-drift findings on both, so cap=1
        # engages.
        for i in range(2):
            device = dev_reg.async_get_or_create(
                config_entry_id=fake_entry.entry_id,
                identifiers={("fake_edw_capbypass", f"device-cap-{i}")},
                name=f"CapDevice {i}",
            )
            entry = ent_reg.async_get_or_create(
                domain="sensor",
                platform="fake_edw_capbypass",
                unique_id=f"drift-{i}",
                device_id=device.id,
                config_entry=fake_entry,
                original_name=f"Original {i}",
            )
            # Set a name override that differs from
            # original_name -> EDW flags name drift.
            ent_reg.async_update_entity(
                entry.entity_id,
                name=f"OverriddenName{i}",
            )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_capbypass",
                include_integrations=["fake_edw_capbypass"],
                drift_checks=["device-entity-name"],
                exclude_integrations=["typoed_edw_capbypass_int"],
                max_device_notifications=1,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        prefix = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_capbypass__"
        )
        per_device = [
            nid for nid in notifs if nid.startswith(f"{prefix}device_")
        ]
        cap_id = f"{prefix}cap"
        unmatched_id = f"{prefix}unmatched_directives"

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_capbypass_state",
        )
        attrs = state.attributes if state else {}
        # Cap engaged: only one per-device fired.
        assert len(per_device) == 1, (
            f"expected exactly 1 per-device notif under cap=1; "
            f"diagnostic state attrs: {attrs}; "
            f"got {sorted(per_device)}"
        )
        assert cap_id in notifs
        assert unmatched_id in notifs, (
            f"unmatched-directives notif suppressed by cap; "
            f"got {sorted(notifs.keys())}"
        )
        body = notifs[unmatched_id]["message"]
        assert "typoed_edw_capbypass_int" in body

    async def test_out_of_target_integration_exclude_does_not_false_flag(
        self,
        hass: HomeAssistant,
    ) -> None:
        """An ``exclude_entities`` entry pointing at a registered
        entity outside ``include_integrations`` is redundant but
        not a typo -- the validator must NOT flag it as "no entity
        matches". Plants a fake registry entry on a non-targeted
        integration, sets ``include_integrations`` to a different
        integration, and asserts the validator stays quiet.
        """
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)

        # Plant a registry entry on integration "plant_other".
        ent_reg = er.async_get(hass)
        from pytest_homeassistant_custom_component.common import (
            MockConfigEntry,
        )

        other_entry = MockConfigEntry(
            domain="plant_other",
            title="plant_other",
        )
        other_entry.add_to_hass(hass)
        ent_reg.async_get_or_create(
            domain="sensor",
            platform="plant_other",
            unique_id="plant_other_only_one",
            suggested_object_id="plant_other_only_one",
            config_entry=other_entry,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_oot",
                include_integrations=["plant_target"],
                exclude_entities=["sensor.plant_other_only_one"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_oot__unmatched_directives"
        )
        notifs = _async_get_or_create_notifications(hass)
        if notif_id in notifs:
            body = notifs[notif_id]["message"]
            assert "sensor.plant_other_only_one" not in body, (
                "out-of-target-integration entity exclude "
                f"false-flagged as no-match: {body!r}"
            )


class TestVisibleAliasedScan:
    """End-to-end coverage of the visible-aliased-entity check.

    Plants a fake ``switch_as_x`` config entry plus the
    matching wrapper + source entity-registry entries, then
    drives a service call with the new ``visible-aliased-entity``
    drift-check value.
    """

    async def _plant_pair(
        self,
        hass: HomeAssistant,
        *,
        source_entity_id: str,
        wrapper_entity_id: str,
        wrapper_target_domain: str,
        source_friendly_name: str,
        source_hidden_by: er.RegistryEntryHider | None = None,
        source_disabled_by: er.RegistryEntryDisabler | None = None,
        source_device_id: str | None = None,
        bad_options: bool = False,
    ) -> MockConfigEntry:
        """Plant a switch_as_x entry + wrapper + source.

        Returns the planted ``MockConfigEntry``.
        """
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        # Source entity (the wrapped switch).
        ent_reg = er.async_get(hass)
        source_domain, source_obj = source_entity_id.split(".", 1)
        source_entry_for_source_eid = _mock_config_entry(
            domain="fake_source_integration",
            title="fake_source_integration",
        )
        source_entry_for_source_eid.add_to_hass(hass)
        # If the test requests a specific device_id, plant a
        # device under the same config entry so the
        # source's registry entry can reference it. The
        # notification body's link uses
        # ``/config/devices/device/<device_id>``.
        device_id_to_attach: str | None = None
        if source_device_id is not None:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_or_create(
                config_entry_id=source_entry_for_source_eid.entry_id,
                identifiers={
                    ("fake_source_integration", source_device_id),
                },
            )
            device_id_to_attach = device.id
        ent_reg.async_get_or_create(
            domain=source_domain,
            platform="fake_source_integration",
            unique_id=f"src-{source_obj}",
            suggested_object_id=source_obj,
            config_entry=source_entry_for_source_eid,
            device_id=device_id_to_attach,
            original_name=source_friendly_name,
            hidden_by=source_hidden_by,
            disabled_by=source_disabled_by,
        )

        # The switch_as_x config entry that wraps the source.
        if bad_options:
            options: dict[str, Any] = {}
        else:
            options = {
                "entity_id": source_entity_id,
                "target_domain": wrapper_target_domain,
            }
        sax_entry = _mock_config_entry(
            domain="switch_as_x",
            title=f"{source_friendly_name} (as {wrapper_target_domain})",
            options=options,
        )
        sax_entry.add_to_hass(hass)

        # Wrapper entity registered under the switch_as_x
        # entry. The handler matches by config_entry_id.
        ent_reg.async_get_or_create(
            domain=wrapper_target_domain,
            platform="switch_as_x",
            unique_id=f"wrap-{wrapper_entity_id}",
            suggested_object_id=wrapper_entity_id,
            config_entry=sax_entry,
            original_name=source_friendly_name,
        )
        return sax_entry

    async def test_visible_source_emits_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A switch_as_x entry whose source has
        ``hidden_by=None`` triggers the aggregate
        notification with a per-finding bullet.
        """
        from homeassistant.helpers import (
            device_registry as dr,
        )
        from homeassistant.helpers import (
            entity_registry as er,
        )

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.kitchen",
            wrapper_entity_id="kitchen",
            wrapper_target_domain="fan",
            source_friendly_name="Kitchen Fan",
            source_hidden_by=None,
            source_device_id="dev-kitchen",
        )
        # Capture the HA-generated device.id; the
        # notification body links to
        # ``/config/devices/device/<id>``.
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        source_entry = ent_reg.async_get("switch.kitchen")
        assert source_entry is not None
        assert source_entry.device_id is not None
        kitchen_device = dev_reg.async_get(source_entry.device_id)
        assert kitchen_device is not None
        device_id = kitchen_device.id
        config_entry_id = source_entry.config_entry_id
        assert config_entry_id is not None

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_visible_aliased",
                drift_checks=["visible-aliased-entity"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_visible_aliased__visible_aliased"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id in notifs, (
            f"expected visible-aliased notif; got {sorted(notifs.keys())}"
        )
        body: str = notifs[notif_id]["message"]
        assert "`switch.kitchen`" in body
        assert "`fan.kitchen`" in body
        assert f"device={device_id}" in body
        assert f"config_entry={config_entry_id}" in body

    async def test_create_repairs_true_publishes_repair_and_fix_rehides(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With ``create_repairs=true`` a visible source surfaces
        as one re-hide repair (not the aggregate notification);
        calling the fix service sets ``hidden_by=integration``.
        """
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.den",
            wrapper_entity_id="den",
            wrapper_target_domain="fan",
            source_friendly_name="Den Fan",
            source_hidden_by=None,
            source_device_id="dev-den",
        )
        # The source is device-attached, so the handler resolves
        # the device's id off the registry; capture HA's generated
        # device.id for the attribution assertion below.
        ent_reg = er.async_get(hass)
        den_source = ent_reg.async_get("switch.den")
        assert den_source is not None
        assert den_source.device_id is not None
        den_device_id = den_source.device_id

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_va_repair",
                drift_checks=["visible-aliased-entity"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        reg = ir.async_get(hass)
        repair_issues = [
            i
            for i in reg.issues.values()
            if i.domain == DOMAIN
            and "__repair_fix_edw_visible_aliased_entity__" in i.issue_id
        ]
        assert len(repair_issues) == 1, sorted(reg.issues)
        nid = repair_issues[0].issue_id
        # The handler threaded the device-attached source's
        # integration + device through to the repair's DeviceRef,
        # so the confirm modal's attribution header carries the
        # Device + Integrations lines.
        attribution = (repair_issues[0].translation_placeholders or {}).get(
            "attribution",
            "",
        )
        assert f"/config/devices/device/{den_device_id}" in attribution
        assert "fake_source_integration" in attribution

        # Repairs on -> the aggregate bucket notification is not
        # emitted; the finding lives only on the Repairs surface.
        agg_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_va_repair__visible_aliased"
        )
        assert agg_id not in _async_get_or_create_notifications(hass)

        ent_reg = er.async_get(hass)
        before = ent_reg.async_get("switch.den")
        assert before is not None
        assert before.hidden_by is None

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_visible_aliased_entity",
            {"notification_id": nid},
            blocking=True,
        )
        await hass.async_block_till_done()

        after = ent_reg.async_get("switch.den")
        assert after is not None
        assert after.hidden_by is er.RegistryEntryHider.INTEGRATION

    async def test_excluding_source_integration_clears_repair(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Excluding the source entity's integration clears the
        repair on the next scan.
        """
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.den",
            wrapper_entity_id="den",
            wrapper_target_domain="fan",
            source_friendly_name="Den Fan",
            source_hidden_by=None,
        )

        for exclude_integrations, expected in (
            (None, 1),
            (["fake_source_integration"], 0),
        ):
            await hass.services.async_call(
                DOMAIN,
                SERVICE,
                _valid_payload(
                    instance_id="automation.edw_va_excluded",
                    drift_checks=["visible-aliased-entity"],
                    create_repairs=True,
                    exclude_integrations=exclude_integrations,
                ),
                blocking=True,
            )
            await hass.async_block_till_done()

            repair_issues = [
                i
                for i in ir.async_get(hass).issues.values()
                if i.domain == DOMAIN
                and "__repair_fix_edw_visible_aliased_entity__" in i.issue_id
            ]
            assert len(repair_issues) == expected

    async def test_repair_header_names_the_source_device_area(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.den",
            wrapper_entity_id="den",
            wrapper_target_domain="fan",
            source_friendly_name="Den Fan",
            source_hidden_by=None,
            source_device_id="dev-den",
        )
        source = er.async_get(hass).async_get("switch.den")
        assert source is not None
        assert source.device_id is not None
        area = ar.async_get(hass).async_get_or_create("Den")
        dr.async_get(hass).async_update_device(
            source.device_id,
            area_id=area.id,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                drift_checks=["visible-aliased-entity"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        [issue] = [
            i
            for i in ir.async_get(hass).issues.values()
            if i.domain == DOMAIN
            and "__repair_fix_edw_visible_aliased_entity__" in i.issue_id
        ]
        attribution = (issue.translation_placeholders or {})["attribution"]
        assert attribution.endswith(" (Den)")

    async def test_excluding_another_integration_on_the_device_clears_repair(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.den",
            wrapper_entity_id="den",
            wrapper_target_domain="fan",
            source_friendly_name="Den Fan",
            source_hidden_by=None,
            source_device_id="dev-den",
        )
        ent_reg = er.async_get(hass)
        source = ent_reg.async_get("switch.den")
        assert source is not None
        ent_reg.async_get_or_create(
            domain="sensor",
            platform="other_integration",
            unique_id="shared-device",
            device_id=source.device_id,
        )

        for exclude_integrations, expected in (
            (None, 1),
            (["other_integration"], 0),
        ):
            await hass.services.async_call(
                DOMAIN,
                SERVICE,
                _valid_payload(
                    instance_id="automation.edw_va_shared",
                    drift_checks=["visible-aliased-entity"],
                    create_repairs=True,
                    exclude_integrations=exclude_integrations,
                ),
                blocking=True,
            )
            await hass.async_block_till_done()

            repair_issues = [
                i
                for i in ir.async_get(hass).issues.values()
                if i.domain == DOMAIN
                and "__repair_fix_edw_visible_aliased_entity__" in i.issue_id
            ]
            assert len(repair_issues) == expected

    async def test_create_repairs_false_emits_aggregate_no_issues(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With ``create_repairs=false`` the visible source stays
        on the aggregate notification surface; no repair issues.
        """
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.loft",
            wrapper_entity_id="loft",
            wrapper_target_domain="fan",
            source_friendly_name="Loft Fan",
            source_hidden_by=None,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_va_notif",
                drift_checks=["visible-aliased-entity"],
                create_repairs=False,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        agg_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_va_notif__visible_aliased"
        )
        assert agg_id in _async_get_or_create_notifications(hass)

        reg = ir.async_get(hass)
        assert not [
            i
            for i in reg.issues.values()
            if i.domain == DOMAIN
            and "__repair_fix_edw_visible_aliased_entity__" in i.issue_id
        ]

    async def test_fix_unknown_notification_id_is_noop(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The re-hide fix no-ops (no raise) when the
        notification_id maps to no stored payload -- e.g. a
        click after a restart cleared instance state, or after
        the next scan cleared the finding.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            "fix_edw_visible_aliased_entity",
            {
                "notification_id": (
                    "blueprint_toolkit_entity_defaults_watchdog"
                    "__automation.x__repair_fix_edw_visible_aliased_entity"
                    "__switch.gone"
                ),
            },
            blocking=True,
        )
        await hass.async_block_till_done()

    async def test_hidden_source_no_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A healthy switch_as_x setup
        (``hidden_by="integration"`` on source) yields no
        finding.
        """
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.bedroom",
            wrapper_entity_id="bedroom",
            wrapper_target_domain="light",
            source_friendly_name="Bedroom Light",
            source_hidden_by=er.RegistryEntryHider.INTEGRATION,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_visible_clean",
                drift_checks=["visible-aliased-entity"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_visible_clean__visible_aliased"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id not in notifs, (
            f"expected no visible-aliased notif; got {sorted(notifs.keys())}"
        )

    async def test_diagnostic_state_carries_counters(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The state entity gets the three new attrs
        whether or not the check is enabled.
        """
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        # One visible (flagged), one hidden (defensive).
        await self._plant_pair(
            hass,
            source_entity_id="switch.flagged",
            wrapper_entity_id="flagged",
            wrapper_target_domain="fan",
            source_friendly_name="Flagged",
            source_hidden_by=None,
        )
        await self._plant_pair(
            hass,
            source_entity_id="switch.healthy",
            wrapper_entity_id="healthy",
            wrapper_target_domain="fan",
            source_friendly_name="Healthy",
            source_hidden_by=er.RegistryEntryHider.INTEGRATION,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_visible_state",
                drift_checks=["visible-aliased-entity"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_visible_state_state",
        )
        assert state is not None
        attrs = state.attributes
        for key in (
            "visible_aliased_total",
            "visible_aliased_excluded",
            "visible_aliased_flagged",
        ):
            assert key in attrs, f"missing {key} in {attrs!r}"
        # Two switch_as_x entries walked total. One flagged,
        # one defensively skipped (already hidden).
        assert attrs["visible_aliased_total"] == 2
        assert attrs["visible_aliased_excluded"] == 1
        assert attrs["visible_aliased_flagged"] == 1

    async def test_disabled_entry_skipped(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A disabled switch_as_x entry never reaches the
        logic layer and counts as defensive-skipped.
        """
        from homeassistant.config_entries import ConfigEntryDisabler

        await _setup_integration(hass)
        sax_entry = await self._plant_pair(
            hass,
            source_entity_id="switch.disabled_entry",
            wrapper_entity_id="disabled_entry",
            wrapper_target_domain="fan",
            source_friendly_name="Disabled Entry",
            source_hidden_by=None,
        )
        await hass.config_entries.async_set_disabled_by(
            sax_entry.entry_id,
            ConfigEntryDisabler.USER,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_visible_disabled",
                drift_checks=["visible-aliased-entity"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_visible_disabled__visible_aliased"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id not in notifs

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_visible_disabled_state",
        )
        assert state is not None
        assert state.attributes["visible_aliased_flagged"] == 0
        assert state.attributes["visible_aliased_excluded"] == 1

    async def test_check_disabled_no_findings(
        self,
        hass: HomeAssistant,
    ) -> None:
        """When ``visible-aliased-entity`` is not in
        ``drift_checks``, the logic short-circuits and no
        notification is emitted even if a candidate exists.
        """
        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.would_be_flagged",
            wrapper_entity_id="would_be_flagged",
            wrapper_target_domain="fan",
            source_friendly_name="Would Be Flagged",
            source_hidden_by=None,
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_visible_off",
                drift_checks=["entity-id"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_visible_off__visible_aliased"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id not in notifs

    async def test_flagged_run_leaves_hidden_by_unchanged(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The check is detection-only: flagging a source
        must not mutate ``hidden_by`` on its registry entry.

        Locks down the load-bearing "no auto-fix" guarantee.
        A future regression that silently re-hides flagged
        sources would be a surprising registry mutation
        during a watchdog scan, and would also defeat the
        user's deliberate "I want both rows visible" choice.
        """
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        await self._plant_pair(
            hass,
            source_entity_id="switch.detection_only",
            wrapper_entity_id="detection_only",
            wrapper_target_domain="fan",
            source_friendly_name="Detection Only",
            source_hidden_by=None,
        )

        ent_reg = er.async_get(hass)
        before = ent_reg.async_get("switch.detection_only")
        assert before is not None
        assert before.hidden_by is None

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_detection_only",
                drift_checks=["visible-aliased-entity"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_entity_defaults_watchdog"
            "__automation.edw_detection_only__visible_aliased"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id in notifs, (
            "expected the visible-aliased notif to fire so the "
            "hidden_by-unchanged assertion is meaningful"
        )

        after = ent_reg.async_get("switch.detection_only")
        assert after is not None
        assert after.hidden_by is None, (
            f"hidden_by must remain None after a flagged run; "
            f"got {after.hidden_by!r}"
        )


class TestScriptYamlKeyScan:
    """End-to-end coverage of the script-yaml-key drift check.

    Plants a ``platform == "script"`` registry entry whose
    ``unique_id`` (the scripts.yaml block key) differs from
    its entity-id slug, then drives a service call with the
    new ``script-yaml-key`` drift-check value. The check is
    repair-only: it surfaces on the Repairs surface when
    ``create_repairs`` is on and on no surface at all when
    off.
    """

    def _plant_script(
        self,
        hass: HomeAssistant,
        *,
        unique_id: str,
        suggested_object_id: str,
        friendly_name: str = "Bath Fan",
    ) -> str:
        """Register a script entity; return its entity_id."""
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="script",
            platform="script",
            unique_id=unique_id,
            suggested_object_id=suggested_object_id,
            original_name=friendly_name,
        )
        return entry.entity_id

    async def test_create_repairs_true_publishes_repair(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With ``create_repairs=true`` a drifted script
        surfaces as one block-key-rename repair issue.
        """
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        eid = self._plant_script(
            hass,
            unique_id="bath_fan",
            suggested_object_id="bathroom",
        )
        assert eid == "script.bathroom"

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_script_repair",
                drift_checks=["script-yaml-key"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        reg = ir.async_get(hass)
        repair_issues = [
            i
            for i in reg.issues.values()
            if i.domain == DOMAIN
            and "__repair_fix_edw_script_yaml_key__" in i.issue_id
        ]
        assert len(repair_issues) == 1, sorted(reg.issues)
        # The confirm modal leads with the shared attribution
        # header; the dispatcher injects the placeholder for
        # every repair (see AUTOMATIONS.md "Repairs"), and the
        # confirm string must reference it. Scripts are
        # deviceless, so the only attribution context is the
        # built-in ``script`` integration, linked to the
        # script-list dashboard.
        attribution = (repair_issues[0].translation_placeholders or {}).get(
            "attribution",
            "",
        )
        assert "[script](/config/script/dashboard)" in attribution
        assert "/config/devices/device/" not in attribution

    async def test_excluding_script_integration_clears_repair(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Excluding the ``script`` integration clears the repair
        on the next scan, as it does for any other integration.
        """
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        self._plant_script(
            hass,
            unique_id="bath_fan",
            suggested_object_id="bathroom",
        )

        for exclude_integrations, expected in ((None, 1), (["script"], 0)):
            await hass.services.async_call(
                DOMAIN,
                SERVICE,
                _valid_payload(
                    instance_id="automation.edw_script_excluded",
                    drift_checks=["script-yaml-key"],
                    create_repairs=True,
                    exclude_integrations=exclude_integrations,
                ),
                blocking=True,
            )
            await hass.async_block_till_done()

            repair_issues = [
                i
                for i in ir.async_get(hass).issues.values()
                if i.domain == DOMAIN
                and "__repair_fix_edw_script_yaml_key__" in i.issue_id
            ]
            assert len(repair_issues) == expected

    async def test_create_repairs_false_no_issue_no_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With ``create_repairs=false`` a drifted script
        surfaces on no surface at all -- no repair issue and
        no persistent notification (repair-only by design).
        """
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )
        from homeassistant.helpers import issue_registry as ir

        await _setup_integration(hass)
        self._plant_script(
            hass,
            unique_id="bath_fan",
            suggested_object_id="bathroom",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_script_notif",
                drift_checks=["script-yaml-key"],
                create_repairs=False,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        reg = ir.async_get(hass)
        assert not [
            i
            for i in reg.issues.values()
            if i.domain == DOMAIN
            and "__repair_fix_edw_script_yaml_key__" in i.issue_id
        ]
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        script_notifs = [
            k
            for k in notifs
            if "edw_script_notif" in k and "config_error" not in k
        ]
        assert script_notifs == [], sorted(notifs)

    async def test_diagnostic_state_carries_counter(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The state entity gets ``script_yaml_key_flagged``."""
        await _setup_integration(hass)
        self._plant_script(
            hass,
            unique_id="bath_fan",
            suggested_object_id="bathroom",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.edw_script_state",
                drift_checks=["script-yaml-key"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.edw_edw_script_state_state",
        )
        assert state is not None
        assert state.attributes["script_yaml_key_flagged"] == 1

    async def test_fix_rewrites_scripts_yaml_block_key(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The fix service rewrites the scripts.yaml block key
        and writes a timestamped backup.

        Plants the per-repair payload directly + a real
        scripts.yaml under the HA config dir, then calls the
        fix service. Asserts the on-disk key was renamed and a
        backup file was left behind. The registry-rebuild /
        slug-reconcile dance after ``script.reload`` depends on
        the script component fully wiring up in the harness, so
        this test pins the deterministic file-edit behaviour
        and leaves the registry-side reconcile to live
        dev-deploy verification.
        """
        from homeassistant.setup import async_setup_component

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            handler as edw,
        )
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        await _setup_integration(hass)
        scripts_path = Path(hass.config.path("scripts.yaml"))
        scripts_path.write_text(
            "bath_fan:\n"
            "  alias: Bath Fan\n"
            "  sequence:\n"
            "    - delay: 1\n"
            "other_script:\n"
            "  alias: Other\n",
        )
        # The fix service calls ``script.reload`` after the
        # file edit; set up the script component so the
        # service exists, and provide the configuration.yaml
        # the reload reads (the harness ships none).
        config_yaml = Path(hass.config.path("configuration.yaml"))
        if not config_yaml.exists():
            config_yaml.write_text("script: !include scripts.yaml\n")
        assert await async_setup_component(hass, "script", {"script": {}})
        await hass.async_block_till_done()

        # The harness config dir persists across runs, so
        # snapshot pre-existing backups and diff against them.
        backup_glob = "scripts.yaml.edw-repair-*.bak"
        before = set(scripts_path.parent.glob(backup_glob))

        nid = (
            "blueprint_toolkit_edw__automation.x__"
            "repair_fix_edw_script_yaml_key__bathroom"
        )
        insts = edw._instances(hass)
        insts["automation.x"] = edw.EdwInstanceState(
            instance_id="automation.x",
        )
        insts["automation.x"].repairs[nid] = edw_logic.ScriptYamlKeyDriftRepair(
            old_key="bath_fan",
            new_slug="bathroom",
            entity_id="script.bathroom",
        )

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_script_yaml_key",
            {"notification_id": nid},
            blocking=True,
        )
        await hass.async_block_till_done()

        new_text = scripts_path.read_text()
        assert new_text.startswith("bathroom:\n")
        assert "bath_fan:" not in new_text
        assert "other_script:\n" in new_text
        new_backups = set(scripts_path.parent.glob(backup_glob)) - before
        assert len(new_backups) == 1
        assert next(iter(new_backups)).read_text().startswith("bath_fan:\n")

    async def test_fix_missing_key_raises_and_leaves_file_untouched(
        self,
        hass: HomeAssistant,
    ) -> None:
        """If the captured block key is absent from
        scripts.yaml (script defined via packages, or the
        file edited out-of-band), the fix raises so the
        shared crash-PN wrap surfaces feedback, and leaves
        the file unchanged.
        """
        from homeassistant.exceptions import HomeAssistantError

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            handler as edw,
        )
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        await _setup_integration(hass)
        scripts_path = Path(hass.config.path("scripts.yaml"))
        original = "other_script:\n  alias: Other\n"
        scripts_path.write_text(original)
        # The harness config dir persists across runs, so
        # snapshot pre-existing backups and diff against them.
        backup_glob = "scripts.yaml.edw-repair-*.bak"
        before = set(scripts_path.parent.glob(backup_glob))

        nid = (
            "blueprint_toolkit_edw__automation.x__"
            "repair_fix_edw_script_yaml_key__bathroom"
        )
        insts = edw._instances(hass)
        insts["automation.x"] = edw.EdwInstanceState(
            instance_id="automation.x",
        )
        insts["automation.x"].repairs[nid] = edw_logic.ScriptYamlKeyDriftRepair(
            old_key="bath_fan",
            new_slug="bathroom",
            entity_id="script.bathroom",
        )

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN,
                "fix_edw_script_yaml_key",
                {"notification_id": nid},
                blocking=True,
            )
        await hass.async_block_till_done()

        assert scripts_path.read_text() == original
        assert set(scripts_path.parent.glob(backup_glob)) == before

    async def test_fix_unknown_notification_id_is_noop(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The fix no-ops (no raise) when the notification_id
        maps to no stored payload.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            "fix_edw_script_yaml_key",
            {
                "notification_id": (
                    "blueprint_toolkit_entity_defaults_watchdog"
                    "__automation.x__repair_fix_edw_script_yaml_key"
                    "__gone"
                ),
            },
            blocking=True,
        )
        await hass.async_block_till_done()


class TestFixServiceDeviceDrift:
    """End-to-end EDW id-drift / name-drift repair fixes.

    Populates an instance's per-repair payload directly --
    the scan-side build is covered by the logic tests -- then
    calls each fix service and asserts the registry mutation
    lands on exactly the captured entities (rename for
    id-drift; set / clear name override for name-drift).
    """

    async def test_id_drift_submit_renames_entity(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            handler as edw,
        )
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        await _setup_integration(hass)
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id="drift-1",
            original_name="Temp",
        )
        old_id = entry.entity_id
        new_id = "sensor.renamed_target"

        nid = (
            "blueprint_toolkit_edw__automation.x__"
            "repair_fix_edw_entity_id_drift__dev1"
        )
        insts = edw._instances(hass)
        insts["automation.x"] = edw.EdwInstanceState(
            instance_id="automation.x",
        )
        insts["automation.x"].repairs[nid] = edw_logic.EntityIdDriftRepair(
            entity_renames=((old_id, new_id),),
        )

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_entity_id_drift",
            {"notification_id": nid},
            blocking=True,
        )
        await hass.async_block_till_done()

        assert ent_reg.async_get(new_id) is not None
        assert ent_reg.async_get(old_id) is None

    async def test_name_drift_submit_sets_override(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            handler as edw,
        )
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        await _setup_integration(hass)
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id="name-1",
            original_name="Temp",
        )

        nid = (
            "blueprint_toolkit_edw__automation.x__"
            "repair_device_entity_name_drift__dev1"
        )
        insts = edw._instances(hass)
        insts["automation.x"] = edw.EdwInstanceState(
            instance_id="automation.x",
        )
        insts["automation.x"].repairs[nid] = (
            edw_logic.DeviceEntityNameDriftRepair(
                device_id="dev1",
                entity_name_targets=((entry.entity_id, "Custom Name"),),
            )
        )

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_device_entity_name_drift",
            {"notification_id": nid},
            blocking=True,
        )
        await hass.async_block_till_done()

        updated = ent_reg.async_get(entry.entity_id)
        assert updated is not None
        assert updated.name == "Custom Name"

    async def test_name_drift_submit_clears_stale_override(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            handler as edw,
        )
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        await _setup_integration(hass)
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id="name-2",
            original_name="Temp",
        )
        ent_reg.async_update_entity(entry.entity_id, name="Stale Override")

        nid = (
            "blueprint_toolkit_edw__automation.x__"
            "repair_device_entity_name_drift__dev2"
        )
        insts = edw._instances(hass)
        insts["automation.x"] = edw.EdwInstanceState(
            instance_id="automation.x",
        )
        # None target CLEARS the override, reverting to the
        # integration-provided default name.
        insts["automation.x"].repairs[nid] = (
            edw_logic.DeviceEntityNameDriftRepair(
                device_id="dev2",
                entity_name_targets=((entry.entity_id, None),),
            )
        )

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_device_entity_name_drift",
            {"notification_id": nid},
            blocking=True,
        )
        await hass.async_block_till_done()

        updated = ent_reg.async_get(entry.entity_id)
        assert updated is not None
        assert updated.name is None

    async def test_unknown_notification_id_is_noop(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            "fix_edw_entity_id_drift",
            {"notification_id": "blueprint_toolkit_edw__x__repair_x__none"},
            blocking=True,
        )
        await hass.async_block_till_done()


class TestLegacyNamesFollowHomeAssistant:
    """Legacy entity names on a renamed device, against real HA.

    The name HA stores at a device rename comes from private
    registry code, so ``_compute_recommended_override`` is a
    copy of that rule. These tests run the real rename: a Home
    Assistant release that changes the rule turns them red,
    which blocks the HACC bump bringing it in.
    """

    def _plant(
        self,
        hass: HomeAssistant,
        *,
        device_name: str,
        original_name: str,
        entity_id: str,
        tag: str = "legacy",
    ) -> str:
        """Plant a legacy entity and return its device id.

        The entity starts on ``entity_id``, the ID it keeps
        when its device loses the area from its name.
        """
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr

        fake_entry = _mock_config_entry(
            domain="fake_integration",
            title="fake_integration",
        )
        fake_entry.add_to_hass(hass)
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=fake_entry.entry_id,
            identifiers={("fake_integration", tag)},
            name=device_name,
        )
        area = ar.async_get(hass).async_get_or_create("Main Bath")
        dev_reg.async_update_device(device.id, area_id=area.id)
        self._plant_sibling(
            hass,
            device_id=device.id,
            original_name=original_name,
            entity_id=entity_id,
            platform="fake_integration",
            tag=tag,
        )
        return device.id

    def _plant_sibling(
        self,
        hass: HomeAssistant,
        *,
        device_id: str,
        original_name: str,
        entity_id: str,
        platform: str,
        tag: str,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        domain = entity_id.split(".", 1)[0]
        entry = ent_reg.async_get_or_create(
            domain=domain,
            platform=platform,
            unique_id=tag,
            device_id=device_id,
            has_entity_name=False,
            original_name=original_name,
            object_id_base=original_name,
        )
        ent_reg.async_update_entity(entry.entity_id, new_entity_id=entity_id)

    async def _rename_device(
        self,
        hass: HomeAssistant,
        device_id: str,
        name: str,
    ) -> None:
        from homeassistant.helpers import device_registry as dr

        dr.async_get(hass).async_update_device(device_id, name_by_user=name)
        await hass.async_block_till_done()

    async def _scan(self, hass: HomeAssistant) -> None:
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                drift_checks=["device-entity-id", "device-entity-name"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

    def _repairs(self, hass: HomeAssistant, fix_service: str) -> list[Any]:
        from homeassistant.helpers import issue_registry as ir

        return [
            issue
            for issue in ir.async_get(hass).issues.values()
            if issue.domain == DOMAIN
            and f"__repair_{fix_service}__" in issue.issue_id
        ]

    @pytest.mark.parametrize(
        ("original_name", "device_name", "renamed_to"),
        [
            ("Main Bath Fan", "Main Bath Fan", "Fan"),
            ("Kitchen Remote Off", "Kitchen Remote", "Remote"),
            ("Kitchen Remote off", "Kitchen Remote", "Remote"),
            ("Kitchen Remote iPhone Dock", "Kitchen Remote", "Remote"),
            ("kitchen remote Off", "Kitchen Remote", "Remote"),
            ("Kitchen Remote - Off", "Kitchen Remote", "Remote"),
            ("Kitchen Remote: Off", "Kitchen Remote", "Remote"),
            ("Kitchen Remote  Off", "Kitchen Remote", "Remote"),
            ("Kitchen Remotely Off", "Kitchen Remote", "Remote"),
            ("Hall Remote Off", "Kitchen Remote", "Remote"),
            ("Straße Off", "STRASSE", "Road"),
            ("STRASSE Off", "Straße", "Road"),
            ("Straße Off", "STRAS", "Road"),
        ],
    )
    async def test_recommendation_matches_what_ha_stores(
        self,
        hass: HomeAssistant,
        original_name: str,
        device_name: str,
        renamed_to: str,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501
            logic as edw_logic,
        )

        device_id = self._plant(
            hass,
            device_name=device_name,
            original_name=original_name,
            entity_id="switch.planted",
        )

        await self._rename_device(hass, device_id, renamed_to)

        stored = er.async_get(hass).async_get("switch.planted")
        assert stored is not None
        assert (
            edw_logic._compute_recommended_override(
                original_name,
                device_name,
                renamed_to,
                has_entity_name=False,
            )
            == stored.name
        )

    async def test_suffixed_name_ha_stored_is_not_drift(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Remote",
            original_name="Main Bath Remote Off",
            entity_id="button.main_bath_remote_off",
        )
        await self._rename_device(hass, device_id, "Remote")

        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

    async def test_stored_copy_of_device_name_is_not_drift(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        stored = er.async_get(hass).async_get("switch.main_bath_fan")
        assert stored is not None
        assert stored.name == "Fan"

        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

    async def test_copy_left_by_an_earlier_rename_is_unset(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        await self._rename_device(hass, device_id, "Exhaust")

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert '"Fan" -> `<unset>`' in entities

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_device_entity_name_drift",
            {"notification_id": repairs[0].issue_id},
            blocking=True,
        )
        await hass.async_block_till_done()
        await self._scan(hass)

        ent_reg = er.async_get(hass)
        fixed = ent_reg.async_get("switch.main_bath_fan")
        assert fixed is not None
        assert fixed.name == ""
        assert er.async_get_full_entity_name(hass, fixed) == "Exhaust"
        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []

        # The reason to prefer blank: the name now follows the device.
        await self._rename_device(hass, device_id, "Vent")
        renamed = ent_reg.async_get("switch.main_bath_fan")
        assert renamed is not None
        assert er.async_get_full_entity_name(hass, renamed) == "Vent"

    async def test_stored_copy_on_entity_with_its_own_area_is_unset(
        self,
        hass: HomeAssistant,
    ) -> None:
        # An entity's own area turns HA's switch off for a stored
        # copy, which leaves the name editable.
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        closet = ar.async_get(hass).async_get_or_create("Closet")
        er.async_get(hass).async_update_entity(
            "switch.main_bath_fan",
            area_id=closet.id,
        )

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert '"Fan" -> `<unset>`' in entities

    async def test_use_device_name_is_left_alone_on_suffixed_entity(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Remote",
            original_name="Main Bath Remote Off",
            entity_id="button.main_bath_remote_off",
        )
        await self._rename_device(hass, device_id, "Remote")
        er.async_get(hass).async_update_entity(
            "button.main_bath_remote_off",
            name="",
        )

        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        # Its ID has nothing left to wait on.
        repairs = self._repairs(hass, "fix_edw_entity_id_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert (
            "`button.main_bath_remote_off` -> `button.main_bath_remote`"
            in entities
        )

    @pytest.mark.parametrize("stored_name", ["", "Main Bath Sensor"])
    async def test_use_device_name_is_left_alone_on_modern_entity(
        self,
        hass: HomeAssistant,
        stored_name: str,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Sensor",
            original_name="Main Bath Sensor",
            entity_id="sensor.main_bath_sensor",
        )
        ent_reg = er.async_get(hass)
        modern = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id="modern",
            device_id=device_id,
            has_entity_name=True,
            original_name="Temperature",
            object_id_base="Temperature",
        )
        ent_reg.async_update_entity(modern.entity_id, name=stored_name)

        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []

    async def test_blank_name_is_not_drift(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        er.async_get(hass).async_update_entity(
            "switch.main_bath_fan",
            name="",
        )

        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

    async def test_second_integration_on_the_device_changes_nothing(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        self._plant_sibling(
            hass,
            device_id=device_id,
            original_name="Main Bath Fan",
            entity_id="fan.main_bath_fan",
            platform="switch_as_x",
            tag="wrapper",
        )
        await self._rename_device(hass, device_id, "Fan")
        ent_reg = er.async_get(hass)
        ent_reg.async_update_entity("switch.main_bath_fan", name=None)
        ent_reg.async_update_entity("fan.main_bath_fan", name=None)

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert (
            '`switch.main_bath_fan`: "Fan Main Bath Fan" -> `<unset>`'
            in entities
        )
        assert (
            '`fan.main_bath_fan`: "Fan Main Bath Fan" -> `<unset>`' in entities
        )

        ent_reg.async_update_entity("switch.main_bath_fan", name="")
        ent_reg.async_update_entity("fan.main_bath_fan", name="")
        await self._scan(hass)

        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

    async def test_cleared_name_is_repaired_with_the_device_name(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        ent_reg = er.async_get(hass)
        ent_reg.async_update_entity("switch.main_bath_fan", name=None)

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert '"Fan Main Bath Fan" -> `<unset>`' in entities
        # The doubled ID HA derives from the cleared name is not offered.
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

        await hass.services.async_call(
            DOMAIN,
            "fix_edw_device_entity_name_drift",
            {"notification_id": repairs[0].issue_id},
            blocking=True,
        )
        await hass.async_block_till_done()
        await self._scan(hass)

        fixed = ent_reg.async_get("switch.main_bath_fan")
        assert fixed is not None
        assert fixed.name == ""
        assert self._repairs(hass, "fix_edw_device_entity_name_drift") == []
        assert self._repairs(hass, "fix_edw_entity_id_drift") == []

    async def test_stored_copy_keeps_id_drift_visible(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        er.async_get(hass).async_update_entity(
            "switch.main_bath_fan",
            new_entity_id="switch.old_id",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                drift_checks=["device-entity-id"],
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        repairs = self._repairs(hass, "fix_edw_entity_id_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert "`switch.old_id` -> `switch.main_bath_fan`" in entities

    async def test_repair_header_names_the_device_area(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Fan",
            original_name="Main Bath Fan",
            entity_id="switch.main_bath_fan",
        )
        await self._rename_device(hass, device_id, "Fan")
        er.async_get(hass).async_update_entity(
            "switch.main_bath_fan",
            name=None,
        )

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        attribution = (repairs[0].translation_placeholders or {})["attribution"]
        assert (
            f"Device: [Fan](/config/devices/device/{device_id}) (Main Bath)"
            in attribution
        )

    async def test_second_rename_flags_the_stale_name(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        device_id = self._plant(
            hass,
            device_name="Main Bath Remote",
            original_name="Main Bath Remote Off",
            entity_id="button.main_bath_remote_off",
        )
        await self._rename_device(hass, device_id, "Remote")
        await self._rename_device(hass, device_id, "Clicker")

        await self._scan(hass)

        repairs = self._repairs(hass, "fix_edw_device_entity_name_drift")
        assert len(repairs) == 1
        entities = (repairs[0].translation_placeholders or {})["entities"]
        assert '"Remote Off" -> "Clicker Off"' in entities


class TestRedundantPrefixComesFromHomeAssistant:
    @pytest.mark.parametrize(
        ("override", "own_area", "section"),
        [
            ("Kitchen Sensor Temp", False, "redundant device name"),
            ("kitchen sensor Temp", False, "redundant device name"),
            ("Kitchen Sensorium", False, "Name overrides to clear"),
            ("Kitchen Sensor Temp", True, "Name overrides to clear"),
        ],
    )
    async def test_notification_section_follows_ha(
        self,
        hass: HomeAssistant,
        override: str,
        own_area: bool,
        section: str,
    ) -> None:
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        fake_entry = _mock_config_entry(
            domain="fake_integration",
            title="fake_integration",
        )
        fake_entry.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=fake_entry.entry_id,
            identifiers={("fake_integration", "sensor")},
            name="Kitchen Sensor",
        )
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id="temp",
            device_id=device.id,
            has_entity_name=True,
            original_name="Temperature",
        )
        ent_reg.async_update_entity(entry.entity_id, name=override)
        if own_area:
            # HA doesn't build this entity's name from the device.
            area = ar.async_get(hass).async_get_or_create("Kitchen")
            ent_reg.async_update_entity(entry.entity_id, area_id=area.id)

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(drift_checks=["device-entity-name"]),
            blocking=True,
        )
        await hass.async_block_till_done()

        bodies = [
            n["message"]
            for n in _async_get_or_create_notifications(hass).values()
            if entry.entity_id in n["message"]
        ]
        assert len(bodies) == 1
        assert section in bodies[0]


class TestFindingLifecycle(WatchdogFindingLifecycleBase):
    service = SERVICE
    setup_integration = staticmethod(_setup_integration)
    exclusions: ClassVar[dict[str, dict[str, Any]]] = {
        "integration": {"exclude_integrations": ["fake_integration"]},
        "device": {"exclude_device_name_regex": "Lifecycle Device"},
        "entity": {"exclude_entities": ["sensor.lifecycle_drift_0"]},
        "entity id": {"exclude_entity_id_regex": "lifecycle_drift"},
        "entity name": {"exclude_entity_name_regex": "Lifecycle Temp"},
    }

    def payload(self, **overrides: Any) -> dict[str, Any]:
        return _valid_payload(drift_checks=["device-entity-id"], **overrides)

    def seed_finding(self, hass: HomeAssistant, index: int = 0) -> None:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        fake_entry = _mock_config_entry(
            domain="fake_integration",
            title="fake_integration",
        )
        fake_entry.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=fake_entry.entry_id,
            identifiers={("fake_integration", f"lifecycle-{index}")},
            name=f"Lifecycle Device {index}",
        )
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            domain="sensor",
            platform="fake_integration",
            unique_id=f"lifecycle-{index}",
            device_id=device.id,
            config_entry=fake_entry,
            original_name="Lifecycle Temp",
        )
        ent_reg.async_update_entity(
            entry.entity_id,
            new_entity_id=f"sensor.lifecycle_drift_{index}",
        )

    def fix_finding(self, hass: HomeAssistant, index: int = 0) -> None:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        entity_id = f"sensor.lifecycle_drift_{index}"
        entry = ent_reg.async_get(entity_id)
        assert entry is not None
        ent_reg.async_update_entity(
            entity_id,
            new_entity_id=ent_reg.async_regenerate_entity_id(entry),
        )

    def finding_device_id(self, hass: HomeAssistant, index: int = 0) -> str:
        from homeassistant.helpers import entity_registry as er

        entry = er.async_get(hass).async_get(
            f"sensor.lifecycle_drift_{index}",
        )
        assert entry is not None
        assert entry.device_id is not None
        return entry.device_id


class TestExcludedIntegrationCoversTheDevice:
    def _plant(self, hass: HomeAssistant) -> None:
        """Plant a drifted ``switch_as_x`` wrapper on a Lutron device."""
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        lutron_entry = _mock_config_entry(domain="lutron_caseta")
        lutron_entry.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=lutron_entry.entry_id,
            identifiers={("lutron_caseta", "fan")},
            name="Main Bath Fan",
        )
        ent_reg = er.async_get(hass)
        ent_reg.async_get_or_create(
            domain="switch",
            platform="lutron_caseta",
            unique_id="fan",
            device_id=device.id,
            config_entry=lutron_entry,
        )
        wrapper = ent_reg.async_get_or_create(
            domain="fan",
            platform="switch_as_x",
            unique_id="fan",
            device_id=device.id,
            has_entity_name=False,
            original_name="Main Bath Fan",
            object_id_base="Main Bath Fan",
        )
        ent_reg.async_update_entity(
            wrapper.entity_id,
            new_entity_id="fan.old_id",
        )

    async def _id_repairs(
        self,
        hass: HomeAssistant,
        exclude: list[str],
    ) -> list[str]:
        from homeassistant.helpers import issue_registry as ir

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                drift_checks=["device-entity-id"],
                exclude_integrations=exclude,
                create_repairs=True,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()
        return [
            issue.issue_id
            for issue in ir.async_get(hass).issues.values()
            if issue.domain == DOMAIN
            and "__repair_fix_edw_entity_id_drift__" in issue.issue_id
        ]

    async def test_drifted_wrapper_on_an_excluded_device_is_skipped(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        self._plant(hass)

        assert len(await self._id_repairs(hass, [])) == 1
        assert await self._id_repairs(hass, ["lutron_caseta"]) == []

    async def test_disabled_entity_still_ties_the_device_to_its_integration(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await _setup_integration(hass)
        self._plant(hass)
        ent_reg = er.async_get(hass)
        source = ent_reg.async_get_entity_id(
            "switch",
            "lutron_caseta",
            "fan",
        )
        assert source is not None
        ent_reg.async_update_entity(
            source,
            disabled_by=er.RegistryEntryDisabler.USER,
        )

        assert await self._id_repairs(hass, ["lutron_caseta"]) == []


class TestRecoveryEvents(RecoveryEventsIntegrationBase):
    service_tag = "EDW"
    setup_integration = staticmethod(_setup_integration)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
