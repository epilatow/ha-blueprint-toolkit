#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pyyaml",
#     "pytest-homeassistant-custom-component==0.13.357",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the zwave_parameter_manager logic module.

Device + param fixtures mirror real metadata from the author's fleet
(Zooz ZSE11/ZSE70/ZSE44, Aeotec ZWA045/ZWA039) plus synthetic
outliers (a descending sensitivity scale, a 0.1%-unit humidity
sensor, a seconds-unit check interval). The MappingTable fixture
stands in for the generated mapping data the resolver consumes.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    CATALOG,
    WAKE_UP_INTERVAL_VALUE,
    Device,
    DeviceType,
    GenericParamNames,
    LabelMatch,
    MappingTable,
    ModelId,
    ModelQuirk,
    ParamMeta,
    ParamType,
    ParamValue,
    Plan,
    Policy,
    Power,
    ResolutionStatus,
    Selector,
    evaluate_policies,
    policy_matches,
    resolve,
    selector_matches,
    validate_value,
)

# -- Concept-name aliases + value helper -------------------------

MS = GenericParamNames.MOTION_SENSITIVITY
LOM = GenericParamNames.LIGHT_ON_MOTION
HRT = GenericParamNames.HUMIDITY_REPORT_THRESHOLD
TCI = GenericParamNames.THRESHOLD_CHECK_INTERVAL
WUI = GenericParamNames.WAKE_UP_INTERVAL


def pv(name: GenericParamNames, value: bool | int | float) -> ParamValue:
    """Build a ParamValue for a concept the way the boundary would."""

    return ParamValue.of(CATALOG[name], value)


# -- Mapping table fixture (stands in for generated data) --------

MAPPING = MappingTable(
    locators={
        MS: LabelMatch(
            (
                "Motion Sensor Sensitivity",
                "Motion Sensitivity",
                "PIR Sensitivity",
            )
        ),
        LOM: LabelMatch(("Flash LED on Motion", "LED Indicator (Motion)")),
        HRT: LabelMatch(
            ("Humidity Report Threshold", "Humidity Change Report Threshold")
        ),
        TCI: LabelMatch(("Threshold Check Interval",)),
        WUI: WAKE_UP_INTERVAL_VALUE,
    },
    off_labels=frozenset({"disable", "disabled", "off", "no", "none"}),
    on_labels=frozenset({"enable", "enabled", "on", "yes"}),
    low_tokens=("lowest", "low"),
    high_tokens=("highest", "high"),
)

# -- Parameter fixtures (real metadata) --------------------------

ZSE11_SENS = ParamMeta(
    command_class=112,
    property=12,
    label="Motion Sensor Sensitivity",
    range=(0, 8),
    states={0: "Disable"},
)
ZSE11_LED = ParamMeta(
    command_class=112,
    property=19,
    label="Flash LED on Motion",
    range=(0, 1),
    states={0: "Disable", 1: "Enable"},
)
ZWA045_SENS = ParamMeta(
    command_class=112,
    property=4,
    label="Motion Sensitivity",
    range=(0, 3),
    states={0: "Disable", 1: "Low", 2: "Medium", 3: "High"},
)
ZSE44_HUM = ParamMeta(
    command_class=112,
    property=4,
    label="Humidity Report Threshold",
    range=(0, 50),
    unit="%",
    states={0: "Disable"},
)
ZWA039_HUM = ParamMeta(
    command_class=112,
    property=2,
    label="Humidity Change Report Threshold",
    range=(0, 20),
    unit="%",
    states={0: "Disable"},
)
ZWA039_CHECK = ParamMeta(
    command_class=112,
    property=3,
    label="Threshold Check Interval",
    range=(1, 255),
    unit="minutes",
)
WAKEUP = ParamMeta(
    command_class=132,
    property="wakeUpInterval",
    label="Wake Up Interval",
    range=(0, 86400),
    unit="seconds",
)

# -- Device fixtures (node_id is the universal key) --------------

