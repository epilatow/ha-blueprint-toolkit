# This is AI generated code
"""The ZPM concept catalog.

The catalog is the canonical list of device-agnostic settings ZPM
exposes (``motion_sensitivity``, ``light_on_motion``, ...). Each entry
declares its name, value shape (``ParamType``), units / scale, and a
human-readable description suitable for both the maintainer and the
end user.

This module is split out from ``logic.py`` so consumers that only need
the concept definitions (the mapping-suggester skill, the future
user-facing concept-reference doc renderer, etc.) can read a small
focused file rather than the whole resolver / planner. ``logic.py``
re-exports the names below for back-compat.

Concept descriptions are plain markdown so a future doc renderer can
extract them directly: the first sentence is the one-line summary
suitable for a list view, then detail paragraphs follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum, auto


class ParamType(Enum):
    """How a GenericParam's user-facing value is expressed."""

    BOOL = "bool"  # true/false, mapped to the device's on/off
    RANGE = "range"  # an integer rescaled onto the param's range
    VALUE = "value"  # real units, converted to the param's unit


class GenericParamNames(StrEnum):
    """Stable identifier for every concept the catalog defines.

    Using an enum (not bare strings) as the concept key means a policy
    can only name a concept that exists -- an invalid concept is
    unrepresentable rather than discovered at evaluation time.
    """

    MOTION_SENSITIVITY = auto()
    LIGHT_ON_MOTION = auto()
    HUMIDITY_REPORT_THRESHOLD = auto()
    THRESHOLD_CHECK_INTERVAL = auto()
    WAKE_UP_INTERVAL = auto()


# An inclusive (min, max) integer range. Used both for a RANGE
# concept's abstract target scale and for a device param's raw bounds.
ParamRange = tuple[int, int]


@dataclass(frozen=True)
class GenericParam:
    """An abstract, device-agnostic setting.

    ``description`` is plain markdown -- first sentence is the
    one-line summary, then detail paragraphs follow. A future doc
    renderer extracts these to build the concept reference for end
    users.

    ``units`` is the unit the user writes for VALUE params (and the
    base unit conversions are expressed in); ``None`` for BOOL/RANGE.
    ``range`` is the inclusive scale a RANGE param's value is given on
    and rescaled from (e.g. ``(1, 10)``); ``None`` for BOOL/VALUE.
    """

    name: GenericParamNames
    param_type: ParamType
    description: str
    units: str | None = None
    range: ParamRange | None = None


GENERIC_PARAMS: list[GenericParam] = [
    GenericParam(
        name=GenericParamNames.MOTION_SENSITIVITY,
        param_type=ParamType.RANGE,
        range=(1, 10),
        description="""\
How sensitive the device's motion or PIR sensor is, on a 1 (least
sensitive) - 10 (most sensitive) scale.

The resolver rescales the generic value onto each device's own
sensitivity range, so a value of 10 always picks the device's maximum
sensitivity regardless of whether its underlying scale runs 0-8, 1-3,
or anything else. A value of 1 always picks the lowest non-disabled
setting (the "disabled" state, where the device exposes one, is
preserved as off and not used as a low-end target).
""",
    ),
    GenericParam(
        name=GenericParamNames.LIGHT_ON_MOTION,
        param_type=ParamType.BOOL,
        description="""\
Whether the device's status LED illuminates when motion is detected.

`true` lights or flashes the LED on motion; `false` keeps it dark.
Devices typically expose this as an option-state parameter the
resolver maps to whichever raw value the device's metadata labels as
the off / on state.
""",
    ),
    GenericParam(
        name=GenericParamNames.HUMIDITY_REPORT_THRESHOLD,
        param_type=ParamType.VALUE,
        units="%",
        description="""\
The minimum humidity change (in percent) before the device sends an
unsolicited humidity report.

A value of `1` means "report on every 1% change"; a value of `5`
means "report only when humidity has changed by at least 5% since the
last report". Trades reporting freshness against radio airtime and
battery drain; battery devices typically want larger thresholds.
""",
    ),
    GenericParam(
        name=GenericParamNames.THRESHOLD_CHECK_INTERVAL,
        param_type=ParamType.VALUE,
        units="minutes",
        description="""\
How often (in minutes) the device wakes its sensors to compare the
current reading against the configured report thresholds.

Pairs with the report-threshold settings (humidity, temperature,
brightness, etc.): a shorter interval catches threshold crossings
faster at the cost of more battery; a longer interval saves battery
at the cost of staler reports.
""",
    ),
    GenericParam(
        name=GenericParamNames.WAKE_UP_INTERVAL,
        param_type=ParamType.VALUE,
        units="seconds",
        description="""\
How often (in seconds) a battery-powered device wakes up to check in
with the controller for queued commands.

Controls the latency for configuration and command delivery to
sleeping devices: shorter intervals deliver settings faster but drain
battery faster. The Z-Wave protocol uses command class 132 (Wake Up)
with the universal `wakeUpInterval` property for this, so the
locator is fixed across all devices rather than label-matched.
""",
    ),
]


CATALOG: dict[GenericParamNames, GenericParam] = {
    gp.name: gp for gp in GENERIC_PARAMS
}


# Catalog invariants the type system can't express (a RANGE param
# requires an ascending scale; others must not carry one) -- checked
# at import so a malformed catalog fails immediately, not at resolve.
assert set(CATALOG) == set(GenericParamNames), (
    "GENERIC_PARAMS must define every GenericParamNames member"
)
assert all(
    gp.range is None
    if gp.param_type is not ParamType.RANGE
    else gp.range is not None and gp.range[0] < gp.range[1]
    for gp in GENERIC_PARAMS
), "a RANGE concept needs an ascending range; others must set none"
assert all(gp.description.strip() for gp in GENERIC_PARAMS), (
    "every catalog entry needs a non-empty description"
)
