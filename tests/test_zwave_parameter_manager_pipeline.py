#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for the shared ZPM pipeline.

``pipeline`` holds the policy-file load, the shipped mapping load, and the
plan + report composition that BOTH the in-process handler and the standalone
``zwavectl`` CLI run -- the one place either consumer's pipeline lives.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from custom_components.blueprint_toolkit.zwave_parameter_manager import (
    pipeline,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (
    MappingTable,
)

_VALID = """
policies:
  - name: hourly-checkin
    match:
      power: battery
    settings:
      wake_up_interval: 3600
"""


def test_load_policies_parses_a_valid_file(tmp_path: Path) -> None:
    f = tmp_path / "zpm.yaml"
    f.write_text(_VALID)
    policies, errors = pipeline.load_policies(f)
    assert errors == []
    assert [p.name for p in policies] == ["hourly-checkin"]


def test_load_policies_missing_file_does_not_crash(tmp_path: Path) -> None:
    # A missing file reads clean (no OSError surfaced); the empty content then
    # fails validation like any other invalid config -- the same behavior the
    # in-process handler had before this pipeline was extracted.
    policies, errors = pipeline.load_policies(tmp_path / "absent.yaml")
    assert policies == ()
    assert errors == ["'policies' must be a list"]


def test_load_policies_reports_bad_yaml(tmp_path: Path) -> None:
    f = tmp_path / "zpm.yaml"
    f.write_text("policies: [oops\n")
    policies, errors = pipeline.load_policies(f)
    assert policies == ()
    assert errors and "YAML parse error" in errors[0]


def test_load_mapping_loads_the_shipped_table() -> None:
    mapping, err = pipeline.load_mapping()
    assert err is None
    assert isinstance(mapping, MappingTable)


def test_plan_and_report_composes_over_an_empty_fleet() -> None:
    mapping, _ = pipeline.load_mapping()
    assert mapping is not None
    plan, report = pipeline.plan_and_report([], [], mapping)
    assert plan.writes == ()
    assert report.devices == ()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