ZSE11 = Device(
    node_id=273,
    name="Office",
    manufacturer="Zooz",
    model="ZSE11",
    is_listening=False,
    device_types=frozenset({DeviceType.MOTION}),
    params=(ZSE11_SENS, ZSE11_LED, WAKEUP),
)
ZWA045 = Device(
    node_id=256,
    name="Den Hall",
    manufacturer="Aeotec Ltd.",
    model="ZWA045",
    is_listening=False,
    device_types=frozenset({DeviceType.MOTION}),
    params=(ZWA045_SENS, WAKEUP),
)
ZSE44 = Device(
    node_id=264,
    name="Main Bath",
    manufacturer="Zooz",
    model="ZSE44",
    is_listening=False,
    device_types=frozenset({DeviceType.HUMIDITY, DeviceType.TEMPERATURE}),
    params=(ZSE44_HUM, WAKEUP),
)
ZWA039 = Device(
    node_id=42,
    name="Guest Bath",
    manufacturer="Aeotec Ltd.",
    model="ZWA039",
    is_listening=False,
    device_types=frozenset({DeviceType.HUMIDITY, DeviceType.TEMPERATURE}),
    params=(ZWA039_HUM, ZWA039_CHECK, WAKEUP),
)
REPEATER = Device(
    node_id=50,
    name="Repeater",
    manufacturer="Zooz",
    model="ZAC38",
    is_listening=True,
    params=(),
)


def test_catalog_covers_every_name() -> None:
    assert set(CATALOG) == set(GenericParamNames)
    assert CATALOG[LOM].param_type is ParamType.BOOL
    assert CATALOG[MS].param_type is ParamType.RANGE
    assert CATALOG[MS].range == (1, 10)
    assert CATALOG[HRT].units == "%"


def test_range_params_carry_a_scale() -> None:
    for gp in CATALOG.values():
        if gp.param_type is ParamType.RANGE:
            assert gp.range is not None
            lo, hi = gp.range
            assert lo < hi
        else:
            assert gp.range is None


# -- MappingTable invariants -------------------------------------


def test_mapping_rejects_overlapping_label_categories() -> None:
    import pytest

    with pytest.raises(ValueError, match="off_labels and on_labels"):
        MappingTable(
            locators={},
            off_labels=frozenset({"off", "no"}),
            on_labels=frozenset({"on", "no"}),
        )


def test_mapping_disjoint_check_is_case_insensitive() -> None:
    import pytest

    with pytest.raises(ValueError, match="low_tokens and high_tokens"):
        MappingTable(
            locators={},
            low_tokens=("low",),
            high_tokens=("High", "LOW"),
        )


# -- validate_value (strict input, at the boundary) --------------


def test_validate_bool_rejects_non_bool() -> None:
    assert validate_value(CATALOG[LOM], True) == []
    assert validate_value(CATALOG[LOM], 1)  # non-empty errors


def test_validate_range_type_and_bounds() -> None:
    assert validate_value(CATALOG[MS], 5) == []
    assert validate_value(CATALOG[MS], 11)  # out of range
    assert validate_value(CATALOG[MS], True)  # bool != range


def test_validate_value_rejects_negative() -> None:
    assert validate_value(CATALOG[HRT], 2) == []
    assert validate_value(CATALOG[HRT], -1)


def test_validate_value_rejects_non_finite() -> None:
    assert validate_value(CATALOG[HRT], float("nan"))
    assert validate_value(CATALOG[HRT], float("inf"))
    assert validate_value(CATALOG[HRT], float("-inf"))


# -- BOOL (light_on_motion) --------------------------------------


def test_bool_false_maps_to_off_state() -> None:
    res = resolve(ZSE11, CATALOG[LOM], MAPPING, pv(LOM, False))
    assert res.status is ResolutionStatus.RESOLVED
    assert (res.command_class, res.property, res.value) == (112, 19, 0)


def test_bool_true_maps_to_on_state() -> None:
    res = resolve(ZSE11, CATALOG[LOM], MAPPING, pv(LOM, True))
    assert res.value == 1


def test_bool_quirk_overrides_value() -> None:
    mapping = MappingTable(
        locators=MAPPING.locators,
        quirks={
            (LOM, ModelId("Zooz", "ZSE11")): ModelQuirk(off_value=0, on_value=7)
        },
        off_labels=MAPPING.off_labels,
        on_labels=MAPPING.on_labels,
    )
    assert resolve(ZSE11, CATALOG[LOM], mapping, pv(LOM, True)).value == 7


