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
"""Tests for the shared zwave.convergence model."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave.convergence import (  # noqa: E402
    ConvergenceDevice,
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)

WOKE = datetime(2026, 5, 26, 14, 0, 0)


def _dev(**kw: object) -> ConvergenceDevice:
    base: dict[str, object] = {"node_id": 42, "name": "Guest Bath"}
    base.update(kw)
    return ConvergenceDevice(**base)  # type: ignore[arg-type]


# -- ParamConvergence.converged ----------------------------------


def test_param_converged_when_actual_equals_desired() -> None:
    assert ParamConvergence("wake_up_interval", "3600", "3600").converged
    assert not ParamConvergence("wake_up_interval", "3600", "604800").converged


def test_param_unread_actual_is_pending() -> None:
    p = ParamConvergence("motion_sensitivity", "8")
    assert p.actual is None
    assert not p.converged


# -- ConvergenceDevice.expected_next_wake ------------------------


def test_expected_next_wake_is_last_awake_plus_interval() -> None:
    dev = _dev(wake_interval_seconds=3600, last_awake_at=WOKE)
    assert dev.expected_next_wake == WOKE + timedelta(hours=1)


def test_expected_next_wake_none_without_interval_or_last_awake() -> None:
    assert _dev(last_awake_at=WOKE).expected_next_wake is None
    assert _dev(wake_interval_seconds=3600).expected_next_wake is None
    assert _dev().expected_next_wake is None


def test_device_id_optional() -> None:
    assert _dev().device_id is None
    assert _dev(device_id="abc123").device_id == "abc123"


# -- DeviceConvergence -------------------------------------------


def test_device_converged_and_pending_params() -> None:
    dev = DeviceConvergence(
        device=_dev(),
        params=(
            ParamConvergence("humidity_report_threshold", "2", "2"),
            ParamConvergence("threshold_check_interval", "1", "5"),
        ),
    )
    assert not dev.converged
    assert tuple(p.param for p in dev.pending_params) == (
        "threshold_check_interval",
    )


def test_device_with_no_params_is_vacuously_converged() -> None:
    dev = DeviceConvergence(device=_dev())
    assert dev.converged
    assert dev.pending_params == ()


# -- ConvergenceReport -------------------------------------------


def _report() -> ConvergenceReport:
    return ConvergenceReport(
        subsystem="Parameter Manager",
        devices=(
            DeviceConvergence(
                device=_dev(node_id=264, name="Main Bath"),
                params=(
                    ParamConvergence("humidity_report_threshold", "2", "2"),
                ),
            ),
            DeviceConvergence(
                device=_dev(node_id=42, name="Guest Bath"),
                params=(
                    ParamConvergence("humidity_report_threshold", "2", "2"),
                    ParamConvergence("threshold_check_interval", "1", "5"),
                ),
            ),
        ),
    )


def test_report_pending_devices_and_counts() -> None:
    report = _report()
    assert not report.converged
    assert tuple(d.device.node_id for d in report.pending_devices) == (42,)
    assert report.converged_count == 2
    assert report.pending_count == 1


def test_empty_report_is_converged() -> None:
    report = ConvergenceReport(subsystem="Route Manager")
    assert report.converged
    assert report.pending_devices == ()
    assert (report.converged_count, report.pending_count) == (0, 0)


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
