#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.375",
#     "zwave-js-server-python==0.73.1",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the Node -> ParamMeta adapter.

Builds genuine ``zwave_js_server`` Node objects from state dicts (the
``start_listening`` shape, the same the HA driver + the 3000 server
emit) with a mock client, so the mapping is exercised against the real
model rather than hand-mocked attributes.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from zwave_js_server.model.node import Node  # noqa: E402

from custom_components.blueprint_toolkit.zwave_parameter_manager.adapter import (  # noqa: E402, E501
    actual_values,
    build_device,
    derive_device_types,
    node_param_metas,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    CATALOG,
    WAKE_UP_INTERVAL_VALUE,
    Device,
    DeviceType,
    GenericParamNames,
    LabelMatch,
    MappingTable,
    ParamId,
    ParamValue,
    ResolutionStatus,
    resolve,
)


def _config_value(
    prop: int,
    label: str,
    value: int | None,
    lo: int,
    hi: int,
    states: dict[str, str] | None = None,
    unit: str | None = None,
) -> dict[str, object]:
    return {
        "endpoint": 0,
        "commandClass": 112,
        "commandClassName": "Configuration",
        "property": prop,
        "propertyName": label,
        "value": value,
        "metadata": {
            "type": "number",
            "label": label,
            "min": lo,
            "max": hi,
            "unit": unit,
            "states": states or {},
            "writeable": True,
        },
    }


def _wakeup_value(value: int) -> dict[str, object]:
    return {
        "endpoint": 0,
        "commandClass": 132,
        "commandClassName": "Wake Up",
        "property": "wakeUpInterval",
        "propertyName": "Wake-up interval",
        "value": value,
        "metadata": {
            "type": "number",
            "label": "Wake-up interval",
            "min": 0,
            "max": 86400,
            "unit": "seconds",
            "writeable": True,
        },
    }


def _sensor_value(cc: int, prop: str, value: float) -> dict[str, object]:
    """A read-only sensor reading -- must be excluded from params."""

    return {
        "endpoint": 0,
        "commandClass": cc,
        "commandClassName": "Multilevel Sensor",
        "property": prop,
        "propertyName": prop,
        "value": value,
        "metadata": {"type": "number", "label": prop, "writeable": False},
    }


def _node(
    node_id: int,
    values: list[dict[str, object]],
    *,
    name: str | None = None,
    is_listening: bool = False,
    manufacturer: str = "Zooz",
    model: str = "ZSE11",
) -> Node:
    data = {
        "nodeId": node_id,
        "index": 0,
        "status": 1,
        "ready": True,
        "isListening": is_listening,
        "isRouting": True,
        "isSecure": False,
        "name": name,
        "deviceConfig": {"manufacturer": manufacturer, "label": model},
        "deviceClass": {
            "basic": {"key": 3, "label": "Routing Slave"},
            "generic": {"key": 7, "label": "Notification Sensor"},
            "specific": {"key": 0, "label": "Unused"},
        },
        "endpoints": [{"nodeId": node_id, "index": 0}],
        "values": values,
    }
    # data is the hand-built start_listening wire shape; the precise
    # NodeDataType TypedDict is not re-exported for a clean import.
    return Node(MagicMock(), data)  # type: ignore[arg-type]


def test_includes_config_and_wakeup_excludes_sensor() -> None:
    node = _node(
        273,
        [
            _config_value(
                12, "Motion Sensor Sensitivity", 8, 0, 8, {"0": "Disable"}
            ),
            _config_value(
                19,
                "Flash LED on Motion",
                1,
                0,
                1,
                {"0": "Disable", "1": "Enable"},
            ),
            _wakeup_value(3600),
            _sensor_value(49, "Air temperature", 21.5),
        ],
    )
    by_id = {m.id: m for m in node_param_metas(node)}
    # The read-only multilevel-sensor reading is excluded.
    assert set(by_id) == {
        ParamId(112, 12),
        ParamId(112, 19),
        ParamId(132, "wakeUpInterval"),
    }

    sens = by_id[ParamId(112, 12)]
    assert sens.label == "Motion Sensor Sensitivity"
    assert sens.range == (0, 8)
    assert sens.states == {0: "Disable"}  # str keys folded to int

    led = by_id[ParamId(112, 19)]
    assert led.states == {0: "Disable", 1: "Enable"}

    wake = by_id[ParamId(132, "wakeUpInterval")]
    assert wake.unit == "seconds"
    assert wake.range == (0, 86400)


def test_wakeup_interval_unit_backfilled_when_missing() -> None:
    """zwave-js's persisted metadata for the protocol-level Wake Up
    value-id omits the unit field; the adapter backfills the spec
    value (seconds) so the resolver's VALUE conversion can run."""

    raw: dict[str, object] = {
        "endpoint": 0,
        "commandClass": 132,
        "commandClassName": "Wake Up",
        "property": "wakeUpInterval",
        "propertyName": "Wake-up interval",
        "value": 3600,
        "metadata": {
            "type": "number",
            "label": "Wake-up interval",
            "min": 0,
            "max": 86400,
            "writeable": True,
        },
    }
    node = _node(273, [raw])
    meta = node_param_metas(node)[0]
    assert meta.id == ParamId(132, "wakeUpInterval")
    assert meta.unit == "seconds"