# -- RANGE (motion_sensitivity) ----------------------------------


def test_range_extremes_zse11() -> None:
    lo = resolve(ZSE11, CATALOG[MS], MAPPING, pv(MS, 1))
    hi = resolve(ZSE11, CATALOG[MS], MAPPING, pv(MS, 10))
    assert lo.value == 1  # 0 is Disable -> usable floor 1
    assert hi.value == 8


def test_range_small_param_zwa045() -> None:
    assert resolve(ZWA045, CATALOG[MS], MAPPING, pv(MS, 10)).value == 3
    assert resolve(ZWA045, CATALOG[MS], MAPPING, pv(MS, 1)).value == 1
    assert resolve(ZWA045, CATALOG[MS], MAPPING, pv(MS, 5)).value == 2


def test_range_descending_detected_when_no_quirk() -> None:
    dev = Device(
        node_id=900,
        name="Old PIR",
        manufacturer="Acme",
        model="OLD",
        is_listening=False,
        params=(
            ParamMeta(
                command_class=112,
                property=5,
                label="PIR Sensitivity",
                range=(1, 7),
                states={1: "Highest", 4: "Medium", 7: "Lowest"},
            ),
        ),
    )
    assert resolve(dev, CATALOG[MS], MAPPING, pv(MS, 10)).value == 1
    assert resolve(dev, CATALOG[MS], MAPPING, pv(MS, 1)).value == 7


def test_range_invert_quirk_is_primary() -> None:
    mapping = MappingTable(
        locators=MAPPING.locators,
        quirks={(MS, ModelId("Zooz", "ZSE11")): ModelQuirk(invert=True)},
        off_labels=MAPPING.off_labels,
    )
    assert resolve(ZSE11, CATALOG[MS], mapping, pv(MS, 10)).value == 1


def test_range_off_state_mid_scale_is_unmappable() -> None:
    dev = Device(
        node_id=901,
        name="Mid-off",
        manufacturer="Acme",
        model="HOLE",
        is_listening=False,
        params=(
            ParamMeta(
                command_class=112,
                property=1,
                label="Motion Sensitivity",
                range=(0, 8),
                states={0: "Disable", 4: "Disable"},
            ),
        ),
    )
    res = resolve(dev, CATALOG[MS], MAPPING, pv(MS, 5))
    assert res.status is ResolutionStatus.UNMAPPABLE


# -- VALUE (humidity / interval / wake-up) -----------------------


def test_value_percent_passthrough() -> None:
    res = resolve(ZSE44, CATALOG[HRT], MAPPING, pv(HRT, 2))
    assert res.value == 2


def test_value_subpercent_scaled() -> None:
    dev = Device(
        node_id=902,
        name="NEO",
        manufacturer="NEO",
        model="PD07",
        is_listening=False,
        params=(
            ParamMeta(
                command_class=112,
                property=40,
                label="Humidity Report Threshold",
                range=(0, 255),
                unit="0.1 %",
                states={0: "Disable"},
            ),
        ),
    )
    assert resolve(dev, CATALOG[HRT], MAPPING, pv(HRT, 2)).value == 20


def test_value_minutes_to_seconds_with_clamp() -> None:
    dev = Device(
        node_id=903,
        name="ZWA023",
        manufacturer="Aeotec Ltd.",
        model="ZWA023",
        is_listening=False,
        params=(
            ParamMeta(
                command_class=112,
                property=3,
                label="Threshold Check Interval",
                range=(60, 65535),
                unit="seconds",
            ),
        ),
    )
    assert resolve(dev, CATALOG[TCI], MAPPING, pv(TCI, 1)).value == 60
    assert resolve(dev, CATALOG[TCI], MAPPING, pv(TCI, 2000)).value == 65535


def test_wake_up_interval_fixed_value_id() -> None:
    res = resolve(ZSE11, CATALOG[WUI], MAPPING, pv(WUI, 3600))
    assert res.status is ResolutionStatus.RESOLVED
    assert (res.command_class, res.property, res.value) == (
        132,
        "wakeUpInterval",
        3600,
    )


