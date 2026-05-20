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
"""Tests for device_watchdog module."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from custom_components.blueprint_toolkit.device_watchdog.logic import (  # noqa: E402, E501
    CHECK_ALL,
    CHECK_DEVICE_UPDATES,
    CHECK_DISABLED_DIAGNOSTICS,
    CHECK_UNAVAILABLE_ENTITIES,
    Config,
    DeviceEntry,
    DeviceInfo,
    DirectiveInputs,
    DisabledDiagnosticsRepair,
    EntityInfo,
    FixServices,
    RegistryEntry,
    _build_notification_message,
    _check_staleness,
    _evaluate_device,
    _filter_entities,
    _validate_dw_directives,
    check_disabled_diagnostics,
    evaluate_devices,
    evaluate_diagnostics,
    run_evaluation,
)
from custom_components.blueprint_toolkit.helpers import (  # noqa: E402
    FixService,
    PersistentNotification,
    repair_notification_id,
    validate_and_join_regex_patterns,
)

T0 = datetime(2024, 1, 15, 12, 0, 0)


# -- Helpers -----------------------------------------


def _config(**overrides: object) -> Config:
    defaults: dict[str, object] = {
        "exclude_device_name_regex": "",
        "exclude_entity_id_regex": "",
        "monitored_entity_domains": [],
        "dead_threshold_seconds": 86400,
        "enabled_checks": CHECK_ALL,
        "notification_prefix": "device_watchdog_test__",
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


_UNSET: datetime = datetime(1970, 1, 1)


def _entity(
    entity_id: str = "sensor.test",
    state: str = "42.0",
    last_reported: datetime | None = _UNSET,
) -> EntityInfo:
    return EntityInfo(
        entity_id=entity_id,
        state=state,
        last_reported=T0 if last_reported is _UNSET else last_reported,
    )


def _device(
    device_id: str = "dev1",
    device_name: str = "Test Device",
    entities: list[EntityInfo] | None = None,
) -> DeviceInfo:
    return DeviceInfo(
        de=DeviceEntry(
            id=device_id,
            name=device_name,
            default_name=device_name,
        ),
        entities=entities or [],
    )


# -- Tests -------------------------------------------


class TestFilterEntities:
    def test_no_filters_keeps_all(self) -> None:
        cfg = _config()
        entities = [_entity("sensor.a"), _entity("sensor.b")]
        kept, filtered = _filter_entities(cfg, entities)
        assert len(kept) == 2
        assert len(filtered) == 0

    def test_domain_filter(self) -> None:
        cfg = _config(
            monitored_entity_domains=["sensor"],
        )
        entities = [
            _entity("sensor.temp"),
            _entity("binary_sensor.door"),
            _entity("switch.light"),
        ]
        kept, filtered = _filter_entities(cfg, entities)
        assert len(kept) == 1
        assert kept[0].entity_id == "sensor.temp"
        assert len(filtered) == 2

    def test_exclude_entity_id_regex(self) -> None:
        cfg = _config(exclude_entity_id_regex="battery")
        entities = [
            _entity("sensor.temp"),
            _entity("sensor.battery_level"),
        ]
        kept, filtered = _filter_entities(cfg, entities)
        assert len(kept) == 1
        assert kept[0].entity_id == "sensor.temp"

    def test_domain_and_exclude_combined(self) -> None:
        cfg = _config(
            monitored_entity_domains=["sensor"],
            exclude_entity_id_regex="battery",
        )
        entities = [
            _entity("sensor.temp"),
            _entity("sensor.battery"),
            _entity("binary_sensor.door"),
        ]
        kept, filtered = _filter_entities(cfg, entities)
        assert len(kept) == 1
        assert kept[0].entity_id == "sensor.temp"
        assert len(filtered) == 2

    def test_empty_entity_list(self) -> None:
        cfg = _config()
        kept, filtered = _filter_entities(cfg, [])
        assert kept == []
        assert filtered == []

    def test_entity_without_dot(self) -> None:
        cfg = _config(monitored_entity_domains=["sensor"])
        entities = [_entity("nodot")]
        kept, filtered = _filter_entities(cfg, entities)
        assert len(kept) == 0
        assert len(filtered) == 1


class TestCheckStaleness:
    def test_no_entities_not_stale(self) -> None:
        is_stale, eid, ts = _check_staleness([], 3600, T0)
        assert is_stale is False
        assert eid is None
        assert ts is None

    def test_recent_entity_not_stale(self) -> None:
        entities = [
            _entity(last_reported=T0 - timedelta(minutes=5)),
        ]
        is_stale, _, _ = _check_staleness(
            entities,
            3600,
            T0,
        )
        assert is_stale is False

    def test_old_entity_is_stale(self) -> None:
        entities = [
            _entity(last_reported=T0 - timedelta(hours=25)),
        ]
        is_stale, _, _ = _check_staleness(
            entities,
            86400,
            T0,
        )
        assert is_stale is True

    def test_returns_newest_entity(self) -> None:
        entities = [
            _entity(
                "sensor.old",
                last_reported=T0 - timedelta(hours=2),
            ),
            _entity(
                "sensor.new",
                last_reported=T0 - timedelta(minutes=5),
            ),
        ]
        _, newest_eid, newest_ts = _check_staleness(
            entities,
            86400,
            T0,
        )
        assert newest_eid == "sensor.new"
        assert newest_ts == T0 - timedelta(minutes=5)

    def test_exact_threshold_not_stale(self) -> None:
        entities = [
            _entity(last_reported=T0 - timedelta(seconds=3600)),
        ]
        is_stale, _, _ = _check_staleness(
            entities,
            3600,
            T0,
        )
        assert is_stale is False

    def test_one_second_over_is_stale(self) -> None:
        entities = [
            _entity(last_reported=T0 - timedelta(seconds=3601)),
        ]
        is_stale, _, _ = _check_staleness(
            entities,
            3600,
            T0,
        )
        assert is_stale is True

    def test_mixed_unavailable_and_fresh(self) -> None:
        entities = [
            _entity(
                "sensor.bad",
                state="unavailable",
                last_reported=T0 - timedelta(hours=25),
            ),
            _entity(
                "sensor.good",
                state="42.0",
                last_reported=T0 - timedelta(minutes=5),
            ),
        ]
        is_stale, newest_eid, _ = _check_staleness(
            entities,
            86400,
            T0,
        )
        assert is_stale is False
        assert newest_eid == "sensor.good"

    def test_all_none_timestamps_indeterminate(self) -> None:
        entities = [
            _entity("sensor.a", last_reported=None),
            _entity("sensor.b", last_reported=None),
        ]
        is_stale, eid, ts = _check_staleness(entities, 3600, T0)
        assert is_stale is False
        assert eid is None
        assert ts is None

    def test_mixed_none_and_timestamped(self) -> None:
        entities = [
            _entity("sensor.missing", last_reported=None),
            _entity(
                "sensor.fresh",
                last_reported=T0 - timedelta(minutes=5),
            ),
        ]
        is_stale, newest_eid, newest_ts = _check_staleness(
            entities,
            3600,
            T0,
        )
        assert is_stale is False
        assert newest_eid == "sensor.fresh"
        assert newest_ts == T0 - timedelta(minutes=5)


class TestEvaluateDevice:
    def test_healthy_device(self) -> None:
        cfg = _config()
        device = _device(
            entities=[
                _entity(
                    state="42.0",
                    last_reported=T0 - timedelta(minutes=5),
                ),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is False
        assert result.notification_message == ""

    def test_unavailable_entity(self) -> None:
        cfg = _config()
        device = _device(
            entities=[
                _entity(
                    "sensor.temp",
                    state="unavailable",
                    last_reported=T0 - timedelta(minutes=5),
                ),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is True
        assert "sensor.temp" in result.unavailable_entities
        assert "Unavailable" in result.notification_message

    def test_unknown_entity(self) -> None:
        cfg = _config()
        device = _device(
            entities=[
                _entity(
                    state="unknown",
                    last_reported=T0 - timedelta(minutes=5),
                ),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is True

    def test_stale_device(self) -> None:
        cfg = _config(dead_threshold_seconds=3600)
        device = _device(
            entities=[
                _entity(
                    state="42.0",
                    last_reported=T0 - timedelta(hours=2),
                ),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is True
        assert result.is_stale is True

    def test_excluded_device(self) -> None:
        cfg = _config(exclude_device_name_regex="Test")
        device = _device(
            device_name="Test Device",
            entities=[
                _entity(state="unavailable"),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is False
        assert result.device_excluded is True
        assert result.entities_evaluated == 0
        assert result.entities_filtered == 0

    def test_notification_id_format(self) -> None:
        cfg = _config()
        device = _device(device_id="abc123")
        result = _evaluate_device(cfg, device, T0)
        assert result.notification_id == ("device_watchdog_test__device_abc123")

    def test_notification_title(self) -> None:
        cfg = _config()
        device = _device(
            device_name="Kitchen Sensor",
            entities=[_entity(state="unavailable")],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.notification_title == "Kitchen Sensor"

    def test_no_entities_not_stale(self) -> None:
        cfg = _config()
        device = _device(entities=[])
        result = _evaluate_device(cfg, device, T0)
        assert result.has_issue is False
        assert result.is_stale is False

    def test_entity_counts(self) -> None:
        cfg = _config(
            monitored_entity_domains=["sensor"],
        )
        device = _device(
            entities=[
                _entity("sensor.a"),
                _entity("binary_sensor.b"),
                _entity("sensor.c"),
            ],
        )
        result = _evaluate_device(cfg, device, T0)
        assert result.entities_evaluated == 2
        assert result.entities_filtered == 1


class TestEnabledChecks:
    """Per-check gating via Config.enabled_checks."""

    def _unavailable_and_stale(self) -> DeviceInfo:
        return _device(
            entities=[
                _entity(
                    "sensor.temp",
                    state="unavailable",
                    last_reported=T0 - timedelta(hours=25),
                ),
            ],
        )

    def test_unavailable_only_flags_unavailable(self) -> None:
        cfg = _config(
            enabled_checks=frozenset({CHECK_UNAVAILABLE_ENTITIES}),
        )
        result = _evaluate_device(
            cfg,
            self._unavailable_and_stale(),
            T0,
        )
        assert result.has_issue is True
        assert "sensor.temp" in result.unavailable_entities
        assert result.is_stale is False
        assert result.newest_entity is None

    def test_staleness_only_flags_stale(self) -> None:
        cfg = _config(
            enabled_checks=frozenset({CHECK_DEVICE_UPDATES}),
        )
        result = _evaluate_device(
            cfg,
            self._unavailable_and_stale(),
            T0,
        )
        assert result.has_issue is True
        assert result.unavailable_entities == []
        assert result.is_stale is True

    def test_neither_yields_no_issue(self) -> None:
        cfg = _config(enabled_checks=frozenset())
        result = _evaluate_device(
            cfg,
            self._unavailable_and_stale(),
            T0,
        )
        assert result.has_issue is False
        assert result.unavailable_entities == []
        assert result.is_stale is False

    def test_diagnostics_only_skips_device_health(self) -> None:
        cfg = _config(
            enabled_checks=frozenset({CHECK_DISABLED_DIAGNOSTICS}),
        )
        result = _evaluate_device(
            cfg,
            self._unavailable_and_stale(),
            T0,
        )
        assert result.has_issue is False


class TestRunEvaluationDiagnosticsGate:
    """run_evaluation reads diagnostics toggle from Config."""

    def _diag_device(self) -> DeviceInfo:
        return DeviceInfo(
            de=DeviceEntry(
                id="d1",
                name="Lock",
                default_name="Lock",
                integration_entities={"zwave_js": set()},
            ),
            registry_entries=[
                RegistryEntry(
                    entity_id="sensor.last_seen",
                    original_name="Last seen",
                    platform="zwave_js",
                    entity_category="diagnostic",
                    disabled=True,
                ),
            ],
        )

    def test_diagnostics_enabled_emits_diag_notification(
        self,
    ) -> None:
        cfg = _config(enabled_checks=CHECK_ALL)
        ev = run_evaluation(
            cfg,
            [self._diag_device()],
            T0,
            all_integrations=["foo"],
            max_notifications=0,
        )
        diag_ids = [
            n.notification_id
            for n in ev.notifications
            if "__diag_" in n.notification_id
        ]
        assert diag_ids == ["device_watchdog_test__diag_d1"]

    def test_diagnostics_disabled_skips_diag_notifications(
        self,
    ) -> None:
        cfg = _config(
            enabled_checks=frozenset(
                {CHECK_UNAVAILABLE_ENTITIES, CHECK_DEVICE_UPDATES},
            ),
        )
        ev = run_evaluation(
            cfg,
            [self._diag_device()],
            T0,
            all_integrations=["foo"],
            max_notifications=0,
        )
        diag_ids = [
            n.notification_id
            for n in ev.notifications
            if "__diag_" in n.notification_id
        ]
        assert diag_ids == []


class TestBuildNotificationMessage:
    def test_unavailable_entities_listed(self) -> None:
        device = _device(device_name="My Device")
        unavailable = [
            _entity("sensor.temp", state="unavailable"),
            _entity("sensor.humid", state="unavailable"),
        ]
        msg = _build_notification_message(
            device,
            unavailable,
            False,
            None,
            None,
            _config(),
        )
        assert "sensor.temp" in msg
        assert "sensor.humid" in msg
        assert "Unavailable entity" in msg

    def test_stale_with_newest(self) -> None:
        device = _device()
        ts = T0 - timedelta(hours=25)
        msg = _build_notification_message(
            device,
            [],
            True,
            "sensor.old",
            ts,
            _config(),
        )
        assert "No entity state report" in msg
        assert "sensor.old" in msg
        assert ts.isoformat() in msg

    def test_stale_no_prior_updates(self) -> None:
        device = _device()
        msg = _build_notification_message(
            device,
            [],
            True,
            None,
            None,
            _config(),
        )
        assert "No prior updates detected" in msg

    def test_device_url_in_message(self) -> None:
        device = _device(device_id="abc")
        msg = _build_notification_message(
            device,
            [_entity(state="unavailable")],
            False,
            None,
            None,
            _config(),
        )
        assert "/config/devices/device/abc" in msg

    def test_raises_on_no_issues(self) -> None:
        """Calling with no unavailable and not stale is a bug."""
        device = _device()
        with pytest.raises(ValueError, match="unavailable or stale"):
            _build_notification_message(
                device,
                [],
                False,
                None,
                None,
                _config(),
            )

    def test_unavailable_body_keeps_device_header_with_blank_line(
        self,
    ) -> None:
        device = _device(device_id="abc", device_name="My Device")
        msg = _build_notification_message(
            device,
            [_entity("sensor.temp", state="unavailable")],
            False,
            None,
            None,
            _config(),
        )
        body_lines = msg.split("\n")
        assert body_lines[0] == (
            "Device: [My Device](/config/devices/device/abc)"
        )
        assert body_lines[1] == ""
        # Body content (Integrations: ..., Unavailable
        # entity: ...) follows after the blank-line.
        assert any(
            line.startswith("Unavailable entity") for line in body_lines[2:]
        )

    def test_device_name_with_brackets_is_escaped(self) -> None:
        # A literal "[" in a device name would otherwise
        # form a bogus markdown link with a later "](" in
        # the same body line.
        device = _device(device_name="Sensor [foo]")
        msg = _build_notification_message(
            device,
            [_entity(state="unavailable")],
            False,
            None,
            None,
            _config(),
        )
        assert "[Sensor \\[foo\\]]" in msg
        assert "[Sensor [foo]]" not in msg

    def test_integration_names_are_escaped(self) -> None:
        # Defense-in-depth: integration IDs are slug-style
        # under HA's current charset, but the notification
        # body interpolates them as bare prose -- escape so
        # a future HA release loosening the charset (or a
        # third-party integration smuggling in markdown
        # specials) can't corrupt the rendered body.
        device = _device()
        device.de.integration_entities["foo[bar]"] = {"sensor.x"}
        msg = _build_notification_message(
            device,
            [_entity(state="unavailable")],
            False,
            None,
            None,
            _config(),
        )
        assert "Integrations: foo\\[bar\\]" in msg

    def test_unavailable_entity_id_is_escaped(self) -> None:
        device = _device()
        unavailable = [_entity("sensor.[foo]", state="unavailable")]
        msg = _build_notification_message(
            device,
            unavailable,
            False,
            None,
            None,
            _config(),
        )
        assert "Unavailable entity: sensor.\\[foo\\]" in msg

    def test_newest_entity_is_escaped_in_stale_message(self) -> None:
        device = _device()
        ts = T0 - timedelta(hours=25)
        msg = _build_notification_message(
            device,
            [],
            True,
            "sensor.[old]",
            ts,
            _config(),
        )
        assert "via sensor.\\[old\\]." in msg


class TestEvaluateDevices:
    def test_multiple_devices(self) -> None:
        cfg = _config()
        devices = [
            _device(
                "healthy",
                "Healthy",
                [_entity(last_reported=T0)],
            ),
            _device(
                "sick",
                "Sick",
                [_entity(state="unavailable")],
            ),
        ]
        results = evaluate_devices(cfg, devices, T0)
        assert len(results) == 2
        healthy = [r for r in results if not r.has_issue]
        sick = [r for r in results if r.has_issue]
        assert len(healthy) == 1
        assert len(sick) == 1
        assert healthy[0].device_id == "healthy"
        assert sick[0].device_id == "sick"

    def test_empty_device_list(self) -> None:
        cfg = _config()
        results = evaluate_devices(cfg, [], T0)
        assert results == []

    def test_all_healthy(self) -> None:
        cfg = _config()
        devices = [
            _device(
                "d1",
                "D1",
                [_entity(last_reported=T0)],
            ),
            _device(
                "d2",
                "D2",
                [_entity(last_reported=T0)],
            ),
        ]
        results = evaluate_devices(cfg, devices, T0)
        assert all(not r.has_issue for r in results)

    def test_all_unhealthy(self) -> None:
        cfg = _config(dead_threshold_seconds=60)
        old = T0 - timedelta(hours=1)
        devices = [
            _device(
                "d1",
                "D1",
                [_entity(last_reported=old)],
            ),
            _device(
                "d2",
                "D2",
                [_entity(last_reported=old)],
            ),
        ]
        results = evaluate_devices(cfg, devices, T0)
        assert all(r.has_issue for r in results)


def _reg_entry(
    entity_id: str = "sensor.test",
    original_name: str = "Test",
    platform: str = "zwave_js",
    entity_category: str | None = "diagnostic",
    disabled: bool = False,
) -> RegistryEntry:
    return RegistryEntry(
        entity_id=entity_id,
        original_name=original_name,
        platform=platform,
        entity_category=entity_category,
        disabled=disabled,
    )


class TestCheckDisabledDiagnostics:
    def test_disabled_entity_flagged(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert [d.original_name for d in result] == ["Last seen"]

    def test_enabled_entity_not_flagged(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                disabled=False,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert result == []

    def test_missing_entity_skipped(self) -> None:
        result = check_disabled_diagnostics(
            "zwave_js",
            [],
        )
        assert result == []

    def test_non_diagnostic_ignored(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                entity_category=None,
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert result == []

    def test_wrong_platform_ignored(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                platform="matter",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert result == []

    def test_unknown_integration_returns_empty(
        self,
    ) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                platform="unknown",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "unknown",
            entries,
        )
        assert result == []

    def test_multiple_disabled(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                disabled=True,
            ),
            _reg_entry(
                original_name="Node status",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert [d.original_name for d in result] == ["Last seen", "Node status"]

    def test_partial_disabled(self) -> None:
        entries = [
            _reg_entry(
                original_name="Last seen",
                disabled=False,
            ),
            _reg_entry(
                original_name="Node status",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert [d.original_name for d in result] == ["Node status"]

    def test_unifiprotect_disabled_flagged(self) -> None:
        entries = [
            _reg_entry(
                original_name="Wi-Fi signal strength",
                platform="unifiprotect",
                disabled=True,
            ),
            _reg_entry(
                original_name="Uptime",
                platform="unifiprotect",
                disabled=False,
            ),
        ]
        result = check_disabled_diagnostics(
            "unifiprotect",
            entries,
        )
        assert [d.original_name for d in result] == ["Wi-Fi signal strength"]

    def test_zwave_js_signal_strength_flagged(self) -> None:
        entries = [
            _reg_entry(
                original_name="Signal strength",
                platform="zwave_js",
                disabled=True,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert [d.original_name for d in result] == ["Signal strength"]

    def test_zwave_js_signal_strength_clean(self) -> None:
        entries = [
            _reg_entry(
                original_name="Signal strength",
                platform="zwave_js",
                disabled=False,
            ),
        ]
        result = check_disabled_diagnostics(
            "zwave_js",
            entries,
        )
        assert result == []

    def test_per_platform_isolation(self) -> None:
        # bthome: "Signal strength" IS in the platform list,
        # so a disabled match flags.
        bthome = _reg_entry(
            original_name="Signal strength",
            platform="bthome",
            disabled=True,
        )
        assert [
            d.original_name
            for d in check_disabled_diagnostics("bthome", [bthome])
        ] == ["Signal strength"]

        # shelly: "Signal strength" is NOT in shelly's list
        # ("RSSI" is). Disabled match must NOT flag, even
        # though the same string flags on bthome / zwave_js.
        # Locks down per-platform scoping after the shared
        # string was added to multiple lists.
        shelly = _reg_entry(
            original_name="Signal strength",
            platform="shelly",
            disabled=True,
        )
        assert check_disabled_diagnostics("shelly", [shelly]) == []


class TestEvaluateDiagnostics:
    def _diag_device(
        self,
        device_id: str = "dev1",
        device_name: str = "Lock",
        integrations: list[str] | None = None,
        registry_entries: list[RegistryEntry] | None = None,
    ) -> DeviceInfo:
        ints = integrations or ["zwave_js"]
        ie: dict[str, set[str]] = {i: set() for i in ints}
        return DeviceInfo(
            de=DeviceEntry(
                id=device_id,
                name=device_name,
                default_name=device_name,
                integration_entities=ie,
            ),
            registry_entries=registry_entries or [],
        )

    def test_device_with_disabled_generates_active(
        self,
    ) -> None:
        device = self._diag_device(
            device_name="Front Door Lock",
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert len(results) == 1
        assert results[0].active is True
        assert "Last seen" in results[0].message
        assert "Front Door Lock" in results[0].title

    def test_zwave_js_signal_strength_end_to_end(
        self,
    ) -> None:
        device = self._diag_device(
            device_name="Front Door Lock",
            registry_entries=[
                _reg_entry(
                    original_name="Signal strength",
                    platform="zwave_js",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert len(results) == 1
        assert results[0].active is True
        assert "Signal strength" in results[0].message
        assert "Front Door Lock" in results[0].title

    def test_disabled_diagnostics_body_includes_device_header(
        self,
    ) -> None:
        device = self._diag_device(
            device_id="abc",
            device_name="Front Door Lock",
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        body_lines = results[0].message.split("\n")
        assert body_lines[0] == (
            "Device: [Front Door Lock](/config/devices/device/abc)"
        )
        assert body_lines[1] == ""

    def test_disabled_diagnostics_body_drops_settings_link(
        self,
    ) -> None:
        device = self._diag_device(
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        body = results[0].message
        assert "Enable in [Settings > Devices]" not in body
        assert "for better health monitoring" not in body

    def test_disabled_diagnostics_title_drops_suffix(
        self,
    ) -> None:
        device = self._diag_device(
            device_name="Front Door Lock",
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert results[0].title == "Front Door Lock"

    def test_device_all_enabled_emits_nothing(
        self,
    ) -> None:
        # A device whose recommended diagnostics are all
        # enabled produces no spec; the dispatcher's prefix
        # sweep dismisses any prior-run notification / issue
        # for it. (Previously this emitted an explicit
        # inactive dismiss spec; the sweep makes that
        # redundant.)
        device = self._diag_device(
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=False,
                ),
            ],
        )
        results, repairs = evaluate_diagnostics(_config(), [device])
        assert results == []
        assert repairs == {}

    def test_notification_id_uses_device_id(
        self,
    ) -> None:
        device = self._diag_device(
            device_id="abc123",
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert results[0].notification_id == (
            "device_watchdog_test__diag_abc123"
        )

    def test_returns_persistent_notification(
        self,
    ) -> None:
        device = self._diag_device(
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert isinstance(
            results[0],
            PersistentNotification,
        )

    def test_skips_device_with_no_known_diagnostics(
        self,
    ) -> None:
        device = self._diag_device(
            integrations=["unknown_integration"],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert results == []

    def test_mixed_known_and_unknown_integrations(
        self,
    ) -> None:
        device = self._diag_device(
            integrations=[
                "unknown_integration",
                "zwave_js",
            ],
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(_config(), [device])
        assert len(results) == 1
        assert results[0].active is True


class TestEvaluateDiagnosticsRepairs:
    """evaluate_diagnostics with create_repairs=True.

    Asserts the repair surface: a single per-device repair-
    carrying spec, the matching off-wire payload keyed by
    notification_id, and the issue-ID format.
    """

    def _diag_device(
        self,
        device_id: str = "dev1",
        device_name: str = "Lock",
        registry_entries: list[RegistryEntry] | None = None,
    ) -> DeviceInfo:
        return DeviceInfo(
            de=DeviceEntry(
                id=device_id,
                name=device_name,
                default_name=device_name,
                integration_entities={"zwave_js": set()},
            ),
            registry_entries=registry_entries or [],
        )

    def _device_two_disabled(self) -> DeviceInfo:
        return self._diag_device(
            device_id="abc",
            device_name="Front Door Lock",
            registry_entries=[
                _reg_entry(
                    entity_id="sensor.last_seen",
                    original_name="Last seen",
                    disabled=True,
                ),
                _reg_entry(
                    entity_id="sensor.signal_strength",
                    original_name="Signal strength",
                    disabled=True,
                ),
            ],
        )

    def test_emits_single_repair_spec_per_device(self) -> None:
        results, _ = evaluate_diagnostics(
            _config(create_repairs=True),
            [self._device_two_disabled()],
        )
        assert len(results) == 1
        spec = results[0]
        assert isinstance(spec.repair_callback, FixService)
        assert spec.active is True

    def test_repair_spec_id_and_callback_match(self) -> None:
        cfg = _config(create_repairs=True)
        results, _ = evaluate_diagnostics(cfg, [self._device_two_disabled()])
        spec = results[0]
        expected_id = repair_notification_id(
            cfg.notification_prefix,
            FixServices.DEVICE_DISABLED_DIAGNOSTICS,
            "abc",
        )
        assert spec.notification_id == expected_id
        assert "__repair_" in spec.notification_id
        assert spec.notification_id.endswith("__abc")
        assert spec.repair_callback is not None
        assert spec.repair_callback.notification_id == expected_id
        assert spec.repair_callback.service_name == (
            FixServices.DEVICE_DISABLED_DIAGNOSTICS.value
        )

    def test_translation_placeholders_name_device_and_count(
        self,
    ) -> None:
        results, _ = evaluate_diagnostics(
            _config(create_repairs=True),
            [self._device_two_disabled()],
        )
        spec = results[0]
        assert spec.translation_key == "dw_device_disabled_diagnostics"
        assert spec.translation_placeholders == {
            "device_name": "Front Door Lock",
            "count": "2",
        }

    def test_payload_captures_flagged_entity_set(self) -> None:
        cfg = _config(create_repairs=True)
        results, repairs = evaluate_diagnostics(
            cfg,
            [self._device_two_disabled()],
        )
        nid = results[0].notification_id
        assert set(repairs) == {nid}
        payload = repairs[nid]
        assert isinstance(payload, DisabledDiagnosticsRepair)
        assert payload.device_id == "abc"
        assert set(payload.entity_ids) == {
            "sensor.last_seen",
            "sensor.signal_strength",
        }

    def test_device_name_falls_back_to_id(self) -> None:
        device = self._diag_device(
            device_id="abc",
            device_name="",
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=True,
                ),
            ],
        )
        results, _ = evaluate_diagnostics(
            _config(create_repairs=True),
            [device],
        )
        placeholders = results[0].translation_placeholders
        assert placeholders is not None
        assert placeholders["device_name"] == "abc"

    def test_no_disabled_emits_no_repair(self) -> None:
        device = self._diag_device(
            registry_entries=[
                _reg_entry(
                    original_name="Last seen",
                    disabled=False,
                ),
            ],
        )
        results, repairs = evaluate_diagnostics(
            _config(create_repairs=True),
            [device],
        )
        assert results == []
        assert repairs == {}


class TestNotificationPrefixIsolation:
    """Two configs with different prefixes produce disjoint IDs.

    The orphan sweep relies on this invariant: no notification
    from instance A should ever collide with one from instance B.
    """

    def _dev(self, device_id: str) -> DeviceInfo:
        ie: dict[str, set[str]] = {"zwave_js": set()}
        return DeviceInfo(
            de=DeviceEntry(
                id=device_id,
                name=device_id,
                default_name=device_id,
                integration_entities=ie,
            ),
            registry_entries=[
                RegistryEntry(
                    entity_id=f"sensor.{device_id}",
                    original_name="Last seen",
                    platform="zwave_js",
                    entity_category="diagnostic",
                    disabled=True,
                ),
            ],
        )

    def test_device_ids_include_prefix(self) -> None:
        cfg_a = _config(
            notification_prefix="device_watchdog_automation_a__",
        )
        cfg_b = _config(
            notification_prefix="device_watchdog_automation_b__",
        )
        dev = self._dev("shared_device")
        res_a = _evaluate_device(cfg_a, dev, T0)
        res_b = _evaluate_device(cfg_b, dev, T0)
        assert res_a.notification_id != res_b.notification_id
        assert res_a.notification_id.startswith(
            "device_watchdog_automation_a__"
        )
        assert res_b.notification_id.startswith(
            "device_watchdog_automation_b__"
        )

    def test_diag_ids_include_prefix(self) -> None:
        cfg_a = _config(
            notification_prefix="device_watchdog_automation_a__",
        )
        cfg_b = _config(
            notification_prefix="device_watchdog_automation_b__",
        )
        dev = self._dev("shared_device")
        ids_a = {
            n.notification_id for n in evaluate_diagnostics(cfg_a, [dev])[0]
        }
        ids_b = {
            n.notification_id for n in evaluate_diagnostics(cfg_b, [dev])[0]
        }
        assert ids_a.isdisjoint(ids_b)


class TestValidateDwDirectives:
    """Direct tests against ``_validate_dw_directives`` -- the
    handler builds candidate sets from the FULL registries
    (not the post-include/exclude-integration set), so the
    validator should report a regex as matched whenever its
    pattern matches ANYTHING in the candidate set the
    handler hands over, even if the actual exclusion code's
    integration-filter would have pruned the match.
    """

    @staticmethod
    def _di(
        *,
        entity_id_regex: str = "",
        device_name_regex: str = "",
        entity_id_candidates: frozenset[str] = frozenset(),
        device_name_candidates: frozenset[str] = frozenset(),
        include_integrations: list[str] | None = None,
        exclude_integrations: list[str] | None = None,
    ) -> DirectiveInputs:
        return DirectiveInputs(
            enabled=True,
            include_integrations=include_integrations or [],
            exclude_integrations=exclude_integrations or [],
            exclude_device_name_regex_lines=validate_and_join_regex_patterns(
                device_name_regex,
                "exclude_device_name_regex",
            ).lines,
            exclude_entity_id_regex_lines=validate_and_join_regex_patterns(
                entity_id_regex,
                "exclude_entity_id_regex",
            ).lines,
            device_name_candidates=device_name_candidates,
            entity_id_candidates=entity_id_candidates,
        )

    def test_entity_id_regex_matches_candidate_set(self) -> None:
        # Bug-fix coverage: a regex matching an entity in
        # the broad candidate set is NOT flagged unmatched
        # even if the entity belongs to an integration the
        # user excluded at the integration layer. The
        # handler is responsible for sourcing this set from
        # the FULL registries.
        di = self._di(
            entity_id_regex=(
                r"sensor\.clothes_.*_(total_time|remaining_time|delayed_start)"
            ),
            entity_id_candidates=frozenset(
                {
                    "sensor.clothes_dryer_total_time",
                    "sensor.clothes_washer_remaining_time",
                    "sensor.unrelated_temp",
                }
            ),
            exclude_integrations=["lg_thinq"],
        )
        out = _validate_dw_directives(
            di,
            all_integrations=["lg_thinq", "tplink"],
        )
        # No bullet for ``exclude_entity_id_regex`` -- the
        # regex matched two of the three candidates.
        assert not [u for u in out if u.field == "exclude_entity_id_regex"], out

    def test_entity_id_regex_unmatched_when_no_candidate_matches(
        self,
    ) -> None:
        di = self._di(
            entity_id_regex=r"^xyz_no_entity_matches$",
            entity_id_candidates=frozenset({"sensor.foo", "sensor.bar"}),
        )
        out = _validate_dw_directives(di, all_integrations=[])
        unmatched = [u for u in out if u.field == "exclude_entity_id_regex"]
        assert len(unmatched) == 1
        assert unmatched[0].value == r"^xyz_no_entity_matches$"

    def test_leading_space_regex_is_unmatched(self) -> None:
        # Bug-fix coverage: the helper preserves leading
        # whitespace verbatim, so a typo'd "  _audio_input_format$"
        # (leading space) compiles to a pattern requiring a
        # literal space before ``_audio_input_format``. No
        # entity_id contains a space, so the validator
        # correctly flags the line.
        di = self._di(
            entity_id_regex=" _audio_input_format$",
            entity_id_candidates=frozenset(
                {
                    "sensor.kitchen_sonos_audio_input_format",
                    "sensor.living_room_sonos_audio_input_format",
                }
            ),
        )
        out = _validate_dw_directives(di, all_integrations=[])
        unmatched = [u for u in out if u.field == "exclude_entity_id_regex"]
        assert len(unmatched) == 1
        assert unmatched[0].value == " _audio_input_format$"

    def test_device_name_regex_uses_candidate_set(self) -> None:
        di = self._di(
            device_name_regex=r"^Clothes (Washer|Dryer)$",
            device_name_candidates=frozenset(
                {"Clothes Washer", "Clothes Dryer", "Front Door Lock"}
            ),
        )
        out = _validate_dw_directives(di, all_integrations=[])
        assert not [u for u in out if u.field == "exclude_device_name_regex"], (
            out
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
