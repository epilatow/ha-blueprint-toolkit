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
"""Integration-level tests for the RW handler.

Exercises the parts the in-process unit tests
(``tests/test_reference_watchdog_handler.py``) deliberately
don't cover: the live ``vol.Schema`` argparse, the
helper-driven multi-line regex validation, the full
``_async_service_layer`` build-and-apply loop against
``hass.states`` / ``hass.services`` (truth-set assembly +
executor offload of ``run_evaluation`` + sweep dispatch +
``update_instance_state``), and the
automation-link-prefix-on-notification-body invariant the
RW code review flagged as a P1 regression. Same
pytest-HACC harness as ``test_integration.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make custom_components/ importable as a top-level
# package; the uv-script env doesn't add the repo root to
# sys.path the way ``python -m pytest`` would.
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
SERVICE = "reference_watchdog"


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
    instance_id: str = "automation.rw_test",
    exclude_entity_id_regex: str = "",
    check_interval_minutes: int = 60,
    max_source_notifications: int = 0,
    validate_includes_excludes: bool = True,
    exclude_integrations: list[str] | None = None,
    exclude_entities: list[str] | None = None,
    exclude_paths: str = "",
) -> dict[str, Any]:
    """Build a fully-populated RW service-call payload."""
    return {
        "instance_id": instance_id,
        "trigger_id": "manual",
        "exclude_paths_raw": exclude_paths,
        "exclude_integrations_raw": list(exclude_integrations or []),
        "exclude_entities_raw": list(exclude_entities or []),
        "exclude_entity_id_regex_raw": exclude_entity_id_regex,
        "check_disabled_entities_raw": False,
        "check_interval_minutes_raw": check_interval_minutes,
        "max_source_notifications_raw": max_source_notifications,
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
            {"instance_id": "automation.rw_bad_call"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_bad_call__config_error"
        )
        assert notif_id in notifs, "config-error notification was not emitted"
        assert "schema:" in notifs[notif_id]["message"]

    async def test_invalid_regex_creates_notification(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """A bad ``exclude_entity_id_regex`` line surfaces as a
        per-line config error -- this is the live-host
        version of the regression the user reported.
        """
        await _setup_integration(hass)

        payload = _valid_payload(
            instance_id="automation.rw_bad_regex",
            exclude_entity_id_regex="[unclosed",
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            payload,
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_bad_regex__config_error"
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
            instance_id="automation.rw_match_all",
            exclude_entity_id_regex=".*",
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            payload,
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_match_all__config_error"
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
            "automation.rw_link",
            "on",
            {"friendly_name": "RW: Linked", "id": "1234"},
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.rw_link"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_link__config_error"
        )
        assert notif_id in notifs
        body: str = notifs[notif_id]["message"]
        assert body.startswith(
            "Automation: [RW: Linked](/config/automation/edit/1234)\n",
        )

    async def test_notification_md_escapes_friendly_name(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """``[`` / ``]`` in the friendly name would otherwise
        pair with the ``](`` of the link and corrupt the
        rendered link. Verify the escape lands end-to-end.
        """
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.rw_escape",
            "on",
            {"friendly_name": "Office [Lights]", "id": "42"},
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.rw_escape"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_escape__config_error"
        )
        body: str = notifs[notif_id]["message"]
        assert "[Office \\[Lights\\]]" in body

    async def test_successful_call_dismisses_prior_notification(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        await _setup_integration(hass)
        # Bad call first.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.rw_dismiss"},
            blocking=True,
        )
        # Then a good call with the same instance_id.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.rw_dismiss"),
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_dismiss__config_error"
        )
        assert notif_id not in notifs


class TestServiceLayerScan:
    async def test_successful_scan_creates_diagnostic_state(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """A successful scan populates the diagnostic state
        entity at
        ``blueprint_toolkit.rw_<slug>_state``
        with the common attrs (``instance_id``, ``last_run``,
        ``runtime``) plus the per-port stat extras.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.rw_scan"),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.rw_rw_scan_state",
        )
        assert state is not None, "diagnostic state entity not created"
        assert state.state == "ok"
        attrs = state.attributes
        # Common attrs.
        assert attrs["instance_id"] == "automation.rw_scan"
        assert "last_run" in attrs
        assert "runtime" in attrs
        # Per-port stat extras (subset; full list in the
        # handler).
        for key in (
            "paths_included",
            "paths_excluded",
            "owners_total",
            "owners_with_issues",
            "total_findings",
            "broken_entity_count",
            "broken_device_count",
            "refs_total",
            "source_orphan_count",
        ):
            assert key in attrs, f"missing diagnostic attr: {key}"
        # Trigger label propagates from the payload.
        assert attrs["last_trigger"] == "manual"

    async def test_owner_finding_notification_carries_automation_link(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """RW per-owner notifications must carry the
        ``Automation: [name](link)`` prefix. Regression
        guard for the P1 the code review caught: the
        handler initially built per-owner specs without
        ``instance_id``, so the dispatcher's friendly-name
        lookup never fired and users couldn't click through
        to the automation that was scanning.
        """
        await _setup_integration(hass)
        # Register the automation entity so the dispatcher
        # can find a friendly name + YAML id to build the
        # link.
        hass.states.async_set(
            "automation.rw_finding",
            "on",
            {"friendly_name": "RW: Finding", "id": "9999"},
        )
        # Plant a template.yaml with a broken jinja
        # entity reference. RW's
        # ``_scan_template`` adapter walks YAML reachable
        # from configuration.yaml; we feed
        # template.yaml directly via a configuration.yaml
        # include.
        config_dir = Path(hass.config.config_dir)
        (config_dir / "configuration.yaml").write_text(
            "template: !include template.yaml\n",
        )
        (config_dir / "template.yaml").write_text(
            "- sensor:\n"
            "    - name: BogusRef\n"
            "      state: \"{{ states('sensor.does_not_exist') }}\"\n",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.rw_finding"),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        # Exactly one per-owner notification with the RW
        # prefix should be present (modulo unrelated HA
        # notifications); identify it by the
        # service-prefix + the ``owner_`` infix RW's
        # builders use.
        rw_owner_notifs = {
            nid: spec
            for nid, spec in notifs.items()
            if nid.startswith(
                "blueprint_toolkit_reference_watchdog"
                "__automation.rw_finding__owner_"
            )
        }
        assert len(rw_owner_notifs) >= 1, (
            "expected at least one per-owner RW notification; "
            f"got {sorted(notifs.keys())}"
        )
        spec = next(iter(rw_owner_notifs.values()))
        body: str = spec["message"]
        # Critical assertion: the dispatcher prepended the
        # automation-link header. Pre-fix this body
        # started with the per-owner content directly.
        assert body.startswith(
            "Automation: [RW: Finding](/config/automation/edit/9999)\n",
        ), f"missing automation-link prefix; body was: {body[:200]!r}"

    async def test_broken_service_call_surfaces_in_owner_notification(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """A broken ``service: script.<name>`` in
        ``automations.yaml`` reaches the sniff path,
        bypasses the negative truth set (no such service
        registered), and surfaces in the owner's
        ``Broken entity references`` section. Covers both
        the literal-string form and the list-form.
        """
        await _setup_integration(hass)
        # An automation entity is required so RW's owner-
        # builder can resolve a friendly name.
        hass.states.async_set(
            "automation.rw_broken_service",
            "on",
            {
                "friendly_name": "RW: BrokenService",
                "id": "8888",
            },
        )
        # Seed at least one ``script.*`` entity so the sniff
        # regex's domain check fires for the broken refs.
        hass.states.async_set(
            "script.exists",
            "off",
            {"friendly_name": "Exists"},
        )
        config_dir = Path(hass.config.config_dir)
        (config_dir / "automations.yaml").write_text(
            "- id: '8888'\n"
            "  alias: RW BrokenService\n"
            "  trigger: []\n"
            "  action:\n"
            "    - service: script.does_not_exist\n"
            "    - service:\n"
            "        - script.also_missing\n"
            "        - script.exists\n",
        )
        # configuration.yaml needs to include the
        # automations file so RW's discovery picks it up.
        (config_dir / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.rw_broken_service"),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        owner_notifs = {
            nid: spec
            for nid, spec in notifs.items()
            if nid.startswith(
                "blueprint_toolkit_reference_watchdog"
                "__automation.rw_broken_service__owner_"
            )
        }
        assert len(owner_notifs) >= 1, (
            "expected owner notification for broken service refs; "
            f"got {sorted(notifs.keys())}"
        )
        body = "\n".join(spec["message"] for spec in owner_notifs.values())
        assert "script.does_not_exist" in body
        assert "script.also_missing" in body
        # The valid script in the list MUST NOT be flagged.
        assert "script.exists" not in body


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
                instance_id="automation.rw_unmatched",
                exclude_integrations=["typoed_integration"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_unmatched__unmatched_directives"
        )
        assert notif_id in notifs, (
            "expected unmatched-directives notification; got: "
            f"{sorted(notifs.keys())}"
        )
        body: str = notifs[notif_id]["message"]
        assert "typoed_integration" in body
        assert "exclude_integrations" in body
        assert "unknown integration" in body

    async def test_toggle_off_dismisses_prior_notification(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        await _setup_integration(hass)
        # First run: typo'd integration with toggle on ->
        # notification fires.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_toggle",
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
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_toggle__unmatched_directives"
        )
        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        assert notif_id in notifs, "first run should fire the notification"

        # Second run: toggle off -> the prior notification
        # gets dismissed, even with the same typo'd value.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_toggle",
                exclude_integrations=["typoed_integration"],
                validate_includes_excludes=False,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        notifs = _async_get_or_create_notifications(hass)
        assert notif_id not in notifs, (
            "toggle-off run must dismiss the prior unmatched-directives notif"
        )

    async def test_each_directive_category_surfaces_end_to_end(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """One representative bullet per directive category in a single
        notification body: integration / entity / path / regex.

        Locks down the per-handler ``_validate_rw_directives``
        composition so a refactor that drops a category from
        the orchestration silently fails CI rather than
        silently shipping.
        """
        await _setup_integration(hass)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_categories",
                exclude_integrations=["typoed_integration"],
                exclude_entities=["sensor.test_each_dir_cat_unique_id"],
                exclude_paths="deleted_dir/*.yaml",
                exclude_entity_id_regex=r"^xyz_no_match_anywhere_each_cat$",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_categories__unmatched_directives"
        )
        body = _async_get_or_create_notifications(hass)[notif_id]["message"]
        assert "exclude_integrations" in body
        assert "exclude_entities" in body
        assert "exclude_paths" in body
        assert "exclude_entity_id_regex" in body
        assert "typoed_integration" in body
        assert "sensor.test_each_dir_cat_unique_id" in body
        assert "deleted_dir" in body
        assert "xyz_no_match_anywhere_each_cat" in body

    async def test_cap_bypass_unmatched_directives_always_surfaces(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """The unmatched-directives notification rides outside the
        per-owner cap.

        Regression guard: the cap-bypass is structural -- the
        unmatched spec is appended to the dispatch list AFTER
        ``prepare_notifications`` already trimmed the per-owner
        results. A future refactor that lifts the cap into the
        dispatcher (or moves the unmatched spec inside the input
        list ``prepare_notifications`` sees) would silently bury
        the user's typo'd-exclusion diagnostic under a busy run.
        Plant two owners with broken refs (so cap=1 engages) plus
        a typo'd directive; assert the cap-summary AND the
        unmatched-directives notification both fire.
        """
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.rw_capbypass",
            "on",
            {"friendly_name": "RW: CapBypass", "id": "8989"},
        )
        config_dir = Path(hass.config.config_dir)
        # Two distinct owners with broken refs -> two
        # candidates for the per-owner cap.
        (config_dir / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n"
            "template: !include template.yaml\n",
        )
        (config_dir / "automations.yaml").write_text(
            "- id: '6601'\n"
            "  alias: RW CapAuto\n"
            "  trigger: []\n"
            "  action:\n"
            "    - service: homeassistant.turn_on\n"
            "      entity_id: light.cap_does_not_exist_a\n",
        )
        (config_dir / "template.yaml").write_text(
            "- sensor:\n"
            "    - name: BogusCapRef\n"
            "      state: \"{{ states('sensor.cap_does_not_exist_b') }}\"\n",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_capbypass",
                exclude_integrations=["typoed_capbypass_int"],
                max_source_notifications=1,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        prefix = (
            "blueprint_toolkit_reference_watchdog__automation.rw_capbypass__"
        )
        per_owner = [nid for nid in notifs if nid.startswith(f"{prefix}owner_")]
        cap_id = f"{prefix}cap"
        unmatched_id = f"{prefix}unmatched_directives"
        # Cap engaged: only one per-owner fired.
        assert len(per_owner) == 1, (
            f"expected exactly 1 per-owner notif under cap=1; "
            f"got {sorted(per_owner)}"
        )
        # Cap-summary fires alongside.
        assert cap_id in notifs
        # Unmatched-directives notification still surfaces.
        assert unmatched_id in notifs, (
            f"unmatched-directives notif suppressed by cap; "
            f"got {sorted(notifs.keys())}"
        )
        body = notifs[unmatched_id]["message"]
        assert "typoed_capbypass_int" in body

    async def test_customize_exclude_does_not_false_flag(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """``exclude_entities`` is also documented as silencing
        customize.yaml entries (the YAML key IS the entity_id).
        Regression for the customize-branch ``seen_entity_refs``
        gap: if the customize key didn't end up in
        ``seen_entity_refs``, the user's exclusion would
        false-flag as "no entity matches".
        """
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.rw_customize",
            "on",
            {"friendly_name": "RW: Customize", "id": "5555"},
        )
        config_dir = Path(hass.config.config_dir)
        (config_dir / "configuration.yaml").write_text(
            "homeassistant:\n  customize: !include customize.yaml\n",
        )
        (config_dir / "customize.yaml").write_text(
            "sensor.removed_in_customize:\n  friendly_name: Old Name\n",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_customize",
                exclude_entities=["sensor.removed_in_customize"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_customize__unmatched_directives"
        )
        notifs = _async_get_or_create_notifications(hass)
        if notif_id in notifs:
            body = notifs[notif_id]["message"]
            assert "sensor.removed_in_customize" not in body, (
                f"customize-key suppression false-flagged: {body!r}"
            )

    async def test_broken_ref_suppression_does_not_false_flag(
        self,
        hass,  # noqa: ANN001
    ) -> None:
        """``exclude_entities`` is documented as silencing broken
        reference findings (target side). The value used to silence
        a broken ref is by definition NOT a registered entity --
        the validator must NOT flag it as "no entity matches".

        Plants a broken reference in a real automations.yaml,
        adds the broken target to ``exclude_entities``, asserts
        no unmatched-directives notification fires.
        """
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.rw_brokenref",
            "on",
            {"friendly_name": "RW: BrokenRef", "id": "7777"},
        )
        config_dir = Path(hass.config.config_dir)
        (config_dir / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n",
        )
        (config_dir / "automations.yaml").write_text(
            "- id: '7777'\n"
            "  alias: RW BrokenRef\n"
            "  trigger: []\n"
            "  action:\n"
            "    - service: homeassistant.turn_on\n"
            "      entity_id: light.does_not_exist\n",
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.rw_brokenref",
                exclude_entities=["light.does_not_exist"],
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notif_id = (
            "blueprint_toolkit_reference_watchdog"
            "__automation.rw_brokenref__unmatched_directives"
        )
        notifs = _async_get_or_create_notifications(hass)
        # The unmatched-directives notification spec is always
        # dispatched, but it's inactive (auto-dismiss) when there
        # are no unmatched entries -- so it shouldn't appear in the
        # active set.
        if notif_id in notifs:
            body = notifs[notif_id]["message"]
            assert "light.does_not_exist" not in body, (
                f"broken-ref suppression false-flagged: {body!r}"
            )


class TestRecoveryEvents(RecoveryEventsIntegrationBase):
    service_tag = "RW"
    setup_integration = staticmethod(_setup_integration)


class TestCodeQuality(CodeQualityBase):
    ruff_targets = [
        "tests/test_reference_watchdog_integration.py",
    ]
    mypy_targets: list[str] = []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
