#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pyyaml",
#     "pytest-homeassistant-custom-component==0.13.372",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the shared zwave.formatting display helpers."""

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


import pytest  # noqa: E402

from custom_components.blueprint_toolkit.zwave.formatting import (  # noqa: E402
    format_wake_time,
    humanize_duration,
)


def test_humanize_round_single_units() -> None:
    assert humanize_duration(604800) == "7 days"
    assert humanize_duration(86400) == "1 day"
    assert humanize_duration(14400) == "4 hours"
    assert humanize_duration(3600) == "1 hour"
    assert humanize_duration(60) == "1 minute"


def test_humanize_compound_units() -> None:
    assert humanize_duration(5400) == "1 hour 30 minutes"
    assert humanize_duration(90) == "1 minute 30 seconds"
    # Every unit present, all singular.
    assert humanize_duration(90061) == "1 day 1 hour 1 minute 1 second"


def test_humanize_zero() -> None:
    assert humanize_duration(0) == "0 seconds"


def test_humanize_negative_raises() -> None:
    with pytest.raises(ValueError):
        humanize_duration(-1)


def test_format_wake_time_minute_precision() -> None:
    assert format_wake_time(datetime(2026, 6, 8, 14, 5)) == "2026-06-08 14:05"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
