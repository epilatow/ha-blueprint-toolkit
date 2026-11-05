#!/usr/bin/env -S uv run --script --exact
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant==2026.11.0",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the battery_watchdog logic module."""

import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "battery_watchdog"
    / "logic.py"
)

sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from custom_components.blueprint_toolkit.battery_watchdog.logic import (  # noqa: E402
    BatteryDevice,
    BatteryInfo,
    Config,
    DirectiveInputs,
    is_excluded,
    is_low,
    render_lines,
    run_evaluation,
)
from custom_components.blueprint_toolkit.helpers import (  # noqa: E402
    JoinedRegexLine,
    validate_and_join_regex_patterns,
)

PREFIX = "blueprint_toolkit_battery_watchdog__automation.bw__"

# Tests vary these with ``dataclasses.replace`` so each
# override is type-checked against the dataclass fields.
CONFIG = Config(warning_level=25, notification_prefix=PREFIX)
DIRECTIVES = DirectiveInputs(
    enabled=True,
    include_integrations=[],
    exclude_integrations=[],
    include_entities=[],
    exclude_entities=[],
    exclude_device_name_regex_lines=[],
    exclude_entity_id_regex_lines=[],
    exclude_entity_name_regex_lines=[],
)
WINDOW = BatteryDevice(
    device_id="dev1", name="Window", integrations=frozenset({"zwave_js"})
)


def _battery(
    entity_id: str = "sensor.window_battery",
    *,
    name: str = "Window Battery",
    integration: str = "zwave_js",
    state: str = "20",
    binary: bool = False,
    device: BatteryDevice | None = WINDOW,
    area: str | None = "Kitchen",
) -> BatteryInfo:
    return BatteryInfo(
        entity_id=entity_id,
        name=name,
        integration=integration,
        state=state,
        binary=binary,
        device=device,
        area=area,
    )


def _device(device_id: str, name: str) -> BatteryDevice:
    return BatteryDevice(device_id=device_id, name=name)


def _regex_lines(text: str) -> list[JoinedRegexLine]:
    return validate_and_join_regex_patterns(text, "field").lines


class TestIsLow:
    @pytest.mark.parametrize(
        ("state", "low"),
        [
            ("0", True),
            ("24.9", True),
            ("25", True),
            ("25.1", False),
            ("80", False),
            ("-1", False),
            ("nan", False),
            ("inf", False),
            ("-inf", False),
            ("unavailable", False),
            ("unknown", False),
        ],
    )
    def test_numeric_level_against_warning_level(
        self, state: str, low: bool
    ) -> None:
        assert is_low(_battery(state=state), 25) is low

    @pytest.mark.parametrize(
        ("state", "low"),
        [("on", True), ("off", False), ("unavailable", False)],
    )
    def test_binary_low_when_on(self, state: str, low: bool) -> None:
        assert is_low(_battery(state=state, binary=True), 25) is low


class TestIsExcluded:
    def test_nothing_configured_keeps_every_battery(self) -> None:
        assert not is_excluded(CONFIG, _battery())

    def test_include_integrations_keeps_only_listed(self) -> None:
        config = replace(CONFIG, include_integrations=frozenset({"shelly"}))
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery(integration="shelly"))

    def test_include_integrations_drops_an_unregistered_battery(
        self,
    ) -> None:
        config = replace(CONFIG, include_integrations=frozenset({"zwave_js"}))
        assert is_excluded(config, _battery(integration=""))

    def test_exclude_integration_drops_its_batteries(self) -> None:
        config = replace(CONFIG, exclude_integrations=frozenset({"zwave_js"}))
        assert is_excluded(config, _battery(device=None))

    def test_exclude_integration_drops_its_whole_device(self) -> None:
        # The device carries a switch_as_x wrapper; excluding
        # that integration excludes the device's battery too.
        config = replace(
            CONFIG, exclude_integrations=frozenset({"switch_as_x"})
        )
        device = replace(
            WINDOW, integrations=frozenset({"zwave_js", "switch_as_x"})
        )
        assert is_excluded(config, _battery(device=device))

    def test_exclude_entities(self) -> None:
        config = replace(
            CONFIG, exclude_entities=frozenset({"sensor.window_battery"})
        )
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery("sensor.door_battery"))

    def test_entity_id_regex(self) -> None:
        config = replace(CONFIG, exclude_entity_id_regex="window")
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery("sensor.door_battery"))

    def test_entity_name_regex(self) -> None:
        config = replace(CONFIG, exclude_entity_name_regex="^Window Battery$")
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery(name="Door Battery"))

    def test_device_name_regex(self) -> None:
        config = replace(CONFIG, exclude_device_name_regex="^window$")
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery(device=_device("dev2", "Door")))

    def test_device_name_regex_skips_a_deviceless_battery(self) -> None:
        config = replace(CONFIG, exclude_device_name_regex="Window")
        assert not is_excluded(config, _battery(device=None))

    def test_include_entities_keeps_only_listed(self) -> None:
        config = replace(
            CONFIG, include_entities=frozenset({"sensor.door_battery"})
        )
        assert is_excluded(config, _battery())
        assert not is_excluded(config, _battery("sensor.door_battery"))

    def test_include_entities_ignores_the_other_filters(self) -> None:
        config = replace(
            CONFIG,
            include_entities=frozenset({"sensor.window_battery"}),
            exclude_entities=frozenset({"sensor.window_battery"}),
            exclude_integrations=frozenset({"zwave_js"}),
        )
        assert not is_excluded(config, _battery())

    def test_exclude_integration_wins_over_include(self) -> None:
        config = replace(
            CONFIG,
            include_integrations=frozenset({"zwave_js"}),
            exclude_integrations=frozenset({"zwave_js"}),
        )
        assert is_excluded(config, _battery())


