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
"""Tests for ``scripts/verify_zwave_mapping.py``.

Exercises the fleet YAML load + resolver classification path against
hand-built mapping.json / fleet.yaml pairs that target the three
status modes the script cares about: RESOLVED, NOT_APPLICABLE,
AMBIGUOUS.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_zwave_mapping.py"


def _run(
    tmp_path: Path,
    mapping: dict[str, object],
    fleet: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    mapping_path = tmp_path / "mapping.json"
    fleet_path = tmp_path / "fleet.yaml"
    mapping_path.write_text(json.dumps(mapping))
    fleet_path.write_text(yaml.safe_dump(fleet))
    return subprocess.run(
        [
            str(SCRIPT),
            "--mapping",
            str(mapping_path),
            "--fleet",
            str(fleet_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


_GOOD_MAPPING: dict[str, object] = {
    "locators": {
        "motion_sensitivity": {
            "labels": ["Motion Sensor Sensitivity", "PIR Sensitivity"]
        },
        "light_on_motion": {"labels": ["Flash LED on Motion"]},
        "humidity_report_threshold": {"labels": ["Humidity Report Threshold"]},
        "threshold_check_interval": {"labels": ["Threshold Check Interval"]},
        "wake_up_interval": {
            "command_class": 132,
            "property": "wakeUpInterval",
        },
    }
}


def _zse11_device() -> dict[str, object]:
    return {
        "node_id": 273,
        "name": "Office",
        "manufacturer": "Zooz",
        "model": "ZSE11",
        "is_listening": False,
        "params": [
            {
                "command_class": 112,
                "property": 12,
                "label": "Motion Sensor Sensitivity",
                "min": 0,
                "max": 8,
                "states": {0: "Disable"},
            },
            {
                "command_class": 132,
                "property": "wakeUpInterval",
                "label": "Wake Up Interval",
                "min": 0,
                "max": 86400,
                "unit": "seconds",
            },
        ],
    }


def test_resolved_exits_zero(tmp_path: Path) -> None:
    fleet: dict[str, object] = {"devices": [_zse11_device()]}
    proc = _run(tmp_path, _GOOD_MAPPING, fleet)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "RESOLVED" in proc.stdout
    # ZSE11 has no humidity threshold; concept should be NOT_APPLICABLE.
    assert "NOT_APPLICABLE" in proc.stdout
    # The matched param's label appears next to the resolution arrow.
    assert "Motion Sensor Sensitivity" in proc.stdout


def test_ambiguous_exits_nonzero(tmp_path: Path) -> None:
    # Device has two params whose labels both match the locator's
    # case-insensitive set -- a real bug in the mapping that verify
    # has to flag.
    fleet: dict[str, object] = {
        "devices": [
            {
                "node_id": 1,
                "name": "Duplicate-Match",
                "manufacturer": "TestMfg",
                "model": "TM-1",
                "is_listening": True,
                "params": [
                    {
                        "command_class": 112,
                        "property": 1,
                        "label": "Motion Sensor Sensitivity",
                        "min": 0,
                        "max": 8,
                    },
                    {
                        "command_class": 112,
                        "property": 2,
                        "label": "PIR Sensitivity",
                        "min": 0,
                        "max": 8,
                    },
                ],
            }
        ]
    }
    proc = _run(tmp_path, _GOOD_MAPPING, fleet)
    assert proc.returncode == 1, proc.stderr + proc.stdout
    assert "AMBIGUOUS" in proc.stdout


def test_ambiguous_params_excluded_from_unmapped(tmp_path: Path) -> None:
    """The unmapped-params rollup feeds the next LLM run; an
    AMBIGUOUS match still means the mapping captures those labels,
    so they must not appear as 'labels we might be missing'."""

    fleet: dict[str, object] = {
        "devices": [
            {
                "node_id": 3,
                "name": "Ambig",
                "manufacturer": "TestMfg",
                "model": "AM-1",
                "is_listening": True,
                "params": [
                    {
                        "command_class": 112,
                        "property": 1,
                        "label": "Motion Sensor Sensitivity",
                        "min": 0,
                        "max": 8,
                    },
                    {
                        "command_class": 112,
                        "property": 2,
                        "label": "PIR Sensitivity",
                        "min": 0,
                        "max": 8,
                    },
                ],
            }
        ]
    }
    proc = _run(tmp_path, _GOOD_MAPPING, fleet)
    assert proc.returncode == 1, proc.stderr + proc.stdout
    assert "AMBIGUOUS" in proc.stdout
    # Body section, not header -- "Motion Sensor Sensitivity" appears
    # in the row but the unmapped block below must omit both labels.
    if "Unmapped param labels" in proc.stdout:
        unmapped_block = proc.stdout.split("Unmapped param labels", 1)[1]
    else:
        unmapped_block = ""
    assert "Motion Sensor Sensitivity" not in unmapped_block
    assert "PIR Sensitivity" not in unmapped_block


def test_unmapped_params_summary(tmp_path: Path) -> None:
    """A param the mapping has no locator for surfaces in the
    unmapped-summary -- the candidate-finder for the suggester."""

    fleet: dict[str, object] = {
        "devices": [
            {
                "node_id": 2,
                "name": "Hum",
                "manufacturer": "TestMfg",
                "model": "HM-1",
                "is_listening": True,
                "params": [
                    {
                        "command_class": 112,
                        "property": 5,
                        "label": "Mystery Setting",
                        "min": 0,
                        "max": 10,
                    }
                ],
            }
        ]
    }
    proc = _run(tmp_path, _GOOD_MAPPING, fleet)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Unmapped param labels" in proc.stdout
    assert "Mystery Setting" in proc.stdout


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
