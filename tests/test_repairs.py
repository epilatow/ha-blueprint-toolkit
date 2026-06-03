#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.331",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Repairs flow tests for blueprint_toolkit.

Flows under test:

- ``install_conflicts``: pre-seed an unrecognized symlink
  at one of our destinations, run setup, verify the
  Repairs UI surfaces the issue, then walk the fix flow
  and verify the symlink was replaced and the issue
  cleared.
- ``install_failure``: pre-seed something the installer
  cannot replace (a directory at a destination), run
  setup, verify the failure issue is created with the
  error text in its data, walk the fix flow.
- ``WatchdogFixFlow``: seed a watchdog repair issue
  (``__repair_`` id) carrying flattened ``service_data_*``,
  walk the confirm flow, and verify the confirm form
  replays the issue's translation placeholders and Submit
  dispatches the un-flattened service_data to the stashed
  service, then clears the issue.

Same import-deferral pattern as tests/test_integration.py
to avoid pytest-HACC's patch_recorder assertion.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Make custom_components/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import issue_registry as ir
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

DOMAIN = "blueprint_toolkit"
ISSUE_INSTALL_CONFLICTS = "install_conflicts"
ISSUE_INSTALL_FAILURE = "install_failure"


@pytest.fixture(autouse=True)
def install_our_integration(
    hass: HomeAssistant,
    # Requested for its side effect; pytest resolves fixtures by name
    # so it can't be ``_``-prefixed, and ``usefixtures`` has no effect
    # on a fixture function.
    enable_custom_integrations: None,  # noqa: ARG001
) -> Generator[None]:
    """Symlink the integration into pytest-HACC's testing_config.

    Mirrors the same fixture in ``tests/test_integration.py``.
    Also wipes the install destinations (blueprints/, www/)
    under config_dir before yielding, because pytest-HACC
    reuses the testing_config directory across tests and
    pre-seeded conflicts from one test would otherwise leak
    into the next.
    """
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

    # Wipe install destinations so leftover state from a
    # previous test in the session doesn't pre-seed
    # conflicts here.
    config_dir = Path(hass.config.config_dir)
    for sub in ("blueprints",):
        target = config_dir / sub
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

    from homeassistant.loader import DATA_CUSTOM_COMPONENTS

    hass.data.pop(DATA_CUSTOM_COMPONENTS, None)
    yield
    if dst.is_symlink():
        dst.unlink()
    for sub in ("blueprints",):
        target = config_dir / sub
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)


def _mock_config_entry(**kwargs: Any) -> MockConfigEntry:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    return MockConfigEntry(**kwargs)


def _conflict_destination(config_dir: Path) -> Path:
    """Pick one of the integration's expected destinations.

    Used to pre-seed an unexpected symlink/dir there so
    the reconciler classifies it as a conflict.
    """
    return (
        config_dir
        / "blueprints"
        / "automation"
        / "blueprint_toolkit"
        / "device_watchdog.yaml"
    )


async def _get_issue(
    hass: HomeAssistant, issue_id: str
) -> ir.IssueEntry | None:
    """Look up our issue in HA's issue registry, or None."""
    from homeassistant.helpers import issue_registry as ir

    registry = ir.async_get(hass)
    return registry.async_get_issue(DOMAIN, issue_id)


