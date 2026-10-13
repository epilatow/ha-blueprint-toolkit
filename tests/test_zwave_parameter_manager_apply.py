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
"""Tests for the zwave_parameter_manager apply-decision module.

select_writes decides which planned writes to issue this reconcile cycle.
A command is issued at most once per pending epoch; the handler ends an
epoch (re-allowing issue) by clearing the pending map on a queue flush.
Each case isolates one branch of the issue / suppress decision.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave_parameter_manager.apply import (  # noqa: E402
    select_writes,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    Device,
    GenericParamNames,
    ParamId,
    Plan,
    PlannedWrite,
)

_MOTION = ParamId(112, 12)
_NODE = 5


def _device() -> Device:
    return Device(
        node_id=_NODE,
        name="node5",
        manufacturer="Zooz",
        model="ZSE11",
        is_listening=False,
    )


def _write(value: int) -> PlannedWrite:
    return PlannedWrite(
        device=_device(),
        concept=GenericParamNames.MOTION_SENSITIVITY,
        policy="p1",
        id=_MOTION,
        value=value,
        generic_value=value,
    )


def _key() -> tuple[int, ParamId]:
    return (_NODE, _MOTION)


def test_first_issue_records_pending() -> None:
    write = _write(8)
    decision = select_writes(Plan(writes=(write,)), {_NODE: {_MOTION: 3}}, {})
    assert decision.writes == (write,)
    assert decision.pending == {_key(): 8}


def test_suppressed_when_already_pending_same_value() -> None:
    # Mismatched but already issued this epoch: still queued, do not re-issue.
    write = _write(8)
    decision = select_writes(
        Plan(writes=(write,)), {_NODE: {_MOTION: 3}}, {_key(): 8}
    )
    assert decision.writes == ()
    # The pending entry is carried forward.
    assert decision.pending == {_key(): 8}


def test_cleared_pending_reissues() -> None:
    # The handler clears the pending map on a queue flush (add-on restart or
    # a fresh Core process); the next cycle then re-issues.
    write = _write(8)
    decision = select_writes(Plan(writes=(write,)), {_NODE: {_MOTION: 3}}, {})
    assert decision.writes == (write,)


def test_reissues_on_desired_change() -> None:
    # The pending map holds a different value; the desired changed since.
    write = _write(8)
    decision = select_writes(
        Plan(writes=(write,)), {_NODE: {_MOTION: 3}}, {_key(): 5}
    )
    assert decision.writes == (write,)
    assert decision.pending == {_key(): 8}


def test_converged_clears_pending() -> None:
    write = _write(8)
    decision = select_writes(
        Plan(writes=(write,)), {_NODE: {_MOTION: 8}}, {_key(): 8}
    )
    assert decision.writes == ()
    assert _key() not in decision.pending


def test_converged_then_redrift_reissues() -> None:
    # Convergence drops the pending entry, so a later out-of-band drift is a
    # fresh command and re-issues within the same epoch.
    write = _write(8)
    converged = select_writes(
        Plan(writes=(write,)), {_NODE: {_MOTION: 8}}, {_key(): 8}
    )
    drifted = select_writes(
        Plan(writes=(write,)), {_NODE: {_MOTION: 3}}, converged.pending
    )
    assert drifted.writes == (write,)


def test_removed_write_drops_from_pending() -> None:
    # A pending entry whose write is no longer planned clears itself.
    decision = select_writes(Plan(), {}, {_key(): 8})
    assert decision.writes == ()
    assert decision.pending == {}


def test_unread_actual_is_issued() -> None:
    # A never-reported value reads as a mismatch and is queued.
    write = _write(8)
    decision = select_writes(Plan(writes=(write,)), {_NODE: {}}, {})
    assert decision.writes == (write,)


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
