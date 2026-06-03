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
"""Integration-level tests for the STEC handler.

Exercises the parts the in-process unit tests
(``tests/test_sensor_threshold_entity_controller_handler.py``)
deliberately don't cover: the live ``vol.Schema`` argparse,
the cross-field check against ``hass.states`` for
``controlled_entities``, the full ``_async_service_layer``
state-load / action-dispatch / response-shape loop (including
the multi-entity turn-OFF on-subset targeting), and the
diagnostic-state attrs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Make custom_components/ importable as a top-level package.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402
from conftest import (  # noqa: E402
    RecoveryEventsIntegrationBase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

DOMAIN = "blueprint_toolkit"
SERVICE = "sensor_threshold_entity_controller"


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


def _seed_controlled(
    hass: Any,
    entity_id: str = "switch.fan",
    *,
    state: str = "off",
    friendly_name: str = "Test Fan",
) -> None:
    """Plant a fake controlled entity in the state machine.

    STEC's argparse cross-field check requires each
    controlled entity to exist as a known state; the
    service layer also reads the live state to build the
    on-subset / friendly-name maps. We only need them
    visible to ``hass.states.get`` so we can drive the
    service-call path through to the service layer without
    a real switch integration.
    """
    hass.states.async_set(entity_id, state, {"friendly_name": friendly_name})


def _valid_payload(
    *,
    instance_id: str = "automation.stec_test",
    controlled_entities: list[str] | None = None,
    sensor_value: str = "55.0",
    trigger_entity: str = "sensor.humidity",
    trigger_threshold: float = 70.0,
    release_threshold: float = 60.0,
) -> dict[str, Any]:
    """Build a fully-populated STEC service-call payload."""
    return {
        "instance_id": instance_id,
        "trigger_id": "manual",
        "controlled_entities_raw": (
            ["switch.fan"]
            if controlled_entities is None
            else controlled_entities
        ),
        "sensor_value": sensor_value,
        "trigger_entity": trigger_entity,
        "trigger_threshold_raw": trigger_threshold,
        "release_threshold_raw": release_threshold,
        "sampling_window_seconds_raw": 600,
        "disable_window_seconds_raw": 30,
        "auto_off_minutes_raw": 60,
        "notification_prefix": "",
        "notification_suffix": "",
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
        await _setup_integration(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.stec_bad_call"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_bad_call__config_error"
        )
        assert notif_id in notifs, "config-error notification was not emitted"
        assert "schema:" in notifs[notif_id]["message"]

    async def test_empty_controlled_entities_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """An empty controlled set has nothing to drive; the
        cross-field check rejects it so a YAML edit that
        clears the list doesn't silently no-op forever.
        """
        await _setup_integration(hass)

        payload = _valid_payload(
            instance_id="automation.stec_empty",
            controlled_entities=[],
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_empty__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "controlled_entities" in msg
        assert "at least one entity is required" in msg

    async def test_unknown_controlled_entity_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)

        # No ``_seed_controlled`` -- the entity doesn't
        # exist; the cross-field check should reject.
        payload = _valid_payload(
            instance_id="automation.stec_bad_switch",
            controlled_entities=["switch.does_not_exist"],
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_bad_switch__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "controlled_entities" in msg
        assert "switch.does_not_exist" in msg

    async def test_non_controllable_controlled_entity_creates_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Cross-field guard: each controlled entity must
        live in a domain that responds to
        ``homeassistant.turn_on`` / ``turn_off``. The
        blueprint selector restricts the input to
        ``switch / fan / light / input_boolean``, but a
        hand-edited YAML automation can bypass the
        selector. Argparse rejects it (with the per-entity
        bullet) before the service layer dispatches a
        silent no-op.
        """
        await _setup_integration(hass)
        # Existing entity, wrong domain (sensors don't
        # respond to homeassistant.turn_on/off).
        hass.states.async_set("sensor.humidity", "55.0")
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")

        payload = _valid_payload(
            instance_id="automation.stec_bad_domain",
            controlled_entities=["sensor.humidity"],
        )
        await hass.services.async_call(DOMAIN, SERVICE, payload, blocking=True)
        await hass.async_block_till_done()

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_bad_domain__config_error"
        )
        assert notif_id in notifs
        msg: str = notifs[notif_id]["message"]
        assert "controlled_entities" in msg
        assert "'sensor.humidity'" in msg
        assert "does not support on/off" in msg
        # Argparse rejected; service layer must not have
        # dispatched a turn_on against the bad entity.
        assert turn_on_calls == []

    async def test_notification_includes_automation_link_when_known(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        hass.states.async_set(
            "automation.stec_link",
            "on",
            {"friendly_name": "STEC: Linked", "id": "1234"},
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.stec_link"},
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_link__config_error"
        )
        assert notif_id in notifs
        body: str = notifs[notif_id]["message"]
        assert body.startswith(
            "Automation: [STEC: Linked](/config/automation/edit/1234)\n",
        )

    async def test_successful_call_dismisses_prior_notification(
        self,
        hass: HomeAssistant,
    ) -> None:
        await _setup_integration(hass)
        _seed_controlled(hass)

        # Bad call first.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"instance_id": "automation.stec_dismiss"},
            blocking=True,
        )
        # Good call with the same instance_id.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.stec_dismiss"),
            blocking=True,
        )

        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        notifs: dict[str, Any] = _async_get_or_create_notifications(hass)
        notif_id = (
            "blueprint_toolkit_sensor_threshold_entity_controller"
            "__automation.stec_dismiss__config_error"
        )
        assert notif_id not in notifs


