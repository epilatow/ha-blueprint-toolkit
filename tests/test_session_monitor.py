#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "probatio",
#     "pyyaml",
#     "zwave-js-server-python==0.73.1",
#     "pytest-homeassistant-custom-component==0.13.373",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the always-on Z-Wave driver-session monitor.

Uses the lightweight homeassistant-modules stub the handler tests install
(so the function-scoped ``dt`` / ``event`` imports resolve) plus small fake
driver objects. The reset-detection itself lives in ``zwave.driver_session``
and is covered by ``test_zwave_driver_session``; here we exercise the
duck-typed driver read and the sample-then-write glue.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from _handler_stubs import install_homeassistant_stubs  # noqa: E402

FROZEN = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
install_homeassistant_stubs(frozen_now=FROZEN)

from custom_components.blueprint_toolkit import (  # noqa: E402
    session_monitor,
)
from custom_components.blueprint_toolkit.zwave import (  # noqa: E402
    driver_session as ds,
)


class _Stats:
    def __init__(self, rx: int, tx: int) -> None:
        self.messages_rx = rx
        self.messages_tx = tx


class _Controller:
    def __init__(self, home_id: int, rx: int, tx: int) -> None:
        self.home_id = home_id
        self.statistics = _Stats(rx, tx)


class _Hass:
    """Minimal hass: one optional loaded zwave_js entry + a sync executor.

    The monitor selects its entry through the shared accessor, which
    asks for LOADED entries only, so the stub answers
    ``async_loaded_entries``.
    """

    def __init__(self, controller: object | None) -> None:
        driver = None
        if controller is not None:
            driver = type("D", (), {"controller": controller})()
        client = type("C", (), {"driver": driver})()
        runtime = type("R", (), {"client": client})()
        entry = type("E", (), {"runtime_data": runtime})()
        entries = [entry] if controller is not None else []
        self.config_entries = type(
            "CE",
            (),
            {"async_loaded_entries": lambda _self, _domain: entries},
        )()

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


def _hass(controller: object | None) -> Any:
    return _Hass(controller)


class TestReadLive:
    def test_reads_driver_stats(self) -> None:
        stats = session_monitor._read_live(_hass(_Controller(42, 100, 50)))
        assert stats is not None
        assert (stats.home_id, stats.messages_rx, stats.messages_tx) == (
            42,
            100,
            50,
        )

    def test_no_zwave_js_entry_is_none(self) -> None:
        assert session_monitor._read_live(_hass(None)) is None

    def test_non_int_stats_are_none(self) -> None:
        # A driver whose statistics aren't populated with ints (e.g. a test
        # MagicMock, or the driver still connecting) reads as unavailable
        # rather than crashing the sampler.
        class _Bad:
            home_id = 1
            statistics = object()  # no messages_rx / messages_tx

        assert session_monitor._read_live(_hass(_Bad())) is None


class TestRefreshOnce:
    async def test_writes_the_record(self, tmp_path: Path) -> None:
        path = tmp_path / "blueprint_toolkit" / "zwave-js-info.json"
        await session_monitor.async_refresh(
            _hass(_Controller(42, 100, 50)), path
        )
        rec = ds.load(path)
        assert rec is not None
        assert rec.home_id == 42
        assert (rec.messages_rx, rec.messages_tx) == (100, 50)
        assert rec.last_reset_at == FROZEN

    async def test_no_driver_writes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "blueprint_toolkit" / "zwave-js-info.json"
        await session_monitor.async_refresh(_hass(None), path)
        assert not path.exists()


class TestStart:
    async def test_samples_now_and_returns_unsub(self, tmp_path: Path) -> None:
        path = tmp_path / "blueprint_toolkit" / "zwave-js-info.json"
        unsub = await session_monitor.async_start(
            _hass(_Controller(7, 3, 4)), path
        )
        # The initial sample wrote the record; the return is the timer unsub.
        assert ds.load(path) is not None
        assert callable(unsub)


if __name__ == "__main__":
    import pytest

    # ``-p no:homeassistant`` disables pytest-HACC's plugin, which conflicts
    # with the homeassistant-module stubs this file installs.
    sys.exit(
        pytest.main([__file__, "-v", "-p", "no:homeassistant", *sys.argv[1:]])
    )