def test_adapter_output_resolves() -> None:
    """The ParamMeta the adapter emits feed the resolver end to end."""

    node = _node(
        273,
        [
            _config_value(
                12, "Motion Sensor Sensitivity", 4, 0, 8, {"0": "Disable"}
            ),
            _wakeup_value(604800),
        ],
    )
    device = Device(
        node_id=273,
        name="Office",
        manufacturer="Zooz",
        model="ZSE11",
        is_listening=False,
        params=node_param_metas(node),
    )
    mapping = MappingTable(
        locators={
            GenericParamNames.MOTION_SENSITIVITY: LabelMatch(
                ("Motion Sensor Sensitivity",)
            ),
            GenericParamNames.WAKE_UP_INTERVAL: WAKE_UP_INTERVAL_VALUE,
        },
        off_labels=frozenset({"disable"}),
    )
    gp = CATALOG[GenericParamNames.MOTION_SENSITIVITY]
    res = resolve(device, gp, mapping, ParamValue.of(gp, 10))
    assert res.status is ResolutionStatus.RESOLVED
    assert res.value == 8  # generic 10 -> device max (usable 1..8)

    wake_gp = CATALOG[GenericParamNames.WAKE_UP_INTERVAL]
    wake = resolve(device, wake_gp, mapping, ParamValue.of(wake_gp, 3600))
    assert (wake.id, wake.value) == (ParamId(132, "wakeUpInterval"), 3600)


# -- build_device + actual_values --------------------------------


def test_build_device_identity_flags_and_params() -> None:
    node = _node(
        264,
        [
            _config_value(
                5, "Motion Sensor Sensitivity", 8, 0, 8, {"0": "Disable"}
            ),
            _wakeup_value(14400),
        ],
        name="Main Bath",
        is_listening=False,
        manufacturer="Zooz",
        model="ZSE44",
    )
    device = build_device(
        node,
        device_id="dev-264",
        device_types=frozenset({DeviceType.HUMIDITY}),
    )
    assert device.node_id == 264
    assert device.name == "Main Bath"
    # Identity is the device_config -- what the mapping selectors + quirks
    # match on -- not the (often-null) productLabel.
    assert (device.manufacturer, device.model) == ("Zooz", "ZSE44")
    assert device.is_listening is False
    assert device.device_id == "dev-264"
    assert device.device_types == frozenset({DeviceType.HUMIDITY})
    assert {p.id for p in device.params} == {
        ParamId(112, 5),
        ParamId(132, "wakeUpInterval"),
    }


def test_build_device_mains_and_blank_name() -> None:
    node = _node(
        50,
        [_config_value(1, "LED Brightness", 5, 0, 10)],
        name=None,
        is_listening=True,
        manufacturer="Zooz",
        model="ZEN72",
    )
    device = build_device(node, device_id=None, device_types=frozenset())
    assert device.is_listening is True
    assert device.name == ""  # node.name None -> ""
    assert device.device_id is None
    assert (device.manufacturer, device.model) == ("Zooz", "ZEN72")


def test_actual_values_match_param_keys_and_unread_is_none() -> None:
    node = _node(
        21,
        [
            _config_value(12, "Sensitivity", 4, 0, 8),
            _config_value(20, "LED", None, 0, 1),  # not reported -> unread
            _wakeup_value(3600),
            _sensor_value(49, "Air temperature", 21.5),  # read-only, excluded
        ],
    )
    assert actual_values(node) == {
        ParamId(112, 12): 4,
        ParamId(112, 20): None,
        ParamId(132, "wakeUpInterval"): 3600,
    }


def test_actual_values_folds_boolean_param_to_int() -> None:
    # A boolean-type config param reports a Python bool; it folds to its int
    # form so it compares against the resolver's int target.
    node = _node(7, [_config_value(1, "Enabled", True, 0, 1)])
    assert actual_values(node) == {ParamId(112, 1): 1}


def test_param_metas_and_actuals_share_one_key_space() -> None:
    # A ParamMeta's identity and the actual_values keys are the same ParamId
    # set -- the convergence join depends on it (one shared derivation).
    node = _node(
        21, [_config_value(12, "Sensitivity", 4, 0, 8), _wakeup_value(3600)]
    )
    assert {m.id for m in node_param_metas(node)} == set(actual_values(node))


# -- device_types derivation -------------------------------------


def test_derive_device_types_multisensor() -> None:
    tags = derive_device_types(
        [
            ("binary_sensor", "motion"),
            ("sensor", "temperature"),
            ("sensor", "illuminance"),
            ("sensor", "battery"),  # diagnostic -> ignored
            ("sensor", None),  # no device_class -> ignored
            ("update", None),
            ("button", None),
        ]
    )
    assert tags == frozenset(
        {DeviceType.MOTION, DeviceType.TEMPERATURE, DeviceType.ILLUMINANCE}
    )


def test_derive_device_types_contact_collapses() -> None:
    for device_class in ("window", "door", "garage_door"):
        assert derive_device_types(
            [("binary_sensor", device_class)]
        ) == frozenset({DeviceType.CONTACT})


def test_derive_device_types_lock_and_siren_from_domain() -> None:
    assert derive_device_types(
        [("lock", None), ("sensor", "battery"), ("button", None)]
    ) == frozenset({DeviceType.LOCK})
    assert derive_device_types([("siren", None)]) == frozenset(
        {DeviceType.SIREN}
    )


def test_derive_device_types_smoke_co_alarm() -> None:
    assert derive_device_types(
        [("binary_sensor", "smoke"), ("binary_sensor", "carbon_monoxide")]
    ) == frozenset({DeviceType.SMOKE, DeviceType.CARBON_MONOXIDE})


def test_derive_device_types_diagnostics_only_is_empty() -> None:
    assert (
        derive_device_types(
            [
                ("sensor", "battery"),
                ("sensor", "signal_strength"),
                ("update", None),
            ]
        )
        == frozenset()
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
