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
"""Tests for the zwave_parameter_manager report builder.

build_report joins a Plan's writes against per-node live values into the
shared ConvergenceReport. PlannedWrite / Device / ParamMeta fixtures are
built directly (rather than through evaluate_policies) so each case
isolates the join + value rendering.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave.convergence import (  # noqa: E402, E501
    ConvergenceDevice,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    Device,
    GenericParamNames,
    ParamId,
    ParamMeta,
    Plan,
    PlannedWrite,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.report import (  # noqa: E402, E501
    build_report,
)

_MOTION = ParamId(112, 12)
_WAKE = ParamId(132, "wakeUpInterval")
_LED = ParamId(112, 5)

_MOTION_META = ParamMeta(
    id=_MOTION,
    label="Motion Sensor Sensitivity",
    range=(0, 8),
    states={0: "Disable"},
)
_WAKE_META = ParamMeta(id=_WAKE, label="Wake-up interval", unit="seconds")
_LED_META = ParamMeta(
    id=_LED, label="LED Indicator", states={0: "Disabled", 1: "Enabled"}
)


def _device(*params: ParamMeta) -> Device:
    return Device(
        node_id=5,
        name="node5",
        manufacturer="Zooz",
        model="ZSE11",
        is_listening=False,
        params=params,
    )


def _write(
    device: Device, concept: GenericParamNames, pid: ParamId, value: int
) -> PlannedWrite:
    return PlannedWrite(
        device=device,
        concept=concept,
        policy="p1",
        id=pid,
        value=value,
        generic_value=value,
    )


def test_build_report_joins_desired_and_actual() -> None:
    device = _device(_MOTION_META, _WAKE_META)
    plan = Plan(
        writes=(
            _write(device, GenericParamNames.MOTION_SENSITIVITY, _MOTION, 8),
            _write(device, GenericParamNames.WAKE_UP_INTERVAL, _WAKE, 3600),
        )
    )
    cd = ConvergenceDevice(
        node_id=5,
        name="Guest Bath Motion",
        location="Guest Bath",
        wake_interval_seconds=3600,
    )
    actuals = {5: {_MOTION: 8, _WAKE: 1800}}

    report = build_report(plan, {5: cd}, actuals)

    assert report.subsystem == "Z-Wave Parameter Manager"
    assert len(report.devices) == 1
    dc = report.devices[0]
    # The convergence device (wake context) is carried through verbatim.
    assert dc.device is cd

    motion, wake = dc.params
    assert (motion.param, motion.desired, motion.actual) == (
        "Motion Sensor Sensitivity",
        "8",
        "8",
    )
    assert motion.converged is True
    # Unit-bearing values render with their unit; a mismatch is pending.
    assert (wake.param, wake.desired, wake.actual) == (
        "Wake-up interval",
        "3600 seconds",
        "1800 seconds",
    )
    assert wake.converged is False

    # The generic (concept) view rides alongside the device view.
    assert (motion.concept, motion.concept_desired) == (
        "motion_sensitivity",
        "8",
    )
    assert (wake.concept, wake.concept_desired) == (
        "wake_up_interval",
        "3600",
    )

    assert dc.converged is False
    assert dc.pending_params == (wake,)
    assert report.converged_count == 1
    assert report.pending_count == 1
    assert report.pending_devices == (dc,)


def test_bool_concept_renders_generic_value_as_word() -> None:
    # A boolean concept's generic value renders true/false, not 1/0 (bool is
    # an int subclass, so the renderer must check it first).
    device = _device(_MOTION_META)
    plan = Plan(
        writes=(
            PlannedWrite(
                device=device,
                concept=GenericParamNames.LIGHT_ON_MOTION,
                policy="p1",
                id=_MOTION,
                value=1,
                generic_value=True,
            ),
        )
    )
    row = build_report(plan, {}, {}).devices[0].params[0]
    assert (row.concept, row.concept_desired) == ("light_on_motion", "true")


def test_unread_actual_is_pending() -> None:
    device = _device(_MOTION_META)
    plan = Plan(
        writes=(
            _write(device, GenericParamNames.MOTION_SENSITIVITY, _MOTION, 8),
        )
    )
    # The node reported no value for the param.
    report = build_report(plan, {}, {5: {}})

    row = report.devices[0].params[0]
    assert row.actual is None
    assert row.desired == "8"
    assert row.converged is False


def test_option_state_renders_label_and_raw() -> None:
    device = _device(_LED_META)
    plan = Plan(
        writes=(_write(device, GenericParamNames.LIGHT_ON_MOTION, _LED, 1),)
    )
    cd = ConvergenceDevice(node_id=5, name="n")

    pending = build_report(plan, {5: cd}, {5: {_LED: 0}}).devices[0].params[0]
    assert (pending.desired, pending.actual) == ("Enabled (1)", "Disabled (0)")
    assert pending.converged is False

    converged = build_report(plan, {5: cd}, {5: {_LED: 1}}).devices[0].params[0]
    assert (converged.desired, converged.actual) == (
        "Enabled (1)",
        "Enabled (1)",
    )
    assert converged.converged is True


def test_node_absent_from_convergence_uses_bare_device() -> None:
    device = _device(_MOTION_META)
    plan = Plan(
        writes=(
            _write(device, GenericParamNames.MOTION_SENSITIVITY, _MOTION, 8),
        )
    )
    # No convergence entry for node 5 (gone between read and plan).
    cd = build_report(plan, {}, {5: {_MOTION: 8}}).devices[0].device
    assert cd.node_id == 5
    assert cd.name == "node5"
    assert cd.location is None
    assert cd.wake_interval_seconds is None


def test_param_label_falls_back_to_concept_when_meta_absent() -> None:
    # A write whose ParamId matches no device ParamMeta renders the
    # concept name and the bare value.
    device = _device()
    plan = Plan(
        writes=(
            _write(
                device,
                GenericParamNames.MOTION_SENSITIVITY,
                ParamId(112, 99),
                5,
            ),
        )
    )
    row = (
        build_report(plan, {}, {5: {ParamId(112, 99): 3}}).devices[0].params[0]
    )
    assert row.param == "motion_sensitivity"
    assert (row.desired, row.actual) == ("5", "3")


def test_param_label_falls_back_to_concept_when_meta_label_empty() -> None:
    # A ParamMeta present but with no label also falls back to the
    # concept name (rather than rendering an empty param label).
    blank = ParamMeta(id=_MOTION, label="")
    device = _device(blank)
    plan = Plan(
        writes=(
            _write(device, GenericParamNames.MOTION_SENSITIVITY, _MOTION, 5),
        )
    )
    row = build_report(plan, {}, {5: {_MOTION: 5}}).devices[0].params[0]
    assert row.param == "motion_sensitivity"
    assert row.converged is True


def test_empty_plan_is_empty_report() -> None:
    report = build_report(Plan(), {}, {})
    assert report.devices == ()
    assert report.converged is True
    assert report.pending_devices == ()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