class TestRenderLines:
    def test_line_links_device_and_level(self) -> None:
        assert render_lines([_battery()]) == [
            (
                "- Kitchen -> [Window](/config/devices/device/dev1): "
                "[20%](/history?entity_id=sensor.window_battery)"
            )
        ]

    def test_level_drops_a_trailing_zero_fraction(self) -> None:
        (line,) = render_lines([_battery(state="20.0")])
        assert "[20%]" in line
        (line,) = render_lines([_battery(state="37.5")])
        assert "[37.5%]" in line

    def test_binary_battery_reads_low(self) -> None:
        (line,) = render_lines([_battery(state="on", binary=True)])
        assert line.endswith(
            ": [low](/history?entity_id=sensor.window_battery)"
        )

    def test_no_area_drops_the_area_prefix(self) -> None:
        (line,) = render_lines([_battery(area=None)])
        assert line == (
            "- [Window](/config/devices/device/dev1): "
            "[20%](/history?entity_id=sensor.window_battery)"
        )

    def test_deviceless_battery_shows_its_name_unlinked(self) -> None:
        (line,) = render_lines([_battery(device=None, name="Spare")])
        assert line == (
            "- Kitchen -> Spare: "
            "[20%](/history?entity_id=sensor.window_battery)"
        )

    def test_device_with_two_low_batteries_names_each(self) -> None:
        lines = render_lines(
            [
                _battery("sensor.a", name="Battery A"),
                _battery("sensor.b", name="Battery B"),
            ]
        )
        assert lines == [
            (
                "- Kitchen -> [Window](/config/devices/device/dev1) "
                "(Battery A): [20%](/history?entity_id=sensor.a)"
            ),
            (
                "- Kitchen -> [Window](/config/devices/device/dev1) "
                "(Battery B): [20%](/history?entity_id=sensor.b)"
            ),
        ]

    def test_sorted_by_area_then_device(self) -> None:
        lines = render_lines(
            [
                _battery("sensor.c", device=_device("d3", "Zed")),
                _battery(
                    "sensor.b", device=_device("d2", "Alpha"), area="Office"
                ),
                _battery("sensor.a", device=_device("d1", "beta")),
            ]
        )
        assert [line.split(": ")[0] for line in lines] == [
            "- Kitchen -> [beta](/config/devices/device/d1)",
            "- Kitchen -> [Zed](/config/devices/device/d3)",
            "- Office -> [Alpha](/config/devices/device/d2)",
        ]

    def test_no_area_sorts_last(self) -> None:
        lines = render_lines(
            [
                _battery("sensor.a", device=_device("d1", "A"), area=None),
                _battery("sensor.z", device=_device("d2", "Z"), area="Zoo"),
            ]
        )
        assert [line.split(": ")[0] for line in lines] == [
            "- Zoo -> [Z](/config/devices/device/d2)",
            "- [A](/config/devices/device/d1)",
        ]

    def test_user_text_is_escaped(self) -> None:
        (line,) = render_lines(
            [_battery(area="[Den]", device=_device("dev1", "Lamp [old]"))]
        )
        assert line.startswith(r"- \[Den\] -> [Lamp \[old\]](")

    def test_battery_name_beside_its_device_is_escaped(self) -> None:
        lines = render_lines(
            [
                _battery("sensor.a", name="Cell [1]"),
                _battery("sensor.b", name="Cell [2]"),
            ]
        )
        assert r"(Cell \[1\]): " in lines[0]


