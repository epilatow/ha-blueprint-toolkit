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
"""Tests for entity_defaults_watchdog logic module."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit import helpers  # noqa: E402
from custom_components.blueprint_toolkit.entity_defaults_watchdog.logic import (  # noqa: E402, E501
    CHECK_ALL,
    DRIFT_CHECK_DEVICE_ENTITY_ID,
    DRIFT_CHECK_DEVICE_ENTITY_NAME,
    DRIFT_CHECK_SCRIPT_YAML_KEY,
    DRIFT_CHECK_VISIBLE_ALIASED_ENTITY,
    Config,
    DeviceEntityNameDriftRepair,
    DeviceEntry,
    DeviceInfo,
    DevicelessDriftDetail,
    DevicelessEntityInfo,
    DeviceResult,
    DirectiveInputs,
    DriftDetail,
    EdwRepair,
    EntityDriftInfo,
    EntityIdDriftRepair,
    FixServices,
    ScriptInfo,
    ScriptYamlKeyDriftFinding,
    ScriptYamlKeyDriftRepair,
    VisibleAliasedCandidate,
    VisibleAliasedEntityFinding,
    VisibleAliasedEntityRepair,
    _build_device_notification_message,
    _build_device_repair_specs,
    _build_deviceless_id_drift_repair_specs,
    _build_script_yaml_key_repair_specs,
    _build_visible_aliased_notification_message,
    _build_visible_aliased_repair_specs,
    _check_entity_drift,
    _check_id_enabled,
    _check_name_enabled,
    _compute_recommended_override,
    _evaluate_device,
    _evaluate_deviceless,
    _evaluate_script_yaml_key_drift,
    _evaluate_visible_aliased_entities,
    _is_excluded,
    _matches_with_collision_suffix,
    _validate_edw_directives,
    evaluate_devices,
    rename_top_level_yaml_key,
    run_evaluation,
)

# -- Helpers -----------------------------------------


def _config(**overrides: object) -> Config:
    defaults: dict[str, object] = {
        "drift_checks": CHECK_ALL,
        "exclude_device_name_regex": "",
        "exclude_entity_ids": [],
        "exclude_entity_id_regex": "",
        "exclude_entity_name_regex": "",
        "notification_prefix": "entity_defaults_watchdog_test__",
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def _entity_drift(
    entity_id: str = "sensor.test",
    has_entity_name: bool = True,
    has_name_override: bool = False,
    expected_entity_id: str | None = "sensor.test",
    current_name: str = "Test",
    expected_name: str | None = None,
) -> EntityDriftInfo:
    return EntityDriftInfo(
        entity_id=entity_id,
        has_entity_name=has_entity_name,
        has_name_override=has_name_override,
        expected_entity_id=expected_entity_id,
        current_name=current_name,
        expected_name=expected_name,
    )


def _device(
    device_id: str = "dev1",
    device_name: str = "Test Device",
    default_name: str = "Test Device",
    integrations: list[str] | None = None,
    entities: list[EntityDriftInfo] | None = None,
) -> DeviceInfo:
    ie: dict[str, set[str]] = {}
    for i in integrations or []:
        ie[i] = set()
    return DeviceInfo(
        de=DeviceEntry(
            id=device_id,
            name=device_name,
            default_name=default_name,
            integration_entities=ie,
        ),
        entities=entities or [],
    )


# -- Tests -------------------------------------------


class TestCheckEnabled:
    def test_check_all_enables_all(self) -> None:
        cfg = _config(drift_checks=CHECK_ALL)
        assert _check_id_enabled(cfg) is True
        assert _check_name_enabled(cfg) is True

    def test_id_only(self) -> None:
        cfg = _config(
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_ID}),
        )
        assert _check_id_enabled(cfg) is True
        assert _check_name_enabled(cfg) is False

    def test_name_only(self) -> None:
        cfg = _config(
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_NAME}),
        )
        assert _check_id_enabled(cfg) is False
        assert _check_name_enabled(cfg) is True

    def test_both_explicit(self) -> None:
        cfg = _config(
            drift_checks=frozenset(
                {
                    DRIFT_CHECK_DEVICE_ENTITY_ID,
                    DRIFT_CHECK_DEVICE_ENTITY_NAME,
                },
            ),
        )
        assert _check_id_enabled(cfg) is True
        assert _check_name_enabled(cfg) is True


class TestIsExcluded:
    def test_not_excluded(self) -> None:
        cfg = _config()
        assert _is_excluded(cfg, "sensor.temp", "Temp") is False

    def test_excluded_by_entity_id_list(self) -> None:
        cfg = _config(exclude_entity_ids=["sensor.temp"])
        assert _is_excluded(cfg, "sensor.temp", "Temp") is True

    def test_excluded_by_entity_id_regex(self) -> None:
        cfg = _config(exclude_entity_id_regex="battery")
        assert _is_excluded(cfg, "sensor.battery_level", "Battery") is True
        assert _is_excluded(cfg, "sensor.temp", "Temp") is False

    def test_excluded_by_entity_name_regex(self) -> None:
        cfg = _config(exclude_entity_name_regex="Battery")
        assert _is_excluded(cfg, "sensor.bat", "Battery Level") is True
        assert _is_excluded(cfg, "sensor.bat", "Temperature") is False

    def test_multiple_exclusions(self) -> None:
        cfg = _config(
            exclude_entity_ids=["sensor.a"],
            exclude_entity_id_regex="b$",
            exclude_entity_name_regex="^Ignore",
        )
        assert _is_excluded(cfg, "sensor.a", "A") is True
        assert _is_excluded(cfg, "sensor.b", "B") is True
        assert _is_excluded(cfg, "sensor.c", "Ignore Me") is True
        assert _is_excluded(cfg, "sensor.c", "Keep") is False


class TestCheckEntityDrift:
    def test_no_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift()
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_id_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            entity_id="sensor.old_name",
            expected_entity_id="sensor.new_name",
        )
        result = _check_entity_drift(cfg, entity, _device())
        assert result is not None
        assert result.id_drifted is True
        assert result.name_drifted is False

    def test_name_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            has_name_override=True,
            current_name="Old Name",
            expected_name="New Name",
        )
        result = _check_entity_drift(cfg, entity, _device())
        assert result is not None
        assert result.name_drifted is True
        assert result.id_drifted is False

    def test_both_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            entity_id="sensor.old",
            expected_entity_id="sensor.new",
            has_name_override=True,
            current_name="Old",
            expected_name="New",
        )
        result = _check_entity_drift(cfg, entity, _device())
        assert result is not None
        assert result.id_drifted is True
        assert result.name_drifted is True

    def test_name_drift_only_when_override(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            has_name_override=False,
            current_name="Old",
            expected_name="New",
        )
        result = _check_entity_drift(cfg, entity, _device())
        assert result is None

    def test_id_check_disabled(self) -> None:
        cfg = _config(
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_NAME}),
        )
        entity = _entity_drift(
            entity_id="sensor.old",
            expected_entity_id="sensor.new",
        )
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_name_check_disabled(self) -> None:
        cfg = _config(
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_ID}),
        )
        entity = _entity_drift(
            has_name_override=True,
            current_name="Old",
            expected_name="New",
        )
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_excluded_entity_skipped(self) -> None:
        cfg = _config(exclude_entity_ids=["sensor.skip"])
        entity = _entity_drift(
            entity_id="sensor.skip",
            expected_entity_id="sensor.new",
        )
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_none_expected_id_no_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            entity_id="sensor.test",
            expected_entity_id=None,
        )
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_none_expected_name_no_drift(self) -> None:
        cfg = _config()
        entity = _entity_drift(
            has_name_override=True,
            current_name="Old",
            expected_name=None,
        )
        assert _check_entity_drift(cfg, entity, _device()) is None

    def test_redundant_prefix_preserved(self) -> None:
        cfg = _config()
        dev = _device(device_name="Kitchen Sensor")
        entity = _entity_drift(
            has_name_override=True,
            current_name="Kitchen Sensor Temperature",
            expected_name="Temperature",
        )
        result = _check_entity_drift(cfg, entity, dev)
        assert result is not None
        assert result.has_redundant_prefix is True

    def test_hen_false_correct_override_no_drift(
        self,
    ) -> None:
        cfg = _config()
        # Device renamed from "Pedestal Fan" to
        # "Main Bedroom Pedestal Fan". Entity has
        # correct suffix override.
        dev = _device(
            device_name="Main Bedroom Pedestal Fan",
            default_name="Pedestal Fan",
        )
        entity = _entity_drift(
            has_entity_name=False,
            has_name_override=True,
            current_name="Temperature",
            expected_name="Pedestal Fan Temperature",
        )
        assert _check_entity_drift(cfg, entity, dev) is None

    def test_hen_false_wrong_override_drifted(
        self,
    ) -> None:
        cfg = _config()
        dev = _device(
            device_name="Main Bedroom Pedestal Fan",
            default_name="Pedestal Fan",
        )
        entity = _entity_drift(
            has_entity_name=False,
            has_name_override=True,
            current_name="Pedestal Fan Temperature",
            expected_name="Pedestal Fan Temperature",
        )
        result = _check_entity_drift(cfg, entity, dev)
        assert result is not None
        assert result.name_drifted is True
        assert result.recommended_override == "Temperature"

    def test_hen_false_no_override_drifted(
        self,
    ) -> None:
        cfg = _config()
        dev = _device(
            device_name="Main Bedroom Pedestal Fan",
            default_name="Pedestal Fan",
        )
        entity = _entity_drift(
            has_entity_name=False,
            has_name_override=False,
            current_name="Pedestal Fan Temperature",
            expected_name="Pedestal Fan Temperature",
        )
        result = _check_entity_drift(cfg, entity, dev)
        assert result is not None
        assert result.name_drifted is True

    def test_hen_false_device_entity_correct(
        self,
    ) -> None:
        cfg = _config()
        dev = _device(
            device_name="Main Bedroom Pedestal Fan",
            default_name="Pedestal Fan",
        )
        entity = _entity_drift(
            has_entity_name=False,
            has_name_override=True,
            current_name="Main Bedroom Pedestal Fan",
            expected_name="Pedestal Fan",
        )
        assert _check_entity_drift(cfg, entity, dev) is None


class TestComputeRecommendedOverride:
    def test_multi_integration_skips(self) -> None:
        result = _compute_recommended_override(
            entity_name="Pedestal Fan Temperature",
            device_default_name="Pedestal Fan",
            device_display_name="Main Bedroom Fan",
            has_entity_name=False,
            multi_integration=True,
        )
        assert result is None

    def test_single_integration_recommends(self) -> None:
        result = _compute_recommended_override(
            entity_name="Pedestal Fan Temperature",
            device_default_name="Pedestal Fan",
            device_display_name="Main Bedroom Fan",
            has_entity_name=False,
            multi_integration=False,
        )
        assert result == "Temperature"


class TestBuildNotificationMessage:
    def test_device_result_carries_device_ref(self) -> None:
        # Locks down the lift-not-copy intent: the per-device
        # result hands the framework a DeviceRef (resolved name
        # + the device's integration set) so the shared
        # attribution header -- not the EDW body -- renders the
        # Device / Integrations lines, consistently across
        # DW + EDW + RW.
        device = _device(
            device_id="abc",
            device_name="Kitchen Sensor",
            integrations=["zwave_js", "enphase_envoy"],
        )
        result = _evaluate_device(_config(drift_checks=CHECK_ALL), device)
        expected_device = helpers.DeviceRef(
            device_id="abc",
            name="Kitchen Sensor",
        )
        expected_integrations = ("enphase_envoy", "zwave_js")
        assert result.device == expected_device
        assert result.integrations == expected_integrations
        # The carry survives the spec the dispatcher consumes.
        spec = result.to_notification()
        assert spec.device == expected_device
        assert spec.integrations == expected_integrations

    def test_name_overrides_section(self) -> None:
        device = _device(device_name="Kitchen Sensor")
        drifted = [
            DriftDetail(
                entity_id="sensor.kitchen_temp",
                id_drifted=False,
                name_drifted=True,
                current_name="Old Temp",
                expected_name="Temperature",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Name overrides to clear:**" in msg
        assert '"Old Temp"' in msg
        assert '"Temperature"' not in msg
        assert "exclusion list" in msg

    def test_redundant_prefix_section(self) -> None:
        device = _device(device_name="Kitchen Sensor")
        drifted = [
            DriftDetail(
                entity_id="sensor.kitchen_co2",
                id_drifted=False,
                name_drifted=True,
                current_name="Kitchen Sensor CO2",
                expected_name="CO2",
                has_redundant_prefix=True,
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Name overrides with redundant" in msg
        assert "Kitchen Sensor" in msg
        assert "already adds" in msg

    def test_id_only_section(self) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.old_battery",
                id_drifted=True,
                name_drifted=False,
                current_name="Battery",
                expected_name=None,
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Non-default entity IDs:**" in msg
        assert "`sensor.old_battery`" in msg
        assert "Recreate entity IDs" in msg

    def test_name_and_id_entity_in_name_section_only(
        self,
    ) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.old",
                id_drifted=True,
                name_drifted=True,
                current_name="Old",
                expected_name="New",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Name overrides to clear:**" in msg
        assert "**Non-default entity IDs:**" not in msg

    def test_mixed_sections(self) -> None:
        device = _device(device_name="Dev")
        drifted = [
            DriftDetail(
                entity_id="sensor.name_issue",
                id_drifted=False,
                name_drifted=True,
                current_name="Old",
                expected_name="New",
            ),
            DriftDetail(
                entity_id="sensor.id_issue",
                id_drifted=True,
                name_drifted=False,
                current_name="Fine",
                expected_name=None,
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Name overrides to clear:**" in msg
        assert "**Non-default entity IDs:**" in msg
        assert "Fix names before recreating IDs" in msg

    def test_name_overrides_to_set_section(
        self,
    ) -> None:
        device = _device(device_name="Main Bedroom Fan")
        drifted = [
            DriftDetail(
                entity_id="number.main_bedroom_fan_angle",
                id_drifted=False,
                name_drifted=True,
                current_name="Fan Angle",
                expected_name=None,
                recommended_override="Angle",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "**Name overrides to set:**" in msg
        assert 'set to "Angle"' in msg
        assert "legacy entities" in msg

    def test_id_only_simple_fix(self) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.old",
                id_drifted=True,
                name_drifted=False,
                current_name="X",
                expected_name=None,
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "Recreate entity IDs" in msg
        assert "How to fix" not in msg

    def test_name_only_mentions_next_check(self) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.x",
                id_drifted=False,
                name_drifted=True,
                current_name="Old",
                expected_name="New",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert "next check" in msg

    def test_current_name_is_escaped_in_name_clear(self) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.x",
                id_drifted=False,
                name_drifted=True,
                current_name="bad [name]",
                expected_name="ok",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert '"bad \\[name\\]"' in msg

    def test_redundant_section_escapes_names(self) -> None:
        device = _device(device_name="Dev [x]")
        drifted = [
            DriftDetail(
                entity_id="sensor.x",
                id_drifted=False,
                name_drifted=True,
                current_name="bad [a]",
                expected_name="exp [b]",
                has_redundant_prefix=True,
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert '"bad \\[a\\]"' in msg
        assert '"exp \\[b\\]"' in msg
        # Device name is escaped in the redundant-prefix prose
        # ("remove ... or clear it"); the device header itself
        # now renders in the shared attribution block, not the
        # body, so it appears here exactly once.
        assert msg.count("Dev \\[x\\]") == 1

    def test_recommended_override_is_escaped(self) -> None:
        device = _device()
        drifted = [
            DriftDetail(
                entity_id="sensor.x",
                id_drifted=False,
                name_drifted=True,
                current_name="cur",
                expected_name="exp",
                recommended_override="rec [override]",
            ),
        ]
        msg = _build_device_notification_message(device, drifted)
        assert '"rec \\[override\\]"' in msg


class TestEvaluateDevice:
    def test_no_drift(self) -> None:
        cfg = _config()
        device = _device(entities=[_entity_drift()])
        result = _evaluate_device(cfg, device)
        assert result.has_issue is False
        assert result.drifted_entities == []

    def test_drift_detected(self) -> None:
        cfg = _config()
        device = _device(
            entities=[
                _entity_drift(
                    entity_id="sensor.old",
                    expected_entity_id="sensor.new",
                ),
            ],
        )
        result = _evaluate_device(cfg, device)
        assert result.has_issue is True
        assert len(result.drifted_entities) == 1

    def test_excluded_device(self) -> None:
        cfg = _config(exclude_device_name_regex="Test")
        device = _device(
            device_name="Test Device",
            entities=[
                _entity_drift(
                    entity_id="sensor.old",
                    expected_entity_id="sensor.new",
                ),
            ],
        )
        result = _evaluate_device(cfg, device)
        assert result.has_issue is False
        assert result.device_excluded is True
        assert result.entities_checked == 0
        assert result.entities_excluded == 0

    def test_entity_counts(self) -> None:
        cfg = _config(exclude_entity_ids=["sensor.skip"])
        device = _device(
            entities=[
                _entity_drift(
                    entity_id="sensor.drift",
                    expected_entity_id="sensor.new",
                ),
                _entity_drift(entity_id="sensor.clean"),
                _entity_drift(entity_id="sensor.skip"),
            ],
        )
        result = _evaluate_device(cfg, device)
        assert result.entities_checked == 2
        assert result.entities_excluded == 1

    def test_notification_id_format(self) -> None:
        cfg = _config()
        device = _device(device_id="abc123")
        result = _evaluate_device(cfg, device)
        assert result.notification_id == (
            "entity_defaults_watchdog_test__device_abc123"
        )

    def test_notification_title(self) -> None:
        cfg = _config()
        device = _device(
            device_name="Kitchen Sensor",
            entities=[
                _entity_drift(
                    entity_id="sensor.old",
                    expected_entity_id="sensor.new",
                ),
            ],
        )
        result = _evaluate_device(cfg, device)
        assert result.notification_title == "Kitchen Sensor"

    def test_no_title_when_clean(self) -> None:
        cfg = _config()
        device = _device(entities=[_entity_drift()])
        result = _evaluate_device(cfg, device)
        assert result.notification_title == ""

    def test_to_notification(self) -> None:
        cfg = _config()
        device = _device(
            entities=[
                _entity_drift(
                    entity_id="sensor.old",
                    expected_entity_id="sensor.new",
                ),
            ],
        )
        result = _evaluate_device(cfg, device)
        notif = result.to_notification()
        assert notif.active is True
        assert notif.notification_id.startswith(
            "entity_defaults_watchdog_test__device_",
        )


class TestEvaluateDevices:
    def test_multiple_devices(self) -> None:
        cfg = _config()
        devices = [
            _device(
                "clean",
                "Clean",
                entities=[_entity_drift()],
            ),
            _device(
                "drifted",
                "Drifted",
                entities=[
                    _entity_drift(
                        entity_id="sensor.old",
                        expected_entity_id="sensor.new",
                    ),
                ],
            ),
        ]
        results = evaluate_devices(cfg, devices)
        assert len(results) == 2
        clean = [r for r in results if not r.has_issue]
        drifted = [r for r in results if r.has_issue]
        assert len(clean) == 1
        assert len(drifted) == 1

    def test_empty_device_list(self) -> None:
        cfg = _config()
        results = evaluate_devices(cfg, [])
        assert results == []

    def test_all_clean(self) -> None:
        cfg = _config()
        devices = [
            _device("d1", "D1", entities=[_entity_drift()]),
            _device("d2", "D2", entities=[_entity_drift()]),
        ]
        results = evaluate_devices(cfg, devices)
        assert all(not r.has_issue for r in results)


class TestMatchesWithCollisionSuffix:
    """Validate the collision-suffix matcher.

    Covers exact match, valid ``_N`` suffix (with peer),
    stale ``_N`` suffix (no peer), and the leading-zero
    edge cases.
    """

    def test_exact_match(self) -> None:
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo",
            "foo",
            peers,
        )
        assert (ok, stale) == (True, False)

    def test_plain_mismatch(self) -> None:
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "bar",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, False)

    def test_valid_suffix_with_base_peer(self) -> None:
        peers = {"foo"}
        ok, stale = _matches_with_collision_suffix(
            "foo_2",
            "foo",
            peers,
        )
        assert (ok, stale) == (True, False)

    def test_stale_suffix(self) -> None:
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo_2",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, True)

    def test_chain_end_flagged(self) -> None:
        # peers={foo_2, foo_3, foo_4}, no foo. Only the
        # highest (foo_4) is flagged; renaming it to foo
        # restores a base peer so the rest become valid.
        peers = {"foo_2", "foo_3", "foo_4"}
        ok, stale = _matches_with_collision_suffix(
            "foo_4",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, True)

    def test_chain_mid_deferred(self) -> None:
        peers = {"foo_2", "foo_3", "foo_4"}
        ok, stale = _matches_with_collision_suffix(
            "foo_3",
            "foo",
            peers,
        )
        assert (ok, stale) == (True, False)

    def test_chain_bottom_deferred(self) -> None:
        peers = {"foo_2", "foo_3", "foo_4"}
        ok, stale = _matches_with_collision_suffix(
            "foo_2",
            "foo",
            peers,
        )
        assert (ok, stale) == (True, False)

    def test_suffix_zero_rejected(self) -> None:
        # HA never uses _0; treat as plain mismatch.
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo_0",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, False)

    def test_suffix_one_rejected(self) -> None:
        # HA never uses _1 either.
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo_1",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, False)

    def test_leading_zero_rejected(self) -> None:
        # "_02" is not a valid HA suffix.
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo_02",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, False)

    def test_non_numeric_suffix_rejected(self) -> None:
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo_bar",
            "foo",
            peers,
        )
        assert (ok, stale) == (False, False)

    def test_empty_expected(self) -> None:
        peers: set[str] = set()
        ok, stale = _matches_with_collision_suffix(
            "foo",
            "",
            peers,
        )
        assert (ok, stale) == (False, False)


def _deviceless(
    entity_id: str,
    effective_name: str = "",
    platform: str | None = None,
    unique_id: str | None = None,
    from_registry: bool = True,
    config_entry_id: str | None = "ui_entry",
) -> DevicelessEntityInfo:
    return DevicelessEntityInfo(
        entity_id=entity_id,
        effective_name=effective_name,
        platform=platform,
        unique_id=unique_id,
        from_registry=from_registry,
        config_entry_id=config_entry_id,
    )


class TestEvaluateDeviceless:
    """Cover the rule end-to-end, including section split."""

    def test_no_entities(self) -> None:
        cfg = _config()
        result = _evaluate_deviceless(cfg, [], {})
        assert result.has_issue is False
        assert result.drifted == []
        assert result.entities_checked == 0

    def test_matching_entity_not_flagged(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "automation.foo",
                effective_name="Foo",
                platform="automation",
                unique_id="1234",
            ),
        ]
        peers = {"automation": {"foo"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is False
        assert result.drifted == []

    def test_drift_flagged(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "automation.old_name",
                effective_name="Renamed Foo",
                platform="automation",
                unique_id="1234",
            ),
        ]
        peers = {"automation": {"old_name"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is True
        assert len(result.drifted) == 1
        d = result.drifted[0]
        assert d.entity_id == "automation.old_name"
        assert d.expected_object_id == "renamed_foo"
        assert d.stale_suffix is False

    def test_notification_bullet_includes_edit_link(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "automation.old",
                effective_name="New Name",
                platform="automation",
                unique_id="1669687974816",
            ),
        ]
        peers = {"automation": {"old"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Friendly name is itself the link for automations
        assert (
            "[New Name](/config/automation/edit/1669687974816)"
            in result.notification_message
        )
        assert "`automation.old`" in result.notification_message
        assert "-> expected `automation.new_name`" in (
            result.notification_message
        )
        # Old quoted-name-plus-Edit-link format is gone
        assert "[Edit]" not in result.notification_message
        assert '"New Name"' not in result.notification_message

    def test_script_pointer(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "script.old",
                effective_name="New Name",
                platform="script",
                unique_id="old",
            ),
        ]
        peers = {"script": {"old"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Friendly name is itself the link for scripts
        assert "[New Name](/config/script/edit/old)" in (
            result.notification_message
        )
        assert "[Edit]" not in result.notification_message

    def test_template_pointer_uses_integration_page(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.template_sensor",
                effective_name="Grid Import Power",
                platform="template",
                unique_id="grid_import_power",
            ),
        ]
        peers = {"sensor": {"template_sensor"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Friendly name plain, integration name links to
        # the integration's config page
        assert (
            "Grid Import Power  -  integration"
            " [template](/config/integrations/integration/template)"
            in result.notification_message
        )

    def test_yaml_configured_drops_integration_link(self) -> None:
        """YAML-configured entities (no config_entry_id)
        get a plain integration name and a ``YAML-configuration``
        note. The integration page doesn't list YAML-defined
        entities, so linking there would mislead."""
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.loft_thermostat_hvac_action",
                effective_name="Loft HVAC Action",
                platform="template",
                unique_id="loft_hvac_action_uid",
                config_entry_id=None,
            ),
        ]
        peers = {"sensor": {"loft_thermostat_hvac_action"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert (
            "Loft HVAC Action  -  integration template  -  YAML-configuration"
            in result.notification_message
        )
        # And definitely no link to the integration page.
        assert (
            "/config/integrations/integration/template"
            not in result.notification_message
        )

    def test_yaml_configured_escapes_friendly_name(self) -> None:
        """Brackets in the friendly name must still be
        markdown-escaped in the YAML-configured branch."""
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.template_sensor",
                effective_name="Grid [Import] Power",
                platform="template",
                unique_id="grid",
                config_entry_id=None,
            ),
        ]
        peers = {"sensor": {"template_sensor"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        expected = (
            "Grid \\[Import\\] Power  -  integration template"
            "  -  YAML-configuration"
        )
        assert expected in result.notification_message

    def test_state_only_pointer_nudges_unique_id(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.template_sensor",
                effective_name="Grid Import Power",
                platform=None,
                unique_id=None,
                from_registry=False,
            ),
        ]
        peers = {"sensor": {"template_sensor"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # No quotes, no integration link, no exclusion
        # nudge -- just the name and the unique_id: hint.
        expected = (
            "Grid Import Power  -  add `unique_id:`"
            " to make this entity manageable"
        )
        assert expected in result.notification_message
        assert '"Grid Import Power"' not in result.notification_message
        assert "exclusion" not in result.notification_message

    def test_link_text_escapes_markdown(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "automation.old",
                effective_name="Name [with] brackets",
                platform="automation",
                unique_id="1234",
            ),
        ]
        peers = {"automation": {"old"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Brackets in the friendly name must be escaped so
        # the surrounding [text](url) markdown isn't
        # broken by unbalanced brackets.
        assert (
            "[Name \\[with\\] brackets](/config/automation/edit/1234)"
            in result.notification_message
        )

    def test_integration_link_escapes_friendly_name(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.template_sensor",
                effective_name="Grid [Import] Power",
                platform="template",
                unique_id="grid",
            ),
        ]
        peers = {"sensor": {"template_sensor"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Brackets in the friendly name must be escaped
        # even in the non-link branch so they can't pair
        # with the trailing `[template](url)` link text.
        assert (
            "Grid \\[Import\\] Power  -  integration"
            " [template](/config/integrations/integration/template)"
            in result.notification_message
        )

    def test_integration_name_escaped_in_link_text(self) -> None:
        # Defense-in-depth: integration IDs are slug-style
        # under HA's current charset, but escape so a future
        # HA release loosening the charset can't corrupt the
        # rendered link.
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.x",
                effective_name="Plain",
                platform="bad[plat]",
                unique_id="x",
            ),
        ]
        peers = {"sensor": {"x"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        # Link text portion is escaped; URL target keeps the
        # raw platform string (URL targets don't render
        # markdown).
        assert (
            "[bad\\[plat\\]](/config/integrations/integration/bad[plat])"
            in result.notification_message
        )

    def test_state_only_nudge_escapes_friendly_name(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.template_sensor",
                effective_name="Grid [Import] Power",
                platform=None,
                unique_id=None,
                from_registry=False,
            ),
        ]
        peers = {"sensor": {"template_sensor"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert (
            "Grid \\[Import\\] Power  -  add `unique_id:`"
            " to make this entity manageable" in result.notification_message
        )

    def test_stale_suffix_separate_section(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "automation.foo_2",
                effective_name="Foo",
                platform="automation",
                unique_id="111",
            ),
        ]
        peers = {"automation": {"foo_2"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is True
        assert len(result.drifted) == 1
        assert result.drifted[0].stale_suffix is True
        assert "Stale collision suffixes" in (result.notification_message)
        assert "-> rename to `automation.foo`" in (result.notification_message)

    def test_valid_collision_suffix_not_flagged(self) -> None:
        cfg = _config()
        # Two automations both named "Foo"; one has the
        # plain slug, the other the collision suffix.
        entities = [
            _deviceless(
                "automation.foo",
                effective_name="Foo",
                platform="automation",
                unique_id="111",
            ),
            _deviceless(
                "automation.foo_2",
                effective_name="Foo",
                platform="automation",
                unique_id="222",
            ),
        ]
        peers = {"automation": {"foo", "foo_2"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is False

    def test_empty_name_skipped(self) -> None:
        cfg = _config()
        entities = [
            _deviceless(
                "sensor.x",
                effective_name="",
                platform="template",
                unique_id="x",
                from_registry=True,
            ),
        ]
        peers = {"sensor": {"x"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is False

    def test_exclusions_apply(self) -> None:
        cfg = _config(
            exclude_entity_ids=["automation.foo"],
        )
        entities = [
            _deviceless(
                "automation.foo",
                effective_name="Bar",
                platform="automation",
                unique_id="111",
            ),
        ]
        peers = {"automation": {"foo"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is False
        assert result.entities_excluded == 1

    def test_entity_id_regex_exclusion(self) -> None:
        cfg = _config(exclude_entity_id_regex="^sensor\\.")
        entities = [
            _deviceless(
                "sensor.foo",
                effective_name="Bar",
                platform="template",
                unique_id="foo",
            ),
        ]
        peers = {"sensor": {"foo"}}
        result = _evaluate_deviceless(cfg, entities, peers)
        assert result.has_issue is False
        assert result.entities_excluded == 1


class TestValidateEdwDirectives:
    """Direct tests against ``_validate_edw_directives`` -- the
    handler builds candidate sets from the FULL registries (not
    the post-include/exclude-integration set) and threads them
    through ``DirectiveInputs``. The validator should report a
    regex as matched whenever its pattern matches anything the
    handler hands over, even if the actual exclusion code's
    integration filter would have pruned the match.
    """

    @staticmethod
    def _di(
        *,
        entity_id_regex: str = "",
        device_name_regex: str = "",
        entity_name_regex: str = "",
        entity_id_candidates: frozenset[str] = frozenset(),
        device_name_candidates: frozenset[str] = frozenset(),
        entity_name_candidates: frozenset[str] = frozenset(),
        all_registered_entity_ids: frozenset[str] = frozenset(),
        exclude_entities: list[str] | None = None,
        include_integrations: list[str] | None = None,
        exclude_integrations: list[str] | None = None,
    ) -> DirectiveInputs:
        return DirectiveInputs(
            enabled=True,
            include_integrations=include_integrations or [],
            exclude_integrations=exclude_integrations or [],
            exclude_entities=exclude_entities or [],
            all_registered_entity_ids=all_registered_entity_ids,
            exclude_device_name_regex_lines=helpers.validate_and_join_regex_patterns(
                device_name_regex,
                "exclude_device_name_regex",
            ).lines,
            exclude_entity_id_regex_lines=helpers.validate_and_join_regex_patterns(
                entity_id_regex,
                "exclude_entity_id_regex",
            ).lines,
            exclude_entity_name_regex_lines=helpers.validate_and_join_regex_patterns(
                entity_name_regex,
                "exclude_entity_name_regex",
            ).lines,
            device_name_candidates=device_name_candidates,
            entity_id_candidates=entity_id_candidates,
            entity_name_candidates=entity_name_candidates,
        )

    def test_entity_id_regex_matches_broad_candidate_set(self) -> None:
        # Bug-fix coverage: a regex matching an entity in
        # the broad candidate set is NOT flagged unmatched
        # even if the entity's integration is in
        # ``exclude_integrations``. EDW's handler sources
        # ``entity_id_candidates`` from the FULL registry.
        di = self._di(
            entity_id_regex=r"sensor\.foo_.+",
            entity_id_candidates=frozenset(
                {"sensor.foo_bar", "sensor.unrelated"}
            ),
            exclude_integrations=["foo_integration"],
        )
        out = _validate_edw_directives(di, all_integrations=["foo_integration"])
        assert not [u for u in out if u.field == "exclude_entity_id_regex"], out

    def test_entity_id_regex_unmatched_when_no_candidate_matches(
        self,
    ) -> None:
        di = self._di(
            entity_id_regex=r"^xyz_no_entity_matches$",
            entity_id_candidates=frozenset({"sensor.foo", "sensor.bar"}),
        )
        out = _validate_edw_directives(di, all_integrations=[])
        unmatched = [u for u in out if u.field == "exclude_entity_id_regex"]
        assert len(unmatched) == 1
        assert unmatched[0].value == r"^xyz_no_entity_matches$"

    def test_leading_space_regex_is_unmatched(self) -> None:
        # Bug-2 coverage at the EDW layer: the helper
        # preserves leading whitespace verbatim, so a
        # typo'd "  _audio_input_format$" line compiles to
        # a pattern requiring a literal space and matches
        # no real entity_id.
        di = self._di(
            entity_id_regex=" _audio_input_format$",
            entity_id_candidates=frozenset(
                {
                    "sensor.kitchen_sonos_audio_input_format",
                    "sensor.living_room_sonos_audio_input_format",
                }
            ),
        )
        out = _validate_edw_directives(di, all_integrations=[])
        unmatched = [u for u in out if u.field == "exclude_entity_id_regex"]
        assert len(unmatched) == 1
        assert unmatched[0].value == " _audio_input_format$"

    def test_entity_name_regex_uses_candidate_set(self) -> None:
        di = self._di(
            entity_name_regex=r"^Loft Humidifier ",
            entity_name_candidates=frozenset(
                {"Loft Humidifier Power", "Kitchen Sonos"}
            ),
        )
        out = _validate_edw_directives(di, all_integrations=[])
        assert not [u for u in out if u.field == "exclude_entity_name_regex"], (
            out
        )

    def test_device_name_regex_uses_candidate_set(self) -> None:
        di = self._di(
            device_name_regex=r"^Kitchen Sonos$",
            device_name_candidates=frozenset(
                {"Kitchen Sonos", "Loft Humidifier"}
            ),
        )
        out = _validate_edw_directives(di, all_integrations=[])
        assert not [u for u in out if u.field == "exclude_device_name_regex"], (
            out
        )

    def test_exclude_entities_uses_all_registered_entity_ids(self) -> None:
        # ``exclude_entities`` measures against the full
        # registry-id set so users can suppress entities
        # outside the include/exclude_integration scope
        # without false-flag.
        di = self._di(
            exclude_entities=["sensor.out_of_scope_but_real"],
            all_registered_entity_ids=frozenset(
                {"sensor.out_of_scope_but_real", "sensor.something_else"}
            ),
        )
        out = _validate_edw_directives(di, all_integrations=[])
        assert not [u for u in out if u.field == "exclude_entities"], out


def _vcandidate(
    source_entity_id: str | None = "switch.foo",
    wrapper_entity_id: str = "foo",
    wrapper_target_domain: str | None = "fan",
    source_friendly_name: str = "Foo",
    source_device_id: str | None = "dev_abc",
    source_config_entry_id: str | None = "cfg_abc",
    *,
    entry_disabled: bool = False,
    source_registered: bool = True,
    source_hidden_by: str | None = None,
    source_disabled_by: str | None = None,
    wrapper_obj_ids: tuple[str, ...] | None = None,
    source_device_name: str | None = None,
    source_device_integrations: tuple[str, ...] = (),
) -> VisibleAliasedCandidate:
    """Build a clean finding-candidate by default.

    The defaults describe a visible source with a single
    wrapper -- a genuine finding. The keyword knobs let a test
    flip one fact to exercise a defensive-skip branch.
    """
    return VisibleAliasedCandidate(
        entry_disabled=entry_disabled,
        source_entity_id=source_entity_id,
        target_domain=wrapper_target_domain,
        source_registered=source_registered,
        wrapper_obj_ids=(
            wrapper_obj_ids
            if wrapper_obj_ids is not None
            else (wrapper_entity_id,)
        ),
        source_hidden_by=source_hidden_by,
        source_disabled_by=source_disabled_by,
        source_friendly_name=source_friendly_name,
        source_device_id=source_device_id,
        source_config_entry_id=source_config_entry_id,
        source_device_name=source_device_name,
        source_device_integrations=source_device_integrations,
    )


class TestVisibleAliasedEvaluate:
    """Per-port logic-side coverage of the visible-aliased
    drift check.

    The handler hands one raw candidate per switch_as_x config
    entry; this logic layer owns both the defensive-skip
    classification (entry disabled, malformed options, source
    missing, wrapper count, source disabled / hidden) and the
    user-exclusion + finding-shape / body-render paths.
    """

    def test_no_candidates_no_findings(self) -> None:
        cfg = _config()
        result = _evaluate_visible_aliased_entities(cfg, [])
        assert result.has_issue is False
        assert result.findings == []
        assert result.entries_kept == 0
        assert result.entries_excluded == 0
        assert result.defensive_skipped == 0

    def test_each_candidate_yields_one_finding(self) -> None:
        cfg = _config()
        candidates = [
            _vcandidate(
                source_entity_id="switch.foo",
                wrapper_entity_id="foo",
                wrapper_target_domain="fan",
                source_friendly_name="Foo",
            ),
            _vcandidate(
                source_entity_id="switch.bar",
                wrapper_entity_id="bar",
                wrapper_target_domain="light",
                source_friendly_name="Bar",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert result.has_issue is True
        assert len(result.findings) == 2
        eids = {f.source_entity_id for f in result.findings}
        assert eids == {"switch.foo", "switch.bar"}
        assert result.entries_kept == 2
        assert result.defensive_skipped == 0

    def test_finding_shape_carries_wrapper_and_source_ids(
        self,
    ) -> None:
        cfg = _config()
        candidates = [
            _vcandidate(
                source_entity_id="switch.kitchen",
                wrapper_entity_id="kitchen",
                wrapper_target_domain="fan",
                source_friendly_name="Kitchen Fan",
                source_device_id="dev_kitchen",
                source_config_entry_id="ce_kitchen",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert isinstance(finding, VisibleAliasedEntityFinding)
        assert finding.source_entity_id == "switch.kitchen"
        assert finding.wrapper_entity_id == "kitchen"
        assert finding.wrapper_target_domain == "fan"
        assert finding.source_friendly_name == "Kitchen Fan"
        assert finding.source_device_id == "dev_kitchen"
        assert finding.source_config_entry_id == "ce_kitchen"

    def test_finding_shape_carries_no_device_id_when_helper_backed(
        self,
    ) -> None:
        # Helper-backed switch_as_x sources can lack a
        # device_id but carry a config_entry_id; the body
        # builder routes to the deviceless link form in
        # that case.
        cfg = _config()
        candidates = [
            _vcandidate(
                source_entity_id="switch.input",
                source_device_id=None,
                source_config_entry_id="cfg_input",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        finding = result.findings[0]
        assert finding.source_device_id is None
        assert finding.source_config_entry_id == "cfg_input"

    def test_entry_disabled_skipped(self) -> None:
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [_vcandidate(entry_disabled=True)],
        )
        assert result.findings == []
        assert result.defensive_skipped == 1

    def test_malformed_options_skipped(self) -> None:
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [
                _vcandidate(source_entity_id=None),
                _vcandidate(wrapper_target_domain=None),
            ],
        )
        assert result.findings == []
        assert result.defensive_skipped == 2

    def test_unregistered_source_skipped(self) -> None:
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [_vcandidate(source_registered=False)],
        )
        assert result.findings == []
        assert result.defensive_skipped == 1

    def test_wrong_wrapper_count_skipped(self) -> None:
        # Zero or multiple wrapper entities for one switch_as_x
        # entry means something has gone sideways; flagging
        # would mislead.
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [
                _vcandidate(wrapper_obj_ids=()),
                _vcandidate(wrapper_obj_ids=("a", "b")),
            ],
        )
        assert result.findings == []
        assert result.defensive_skipped == 2

    def test_disabled_source_skipped(self) -> None:
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [_vcandidate(source_disabled_by="user")],
        )
        assert result.findings == []
        assert result.defensive_skipped == 1

    def test_hidden_source_is_healthy_and_skipped(self) -> None:
        # The source still carrying hidden_by is the healthy
        # state switch_as_x set up -- not a finding.
        cfg = _config()
        result = _evaluate_visible_aliased_entities(
            cfg,
            [_vcandidate(source_hidden_by="integration")],
        )
        assert result.findings == []
        assert result.defensive_skipped == 1

    def test_mixed_finding_skip_and_exclusion_counts(self) -> None:
        cfg = _config(exclude_entity_ids=["switch.excluded"])
        result = _evaluate_visible_aliased_entities(
            cfg,
            [
                _vcandidate(source_entity_id="switch.flagged"),
                _vcandidate(
                    source_entity_id="switch.excluded",
                    wrapper_entity_id="excluded",
                ),
                _vcandidate(
                    source_entity_id="switch.hidden",
                    source_hidden_by="integration",
                ),
            ],
        )
        assert {f.source_entity_id for f in result.findings} == {
            "switch.flagged",
        }
        assert result.entries_kept == 1
        assert result.entries_excluded == 1
        assert result.defensive_skipped == 1

    def test_excluded_by_entity_id_list(self) -> None:
        cfg = _config(exclude_entity_ids=["switch.foo"])
        candidates = [
            _vcandidate(source_entity_id="switch.foo"),
            _vcandidate(
                source_entity_id="switch.bar",
                wrapper_entity_id="bar",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert {f.source_entity_id for f in result.findings} == {
            "switch.bar",
        }
        assert result.entries_excluded == 1

    def test_excluded_by_entity_id_regex(self) -> None:
        cfg = _config(exclude_entity_id_regex="^switch\\.skip_")
        candidates = [
            _vcandidate(source_entity_id="switch.skip_me"),
            _vcandidate(
                source_entity_id="switch.keep",
                wrapper_entity_id="keep",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert {f.source_entity_id for f in result.findings} == {
            "switch.keep",
        }
        assert result.entries_excluded == 1

    def test_excluded_by_entity_name_regex(self) -> None:
        cfg = _config(exclude_entity_name_regex="^Skip ")
        candidates = [
            _vcandidate(
                source_entity_id="switch.foo",
                source_friendly_name="Skip Me",
            ),
            _vcandidate(
                source_entity_id="switch.bar",
                wrapper_entity_id="bar",
                source_friendly_name="Keep",
            ),
        ]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert {f.source_entity_id for f in result.findings} == {
            "switch.bar",
        }
        assert result.entries_excluded == 1

    def test_only_emits_when_nonempty(self) -> None:
        cfg = _config(exclude_entity_ids=["switch.foo"])
        candidates = [_vcandidate(source_entity_id="switch.foo")]
        result = _evaluate_visible_aliased_entities(cfg, candidates)
        assert result.has_issue is False
        assert result.findings == []
        # Title + message stay empty when there is nothing
        # to show so the dispatcher renders a dismiss spec.
        assert result.notification_title == ""
        assert result.notification_message == ""

    def test_notification_id_uses_prefix(self) -> None:
        cfg = _config(
            notification_prefix="entity_defaults_watchdog_test__",
        )
        result = _evaluate_visible_aliased_entities(cfg, [_vcandidate()])
        assert result.notification_id == (
            "entity_defaults_watchdog_test__visible_aliased"
        )


class TestVisibleAliasedNotificationBody:
    def test_body_lists_each_finding(self) -> None:
        findings = [
            VisibleAliasedEntityFinding(
                source_entity_id="switch.kitchen",
                wrapper_entity_id="kitchen",
                wrapper_target_domain="fan",
                source_friendly_name="Kitchen Fan",
                source_device_id="dev_kitchen",
                source_config_entry_id="ce_kitchen",
            ),
        ]
        body = _build_visible_aliased_notification_message(findings)
        assert "`switch.kitchen`" in body
        assert "`fan.kitchen`" in body
        assert "device=dev_kitchen" in body
        assert "config_entry=ce_kitchen" in body
        # Body names switch_as_x so the user knows which
        # integration owns the wrapper.
        assert "switch_as_x" in body

    def test_body_escapes_friendly_name(self) -> None:
        findings = [
            VisibleAliasedEntityFinding(
                source_entity_id="switch.foo",
                wrapper_entity_id="foo",
                wrapper_target_domain="fan",
                source_friendly_name="Bad [Name]",
                source_device_id="dev_foo",
                source_config_entry_id="ce_foo",
            ),
        ]
        body = _build_visible_aliased_notification_message(findings)
        assert "Bad \\[Name\\]" in body
        assert "[Bad [Name]]" not in body

    def test_body_sorts_findings_by_entity_id(self) -> None:
        findings = [
            VisibleAliasedEntityFinding(
                source_entity_id="switch.zeta",
                wrapper_entity_id="zeta",
                wrapper_target_domain="fan",
                source_friendly_name="Zeta",
                source_device_id="dev_zeta",
                source_config_entry_id="ce_zeta",
            ),
            VisibleAliasedEntityFinding(
                source_entity_id="switch.alpha",
                wrapper_entity_id="alpha",
                wrapper_target_domain="fan",
                source_friendly_name="Alpha",
                source_device_id="dev_alpha",
                source_config_entry_id="ce_alpha",
            ),
        ]
        body = _build_visible_aliased_notification_message(findings)
        # alpha must appear before zeta in the rendered body
        assert body.index("switch.alpha") < body.index("switch.zeta")


class TestCheckAllExposesVisibleAliased:
    """The CHECK_ALL <-> blueprint pairing.

    Locks down the constant rename + the user-facing dash
    style so a future refactor can't silently drop the
    drift-check option from CHECK_ALL. The blueprint-side
    selector-options pairing lives in
    ``test_entity_defaults_watchdog_handler.py`` (yaml is
    available there via the test file's PEP 723 deps).
    """

    def test_constant_value_is_dashed(self) -> None:
        assert DRIFT_CHECK_VISIBLE_ALIASED_ENTITY == "visible-aliased-entity"

    def test_constant_in_check_all(self) -> None:
        assert DRIFT_CHECK_VISIBLE_ALIASED_ENTITY in CHECK_ALL


def _drift(
    entity_id: str = "sensor.test",
    id_drifted: bool = False,
    name_drifted: bool = False,
    expected_entity_id: str | None = None,
    recommended_override: str | None = None,
) -> DriftDetail:
    return DriftDetail(
        entity_id=entity_id,
        id_drifted=id_drifted,
        name_drifted=name_drifted,
        current_name="Current",
        expected_name=None,
        recommended_override=recommended_override,
        expected_entity_id=expected_entity_id,
    )


def _device_result(
    device_id: str = "dev1",
    device_name: str = "Test Device",
    has_issue: bool = True,
    device_excluded: bool = False,
    drifted_entities: list[DriftDetail] | None = None,
) -> DeviceResult:
    return DeviceResult(
        device_id=device_id,
        device_name=device_name,
        has_issue=has_issue,
        device_excluded=device_excluded,
        notification_id="ignored",
        notification_title="",
        notification_message="",
        drifted_entities=drifted_entities or [],
        entities_checked=0,
        entities_excluded=0,
        instance_id="automation.edw",
    )


class TestBuildDeviceRepairSpecs:
    """_build_device_repair_specs: per-device id/name split.

    The logic-layer producer of EDW's repair specs + the
    off-wire payloads. Asserts per-device grouping, the
    id-drift vs name-drift split (up to two specs per
    device), the issue-ID format, and payload contents.
    """

    def test_id_drift_only_emits_one_id_spec(self) -> None:
        cfg = _config(create_repairs=True)
        result = _device_result(
            device_id="abc",
            drifted_entities=[
                _drift(
                    entity_id="sensor.old",
                    id_drifted=True,
                    expected_entity_id="sensor.new",
                ),
            ],
        )
        specs, repairs = _build_device_repair_specs(cfg, [result])
        assert len(specs) == 1
        spec = specs[0]
        expected_id = helpers.repair_notification_id(
            cfg.notification_prefix,
            FixServices.ENTITY_ID_DRIFT,
            "abc",
        )
        assert spec.notification_id == expected_id
        assert "__repair_" in spec.notification_id
        assert spec.translation_key == "edw_entity_id_drift"
        assert spec.translation_placeholders == {
            "count": "1",
            "entities": "- `sensor.old` -> `sensor.new`",
        }
        assert spec.repair_callback is not None
        assert spec.repair_callback.service_name == (
            FixServices.ENTITY_ID_DRIFT.value
        )
        payload = repairs[expected_id]
        assert isinstance(payload, EntityIdDriftRepair)
        assert payload.entity_renames == (("sensor.old", "sensor.new"),)

    def test_name_drift_only_emits_one_name_spec(self) -> None:
        cfg = _config(create_repairs=True)
        result = _device_result(
            device_id="abc",
            drifted_entities=[
                _drift(
                    entity_id="sensor.x",
                    name_drifted=True,
                    recommended_override=None,
                ),
            ],
        )
        specs, repairs = _build_device_repair_specs(cfg, [result])
        assert len(specs) == 1
        spec = specs[0]
        expected_id = helpers.repair_notification_id(
            cfg.notification_prefix,
            FixServices.DEVICE_ENTITY_NAME_DRIFT,
            "abc",
        )
        assert spec.notification_id == expected_id
        assert spec.translation_key == "edw_device_entity_name_drift"
        ph = spec.translation_placeholders
        assert ph is not None
        # Clear case (no recommended override, no expected
        # name): the entities line renders the default-name
        # prose on the right-hand side.
        assert ph["entities"] == (
            '- `sensor.x`: "Current" -> the integration default name'
        )
        payload = repairs[expected_id]
        assert isinstance(payload, DeviceEntityNameDriftRepair)
        # None target clears the override (revert to default).
        assert payload.entity_name_targets == (("sensor.x", None),)

    def test_both_drifts_emit_two_specs(self) -> None:
        cfg = _config(create_repairs=True)
        result = _device_result(
            device_id="abc",
            drifted_entities=[
                _drift(
                    entity_id="sensor.a",
                    id_drifted=True,
                    expected_entity_id="sensor.b",
                ),
                _drift(
                    entity_id="sensor.c",
                    name_drifted=True,
                    recommended_override="Custom",
                ),
            ],
        )
        specs, repairs = _build_device_repair_specs(cfg, [result])
        assert len(specs) == 2
        kinds = {s.translation_key for s in specs}
        assert kinds == {
            "edw_entity_id_drift",
            "edw_device_entity_name_drift",
        }
        name_repair = next(
            p
            for p in repairs.values()
            if isinstance(p, DeviceEntityNameDriftRepair)
        )
        # Non-None target SETS the override.
        assert name_repair.entity_name_targets == (("sensor.c", "Custom"),)
        specs_by_kind = {s.translation_key: s for s in specs}
        id_ph = specs_by_kind["edw_entity_id_drift"]
        name_ph = specs_by_kind["edw_device_entity_name_drift"]
        assert id_ph.translation_placeholders is not None
        assert name_ph.translation_placeholders is not None
        assert id_ph.translation_placeholders["entities"] == (
            "- `sensor.a` -> `sensor.b`"
        )
        # Set case (recommended override) renders old -> new.
        assert name_ph.translation_placeholders["entities"] == (
            '- `sensor.c`: "Current" -> "Custom"'
        )

    def test_excluded_device_skipped(self) -> None:
        result = _device_result(
            device_excluded=True,
            drifted_entities=[
                _drift(id_drifted=True, expected_entity_id="sensor.new"),
            ],
        )
        specs, repairs = _build_device_repair_specs(
            _config(create_repairs=True),
            [result],
        )
        assert specs == []
        assert repairs == {}

    def test_no_issue_device_skipped(self) -> None:
        result = _device_result(
            has_issue=False,
            drifted_entities=[
                _drift(id_drifted=True, expected_entity_id="sensor.new"),
            ],
        )
        specs, repairs = _build_device_repair_specs(
            _config(create_repairs=True),
            [result],
        )
        assert specs == []
        assert repairs == {}

    def test_id_drift_without_expected_id_not_captured(self) -> None:
        # id_drifted but expected_entity_id None: nothing to
        # rename to, so no id-drift spec.
        result = _device_result(
            drifted_entities=[
                _drift(
                    entity_id="sensor.x",
                    id_drifted=True,
                    expected_entity_id=None,
                ),
            ],
        )
        specs, repairs = _build_device_repair_specs(
            _config(create_repairs=True),
            [result],
        )
        assert specs == []
        assert repairs == {}

    def test_device_name_falls_back_to_id(self) -> None:
        # Only the name-drift spec carries a device_name
        # placeholder; the id-drift spec leans on the
        # attribution header for device context.
        result = _device_result(
            device_id="abc",
            device_name="",
            drifted_entities=[
                _drift(entity_id="sensor.x", name_drifted=True),
            ],
        )
        specs, _ = _build_device_repair_specs(
            _config(create_repairs=True),
            [result],
        )
        placeholders = specs[0].translation_placeholders
        assert placeholders is not None
        assert placeholders["device_name"] == "abc"

    def test_two_devices_grouped_independently(self) -> None:
        cfg = _config(create_repairs=True)
        results = [
            _device_result(
                device_id="d1",
                drifted_entities=[
                    _drift(id_drifted=True, expected_entity_id="sensor.n1"),
                ],
            ),
            _device_result(
                device_id="d2",
                drifted_entities=[
                    _drift(name_drifted=True),
                ],
            ),
        ]
        specs, repairs = _build_device_repair_specs(cfg, results)
        assert len(specs) == 2
        assert len(repairs) == 2
        assert all(s.notification_id.endswith(("__d1", "__d2")) for s in specs)


def _deviceless_detail(
    entity_id: str,
    expected_object_id: str,
    *,
    platform: str | None = "automation",
) -> DevicelessDriftDetail:
    return DevicelessDriftDetail(
        entity_id=entity_id,
        expected_object_id=expected_object_id,
        friendly_name="Friendly",
        stale_suffix=False,
        platform=platform,
        unique_id="uid",
        from_registry=True,
    )


class TestBuildDevicelessIdDriftRepairSpecs:
    """_build_deviceless_id_drift_repair_specs: one id-drift
    repair per drifted deviceless entity.

    Deviceless entities have no grouping, so this is one
    repair per entity (vs the device builder's per-device
    grouping), keyed on the entity_id, with no device ref.
    """

    def test_one_repair_per_entity(self) -> None:
        cfg = _config(create_repairs=True)
        details = [
            _deviceless_detail("automation.stsc_main", "stec_main"),
            _deviceless_detail("automation.stsc_guest", "stec_guest"),
        ]
        specs, repairs = _build_deviceless_id_drift_repair_specs(cfg, details)
        assert len(specs) == 2
        assert len(repairs) == 2

    def test_spec_shape(self) -> None:
        cfg = _config(create_repairs=True)
        detail = _deviceless_detail("automation.stsc_main", "stec_main")
        specs, repairs = _build_deviceless_id_drift_repair_specs(cfg, [detail])
        spec = specs[0]
        expected_id = helpers.repair_notification_id(
            cfg.notification_prefix,
            FixServices.ENTITY_ID_DRIFT,
            "automation.stsc_main",
        )
        assert spec.notification_id == expected_id
        assert "__repair_" in spec.notification_id
        assert spec.translation_key == "edw_entity_id_drift"
        assert spec.translation_placeholders == {
            "count": "1",
            "entities": ("- `automation.stsc_main` -> `automation.stec_main`"),
        }
        assert spec.device is None
        assert spec.integrations == ("automation",)
        assert spec.repair_callback is not None
        assert spec.repair_callback.service_name == (
            FixServices.ENTITY_ID_DRIFT.value
        )
        payload = repairs[expected_id]
        assert isinstance(payload, EntityIdDriftRepair)
        assert payload.entity_renames == (
            ("automation.stsc_main", "automation.stec_main"),
        )

    def test_no_integration_when_platform_none(self) -> None:
        cfg = _config(create_repairs=True)
        detail = _deviceless_detail("sensor.x", "y", platform=None)
        specs, _ = _build_deviceless_id_drift_repair_specs(cfg, [detail])
        assert specs[0].integrations == ()

    def test_empty_input_no_specs(self) -> None:
        specs, repairs = _build_deviceless_id_drift_repair_specs(
            _config(create_repairs=True), []
        )
        assert specs == []
        assert repairs == {}


class TestBuildVisibleAliasedRepairSpecs:
    """_build_visible_aliased_repair_specs: one re-hide repair
    per flagged source.

    The logic-layer producer of the visible-aliased repair
    specs + off-wire payloads. Asserts the per-finding shape,
    the issue-ID format, the placeholders, and the payload
    contents.
    """

    def test_no_findings_no_specs(self) -> None:
        specs, repairs = _build_visible_aliased_repair_specs(
            _config(create_repairs=True),
            [],
        )
        assert specs == []
        assert repairs == {}

    def test_one_finding_one_spec(self) -> None:
        cfg = _config(create_repairs=True)
        finding = VisibleAliasedEntityFinding(
            source_entity_id="switch.kitchen",
            wrapper_entity_id="kitchen",
            wrapper_target_domain="fan",
            source_friendly_name="Kitchen Fan",
            source_device_id="dev_kitchen",
            source_config_entry_id="ce_kitchen",
            source_device_name="Kitchen Switch",
            source_device_integrations=("zwave_js",),
        )
        specs, repairs = _build_visible_aliased_repair_specs(cfg, [finding])
        assert len(specs) == 1
        spec = specs[0]
        expected_id = helpers.repair_notification_id(
            cfg.notification_prefix,
            FixServices.VISIBLE_ALIASED_ENTITY,
            "switch.kitchen",
        )
        assert spec.notification_id == expected_id
        assert "__repair_" in spec.notification_id
        assert spec.translation_key == "edw_visible_aliased_entity"
        assert spec.translation_placeholders == {
            "source_entity_id": "switch.kitchen",
            "entities": "- `switch.kitchen` (Kitchen Fan)",
        }
        # Device-attached source: the repair carries a DeviceRef
        # (built from the handler-resolved name) plus the device's
        # integrations, so the confirm modal's attribution header
        # shows the Device / Integrations lines.
        assert spec.device == helpers.DeviceRef(
            device_id="dev_kitchen",
            name="Kitchen Switch",
        )
        assert spec.integrations == ("zwave_js",)
        assert spec.repair_callback is not None
        assert spec.repair_callback.service_name == (
            FixServices.VISIBLE_ALIASED_ENTITY.value
        )
        assert spec.repair_callback.notification_id == expected_id
        payload = repairs[expected_id]
        assert isinstance(payload, VisibleAliasedEntityRepair)
        assert payload.source_entity_id == "switch.kitchen"

    def test_deviceless_source_repair_has_no_device_ref(self) -> None:
        # A helper / template source with no device leaves
        # ``spec.device`` None, so the attribution header shows
        # only the automation line.
        cfg = _config(create_repairs=True)
        finding = VisibleAliasedEntityFinding(
            source_entity_id="switch.template_fan",
            wrapper_entity_id="template_fan",
            wrapper_target_domain="fan",
            source_friendly_name="Template Fan",
            source_device_id=None,
            source_config_entry_id=None,
        )
        specs, _ = _build_visible_aliased_repair_specs(cfg, [finding])
        assert specs[0].device is None

    def test_each_finding_gets_its_own_spec(self) -> None:
        cfg = _config(create_repairs=True)
        findings = [
            VisibleAliasedEntityFinding(
                source_entity_id="switch.foo",
                wrapper_entity_id="foo",
                wrapper_target_domain="fan",
                source_friendly_name="Foo",
                source_device_id=None,
                source_config_entry_id=None,
            ),
            VisibleAliasedEntityFinding(
                source_entity_id="switch.bar",
                wrapper_entity_id="bar",
                wrapper_target_domain="light",
                source_friendly_name="Bar",
                source_device_id=None,
                source_config_entry_id=None,
            ),
        ]
        specs, repairs = _build_visible_aliased_repair_specs(cfg, findings)
        assert len(specs) == 2
        assert len(repairs) == 2
        sources = {
            p.source_entity_id
            for p in repairs.values()
            if isinstance(p, VisibleAliasedEntityRepair)
        }
        assert sources == {"switch.foo", "switch.bar"}


class TestVisibleAliasedRepairBranch:
    """run_evaluation routes visible-aliased findings to exactly
    one surface, chosen by ``create_repairs``.

    Mirrors the device-drift one-surface-per-finding split: the
    aggregate ``{prefix}visible_aliased`` notification and the
    per-finding repairs are mutually exclusive.
    """

    _AGG_ID = "entity_defaults_watchdog_test__visible_aliased"

    def _run(
        self,
        cfg: Config,
    ) -> tuple[list[helpers.PersistentNotification], dict[str, EdwRepair]]:
        ev = run_evaluation(
            cfg,
            devices=[],
            deviceless_entities=[],
            peers_by_domain={},
            all_integrations=[],
            max_notifications=100,
            visible_aliased_candidates=[
                _vcandidate(source_entity_id="switch.foo"),
            ],
        )
        return ev.notifications, ev.repairs

    def _repair_specs(
        self,
        notifications: list[helpers.PersistentNotification],
    ) -> list[helpers.PersistentNotification]:
        out: list[helpers.PersistentNotification] = []
        for n in notifications:
            cb = n.repair_callback
            if cb is not None and cb.service_name == (
                FixServices.VISIBLE_ALIASED_ENTITY.value
            ):
                out.append(n)
        return out

    def test_repairs_on_emits_repair_not_aggregate(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=True))
        repair_specs = self._repair_specs(notifications)
        assert len(repair_specs) == 1
        # The aggregate bucket notification is suppressed --
        # not even an inactive slot; the sweep clears any prior.
        assert not [
            n for n in notifications if n.notification_id == self._AGG_ID
        ]
        assert any(
            isinstance(p, VisibleAliasedEntityRepair) for p in repairs.values()
        )

    def test_repairs_off_emits_aggregate_not_repair(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=False))
        assert self._repair_specs(notifications) == []
        agg = [n for n in notifications if n.notification_id == self._AGG_ID]
        assert len(agg) == 1
        assert agg[0].active is True
        assert not any(
            isinstance(p, VisibleAliasedEntityRepair) for p in repairs.values()
        )

    def test_check_disabled_emits_neither(self) -> None:
        cfg = _config(
            create_repairs=True,
            drift_checks=frozenset(
                {DRIFT_CHECK_DEVICE_ENTITY_ID},
            ),
        )
        notifications, repairs = self._run(cfg)
        assert self._repair_specs(notifications) == []
        assert not any(
            isinstance(p, VisibleAliasedEntityRepair) for p in repairs.values()
        )

    def test_excluded_source_yields_no_repair(self) -> None:
        cfg = _config(
            create_repairs=True,
            exclude_entity_ids=["switch.foo"],
        )
        notifications, repairs = self._run(cfg)
        assert self._repair_specs(notifications) == []
        assert not any(
            isinstance(p, VisibleAliasedEntityRepair) for p in repairs.values()
        )


class TestDevicelessIdDriftRepairBranch:
    """run_evaluation routes deviceless id-drift to exactly one
    surface, chosen by ``create_repairs``.

    Mirrors the device-drift + visible-aliased split: the
    aggregate ``{prefix}deviceless`` notification and the
    per-entity id-drift repairs are mutually exclusive.
    """

    _AGG_ID = "entity_defaults_watchdog_test__deviceless"

    def _run(
        self,
        cfg: Config,
    ) -> tuple[list[helpers.PersistentNotification], dict[str, EdwRepair]]:
        ev = run_evaluation(
            cfg,
            devices=[],
            deviceless_entities=[
                _deviceless(
                    "automation.old",
                    effective_name="New",
                    platform="automation",
                    unique_id="1",
                ),
            ],
            peers_by_domain={"automation": {"old"}},
            all_integrations=[],
            max_notifications=100,
        )
        return ev.notifications, ev.repairs

    def _repair_specs(
        self,
        notifications: list[helpers.PersistentNotification],
    ) -> list[helpers.PersistentNotification]:
        return [
            n
            for n in notifications
            if n.repair_callback is not None
            and n.repair_callback.service_name
            == FixServices.ENTITY_ID_DRIFT.value
        ]

    def test_repairs_on_emits_repair_not_aggregate(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=True))
        assert len(self._repair_specs(notifications)) == 1
        # The aggregate bucket notification is suppressed --
        # not even an inactive slot; the sweep clears any prior.
        assert not [
            n for n in notifications if n.notification_id == self._AGG_ID
        ]
        assert any(isinstance(p, EntityIdDriftRepair) for p in repairs.values())

    def test_repairs_off_emits_aggregate_not_repair(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=False))
        assert self._repair_specs(notifications) == []
        agg = [n for n in notifications if n.notification_id == self._AGG_ID]
        assert len(agg) == 1
        assert agg[0].active is True
        assert not any(
            isinstance(p, EntityIdDriftRepair) for p in repairs.values()
        )

    def test_check_disabled_emits_neither(self) -> None:
        cfg = _config(
            create_repairs=True,
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_ID}),
        )
        notifications, repairs = self._run(cfg)
        assert self._repair_specs(notifications) == []
        assert not [
            n for n in notifications if n.notification_id == self._AGG_ID
        ]


class TestRenameTopLevelYamlKey:
    """rename_top_level_yaml_key: rewrite one column-0 block
    key, preserving the rest of the file verbatim.
    """

    def test_renames_the_one_key(self) -> None:
        text = (
            "old_key:\n"
            "  alias: My Script\n"
            "  sequence:\n"
            "    - delay: 1\n"
            "other_key:\n"
            "  alias: Other\n"
        )
        out = rename_top_level_yaml_key(text, "old_key", "new_slug")
        assert out == (
            "new_slug:\n"
            "  alias: My Script\n"
            "  sequence:\n"
            "    - delay: 1\n"
            "other_key:\n"
            "  alias: Other\n"
        )

    def test_does_not_touch_indented_or_value_occurrences(self) -> None:
        # An ``old_key:`` that appears indented (a nested
        # mapping key) or in a value must not be rewritten --
        # only the column-0 block key is.
        text = (
            "old_key:\n"
            "  alias: old_key reference in value\n"
            "  nested:\n"
            "    old_key: keep\n"
        )
        out = rename_top_level_yaml_key(text, "old_key", "new_slug")
        assert out == (
            "new_slug:\n"
            "  alias: old_key reference in value\n"
            "  nested:\n"
            "    old_key: keep\n"
        )

    def test_raises_when_key_absent(self) -> None:
        with pytest.raises(ValueError, match="not found exactly once"):
            rename_top_level_yaml_key("foo:\n  bar: 1\n", "missing", "x")

    def test_raises_when_key_appears_twice(self) -> None:
        text = "dup:\n  a: 1\ndup:\n  b: 2\n"
        with pytest.raises(ValueError, match="not found exactly once"):
            rename_top_level_yaml_key(text, "dup", "x")


def _script_info(
    entity_id: str = "script.bath_fan",
    unique_id: str = "bath_fan",
    friendly_name: str = "Bath Fan",
) -> ScriptInfo:
    return ScriptInfo(
        entity_id=entity_id,
        unique_id=unique_id,
        friendly_name=friendly_name,
    )


class TestEvaluateScriptYamlKeyDrift:
    """_evaluate_script_yaml_key_drift: flag scripts whose YAML
    block key no longer matches the entity-id slug, with the
    UI-script false-positive guard.
    """

    def test_drift_flagged_when_key_differs_from_slug(self) -> None:
        cfg = _config()
        findings = _evaluate_script_yaml_key_drift(
            cfg,
            [_script_info(entity_id="script.bathroom", unique_id="bath_fan")],
        )
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, ScriptYamlKeyDriftFinding)
        assert f.entity_id == "script.bathroom"
        assert f.old_key == "bath_fan"
        assert f.new_slug == "bathroom"
        assert f.friendly_name == "Bath Fan"

    def test_no_drift_when_key_equals_slug(self) -> None:
        cfg = _config()
        findings = _evaluate_script_yaml_key_drift(
            cfg,
            [_script_info(entity_id="script.bath_fan", unique_id="bath_fan")],
        )
        assert findings == []

    def test_drift_flagged_regardless_of_key_shape(self) -> None:
        # No readable-slug guard: any script whose unique_id
        # (the block key / service name) differs from the
        # entity-id slug is flagged, whatever the key's shape.
        cfg = _config()
        findings = _evaluate_script_yaml_key_drift(
            cfg,
            [_script_info(entity_id="script.bathroom", unique_id="1700000000")],
        )
        assert len(findings) == 1
        assert findings[0].old_key == "1700000000"
        assert findings[0].new_slug == "bathroom"

    def test_empty_unique_id_skipped(self) -> None:
        cfg = _config()
        findings = _evaluate_script_yaml_key_drift(
            cfg,
            [_script_info(entity_id="script.bathroom", unique_id="")],
        )
        assert findings == []

    def test_excluded_entity_skipped(self) -> None:
        cfg = _config(exclude_entity_ids=["script.bathroom"])
        findings = _evaluate_script_yaml_key_drift(
            cfg,
            [_script_info(entity_id="script.bathroom", unique_id="bath_fan")],
        )
        assert findings == []


class TestBuildScriptYamlKeyRepairSpecs:
    """_build_script_yaml_key_repair_specs: one block-key-rename
    repair per finding.
    """

    def test_no_findings_no_specs(self) -> None:
        specs, repairs = _build_script_yaml_key_repair_specs(
            _config(create_repairs=True),
            [],
        )
        assert specs == []
        assert repairs == {}

    def test_one_finding_one_spec(self) -> None:
        cfg = _config(create_repairs=True)
        finding = ScriptYamlKeyDriftFinding(
            entity_id="script.bathroom",
            old_key="bath_fan",
            new_slug="bathroom",
            friendly_name="Bath Fan",
        )
        specs, repairs = _build_script_yaml_key_repair_specs(cfg, [finding])
        assert len(specs) == 1
        spec = specs[0]
        expected_id = helpers.repair_notification_id(
            cfg.notification_prefix,
            FixServices.SCRIPT_YAML_KEY_DRIFT,
            "bathroom",
        )
        assert spec.notification_id == expected_id
        assert "__repair_" in spec.notification_id
        # Scripts are deviceless; the only attribution context
        # is the built-in ``script`` integration.
        assert spec.integrations == ("script",)
        assert spec.translation_key == "edw_script_yaml_key_drift"
        assert spec.translation_placeholders == {
            "entity_id": "script.bathroom",
            "old_key": "bath_fan",
            "new_slug": "bathroom",
        }
        assert spec.repair_callback is not None
        assert spec.repair_callback.service_name == (
            FixServices.SCRIPT_YAML_KEY_DRIFT.value
        )
        assert spec.repair_callback.notification_id == expected_id
        payload = repairs[expected_id]
        assert isinstance(payload, ScriptYamlKeyDriftRepair)
        assert payload.old_key == "bath_fan"
        assert payload.new_slug == "bathroom"
        assert payload.entity_id == "script.bathroom"

    def test_each_finding_gets_its_own_spec(self) -> None:
        cfg = _config(create_repairs=True)
        findings = [
            ScriptYamlKeyDriftFinding(
                entity_id="script.one",
                old_key="key_one",
                new_slug="one",
                friendly_name="One",
            ),
            ScriptYamlKeyDriftFinding(
                entity_id="script.two",
                old_key="key_two",
                new_slug="two",
                friendly_name="Two",
            ),
        ]
        specs, repairs = _build_script_yaml_key_repair_specs(cfg, findings)
        assert len(specs) == 2
        assert len(repairs) == 2
        slugs = {
            p.new_slug
            for p in repairs.values()
            if isinstance(p, ScriptYamlKeyDriftRepair)
        }
        assert slugs == {"one", "two"}


class TestScriptYamlKeyRepairBranch:
    """run_evaluation routes script-yaml-key findings to the
    repairs surface only -- there is no notification fallback.
    """

    def _run(
        self,
        cfg: Config,
        *,
        unique_id: str = "bath_fan",
    ) -> tuple[list[helpers.PersistentNotification], dict[str, EdwRepair]]:
        ev = run_evaluation(
            cfg,
            devices=[],
            deviceless_entities=[],
            peers_by_domain={},
            all_integrations=[],
            max_notifications=100,
            script_infos=[
                _script_info(
                    entity_id="script.bathroom",
                    unique_id=unique_id,
                ),
            ],
        )
        return ev.notifications, ev.repairs

    def _repair_specs(
        self,
        notifications: list[helpers.PersistentNotification],
    ) -> list[helpers.PersistentNotification]:
        out: list[helpers.PersistentNotification] = []
        for n in notifications:
            cb = n.repair_callback
            if cb is not None and cb.service_name == (
                FixServices.SCRIPT_YAML_KEY_DRIFT.value
            ):
                out.append(n)
        return out

    def test_repairs_on_emits_repair_and_payload(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=True))
        repair_specs = self._repair_specs(notifications)
        assert len(repair_specs) == 1
        assert any(
            isinstance(p, ScriptYamlKeyDriftRepair) for p in repairs.values()
        )

    def test_repairs_on_emits_no_plain_notification(self) -> None:
        # The finding must surface only on the repairs surface
        # -- no extra notification spec carrying the script.
        notifications, _ = self._run(_config(create_repairs=True))
        non_repair = [
            n
            for n in notifications
            if n.repair_callback is None
            and "bathroom" in (n.message or n.notification_id)
        ]
        assert non_repair == []

    def test_repairs_off_emits_nothing(self) -> None:
        notifications, repairs = self._run(_config(create_repairs=False))
        assert self._repair_specs(notifications) == []
        assert not any(
            isinstance(p, ScriptYamlKeyDriftRepair) for p in repairs.values()
        )
        # No notification fallback either -- silent by design.
        non_repair = [
            n
            for n in notifications
            if n.repair_callback is None
            and "bathroom" in (n.message or n.notification_id)
        ]
        assert non_repair == []

    def test_check_disabled_emits_neither_and_stat_zero(self) -> None:
        cfg = _config(
            create_repairs=True,
            drift_checks=frozenset({DRIFT_CHECK_DEVICE_ENTITY_ID}),
        )
        ev = run_evaluation(
            cfg,
            devices=[],
            deviceless_entities=[],
            peers_by_domain={},
            all_integrations=[],
            max_notifications=100,
            script_infos=[_script_info(unique_id="bath_fan")],
        )
        assert self._repair_specs(ev.notifications) == []
        assert not any(
            isinstance(p, ScriptYamlKeyDriftRepair) for p in ev.repairs.values()
        )
        assert ev.stat_script_yaml_key_flagged == 0

    def test_stat_always_set_when_check_enabled(self) -> None:
        # Stat is set regardless of create_repairs.
        cfg = _config(create_repairs=False)
        ev = run_evaluation(
            cfg,
            devices=[],
            deviceless_entities=[],
            peers_by_domain={},
            all_integrations=[],
            max_notifications=100,
            script_infos=[
                _script_info(
                    entity_id="script.bathroom",
                    unique_id="bath_fan",
                ),
            ],
        )
        assert ev.stat_script_yaml_key_flagged == 1


class TestScriptYamlKeyDriftCheckConstant:
    def test_constant_value(self) -> None:
        assert DRIFT_CHECK_SCRIPT_YAML_KEY == "script-yaml-key"

    def test_in_check_all(self) -> None:
        assert DRIFT_CHECK_SCRIPT_YAML_KEY in CHECK_ALL


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