# -- not-applicable / ambiguous ----------------------------------


def test_not_applicable_when_param_absent() -> None:
    res = resolve(ZWA045, CATALOG[LOM], MAPPING, pv(LOM, False))
    assert res.status is ResolutionStatus.NOT_APPLICABLE


def test_ambiguous_when_multiple_params_match() -> None:
    dupe = Device(
        node_id=904,
        name="Twin",
        manufacturer="Acme",
        model="DUP",
        is_listening=False,
        params=(
            ParamMeta(112, 1, "Motion Sensitivity", range=(0, 10)),
            ParamMeta(112, 2, "PIR Sensitivity", range=(0, 10)),
        ),
    )
    res = resolve(dupe, CATALOG[MS], MAPPING, pv(MS, 5))
    assert res.status is ResolutionStatus.AMBIGUOUS


# -- Selectors ---------------------------------------------------


def test_selector_manufacturer_case_insensitive() -> None:
    assert selector_matches(Selector(manufacturer="zooz"), ZSE11)
    assert not selector_matches(Selector(manufacturer="aeotec ltd."), ZSE11)


def test_selector_power_battery_is_not_listening() -> None:
    assert selector_matches(Selector(power=Power.BATTERY), ZSE11)
    assert not selector_matches(Selector(power=Power.BATTERY), REPEATER)
    assert selector_matches(Selector(power=Power.MAINS), REPEATER)


def test_selector_device_type() -> None:
    assert selector_matches(Selector(device_type=DeviceType.HUMIDITY), ZSE44)
    assert not selector_matches(
        Selector(device_type=DeviceType.HUMIDITY), ZSE11
    )


def test_policy_exclude_removes_match() -> None:
    policy = Policy(
        name="battery checkin",
        match=Selector(power=Power.BATTERY),
        settings={WUI: pv(WUI, 3600)},
        exclude=(Selector(manufacturer="Zooz"),),
    )
    assert not policy_matches(policy, ZSE11)
    assert policy_matches(policy, ZWA045)


# -- evaluate_policies -------------------------------------------


def test_evaluate_emits_writes_and_warning() -> None:
    policies = [
        Policy(
            name="humidity",
            match=Selector(device_type=DeviceType.HUMIDITY),
            settings={HRT: pv(HRT, 2), TCI: pv(TCI, 1)},
        ),
    ]
    plan = evaluate_policies([ZSE44, ZWA039], policies, MAPPING)
    writes = {(w.device.node_id, w.concept) for w in plan.writes}
    assert (42, HRT) in writes
    assert (42, TCI) in writes
    assert (264, HRT) in writes
    assert any(
        w.device.node_id == 264 and w.concept == TCI for w in plan.warnings
    )


def test_evaluate_conflicting_policies_is_error() -> None:
    policies = [
        Policy("a", Selector(model="ZSE11"), {MS: pv(MS, 7)}),
        Policy("b", Selector(manufacturer="Zooz"), {MS: pv(MS, 9)}),
    ]
    plan = evaluate_policies([ZSE11], policies, MAPPING)
    assert any(e.concept == MS for e in plan.errors)
    assert not any(w.concept == MS for w in plan.writes)


def test_evaluate_uses_invert_quirk() -> None:
    mapping = MappingTable(
        locators=MAPPING.locators,
        quirks={(MS, ModelId("Zooz", "ZSE11")): ModelQuirk(invert=True)},
        off_labels=MAPPING.off_labels,
    )
    policies = [
        Policy("outdoor", Selector(model="ZSE11"), {MS: pv(MS, 10)}),
    ]
    plan = evaluate_policies([ZSE11], policies, mapping)
    write = next(w for w in plan.writes if w.concept == MS)
    assert write.value == 1


def test_empty_plan_for_no_match() -> None:
    plan = evaluate_policies(
        [REPEATER],
        [Policy("x", Selector(device_type=DeviceType.MOTION), {MS: pv(MS, 5)})],
        MAPPING,
    )
    assert plan == Plan()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
