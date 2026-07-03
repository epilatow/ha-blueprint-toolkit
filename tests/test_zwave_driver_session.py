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
"""Tests for the shared ``zwave.driver_session`` record + reset detection."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit.zwave import (  # noqa: E402
    driver_session as ds,
)

T0 = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


def _info(tmp_path: Path) -> Path:
    return tmp_path / "blueprint_toolkit" / "zwave-js-info.json"


class TestRefresh:
    def test_first_write_stamps_reset(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        s = ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        assert s.last_reset_at == T0
        assert (s.home_id, s.messages_rx, s.messages_tx) == (1, 100, 50)
        assert ds.load(p) == s

    def test_climbing_counters_keep_reset_time(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        t1 = T0 + timedelta(minutes=1)
        s = ds.refresh(p, home_id=1, messages_rx=140, messages_tx=60, now=t1)
        # No reset: last_reset_at is unchanged, counters + updated_at advance.
        assert s.last_reset_at == T0
        assert s.updated_at == t1
        assert (s.messages_rx, s.messages_tx) == (140, 60)

    def test_rx_drop_stamps_reset(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        t1 = T0 + timedelta(hours=1)
        s = ds.refresh(p, home_id=1, messages_rx=5, messages_tx=60, now=t1)
        assert s.last_reset_at == t1

    def test_tx_drop_stamps_reset(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        t1 = T0 + timedelta(hours=1)
        s = ds.refresh(p, home_id=1, messages_rx=200, messages_tx=3, now=t1)
        assert s.last_reset_at == t1

    def test_home_id_change_stamps_reset(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        t1 = T0 + timedelta(hours=1)
        s = ds.refresh(p, home_id=2, messages_rx=200, messages_tx=99, now=t1)
        assert s.last_reset_at == t1
        assert s.home_id == 2

    def test_equal_counters_are_not_a_reset(self, tmp_path: Path) -> None:
        # A repeated sample with identical counters (an idle mesh) must not
        # register as a restart.
        p = _info(tmp_path)
        ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=T0)
        t1 = T0 + timedelta(minutes=1)
        s = ds.refresh(p, home_id=1, messages_rx=100, messages_tx=50, now=t1)
        assert s.last_reset_at == T0


class TestLoad:
    def test_missing_is_none(self, tmp_path: Path) -> None:
        assert ds.load(_info(tmp_path)) is None

    def test_corrupt_is_none(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        p.parent.mkdir(parents=True)
        p.write_text("{not valid json", encoding="utf-8")
        assert ds.load(p) is None

    def test_partial_is_none(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        p.parent.mkdir(parents=True)
        p.write_text('{"home_id": 1}', encoding="utf-8")
        assert ds.load(p) is None

    def test_roundtrip(self, tmp_path: Path) -> None:
        p = _info(tmp_path)
        s = ds.refresh(p, home_id=7, messages_rx=1, messages_tx=2, now=T0)
        assert ds.load(p) == s


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
