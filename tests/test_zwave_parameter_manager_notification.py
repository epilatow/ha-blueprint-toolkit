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
"""Tests for the ZPM persistent-notification report renderer.

Hand-built ConvergenceReport fixtures stand in for what the handler
assembles from live state; the renderer is pure, so the body is
asserted directly (device-link form via the shared helper, the wake
annotations, current-vs-desired param lines, desired-vs-pending row
filtering, md_escape on free text, and the empty-pending dismiss case).
"""

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


import pytest  # noqa: E402

from custom_components.blueprint_toolkit.helpers_logic import (  # noqa: E402, E501
    device_link,
)
from custom_components.blueprint_toolkit.zwave.convergence import (  # noqa: E402, E501
    ConvergenceDevice,
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    GenericParamNames,
    UnusedSetting,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.notification import (  # noqa: E402, E501
    render_report_body,
    render_unused_body,
)

WOKE = datetime(2026, 6, 1, 8, 0, 0)


def _report() -> ConvergenceReport:
    """Two devices: a sleeping motion sensor with a pending sensitivity,
    and an always-listening contact whose only param is converged."""

    return ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=ConvergenceDevice(
                    node_id=42,
                    name="Guest Bath Motion",
                    device_id="dev-42",
                    location="Guest Bath",
                    wake_interval_seconds=3600,
                    last_awake_at=WOKE,
                ),
                # param, desired, actual -> actual 8 != desired 6: pending.
                params=(ParamConvergence("motion_sensitivity", "6", "8"),),
            ),
            DeviceConvergence(
                device=ConvergenceDevice(
                    node_id=7,
                    name="Hall Contact",
                    device_id="dev-7",
                ),
                params=(ParamConvergence("wake_up_interval", "3600", "3600"),),
            ),
        ),
    )


def test_desired_lists_every_device_and_param() -> None:
    body = render_report_body(_report(), pending_only=False)
    assert device_link("Guest Bath Motion", "dev-42") in body
    assert device_link("Hall Contact", "dev-7") in body
    assert "- `motion_sensitivity`: `8` -> `6`" in body
    # A converged param is still shown in the desired report.
    assert "- `wake_up_interval`: `3600` -> `3600`" in body


def test_desired_annotations_for_sleeping_device() -> None:
    body = render_report_body(_report(), pending_only=False)
    assert "Guest Bath" in body
    assert "node 42" in body
    assert "wakes every 1 hour" in body
    assert "next wake ~2026-06-01 09:00" in body  # 08:00 + 1h
    # The always-listening device carries no wake annotation.
    assert body.count("wakes every") == 1
    assert body.count("next wake") == 1


def test_param_line_recomposes_the_device_unit() -> None:
    # A unit-bearing value is stored split (value + unit); the body must
    # recompose "value unit" for BOTH sides, so a dropped space or unit in the
    # recomposition is caught (the empty-unit path is covered by _report's
    # bare-int rows above).
    report = ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=ConvergenceDevice(
                    node_id=7, name="Hall Contact", device_id="dev-7"
                ),
                params=(
                    ParamConvergence(
                        "wake_up_interval",
                        "3600",
                        "1800",
                        desired_unit="seconds",
                        actual_unit="seconds",
                    ),
                ),
            ),
        ),
    )
    body = render_report_body(report, pending_only=False)
    assert "- `wake_up_interval`: `1800 seconds` -> `3600 seconds`" in body


def test_pending_filters_to_unconverged_rows() -> None:
    body = render_report_body(_report(), pending_only=True)
    assert device_link("Guest Bath Motion", "dev-42") in body
    assert "- `motion_sensitivity`: `8` -> `6`" in body
    # The fully-converged device drops out entirely.
    assert "Hall Contact" not in body
    assert "wake_up_interval" not in body


def test_unread_actual_renders_as_unread() -> None:
    report = ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=ConvergenceDevice(node_id=9, name="Den"),
                params=(ParamConvergence("motion_sensitivity", "6"),),
            ),
        ),
    )
    body = render_report_body(report, pending_only=True)
    assert "- `motion_sensitivity`: unread -> `6`" in body


def test_location_is_md_escaped() -> None:
    report = ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=ConvergenceDevice(node_id=1, name="X", location="A [B]"),
                params=(ParamConvergence("motion_sensitivity", "6", "8"),),
            ),
        ),
    )
    body = render_report_body(report, pending_only=False)
    assert r"A \[B\]" in body


def test_empty_pending_report_is_dismissed() -> None:
    converged = ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=ConvergenceDevice(node_id=1, name="X"),
                params=(ParamConvergence("motion_sensitivity", "6", "6"),),
            ),
        ),
    )
    assert render_report_body(converged, pending_only=True) == ""


# -- unused-config report ----------------------------------------


def test_unused_body_lists_policy_and_setting_findings() -> None:
    unused = (
        UnusedSetting("ghost policy", None, "selector matched no devices"),
        UnusedSetting(
            "indoor motion",
            GenericParamNames.LIGHT_ON_MOTION,
            "no matched device exposes this setting",
        ),
    )
    body = render_unused_body(unused)
    assert (
        body == "- policy `ghost policy`: selector matched no devices\n"
        "- policy `indoor motion` setting `light_on_motion`: "
        "no matched device exposes this setting"
    )


def test_empty_unused_report_is_dismissed() -> None:
    assert render_unused_body(()) == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