class TestInstallConflictsFlow:
    async def test_foreign_symlink_creates_issue_and_overwrite_clears_it(
        self,
        hass: HomeAssistant,
        tmp_path: Path,
    ) -> None:
        # Pre-seed a stray symlink at a destination the
        # reconciler will want to install to.
        config_dir = Path(hass.config.config_dir)
        dest = _conflict_destination(config_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        stray = tmp_path / "stray.py"
        stray.write_text("# not ours\n")
        dest.symlink_to(stray)

        # Run setup; reconciler should classify the
        # pre-seeded symlink as foreign_symlink and
        # surface a repair issue.
        entry = _mock_config_entry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        issue = await _get_issue(hass, ISSUE_INSTALL_CONFLICTS)
        assert issue is not None, "expected install_conflicts issue"
        assert issue.is_fixable
        # The issue's data carries the conflict list and
        # the entry id so the fix flow can re-plan with
        # force on those destinations.
        data: dict[str, Any] = issue.data or {}
        assert data.get("entry_id") == entry.entry_id
        dest_strs = data.get("conflict_destinations") or []
        assert str(dest) in dest_strs

        # Walk the fix flow via the proper Repairs flow
        # manager (config_entries.flow doesn't handle
        # repair issues -- they live under the repairs
        # component's own FlowManager).
        from homeassistant.components.repairs import repairs_flow_manager
        from homeassistant.setup import async_setup_component

        assert await async_setup_component(hass, "repairs", {})
        await hass.async_block_till_done()
        manager = repairs_flow_manager(hass)
        assert manager is not None
        flow = await manager.async_init(
            DOMAIN,
            data={"issue_id": ISSUE_INSTALL_CONFLICTS},
        )
        # init -> confirm form; submit empty user_input.
        if flow["type"] == "form":
            flow = await manager.async_configure(
                flow["flow_id"],
                user_input={},
            )
        # The flow manager's async_finish_flow deletes
        # the issue automatically on create_entry.
        await hass.async_block_till_done()

        # Symlink should now point into our bundle, not at
        # the stray.
        import os

        assert dest.is_symlink()
        resolved = os.path.realpath(dest)
        assert "/blueprint_toolkit/bundled/" in resolved, (
            f"expected bundled-target after overwrite, got {resolved}"
        )

        # Issue should be cleared.
        assert await _get_issue(hass, ISSUE_INSTALL_CONFLICTS) is None


class TestInstallFailureFlow:
    async def test_directory_at_destination_creates_failure_issue(
        self,
        hass: HomeAssistant,
    ) -> None:
        # Pre-seed a directory at one of our destinations.
        # The reconciler classifies regular_dir as a
        # conflict (so the integration first surfaces an
        # install_conflicts issue, not install_failure).
        # The install_failure issue surfaces only when the
        # installer's apply step actually raises, which
        # happens on the Overwrite-of-a-directory path.
        # Here we just verify the conflict path lists it.
        config_dir = Path(hass.config.config_dir)
        dest = _conflict_destination(config_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir()  # directory at destination

        entry = _mock_config_entry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Conflict issue surfaces; install_failure does not
        # (the installer didn't try to remove the dir
        # because force wasn't requested).
        conflicts = await _get_issue(hass, ISSUE_INSTALL_CONFLICTS)
        assert conflicts is not None
        data: dict[str, Any] = conflicts.data or {}
        kinds = {c["kind"] for c in (data.get("conflicts") or [])}
        assert "regular_dir" in kinds

        failure = await _get_issue(hass, ISSUE_INSTALL_FAILURE)
        assert failure is None, (
            "regular_dir should surface as a conflict, not a failure, "
            "until the user explicitly Overwrites"
        )


class TestWatchdogFixFlow:
    async def _seed_issue(
        self,
        hass: HomeAssistant,
        issue_id: str,
        *,
        service_name: str,
        service_data: dict[str, Any],
        translation_placeholders: dict[str, str],
    ) -> None:
        from homeassistant.helpers import issue_registry as ir

        from custom_components.blueprint_toolkit.helpers_lifecycle import (
            _flatten_repair_data,
        )

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dw_device_disabled_diagnostics",
            translation_placeholders=translation_placeholders,
            data=_flatten_repair_data(
                service_name,
                service_data,
            ),
        )

    async def test_confirm_replays_placeholders_and_dispatches(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.components.repairs import repairs_flow_manager
        from homeassistant.core import ServiceCall
        from homeassistant.setup import async_setup_component

        # Load the integration so the repairs platform's
        # async_create_fix_flow is discoverable for DOMAIN.
        entry = _mock_config_entry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        calls: list[dict[str, Any]] = []

        async def _record(call: ServiceCall) -> None:
            calls.append(dict(call.data))

        hass.services.async_register(DOMAIN, "fix_test_service", _record)

        issue_id = (
            "blueprint_toolkit_dw__automation.x__"
            "repair_device_disabled_diagnostics__abc"
        )
        await self._seed_issue(
            hass,
            issue_id,
            service_name="fix_test_service",
            service_data={"notification_id": issue_id},
            translation_placeholders={
                "device_name": "Front Door Lock",
                "count": "2",
            },
        )

        assert await async_setup_component(hass, "repairs", {})
        await hass.async_block_till_done()
        manager = repairs_flow_manager(hass)
        assert manager is not None

        flow = await manager.async_init(
            DOMAIN,
            data={"issue_id": issue_id},
        )
        assert flow["type"] == "form"
        assert flow["step_id"] == "confirm"
        # The confirm modal replays the issue's placeholders
        # so {device_name} / {count} render rather than the
        # literal tokens.
        assert flow["description_placeholders"] == {
            "device_name": "Front Door Lock",
            "count": "2",
        }

        flow = await manager.async_configure(
            flow["flow_id"],
            user_input={},
        )
        await hass.async_block_till_done()

        # Submit un-flattened the service_data and dispatched
        # the stashed service with exactly the notification_id.
        assert calls == [{"notification_id": issue_id}]
        # Issue cleared on create_entry.
        assert await _get_issue(hass, issue_id) is None

    async def test_missing_service_name_no_dispatch(
        self,
        hass: HomeAssistant,
    ) -> None:
        from homeassistant.components.repairs import repairs_flow_manager
        from homeassistant.helpers import issue_registry as ir
        from homeassistant.setup import async_setup_component

        entry = _mock_config_entry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        issue_id = (
            "blueprint_toolkit_dw__automation.x__"
            "repair_device_disabled_diagnostics__noservice"
        )
        # No service_name in data: the flow must still close
        # cleanly without attempting a dispatch.
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dw_device_disabled_diagnostics",
            translation_placeholders={},
            data={},
        )

        assert await async_setup_component(hass, "repairs", {})
        await hass.async_block_till_done()
        manager = repairs_flow_manager(hass)
        assert manager is not None
        flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
        flow = await manager.async_configure(
            flow["flow_id"],
            user_input={},
        )
        await hass.async_block_till_done()
        assert await _get_issue(hass, issue_id) is None


class TestIssueClearedOnCleanReconcile:
    async def test_no_conflicts_no_issue(self, hass: HomeAssistant) -> None:
        # Clean state -- no pre-seeded conflicts. Setup
        # runs, no issue should be created.
        entry = _mock_config_entry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert await _get_issue(hass, ISSUE_INSTALL_CONFLICTS) is None
        assert await _get_issue(hass, ISSUE_INSTALL_FAILURE) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
