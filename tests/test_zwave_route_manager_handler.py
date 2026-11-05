#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "markdown-it-py",
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "probatio",
#     "PyYAML",
#     "pytest-homeassistant-custom-component==0.13.375",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for ``zwave_route_manager.handler``'s lifecycle code.

Covers parts that don't require booting Home Assistant:
the ``_on_reload`` / ``_on_entity_remove`` /
``_on_entity_rename`` / ``_on_teardown`` mutator
callbacks fed into the BlueprintHandlerSpec,
``_ensure_timer``'s schedule + re-arm sequencing,
the restart-recovery kick's synthetic-manual
``automation.trigger`` shape, and the schema vs blueprint
drift check. The argparse + service layers are exercised
end-to-end on a real HA host.

Uses the same lightweight homeassistant-modules stub the
TEC handler tests installed (so ``handler.py``'s HA-side
imports resolve) plus a small mock ``hass``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "zwave_route_manager"
    / "handler.py"
)
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from _handler_stubs import install_homeassistant_stubs  # noqa: E402
from _handler_test_base import (  # noqa: E402
    FrozenNow,
    MockEntry,
    MockHass,
)
from conftest import (  # noqa: E402
    BlueprintDefaultsRoundTripBase,
    BlueprintSchemaDriftBase,
    HandlerArgparseGuardsBase,
)
from markdown_it import MarkdownIt  # noqa: E402

install_homeassistant_stubs(frozen_now=FrozenNow.value)

from custom_components.blueprint_toolkit.helpers import (  # noqa: E402
    PersistentNotification,
    make_config_error_notification,
)
from custom_components.blueprint_toolkit.zwave_route_manager import (  # noqa: E402
    bridge,
    handler,
    logic,
)

# --------------------------------------------------------
# Mock hass surface
# --------------------------------------------------------


def _make_state(
    instance_id: str = "automation.zrm_test",
    *,
    armed_interval_minutes: int = 0,
    cancel_timer: Callable[[], None] | None = None,
) -> handler.ZrmInstanceState:
    return handler.ZrmInstanceState(
        instance_id=instance_id,
        armed_interval_minutes=armed_interval_minutes,
        cancel_timer=cancel_timer,
    )


def _hass_with_instances(
    instances: dict[str, handler.ZrmInstanceState],
) -> MockHass:
    h = MockHass()
    entry = MockEntry()
    entry.runtime_data.handlers["zwave_route_manager"] = {
        "instances": instances,
        "unsubs": [],
    }
    h.config_entries.entries.append(entry)
    return h


# --------------------------------------------------------
# Mutator callbacks
# --------------------------------------------------------


class TestOnReload:
    def test_cancels_pending_timers(self) -> None:
        canceled: list[int] = []

        def _cancel() -> None:
            canceled.append(1)

        s1 = _make_state("automation.a", armed_interval_minutes=5)
        s1.cancel_timer = _cancel
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        # No timer on s2; should not raise.
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_reload(h)

        assert canceled == [1]
        assert s1.cancel_timer is None
        assert s1.armed_interval_minutes == 0
        assert s2.cancel_timer is None
        # State entries themselves remain.
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_route_manager"
        ]
        assert set(bucket["instances"]) == {"automation.a", "automation.b"}


class TestOnEntityRemove:
    def test_drops_state_and_cancels_timer(self) -> None:
        canceled: list[int] = []

        def _cancel() -> None:
            canceled.append(1)

        s = _make_state("automation.a", armed_interval_minutes=5)
        s.cancel_timer = _cancel
        h = _hass_with_instances(
            {"automation.a": s, "automation.b": _make_state("automation.b")}
        )

        handler._on_entity_remove(h, "automation.a")

        assert canceled == [1]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_route_manager"
        ]
        assert set(bucket["instances"]) == {"automation.b"}

    def test_unknown_id_is_noop(self) -> None:
        h = _hass_with_instances({"automation.a": _make_state("automation.a")})
        # Should not raise.
        handler._on_entity_remove(h, "automation.unknown")


