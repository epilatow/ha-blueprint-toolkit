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


from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    CATALOG,
    WAKE_UP_INTERVAL_VALUE,
    Device,
    DeviceType,
    GenericParamNames,
    LabelMatch,
    MappingTable,
    ModelId,
    ModelQuirk,
    ParamId,
    ParamMeta,
    ParamType,
    ParamValue,
    Policy,
    Power,
    ResolutionStatus,
    Selector,
    UnusedSetting,
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


def pv(name: GenericParamNames, value: bool | float) -> ParamValue:
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
    id=ParamId(112, 12),
    label="Motion Sensor Sensitivity",
    range=(0, 8),
    states={0: "Disable"},
)
ZSE11_LED = ParamMeta(
    id=ParamId(112, 19),
    label="Flash LED on Motion",
    range=(0, 1),
    states={0: "Disable", 1: "Enable"},
)
ZWA045_SENS = ParamMeta(
    id=ParamId(112, 4),
    label="Motion Sensitivity",
    range=(0, 3),
    states={0: "Disable", 1: "Low", 2: "Medium", 3: "High"},
)
ZSE44_HUM = ParamMeta(
    id=ParamId(112, 4),
    label="Humidity Report Threshold",
    range=(0, 50),
    unit="%",
    states={0: "Disable"},
)
ZWA039_HUM = ParamMeta(
    id=ParamId(112, 2),
    label="Humidity Change Report Threshold",
    range=(0, 20),
    unit="%",
    states={0: "Disable"},
)
ZWA039_CHECK = ParamMeta(
    id=ParamId(112, 3),
    label="Threshold Check Interval",
    range=(1, 255),
    unit="minutes",
)
WAKEUP = ParamMeta(
    id=ParamId(132, "wakeUpInterval"),
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


# -- MappingTable.from_dict (strict loader for generated JSON) ---


def _from_dict_raises(raw: dict[str, object], match: str) -> None:
    import pytest

    with pytest.raises(ValueError, match=match):
        MappingTable.from_dict(raw)


def test_from_dict_round_trip() -> None:
    raw = {
        "locators": {
            "motion_sensitivity": {
                "labels": ["Motion Sensor Sensitivity", "PIR Sensitivity"]
            },
            "wake_up_interval": {
                "command_class": 132,
                "property": "wakeUpInterval",
            },
        },
        "quirks": {
            "light_on_motion": {
                "Zooz": {"ZSE11": {"off_value": 0, "on_value": 7}}
            }
        },
        "off_labels": ["disable", "off"],
        "on_labels": ["enable", "on"],
        "low_tokens": ["lowest", "low"],
        "high_tokens": ["highest", "high"],
    }
    table = MappingTable.from_dict(raw)
    # The wake_up_interval locator is the same value-id everyone shares.
    assert table.locators[WUI] == WAKE_UP_INTERVAL_VALUE
    assert table.locators[MS] == LabelMatch(
        ("Motion Sensor Sensitivity", "PIR Sensitivity")
    )
    assert table.quirks[(LOM, ModelId("Zooz", "ZSE11"))] == ModelQuirk(
        off_value=0, on_value=7
    )
    assert table.off_labels == frozenset({"disable", "off"})
    assert table.high_tokens == ("highest", "high")


def test_from_dict_inherits_disjoint_invariant() -> None:
    _from_dict_raises(
        {
            "locators": {},
            "off_labels": ["off"],
            "on_labels": ["off"],
        },
        match="off_labels and on_labels",
    )


def test_from_dict_rejects_non_mapping_root() -> None:
    import pytest

    with pytest.raises(ValueError, match="root must be a mapping"):
        MappingTable.from_dict([1, 2, 3])


def test_from_dict_rejects_unknown_top_level_key() -> None:
    _from_dict_raises(
        {"locators": {}, "wat": 1},
        match="unknown top-level key",
    )


def test_from_dict_rejects_unknown_concept_name() -> None:
    _from_dict_raises(
        {"locators": {"motion_sensitvity": {"labels": ["x"]}}},
        match="unknown concept",
    )


def test_from_dict_locator_needs_exactly_one_form() -> None:
    _from_dict_raises(
        {"locators": {"motion_sensitivity": {}}},
        match="exactly one of",
    )
    _from_dict_raises(
        {
            "locators": {
                "motion_sensitivity": {
                    "labels": ["x"],
                    "command_class": 112,
                }
            }
        },
        match="exactly one of",
    )


def test_from_dict_rejects_empty_labels() -> None:
    _from_dict_raises(
        {"locators": {"motion_sensitivity": {"labels": []}}},
        match="non-empty list",
    )


def test_from_dict_quirks_require_manufacturer_layer() -> None:
    # The JSON nesting (concept -> manufacturer -> model -> quirk)
    # has no shortcut for bare-model. Omitting the manufacturer layer
    # fails structurally -- the next level down isn't a valid quirk
    # mapping. Error path locates the rejected level.
    _from_dict_raises(
        {
            "locators": {},
            "quirks": {"light_on_motion": {"ZSE11": {"off_value": 0}}},
        },
        match="must be a mapping",
    )


def test_from_dict_quirk_rejects_unknown_field() -> None:
    _from_dict_raises(
        {
            "locators": {},
            "quirks": {"light_on_motion": {"Zooz": {"ZSE11": {"invrt": True}}}},
        },
        match="unknown key",
    )


def test_from_dict_loads_metadata() -> None:
    """Provenance metadata round-trips intact onto MappingTable.

    The handler logs ``zwave_js_tag`` and friends at startup so the
    operator can confirm which DB snapshot the mapping was generated
    against."""

    raw = {
        "locators": {},
        "metadata": {
            "zwave_js_tag": "v15.24.0",
            "zwave_js_commit": "5ffca2b38393f9eab0bffcdbd65b3020cbeda492",
            "zwave_js_commit_date": "2026-05-12T18:19:20Z",
        },
    }
    table = MappingTable.from_dict(raw)
    assert table.metadata["zwave_js_tag"] == "v15.24.0"
    assert (
        table.metadata["zwave_js_commit"]
        == "5ffca2b38393f9eab0bffcdbd65b3020cbeda492"
    )
    assert table.metadata["zwave_js_commit_date"] == "2026-05-12T18:19:20Z"


def test_from_dict_metadata_optional_defaults_empty() -> None:
    table = MappingTable.from_dict({"locators": {}})
    assert table.metadata == {}


def test_from_dict_rejects_malformed_metadata() -> None:
    _from_dict_raises(
        {"locators": {}, "metadata": "not a mapping"},
        match="'metadata' must be a mapping",
    )
    _from_dict_raises(
        {"locators": {}, "metadata": {"zwave_js_tag": 15}},
        match=r"metadata\['zwave_js_tag'\] must be a string",
    )


def test_from_dict_locator_rejects_unknown_keys() -> None:
    _from_dict_raises(
        {"locators": {"motion_sensitivity": {"labels": ["X"], "garbage": 1}}},
        match="unknown key",
    )
    _from_dict_raises(
        {
            "locators": {
                "wake_up_interval": {
                    "command_class": 132,
                    "property": "wakeUpInterval",
                    "stray": 1,
                }
            }
        },
        match="unknown key",
    )


def test_from_dict_rejects_duplicate_labels_or_tokens() -> None:
    _from_dict_raises(
        {"locators": {}, "off_labels": ["off", "off"]},
        match="duplicate 'off'",
    )
    _from_dict_raises(
        {"locators": {}, "low_tokens": ["low", "lowest", "low"]},
        match="duplicate 'low'",
    )


def test_from_dict_quirk_rejects_bad_int() -> None:
    # bool is an int subclass; the loader must reject True/False here.
    _from_dict_raises(
        {
            "locators": {},
            "quirks": {
                "light_on_motion": {"Zooz": {"ZSE11": {"off_value": True}}}
            },
        },
        match="off_value: must be an int",
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
    assert (res.id, res.value) == (ParamId(112, 19), 0)


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
                id=ParamId(112, 5),
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
                id=ParamId(112, 1),
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
                id=ParamId(112, 40),
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
                id=ParamId(112, 3),
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
    assert (res.id, res.value) == (ParamId(132, "wakeUpInterval"), 3600)


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
            ParamMeta(ParamId(112, 1), "Motion Sensitivity", range=(0, 10)),
            ParamMeta(ParamId(112, 2), "PIR Sensitivity", range=(0, 10)),
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
    # TCI resolved on node 42, so it is used despite being NA on 264.
    assert plan.unused == ()


def test_evaluate_conflicting_policies_is_error() -> None:
    policies = [
        Policy("a", Selector(model="ZSE11"), {MS: pv(MS, 7)}),
        Policy("b", Selector(manufacturer="Zooz"), {MS: pv(MS, 9)}),
    ]
    plan = evaluate_policies([ZSE11], policies, MAPPING)
    assert any(e.concept == MS for e in plan.errors)
    assert not any(w.concept == MS for w in plan.writes)
    # A conflict-blocked setting is an error, not 'unused'.
    assert plan.unused == ()


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


def test_invert_quirk_matches_case_insensitively() -> None:
    # The quirk key's manufacturer/model casing differs from the
    # device's reported strings ("Zooz"/"ZSE11"); the invert must still
    # fire, the same way Selector matches, so a config-vs-node case
    # drift can't silently drop a direction invert.
    mapping = MappingTable(
        locators=MAPPING.locators,
        quirks={(MS, ModelId("ZOOZ", "zse11")): ModelQuirk(invert=True)},
        off_labels=MAPPING.off_labels,
    )
    policies = [
        Policy("outdoor", Selector(model="ZSE11"), {MS: pv(MS, 10)}),
    ]
    plan = evaluate_policies([ZSE11], policies, mapping)
    write = next(w for w in plan.writes if w.concept == MS)
    assert write.value == 1


# -- unused-config detection -------------------------------------


def test_unused_policy_when_selector_matches_nothing() -> None:
    # A policy whose selector matches no device is inert: no writes /
    # warnings / errors, and one policy-level unused finding (its
    # settings aren't enumerated -- the whole policy applied to nothing).
    plan = evaluate_policies(
        [REPEATER],
        [Policy("x", Selector(device_type=DeviceType.MOTION), {MS: pv(MS, 5)})],
        MAPPING,
    )
    assert (plan.writes, plan.warnings, plan.errors) == ((), (), ())
    assert plan.unused == (
        UnusedSetting("x", None, "selector matched no devices"),
    )


def test_unused_setting_when_no_matched_device_exposes_it() -> None:
    # ZWA045 matches device_type motion but has no light_on_motion
    # param, so the setting is NOT_APPLICABLE on every match: the
    # aggregate setting is unused (and also a per-device warning).
    policies = [
        Policy(
            "motion",
            Selector(device_type=DeviceType.MOTION),
            {LOM: pv(LOM, True)},
        ),
    ]
    plan = evaluate_policies([ZWA045], policies, MAPPING)
    assert plan.writes == ()
    assert any(w.concept == LOM for w in plan.warnings)
    assert plan.unused == (
        UnusedSetting("motion", LOM, "no matched device exposes this setting"),
    )


def test_resolved_anywhere_setting_is_not_unused() -> None:
    # ZWA045 lacks light_on_motion but resolves motion_sensitivity, so
    # only the absent setting is unused -- a resolved one never is.
    policies = [
        Policy(
            "motion",
            Selector(device_type=DeviceType.MOTION),
            {MS: pv(MS, 5), LOM: pv(LOM, True)},
        ),
    ]
    plan = evaluate_policies([ZWA045], policies, MAPPING)
    assert {u.concept for u in plan.unused} == {LOM}


def test_resolution_error_setting_is_not_unused() -> None:
    # An AMBIGUOUS (>1 matching param) setting is an error, not 'unused':
    # the config did name a real, exposed parameter family.
    dupe = Device(
        node_id=904,
        name="Twin",
        manufacturer="Acme",
        model="DUP",
        is_listening=False,
        params=(
            ParamMeta(ParamId(112, 1), "Motion Sensitivity", range=(0, 10)),
            ParamMeta(ParamId(112, 2), "PIR Sensitivity", range=(0, 10)),
        ),
    )
    policies = [Policy("dup", Selector(model="DUP"), {MS: pv(MS, 5)})]
    plan = evaluate_policies([dupe], policies, MAPPING)
    assert any(e.concept == MS for e in plan.errors)
    assert plan.unused == ()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
