# This is AI generated code
"""Always-on Z-Wave driver-session monitor.

Samples the in-process ``zwave_js`` driver's controller statistics every
minute and refreshes the shared ``zwave-js-info.json`` (see
``zwave.driver_session``), so ``last_reset_at`` tracks driver / add-on
restarts for every consumer -- the ZPM handler, ZRM, and the CLI -- whether or
not any automation is configured. Persisting the counters is what lets the
first sample after an HA Core restart detect a driver restart that happened
while Core was down.

The driver is read by duck-typing the passed ``hass`` so this module carries
no module-scope HA imports; the timer + clock imports are function-scoped.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from .zwave import driver_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from homeassistant.core import HomeAssistant

    from .zwave.driver_session import DriverSession

_LOGGER = logging.getLogger(__name__)
_INTERVAL = timedelta(seconds=60)
_ZWAVE_JS_DOMAIN = "zwave_js"


@dataclass(frozen=True)
class _LiveStats:
    home_id: int
    messages_rx: int
    messages_tx: int


def _read_live(hass: HomeAssistant) -> _LiveStats | None:
    """The live controller stats, or ``None`` when the driver is unavailable.

    Walks ``zwave_js`` entry -> client -> driver -> controller -> statistics by
    duck-typing, returning ``None`` at any missing hop (zwave_js not loaded,
    the driver still connecting, statistics not yet populated).
    """
    entries = hass.config_entries.async_entries(_ZWAVE_JS_DOMAIN)
    if not entries:
        return None
    runtime = getattr(entries[0], "runtime_data", None)
    client = getattr(runtime, "client", None)
    driver = getattr(client, "driver", None)
    controller = getattr(driver, "controller", None)
    if controller is None:
        return None
    home_id = getattr(controller, "home_id", None)
    stats = getattr(controller, "statistics", None)
    rx = getattr(stats, "messages_rx", None)
    tx = getattr(stats, "messages_tx", None)
    if not (
        isinstance(home_id, int) and isinstance(rx, int) and isinstance(tx, int)
    ):
        return None
    return _LiveStats(home_id=home_id, messages_rx=rx, messages_tx=tx)


async def async_refresh(
    hass: HomeAssistant, path: Path
) -> DriverSession | None:
    """Sample the driver once and fold it into the record.

    Returns the refreshed record (whose ``last_reset_at`` a caller uses to
    decide whether the queue was flushed), or ``None`` when the driver is
    unavailable. The ZPM handler calls this at reconcile time so its flush
    decision doesn't depend on the monitor's own sampling cadence.
    """
    live = _read_live(hass)
    if live is None:
        return None
    from homeassistant.util import dt as dt_util

    session: DriverSession = await hass.async_add_executor_job(
        functools.partial(
            driver_session.refresh,
            path,
            home_id=live.home_id,
            messages_rx=live.messages_rx,
            messages_tx=live.messages_tx,
            now=dt_util.utcnow(),
        )
    )
    return session


async def _safe_refresh(hass: HomeAssistant, path: Path) -> None:
    try:
        await async_refresh(hass, path)
    except OSError as err:
        _LOGGER.warning("zwave-js-info refresh failed: %s", err)


async def async_start(hass: HomeAssistant, path: Path) -> Callable[[], None]:
    """Sample once now, then every minute; return the timer's unsubscribe."""
    from homeassistant.helpers.event import (
        async_track_time_interval,
    )

    async def _tick(_now: datetime) -> None:
        await _safe_refresh(hass, path)

    await _safe_refresh(hass, path)
    unsub: Callable[[], None] = async_track_time_interval(
        hass, _tick, _INTERVAL
    )
    return unsub