# --------------------------------------------------------
# Service layer: state load / save + diagnostic state
# --------------------------------------------------------


class TestServiceLayerScan:
    async def test_successful_call_creates_diagnostic_state(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A successful call populates the diagnostic state
        entity with the standard attrs (``instance_id``,
        ``last_run``, ``runtime``, ``state``) plus the STEC
        decision-context extras + the ``data`` blob.
        """
        await _setup_integration(hass)
        _seed_controlled(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(instance_id="automation.stec_scan"),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.stec_stec_scan_state",
        )
        assert state is not None, "diagnostic state entity not created"
        attrs = state.attributes
        # Common attrs.
        assert attrs["instance_id"] == "automation.stec_scan"
        assert "last_run" in attrs
        assert "runtime" in attrs
        # STEC-specific decision-context extras.
        for key in (
            "last_trigger",
            "last_event",
            "last_action",
            "last_reason",
            "last_sensor",
            "controlled_entities",
            "controlled_on",
            "data",
        ):
            assert key in attrs, f"missing diagnostic attr: {key}"
        assert attrs["controlled_entities"] == ["switch.fan"]
        # Seeded switch is off -> controlled_on is False.
        assert attrs["controlled_on"] is False
        # ``data`` is the JSON-encoded controller state
        # blob the next tick re-loads.
        import json

        loaded = json.loads(attrs["data"])
        assert isinstance(loaded, dict)
        # The controller's State has these keys at minimum
        # (see logic.State.to_dict).
        for key in ("samples", "baseline", "overrides", "initialized"):
            assert key in loaded, (
                f"missing controller-state key: {key}; got {sorted(loaded)}"
            )

    async def test_state_blob_round_trips_across_calls(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The ``data`` attribute the prior call wrote
        should be readable + reflected in the next call's
        decisions. Specifically: after one sensor sample,
        the ``samples`` list in the persisted blob has
        length 1.
        """
        await _setup_integration(hass)
        _seed_controlled(hass)

        # First call: sensor reading well below threshold.
        # Triggers the sensor sample-window path.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.stec_persist",
                sensor_value="50.0",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.stec_stec_persist_state",
        )
        assert state is not None
        import json

        loaded = json.loads(state.attributes["data"])
        # The first sensor sample should be in the
        # samples list. (Empty initially -> populated
        # after this call.)
        assert len(loaded["samples"]) >= 1


# --------------------------------------------------------
# Action dispatch + notification routing
# --------------------------------------------------------


