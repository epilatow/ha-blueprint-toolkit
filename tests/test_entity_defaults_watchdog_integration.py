#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "ruff",
#     "mypy",
#     "pytest-homeassistant-custom-component==0.13.324",
# ]
# ///
# This is AI generated code
"""Integration-level tests for the EDW handler.

Exercises the parts the in-process unit tests
(``tests/test_entity_defaults_watchdog_handler.py``)
deliberately don't cover: the live ``vol.Schema`` argparse,
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
from typing import Any

# Make custom_components/ importable as a top-level package;
# the uv-script env doesn't add the repo root to sys.path
# the way ``python -m pytest`` would.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402
from conftest import (  # noqa: E402
    CodeQualityBase,
    RecoveryEventsIntegrationBase,
)

# pytest-HACC's plugins refuse to load if any
# homeassistant.components.* module is already in
# sys.modules. Defer imports until inside the tests.
DOMAIN = "blueprint_toolkit"
SERVICE = "entity_defaults_watchdog"


@pytest.fixture(autouse=True)
def install_our_integration(hass, enable_custom_integrations):  # noqa: ANN001
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


def _mock_config_entry(**kwargs):  # noqa: ANN001, ANN201
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
        "validate_includes_excludes_raw": validate_includes_excludes,
        "debug_logging_raw": False,
    }


# --------------------------------------------------------
# Argparse / config-error notification path
# --------------------------------------------------------


class TestArgparseEmitsConfigErrorNotification:
    async def test_missing_required_keys_create_notification(
        self,
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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

        # template.integration_entities() matches by config-
        # entry title. Mock a config entry titled
        # "fake_integration" so the watchdog scan can find
        # our planted entities.
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

    async def test_typoed_integration_fires_notification(
        self,
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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
        hass,  # noqa: ANN001
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


class TestRecoveryEvents(RecoveryEventsIntegrationBase):
    service_tag = "EDW"
    setup_integration = staticmethod(_setup_integration)


class TestCodeQuality(CodeQualityBase):
    ruff_targets = [
        "tests/test_entity_defaults_watchdog_integration.py",
    ]
    mypy_targets: list[str] = []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
