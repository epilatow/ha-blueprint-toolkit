#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pyyaml",
#     "pytest-homeassistant-custom-component==0.13.373",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the strict ZPM policy-config parser."""

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave_parameter_manager.config import (  # noqa: E402
    parse_policies,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    DeviceType,
    GenericParamNames,
    ParamType,
    Power,
    Selector,
)

MS = GenericParamNames.MOTION_SENSITIVITY
LOM = GenericParamNames.LIGHT_ON_MOTION
HRT = GenericParamNames.HUMIDITY_REPORT_THRESHOLD
TCI = GenericParamNames.THRESHOLD_CHECK_INTERVAL
WUI = GenericParamNames.WAKE_UP_INTERVAL

# A documentation-quality example: every selector field, every value
# kind. Doubles as the canonical accepted config the user docs show.
# RANGE values are on the generic 1-10 scale (10 = max, rescaled per
# device); units are real (seconds / percent / minutes).
EXAMPLE_CONFIG = """
policies:
  - name: hourly-checkin
    match:
      power: battery
    settings:
      wake_up_interval: 3600
    exclude:
      - manufacturer: Sensative
      - model: SMCO410

  - name: q-sensor-motion
    match:
      manufacturer: Zooz
      model: ZSE11
    settings:
      motion_sensitivity: 10
      light_on_motion: false

  - name: bathroom-humidity
    match:
      device_type: humidity
    settings:
      humidity_report_threshold: 2
      threshold_check_interval: 1
"""


def _valid() -> dict[str, object]:
    return {
        "policies": [
            {
                "name": "outdoor-motion",
                "match": {"device_type": "motion", "model": "ZSE11"},
                "settings": {
                    "motion_sensitivity": 8,
                    "light_on_motion": False,
                },
                "exclude": [{"manufacturer": "Sensative"}],
            },
            {
                "name": "battery-checkin",
                "match": {"power": "battery"},
                "settings": {"wake_up_interval": 3600},
            },
        ]
    }


# -- happy path --------------------------------------------------


def test_valid_config_parses() -> None:
    cfg = parse_policies(_valid())
    assert cfg.errors == ()
    assert len(cfg.policies) == 2

    outdoor = cfg.policies[0]
    assert outdoor.name == "outdoor-motion"
    assert outdoor.match == Selector(
        device_type=DeviceType.MOTION, model="ZSE11"
    )
    assert outdoor.exclude == (Selector(manufacturer="Sensative"),)
    assert outdoor.settings[MS].value == 8
    assert outdoor.settings[MS].param_type is ParamType.RANGE
    assert outdoor.settings[LOM].value is False
    assert outdoor.settings[LOM].param_type is ParamType.BOOL

    battery = cfg.policies[1]
    assert battery.match == Selector(power=Power.BATTERY)
    assert battery.settings[WUI].value == 3600


def test_example_config_yaml_parses() -> None:
    cfg = parse_policies(yaml.safe_load(EXAMPLE_CONFIG))
    assert cfg.errors == ()
    assert [p.name for p in cfg.policies] == [
        "hourly-checkin",
        "q-sensor-motion",
        "bathroom-humidity",
    ]
    checkin, motion, humidity = cfg.policies
    assert checkin.match == Selector(power=Power.BATTERY)
    assert checkin.exclude == (
        Selector(manufacturer="Sensative"),
        Selector(model="SMCO410"),
    )
    assert checkin.settings[WUI].value == 3600
    assert motion.settings[MS].value == 10
    assert motion.settings[MS].param_type is ParamType.RANGE
    assert motion.settings[LOM].value is False
    assert humidity.match == Selector(device_type=DeviceType.HUMIDITY)
    assert humidity.settings[HRT].value == 2
    assert humidity.settings[TCI].value == 1


def test_power_is_case_insensitive() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "p",
                    "match": {"power": "BATTERY"},
                    "settings": {"wake_up_interval": 3600},
                }
            ]
        }
    )
    assert cfg.errors == ()
    assert cfg.policies[0].match.power is Power.BATTERY


# -- structural strictness ---------------------------------------


def test_root_must_be_mapping() -> None:
    cfg = parse_policies([1, 2, 3])
    assert cfg.policies == ()
    assert any("root must be a mapping" in e for e in cfg.errors)