def _spike_payload(
    *,
    instance_id: str,
    sensor_value: str,
    controlled_entities: list[str] | None = None,
) -> dict[str, Any]:
    """Spike-tuned STEC payload.

    The default ``trigger_threshold`` of 5.0 keeps the
    spike-detection bar low so a 55 -> 65 sensor swing in
    the action-dispatch / response-shape tests trips
    ``Action.TURN_ON`` reliably.
    """
    return _valid_payload(
        instance_id=instance_id,
        controlled_entities=controlled_entities,
        sensor_value=sensor_value,
        trigger_entity="sensor.humidity",
        trigger_threshold=5.0,
        release_threshold=2.0,
    )


class TestActionDispatch:
    async def test_spike_dispatches_homeassistant_turn_on(
        self,
        hass: HomeAssistant,
    ) -> None:
        """End-to-end: a sensor spike should provoke a
        single ``homeassistant.turn_on`` against the
        controlled set (a list ``entity_id``). Without this
        test the dispatch is opaque to the test surface (the
        logic suite tests the action enum, not the HA
        service call).

        Also asserts ``context=call.context`` is propagated
        from the originating service call through to the
        ``homeassistant.turn_on`` dispatch -- without this,
        the HA logbook would attribute the action to the
        integration rather than to the originating
        automation.
        """
        from homeassistant.core import Context
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")

        # First call seeds a baseline-low sample.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_spike",
                sensor_value="55.0",
            ),
            blocking=True,
        )
        # Second call jumps above ``baseline + threshold``;
        # logic returns ``Action.TURN_ON``. Attach an
        # explicit ``Context`` so we can assert
        # propagation to the dispatched ``turn_on`` call.
        spike_ctx = Context()
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_spike",
                sensor_value="65.0",
            ),
            blocking=True,
            context=spike_ctx,
        )
        await hass.async_block_till_done()

        assert len(turn_on_calls) == 1
        # A turn-ON targets the full configured list.
        assert turn_on_calls[0].data["entity_id"] == ["switch.fan"]
        # Context propagation: the dispatched ``turn_on``
        # should carry the spike call's context, not a
        # fresh-from-HA one.
        assert turn_on_calls[0].context.id == spike_ctx.id

    async def test_no_action_when_sensor_steady(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A sensor reading at baseline should leave the
        switch alone -- no turn_on / turn_off dispatch.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
        turn_off_calls = async_mock_service(hass, "homeassistant", "turn_off")

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_steady",
                sensor_value="55.0",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        assert turn_on_calls == []
        assert turn_off_calls == []


class TestMultiEntityDispatch:
    """Multi-entity action dispatch: a turn-ON targets the
    full configured set; a turn-OFF (release / auto-off)
    targets and names only the entities that are currently
    on."""

    async def test_spike_turns_on_full_list(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A spike on a two-entity controller dispatches one
        ``turn_on`` whose ``entity_id`` is both entities."""
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass, "switch.fan", friendly_name="Fan One")
        _seed_controlled(hass, "switch.fan2", friendly_name="Fan Two")
        turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")

        controlled = ["switch.fan", "switch.fan2"]
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_multi_on",
                sensor_value="55.0",
                controlled_entities=controlled,
            ),
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_multi_on",
                sensor_value="65.0",
                controlled_entities=controlled,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        assert len(turn_on_calls) == 1
        assert turn_on_calls[0].data["entity_id"] == controlled

    async def test_release_turns_off_only_on_subset(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Two controlled entities, only one on: a sensor
        release fires ONE ``turn_off`` whose ``entity_id`` is
        exactly the on-subset (not both), and the response
        notification names only that subset.

        A baseline is pre-seeded into the diagnostic state's
        ``data`` blob (with an empty sample window) so the
        very next sensor reading -- below ``baseline +
        release`` -- triggers the release path without the
        spike sample lingering in the rolling window.
        """
        import json

        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        from custom_components.blueprint_toolkit.sensor_threshold_entity_controller.logic import (  # noqa: E501
            State,
        )

        await _setup_integration(hass)
        # fan is OFF, fan2 is ON -> the on-subset is [fan2].
        _seed_controlled(
            hass, "switch.fan", state="off", friendly_name="Fan One"
        )
        _seed_controlled(
            hass, "switch.fan2", state="on", friendly_name="Fan Two"
        )
        async_mock_service(hass, "homeassistant", "turn_on")
        turn_off_calls = async_mock_service(hass, "homeassistant", "turn_off")

        instance_id = "automation.stec_multi_off"
        controlled = ["switch.fan", "switch.fan2"]

        # Pre-seed an active baseline with an empty sample
        # window so the next reading drives the release path.
        seeded = State(baseline=60.0, initialized=True)
        hass.states.async_set(
            "blueprint_toolkit.stec_stec_multi_off_state",
            "NONE",
            {"data": json.dumps(seeded.to_dict())},
        )

        # Reading at 61 <= baseline(60) + release(2) -> release.
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id=instance_id,
                sensor_value="61.0",
                controlled_entities=controlled,
            ),
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()

        assert len(turn_off_calls) == 1
        # The turn-OFF targets ONLY the on-subset, never the
        # full configured list.
        assert turn_off_calls[0].data["entity_id"] == ["switch.fan2"]
        # The notification body names only the on-subset.
        assert response is not None
        body = response["notification_message"]
        assert isinstance(body, str)
        assert "Fan Two" in body
        assert "Fan One" not in body


class TestServiceResponseShape:
    async def test_spike_returns_notification_message_in_response(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Spike paths return a ``ServiceResponse`` mapping
        carrying the pre-built notification body under
        ``notification_message`` -- the blueprint captures
        this via ``response_variable`` and runs the
        user-supplied ``notify_action`` step against it.
        Locks down the slot name + the non-empty body
        contract on emit paths.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        async_mock_service(hass, "homeassistant", "turn_on")

        # First call seeds a baseline-low sample; second
        # spikes well above ``baseline + threshold`` so the
        # logic emits a TURN_ON + notification body.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_resp",
                sensor_value="55.0",
            ),
            blocking=True,
            return_response=True,
        )
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_resp",
                sensor_value="65.0",
            ),
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()

        assert isinstance(response, dict)
        assert "notification_message" in response
        assert response["notification_message"]

    async def test_no_op_returns_empty_message(
        self,
        hass: HomeAssistant,
    ) -> None:
        """A baseline-steady sensor reading produces no
        notification, so the response's
        ``notification_message`` slot is the empty string.
        The blueprint's ``choose`` short-circuits on that
        and the user's notify action does not fire.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        async_mock_service(hass, "homeassistant", "turn_on")

        response = await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_noop_resp",
                sensor_value="55.0",
            ),
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()

        assert response == {"notification_message": ""}


class TestServiceRegistersWithSupportsResponse:
    async def test_registered_service_supports_response_optional(
        self,
        hass: HomeAssistant,
    ) -> None:
        """The service registers with
        ``SupportsResponse.OPTIONAL`` so the blueprint can
        capture the handler's return value via
        ``response_variable`` without forcing every
        non-blueprint caller to handle the response.
        """
        from homeassistant.core import SupportsResponse

        await _setup_integration(hass)
        assert (
            hass.services.supports_response(DOMAIN, SERVICE)
            == SupportsResponse.OPTIONAL
        )


class TestStateSavedBeforeResponseReturned:
    async def test_state_persists_before_handler_response(
        self,
        hass: HomeAssistant,
        monkeypatch: Any,
    ) -> None:
        """Code-ordering invariant: the diagnostic state
        write must run before the handler returns the
        response. The blueprint runner invokes the user's
        ``notify_action`` step AFTER the handler returns,
        so this ordering guarantees a notify-action
        failure can't roll back the state save. Catches a
        future refactor that moves the state save below
        the return.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        from custom_components.blueprint_toolkit.sensor_threshold_entity_controller import (  # noqa: E501
            handler as stec_handler,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        async_mock_service(hass, "homeassistant", "turn_on")

        call_order: list[str] = []

        real_update = stec_handler.update_instance_state

        def _spy_update(*args: Any, **kwargs: Any) -> None:
            call_order.append("state")
            real_update(*args, **kwargs)

        monkeypatch.setattr(
            stec_handler,
            "update_instance_state",
            _spy_update,
        )

        # Seed + spike to drive the message-emitting path.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_order",
                sensor_value="55.0",
            ),
            blocking=True,
            return_response=True,
        )
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _spike_payload(
                instance_id="automation.stec_order",
                sensor_value="65.0",
            ),
            blocking=True,
            return_response=True,
        )
        call_order.append("response")
        await hass.async_block_till_done()

        # Both calls hit the state save; the response slot
        # in ``call_order`` lands AFTER both.
        assert call_order.count("state") == 2
        assert call_order[-1] == "response"
        # Sanity: the response carried a non-empty
        # ``notification_message`` so we know we exercised
        # the message-emitting branch (and not a no-op
        # path that would bypass the ordering test).
        assert response and response.get("notification_message")


