# This is AI generated code
"""Shared display formatting for the Z-Wave convergence reports.

Pure value-to-string helpers the report renderers share, so the
automation notification and the CLI table format the same derived
values identically: a wake interval as a human duration, a wake
timestamp as a fixed-width string. No HA / socket deps -- importable
from the CLI venv alongside the rest of the ``zwave`` package.
"""

from __future__ import annotations

from datetime import datetime

# Largest-first so a compound render reads "1 hour 30 minutes".
_DURATION_UNITS: tuple[tuple[str, int], ...] = (
    ("day", 86400),
    ("hour", 3600),
    ("minute", 60),
    ("second", 1),
)


def humanize_duration(seconds: int) -> str:
    """Render a whole-second duration in human units.

    ``604800 -> "7 days"``, ``5400 -> "1 hour 30 minutes"``,
    ``0 -> "0 seconds"``. Each present unit is pluralised and zero-valued
    units drop out. Wake intervals are whole minutes in practice, but the
    breakdown is exact for any non-negative second count.
    """

    if seconds < 0:
        raise ValueError(f"duration must be non-negative, got {seconds}")
    if seconds == 0:
        return "0 seconds"
    parts: list[str] = []
    remaining = seconds
    for unit, size in _DURATION_UNITS:
        count, remaining = divmod(remaining, size)
        if count:
            plural = "" if count == 1 else "s"
            parts.append(f"{count} {unit}{plural}")
    return " ".join(parts)


def format_wake_time(when: datetime) -> str:
    """Render a wake timestamp to minute precision: ``YYYY-MM-DD HH:MM``.

    The caller passes an already-localised ``datetime``; this only fixes
    the field layout so both report surfaces read the same.
    """

    return when.strftime("%Y-%m-%d %H:%M")
