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
"""Tests for the shared ZPM pending store (zpm_pending.json)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit.zwave_parameter_manager import (  # noqa: E402
    pending_store as ps,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    ParamId,
)

T0 = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
K1 = (5, ParamId(112, 12))
K2 = (7, ParamId(132, "wakeUpInterval"))
K3 = (9, ParamId(112, 1, 4))  # a partial/bitmask param (property_key set)


def _path(tmp_path: Path) -> Path:
    return tmp_path / "blueprint_toolkit" / "zpm_pending.json"


class TestReadValid:
    def test_missing_is_empty(self, tmp_path: Path) -> None:
        assert ps.read_valid(_path(tmp_path), home_id=1, last_reset_at=T0) == {}

    def test_fresh_write_then_read(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0 + MIN,
        )
        assert ps.read_valid(p, home_id=1, last_reset_at=T0) == {K1: 8}

    def test_stale_when_issued_before_reset(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        # A reset after the file's issued_at flushes the whole queue.
        assert (
            ps.read_valid(p, home_id=1, last_reset_at=T0 + timedelta(hours=1))
            == {}
        )

    def test_home_id_mismatch_is_empty(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        assert ps.read_valid(p, home_id=999, last_reset_at=T0) == {}


class TestMerge:
    def test_preserves_other_actors_keys(self, tmp_path: Path) -> None:
        # Actor A queues K1; actor B (plan covers only K2) must not drop K1.
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K2}),
            decision_pending={K2: 3600},
            now=T0 + MIN,
        )
        assert ps.read_valid(p, home_id=1, last_reset_at=T0) == {
            K1: 8,
            K2: 3600,
        }

    def test_drops_converged_plan_key(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1, K2}),
            decision_pending={K1: 8, K2: 3600},
            now=T0,
        )
        # K1 converged -> not in decision_pending -> drops from the file.
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1, K2}),
            decision_pending={K2: 3600},
            now=T0 + MIN,
        )
        assert ps.read_valid(p, home_id=1, last_reset_at=T0) == {K2: 3600}

    def test_keeps_epoch_start(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K2}),
            decision_pending={K2: 3600},
            now=T0 + timedelta(hours=1),
        )
        state = ps.load(p)
        assert state is not None
        assert state.issued_at == T0  # epoch start kept, not bumped

    def test_resets_epoch_and_drops_all_when_stale(
        self, tmp_path: Path
    ) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        # A reset happened (last_reset_at now past the file's issued_at). Even
        # though this actor's plan covers only K2, the flush dropped K1 too.
        t2 = T0 + timedelta(hours=2)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0 + timedelta(hours=1),
            plan_keys=frozenset({K2}),
            decision_pending={K2: 3600},
            now=t2,
        )
        state = ps.load(p)
        assert state is not None
        assert state.issued_at == t2
        assert {c.key() for c in state.commands} == {K2}

    def test_empty_clears_file(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={K1: 8},
            now=T0,
        )
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K1}),
            decision_pending={},
            now=T0 + MIN,
        )
        assert not p.exists()

    def test_property_key_round_trips(self, tmp_path: Path) -> None:
        p = _path(tmp_path)
        ps.merge(
            p,
            home_id=1,
            last_reset_at=T0,
            plan_keys=frozenset({K3}),
            decision_pending={K3: 2},
            now=T0,
        )
        assert ps.read_valid(p, home_id=1, last_reset_at=T0) == {K3: 2}


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