class TestRunEvaluation:
    def test_low_batteries_make_one_notification(self) -> None:
        ev = run_evaluation(
            CONFIG,
            [
                _battery("sensor.a", device=_device("d1", "A")),
                _battery("sensor.b", device=_device("d2", "B"), state="90"),
                _battery(
                    "sensor.c",
                    device=_device("d3", "C"),
                    state="on",
                    binary=True,
                ),
            ],
            DIRECTIVES,
        )
        n = ev.notification
        assert n.active
        assert n.notification_id == f"{PREFIX}low_batteries"
        assert n.title == "2 low batteries"
        assert n.message.count("\n") == 1
        assert [b.entity_id for b in ev.low] == ["sensor.a", "sensor.c"]
        assert ev.batteries == 3
        assert ev.batteries_excluded == 0

    def test_one_low_battery_title_is_singular(self) -> None:
        ev = run_evaluation(CONFIG, [_battery()], DIRECTIVES)
        assert ev.notification.title == "1 low battery"

    def test_nothing_low_dismisses(self) -> None:
        ev = run_evaluation(CONFIG, [_battery(state="90")], DIRECTIVES)
        assert not ev.notification.active
        assert ev.notification.notification_id == f"{PREFIX}low_batteries"

    def test_excluded_battery_is_neither_listed_nor_low(self) -> None:
        ev = run_evaluation(
            replace(
                CONFIG, exclude_entities=frozenset({"sensor.window_battery"})
            ),
            [_battery()],
            DIRECTIVES,
        )
        assert not ev.notification.active
        assert ev.low == []
        assert ev.batteries_excluded == 1

    def test_instance_id_rides_on_the_notification(self) -> None:
        ev = run_evaluation(
            replace(CONFIG, instance_id="automation.bw"),
            [_battery()],
            DIRECTIVES,
        )
        assert ev.notification.instance_id == "automation.bw"


class TestValidateDirectives:
    def _fields(
        self, inputs: DirectiveInputs, config: Config = CONFIG
    ) -> list[tuple[str, str]]:
        device = replace(
            WINDOW, integrations=frozenset({"zwave_js", "switch_as_x"})
        )
        ev = run_evaluation(config, [_battery(device=device)], inputs)
        return [(u.field, u.value) for u in ev.unmatched_directives]

    def test_disabled_reports_nothing(self) -> None:
        inputs = replace(
            DIRECTIVES, enabled=False, include_entities=["sensor.nope"]
        )
        assert self._fields(inputs) == []

    def test_matched_directives_report_nothing(self) -> None:
        inputs = replace(
            DIRECTIVES,
            include_integrations=["zwave_js"],
            exclude_integrations=["switch_as_x"],
            exclude_entities=["sensor.window_battery"],
            exclude_device_name_regex_lines=_regex_lines("^Window$"),
            exclude_entity_id_regex_lines=_regex_lines("window"),
            exclude_entity_name_regex_lines=_regex_lines("Battery"),
        )
        assert self._fields(inputs) == []

    def test_a_directive_another_filter_shadows_still_matches(self) -> None:
        # Excluding the integration already drops the battery,
        # so the entity exclude filters nothing more -- but it
        # still names a battery, so it isn't flagged.
        inputs = replace(DIRECTIVES, exclude_entities=["sensor.window_battery"])
        config = replace(CONFIG, exclude_integrations=frozenset({"zwave_js"}))
        assert self._fields(inputs, config) == []

    def test_unmatched_directives_are_reported(self) -> None:
        # switch_as_x is only on the battery's device: an exclude
        # still drops the battery, but an include keeps a battery
        # by its own integration, so it matches nothing.
        inputs = replace(
            DIRECTIVES,
            include_integrations=["switch_as_x"],
            exclude_integrations=["hue"],
            include_entities=["sensor.temperature"],
            exclude_entities=["sensor.door_battery"],
            exclude_device_name_regex_lines=_regex_lines("^Door$"),
            exclude_entity_id_regex_lines=_regex_lines("^light\\."),
            exclude_entity_name_regex_lines=_regex_lines("Humidity"),
        )
        assert self._fields(inputs) == [
            ("include_integrations", "switch_as_x"),
            ("exclude_integrations", "hue"),
            ("include_entities", "sensor.temperature"),
            ("exclude_entities", "sensor.door_battery"),
            ("exclude_device_name_regex", "^Door$"),
            ("exclude_entity_id_regex", "^light\\."),
            ("exclude_entity_name_regex", "Humidity"),
        ]


if __name__ == "__main__":
    from conftest import run_tests

    run_tests(__file__, _SCRIPT_PATH, REPO_ROOT)