def test_unknown_top_level_key() -> None:
    cfg = parse_policies({"policies": [], "policy": []})
    assert any("unknown top-level key" in e for e in cfg.errors)


def test_policies_must_be_list() -> None:
    cfg = parse_policies({"policies": {}})
    assert cfg.policies == ()
    assert any("'policies' must be a list" in e for e in cfg.errors)


def test_unknown_policy_key_and_missing_name() -> None:
    cfg = parse_policies(
        {"policies": [{"match": {"power": "battery"}, "oops": 1}]}
    )
    assert cfg.policies == ()
    assert any("unknown key" in e for e in cfg.errors)
    assert any("'name'" in e for e in cfg.errors)


def test_duplicate_policy_name_drops_the_duplicate() -> None:
    p = {
        "name": "dup",
        "match": {"power": "battery"},
        "settings": {"wake_up_interval": 3600},
    }
    cfg = parse_policies({"policies": [p, dict(p)]})
    assert any("duplicate policy name" in e for e in cfg.errors)
    # First occurrence kept, the duplicate dropped (not silently applied).
    assert [pol.name for pol in cfg.policies] == ["dup"]


def test_name_is_stripped() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "  spacey  ",
                    "match": {"model": "X"},
                    "settings": {"wake_up_interval": 1},
                }
            ]
        }
    )
    assert cfg.errors == ()
    assert cfg.policies[0].name == "spacey"


# -- selector strictness -----------------------------------------


def test_missing_match_and_empty_selector() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {"name": "a", "settings": {"wake_up_interval": 3600}},
                {"name": "b", "match": {}, "settings": {"wake_up_interval": 1}},
            ]
        }
    )
    assert cfg.policies == ()
    assert any("'match' is required" in e for e in cfg.errors)
    assert any("at least one of" in e for e in cfg.errors)


def test_bad_power_and_unknown_selector_key() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "a",
                    "match": {"power": "wired", "zone": "x"},
                    "settings": {"wake_up_interval": 3600},
                }
            ]
        }
    )
    assert cfg.policies == ()
    assert any("'power' must be one of" in e for e in cfg.errors)
    assert any("unknown selector key" in e for e in cfg.errors)


def test_unknown_device_type_rejected() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "a",
                    "match": {"device_type": "thermostat"},
                    "settings": {"wake_up_interval": 3600},
                }
            ]
        }
    )
    assert cfg.policies == ()
    assert any("'device_type' must be one of" in e for e in cfg.errors)


# -- settings / value strictness ---------------------------------


def test_unknown_parameter_name() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "a",
                    "match": {"power": "battery"},
                    "settings": {"motion_sensitvity": 8},
                }
            ]
        }
    )
    assert cfg.policies == ()
    assert any("unknown parameter" in e for e in cfg.errors)


def test_out_of_range_and_type_mismatch_values() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "range",
                    "match": {"model": "ZSE11"},
                    "settings": {"motion_sensitivity": 11},
                },
                {
                    "name": "booltype",
                    "match": {"model": "ZSE11"},
                    "settings": {"light_on_motion": 1},
                },
                {
                    "name": "negative",
                    "match": {"model": "ZSE44"},
                    "settings": {"humidity_report_threshold": -1},
                },
            ]
        }
    )
    assert cfg.policies == ()
    assert len(cfg.errors) >= 3


def test_empty_settings_rejected() -> None:
    cfg = parse_policies(
        {"policies": [{"name": "a", "match": {"model": "X"}, "settings": {}}]}
    )
    assert cfg.policies == ()
    assert any("must not be empty" in e for e in cfg.errors)


def test_bad_exclude_entry() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "a",
                    "match": {"power": "battery"},
                    "settings": {"wake_up_interval": 3600},
                    "exclude": [{"power": "nope"}],
                }
            ]
        }
    )
    assert cfg.policies == ()
    assert any("'power' must be one of" in e for e in cfg.errors)


def test_one_bad_policy_does_not_drop_the_good_one() -> None:
    cfg = parse_policies(
        {
            "policies": [
                {
                    "name": "good",
                    "match": {"power": "battery"},
                    "settings": {"wake_up_interval": 3600},
                },
                {"name": "bad", "settings": {"wake_up_interval": 1}},
            ]
        }
    )
    assert [p.name for p in cfg.policies] == ["good"]
    assert cfg.errors  # the bad one surfaced an error


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