class TestOnEntityRename:
    def test_moves_state_to_new_id(self) -> None:
        s = _make_state("automation.old")
        h = _hass_with_instances({"automation.old": s})

        handler._on_entity_rename(h, "automation.old", "automation.new")

        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_route_manager"
        ]
        assert "automation.old" not in bucket["instances"]
        assert bucket["instances"]["automation.new"] is s
        assert s.instance_id == "automation.new"

    def test_unknown_old_id_is_noop(self) -> None:
        h = _hass_with_instances({"automation.a": _make_state("automation.a")})
        handler._on_entity_rename(h, "automation.unknown", "automation.x")


class TestOnTeardown:
    def test_cancels_all_and_clears(self) -> None:
        canceled: list[int] = []
        s1 = _make_state("automation.a", armed_interval_minutes=5)
        s1.cancel_timer = lambda: canceled.append(1)
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        s2.cancel_timer = lambda: canceled.append(2)
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_teardown(h)

        assert sorted(canceled) == [1, 2]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_route_manager"
        ]
        assert bucket["instances"] == {}


# --------------------------------------------------------
# Periodic timer arming
# --------------------------------------------------------


class TestEnsureTimer:
    def setup_method(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.unsub_called: list[int] = []

        def _fake_schedule(
            _hass: Any,
            entry: Any,
            *,
            interval: timedelta,
            instance_id: str,
            action: Any,
        ) -> Callable[[], None]:
            handle_index = len(self.calls)
            self.calls.append(
                {
                    "entry": entry,
                    "interval": interval,
                    "instance_id": instance_id,
                    "action": action,
                }
            )

            def _unsub() -> None:
                self.unsub_called.append(handle_index)

            return _unsub

        self._real_schedule = handler.schedule_periodic_with_jitter
        handler.schedule_periodic_with_jitter = _fake_schedule  # type: ignore[assignment]

    def teardown_method(self) -> None:
        handler.schedule_periodic_with_jitter = self._real_schedule

    def test_first_call_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zrm")
        e = object()

        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.calls[0]["entry"] is e
        assert self.calls[0]["interval"] == timedelta(minutes=5)
        assert self.calls[0]["instance_id"] == "automation.zrm"
        assert s.armed_interval_minutes == 5
        assert s.cancel_timer is not None

    def test_same_interval_does_not_re_arm(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zrm")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.unsub_called == []

    def test_changed_interval_re_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zrm")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 10)  # type: ignore[arg-type]

        assert self.unsub_called == [0]
        assert len(self.calls) == 2
        assert self.calls[1]["interval"] == timedelta(minutes=10)
        assert s.armed_interval_minutes == 10


# --------------------------------------------------------
# Restart-recovery kick payload
# --------------------------------------------------------


class TestKickWiring:
    def test_spec_kick_variables_match(self) -> None:
        assert handler._SPEC.kick_variables == {"trigger_id": "manual"}


# --------------------------------------------------------
# Notification builders
# --------------------------------------------------------


class TestConfigErrorBullet:
    """``_format_config_error`` renders one ConfigError as one bullet body."""

    def test_no_entity_falls_back_to_location(self) -> None:
        err = logic.ConfigError(
            location="(file)",
            entity_id=None,
            reason="read failed",
        )
        assert handler._format_config_error(err) == "`(file)`: read failed"

    def test_entity_with_device_link(self) -> None:
        err = logic.ConfigError(
            location="routes[0].clients[2]",
            entity_id="binary_sensor.window_front_left",
            device_id="abc123",
            reason=(
                "Device does not support routing: "
                "configured to use Z-Wave Long Range (vs Mesh)"
            ),
        )
        assert handler._format_config_error(err) == (
            "[`binary_sensor.window_front_left`]"
            "(/config/devices/device/abc123) "
            "(`routes[0].clients[2]`): "
            "Device does not support routing: "
            "configured to use Z-Wave Long Range (vs Mesh)"
        )

    def test_entity_without_device_id_unlinked(self) -> None:
        # "Entity not found" errors carry an entity_id but no
        # DeviceResolution, so device_id is None. The bullet
        # renders entity_id as plain backticked text -- the
        # entity isn't in HA so a device-page link wouldn't
        # resolve.
        err = logic.ConfigError(
            location="routes[1].clients[0]",
            entity_id="lock.missing",
            reason="entity not found",
        )
        bullet = handler._format_config_error(err)
        expected = "`lock.missing` (`routes[1].clients[0]`): entity not found"
        assert bullet == expected
        assert "/config/devices/device/" not in bullet


class TestConfigErrorNotification:
    """End-to-end: ZRM bullets -> ``make_config_error_notification``.

    Exercises the integration of ``_format_config_error`` with the
    shared helpers.make_config_error_notification builder that
    ``emit_config_error`` (and thus ``_emit_config_error`` on the
    handler) ultimately dispatches.
    """

    def _build(
        self,
        errors: list[logic.ConfigError],
        instance_id: str = "automation.zrm_test",
    ) -> PersistentNotification:
        bullets = [handler._format_config_error(e) for e in errors]
        return make_config_error_notification(
            service=handler._SERVICE,
            instance_id=instance_id,
            errors=bullets,
            errors_are_markdown=True,
        )

    def test_inactive_when_no_errors(self) -> None:
        notif = self._build([])
        assert notif.active is False
        assert notif.message == ""

    def test_title_is_bare_category(self) -> None:
        # The dispatcher prepends ``<friendly_name>: `` so
        # the spec carries only the category descriptor.
        notif = self._build(
            [
                logic.ConfigError(
                    location="routes[0]", entity_id=None, reason="x"
                )
            ],
            instance_id="automation.zrm_test",
        )
        assert notif.title == "Config Error"

    def test_multiple_errors_all_listed(self) -> None:
        errors = [
            logic.ConfigError(
                location=f"routes[0].clients[{i}]",
                entity_id=f"binary_sensor.lr{i}",
                device_id=f"dev{i}",
                reason=(
                    "Device does not support routing:"
                    " configured to use Z-Wave Long Range (vs Mesh)"
                ),
            )
            for i in range(3)
        ]
        notif = self._build(errors)
        for i in range(3):
            assert (
                f"- [`binary_sensor.lr{i}`](/config/devices/device/dev{i}) "
                f"(`routes[0].clients[{i}]`): Device does not support routing:"
                " configured to use Z-Wave Long Range (vs Mesh)"
            ) in notif.message
        assert notif.message.count("- ") == 3

    def test_missing_entity_and_reason_are_escaped_once(self) -> None:
        notif = self._build(
            [
                logic.ConfigError(
                    location="routes[0].clients[0]",
                    entity_id="binary_sensor.main_bath_window",
                    reason=r"invalid [value] at C:\config",
                ),
            ],
        )
        assert notif.message == (
            "- `binary_sensor.main_bath_window` (`routes[0].clients[0]`): "
            r"invalid \[value\] at C:\\config"
        )

    @pytest.mark.parametrize("device_id", [None, "dev0"])
    def test_rendered_markdown_preserves_code_and_links(
        self, device_id: str | None
    ) -> None:
        notif = self._build(
            [
                logic.ConfigError(
                    location="routes[0].clients[0]",
                    entity_id="binary_sensor.window",
                    device_id=device_id,
                    reason="invalid [value]",
                ),
            ],
        )
        entity_html = "<code>binary_sensor.window</code>"
        if device_id:
            entity_html = (
                f'<a href="/config/devices/device/dev0">{entity_html}</a>'
            )
        assert MarkdownIt().render(notif.message) == (
            f"<ul>\n<li>{entity_html} "
            "(<code>routes[0].clients[0]</code>): invalid [value]</li>\n"
            "</ul>\n"
        )


class _ReconcileHass:
    async def async_add_executor_job[**P, T](
        self, target: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        return target(*args, **kwargs)


@pytest.mark.parametrize(
    ("config_text", "expected_message"),
    [
        (
            "routes:\n  - []\n",
            "- `routes[0]`: route entry must be a mapping; got list",
        ),
        (
            (
                "routes:\n  - repeater: switch.repeater\n"
                "    clients: [binary_sensor.main_bath_window]\n"
            ),
            (
                "- `binary_sensor.main_bath_window` (`routes[0].clients[0]`): "
                "entity not found, is disabled, or is not on a Z-Wave device"
            ),
        ),
    ],
)
async def test_reconcile_config_error_markdown(
    config_text: str, expected_message: str
) -> None:
    hass = _ReconcileHass()
    state = _make_state()
    repeater = logic.DeviceResolution(
        entity_id="switch.repeater",
        device_id="repeater",
        node_id=bridge.NodeID(2),
        is_routing=True,
        is_listening=True,
        is_frequent_listening=False,
        failed=False,
        is_long_range=False,
        max_data_rate_bps=100000,
    )
    with (
        patch.object(
            handler, "_read_config_mtime", autospec=True, return_value=1.0
        ),
        patch.object(
            handler,
            "_read_config_text",
            autospec=True,
            return_value=(config_text, None),
        ),
        patch.object(
            handler,
            "automation_friendly_name",
            autospec=True,
            return_value="Route Manager",
        ),
        patch.object(
            handler,
            "_bridge_get_nodes",
            autospec=True,
            return_value=handler._GetNodesResult(
                api_result=bridge.ApiResult(
                    success=True,
                    message="",
                    api_echo=bridge.API_GET_NODES,
                    result=None,
                ),
                nodes=[],
                error="",
            ),
        ),
        patch.object(
            handler,
            "_build_entity_to_resolution",
            autospec=True,
            return_value=({"switch.repeater": repeater}, repeater),
        ),
        patch.object(handler, "_persist_diagnostic", autospec=True),
        patch.object(
            handler, "_dispatch_terminal_notifications", autospec=True
        ) as dispatch,
    ):
        await handler._do_reconcile(
            hass,  # type: ignore[arg-type]
            state,
            now=FrozenNow.value,
            trigger_id="manual",
            config_file_path="/config/routes.yaml",
            host="localhost",
            port=3000,
            token="",
            clear_unmanaged_routes=False,
            reconcile_interval_minutes=5,
            pending_timeout_hours=24,
            default_route_speed=None,
            max_notifications=10,
            debug_logging=False,
        )
        dispatch.assert_awaited_once_with(
            hass,
            [
                PersistentNotification(
                    active=True,
                    notification_id=(
                        "blueprint_toolkit_zwave_route_manager__"
                        "automation.zrm_test__config_error"
                    ),
                    title="Config Error",
                    message=expected_message,
                    instance_id="automation.zrm_test",
                ),
            ],
            "blueprint_toolkit_zwave_route_manager__automation.zrm_test__",
        )


def _make_action(
    *,
    kind: logic.RouteActionKind = logic.RouteActionKind.SET_APPLICATION_ROUTE,
    node_id: int = 42,
    repeaters: list[int] | None = None,
    client_entity_id: str = "lock.x",
) -> logic.RouteAction:
    return logic.RouteAction(
        kind=kind,
        node_id=node_id,
        repeaters=list(repeaters or []),
        route_speed=None,
        client_entity_id=client_entity_id,
    )


def _make_api_result(message: str) -> bridge.ApiResult:
    return bridge.ApiResult(
        success=False,
        message=message,
        api_echo=None,
        result=None,
    )


class TestApiNotification:
    def test_title_plain(self) -> None:
        notif = handler._api_notification(
            "zrm__", "automation.zrm", "connection refused"
        )
        assert notif.title == "API unavailable"

    def test_brackets_escaped(self) -> None:
        notif = handler._api_notification(
            "zrm__", "automation.zrm", "bad response: [foo]"
        )
        assert "bad response: \\[foo\\]" in notif.message
        assert "bad response: [foo]" not in notif.message

    def test_inactive_when_error_empty(self) -> None:
        # Empty error string yields an inactive notification --
        # ``api_unavailable`` notifications are dismissed by
        # passing through an empty error rather than building
        # a separate dismiss spec.
        notif = handler._api_notification("zrm__", "automation.zrm", "")
        assert notif.active is False


class TestApplyNotification:
    def test_title_includes_node_id(self) -> None:
        notif = handler._apply_notification(
            "zrm__",
            "automation.zrm",
            _make_action(node_id=42),
            _make_api_result("timeout"),
        )
        assert notif.title == "Apply failed for node 42"

    def test_server_response_brackets_escaped(self) -> None:
        notif = handler._apply_notification(
            "zrm__",
            "automation.zrm",
            _make_action(),
            _make_api_result("ack [partial]"),
        )
        assert "Server response: ack \\[partial\\]" in notif.message
        assert "Server response: ack [partial]" not in notif.message

    def test_id_keyed_to_node(self) -> None:
        notif = handler._apply_notification(
            "zrm__",
            "automation.zrm",
            _make_action(node_id=17),
            _make_api_result("oops"),
        )
        assert notif.notification_id == "zrm__apply_17"


class TestTimeoutNotification:
    """Per-attempt timeout-id stability + body content."""

    def test_id_per_attempt(self) -> None:
        from datetime import UTC
        from datetime import datetime as _datetime

        old_ts = _datetime(2026, 4, 22, 1, 23, 45, tzinfo=UTC)
        notif = handler._timeout_notification(
            "zwm__",
            "automation.zrm",
            42,
            logic.RouteType.PRIORITY_APP,
            old_ts,
            3,
            24,
        )
        assert "timeout_42_priority_app" in notif.notification_id
        assert "2026-04-22T01_23_45" in notif.notification_id
        # User-facing message names the route type, the retry
        # count, and the way to stop further retries.
        assert "priority_app" in notif.message
        assert "timeout #3" in notif.message
        assert "Remove the device from the YAML config" in notif.message


class TestCircuitBreakerNotification:
    def test_resume_time_is_in_ha_time_zone(
        self,
        monkeypatch: pytest.MonkeyPatch,
        system_time_zone: Callable[[str], None],
    ) -> None:
        from datetime import UTC
        from datetime import datetime as _datetime
        from zoneinfo import ZoneInfo

        # The process and HA disagree, so only HA's zone gives 17:30.
        system_time_zone("UTC")
        monkeypatch.setattr(
            handler.dt_util,
            "as_local",
            lambda when: when.astimezone(ZoneInfo("Asia/Kolkata")),
            raising=False,
        )
        now = _datetime(2026, 4, 22, 11, 30, tzinfo=UTC)

        notif = handler._circuit_breaker_notification(
            "zwm__",
            "automation.zrm",
            now,
            now + timedelta(minutes=30),
            3,
        )

        assert "retry after 30 minutes (at 17:30)" in notif.message


# --------------------------------------------------------
# Schema vs blueprint drift
# --------------------------------------------------------


class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
    """The blueprint's ``data:`` keys must match the schema."""

    handler = handler
    blueprint_filename = "zwave_route_manager.yaml"


class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
    """Blueprint input defaults must satisfy the schema."""

    handler = handler
    blueprint_filename = "zwave_route_manager.yaml"
    template_defaults: ClassVar = {
        "instance_id": "automation.zrm_default_check",
        "trigger_id": "manual",
    }


class TestArgparseGuards(HandlerArgparseGuardsBase):
    """Schema rejection must short-circuit argparse.

    ZRM has no ``notification_service`` field, so the
    unregistered-notify guard test from the base skips.
    """

    handler = handler


if __name__ == "__main__":
    from conftest import run_tests

    # ``-p no:homeassistant`` disables pytest-HACC's plugin,
    # which fails to import against this file's stubbed
    # ``homeassistant`` modules; HACC is a mypy-only dep here.
    run_tests(
        __file__,
        _SCRIPT_PATH,
        REPO_ROOT,
        pytest_args=["-p", "no:homeassistant"],
    )