# --------------------------------------------------------
# State-blob load defensives
# --------------------------------------------------------


class TestLoadStateBlobMalformed:
    async def test_malformed_json_does_not_crash_reconcile(
        self,
        hass: HomeAssistant,
    ) -> None:
        """``_load_state_blob`` returns ``None`` on
        malformed JSON; the logic module then bootstraps
        fresh state. Prior versions of the handler may
        have written a different blob shape, so this is
        a real upgrade-path concern.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        async_mock_service(hass, "homeassistant", "turn_on")

        # Plant a malformed ``data`` blob in the
        # diagnostic state entity that the handler will
        # try to load.
        hass.states.async_set(
            "blueprint_toolkit.stec_stec_malformed_state",
            "NONE",
            {"data": "{not valid json"},
        )

        # Should not raise; the reconcile bootstraps fresh
        # state and overwrites the blob with a clean one.
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.stec_malformed",
                sensor_value="55.0",
                trigger_entity="sensor.humidity",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.stec_stec_malformed_state",
        )
        assert state is not None
        # Blob was rewritten cleanly -- valid JSON now.
        import json

        loaded = json.loads(state.attributes["data"])
        # Switch is off in the seeded payload -> the
        # bootstrap-arm in ``handle_service_call`` should
        # NOT have armed auto-off. This locks down the
        # "switch=off skips arm" half of the bootstrap
        # decision tree at the integration level.
        assert loaded.get("auto_off_started_at") is None

    async def test_non_string_data_does_not_crash_reconcile(
        self,
        hass: HomeAssistant,
    ) -> None:
        """``_load_state_blob`` treats a non-string ``data``
        attribute as missing. Defensive: the prior run's
        save path always writes a JSON string, but a stray
        upgrade or hand-edit could plant something else and
        the bootstrap path must absorb it cleanly.
        """
        from pytest_homeassistant_custom_component.common import (
            async_mock_service,
        )

        await _setup_integration(hass)
        _seed_controlled(hass)
        async_mock_service(hass, "homeassistant", "turn_on")

        # Plant a non-string ``data`` value (HA states API
        # serializes through JSON so anything that JSON can
        # represent is allowed in attributes).
        hass.states.async_set(
            "blueprint_toolkit.stec_stec_nonstring_state",
            "NONE",
            {"data": {"not": "a string"}},
        )

        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _valid_payload(
                instance_id="automation.stec_nonstring",
                sensor_value="55.0",
                trigger_entity="sensor.humidity",
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(
            "blueprint_toolkit.stec_stec_nonstring_state",
        )
        assert state is not None
        # Bootstrap rewrote the blob with a valid JSON
        # string.
        import json

        json.loads(state.attributes["data"])


class TestRecoveryEvents(RecoveryEventsIntegrationBase):
    service_tag = "STEC"
    setup_integration = staticmethod(_setup_integration)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
