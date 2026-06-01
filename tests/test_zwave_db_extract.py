#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
# ]
# ///
# This is AI generated code
"""Tests for ``scripts/zwave_db_extract.py``.

Exercises the JSONC stripping, ``$import`` resolution (both
device-dir-relative and ``~/``-rooted), and the per-device ``instances``
grouping under each label across an in-repo synthetic device DB.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "zwave_db_extract.py"
FIXTURE_DEVICES = REPO_ROOT / "tests" / "fixtures" / "zwave_db" / "devices"


def _run(output: Path) -> dict[str, object]:
    proc = subprocess.run(
        [
            str(SCRIPT),
            "--tag",
            "v-fixture",
            "--devices-root",
            str(FIXTURE_DEVICES),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    raw = json.loads(output.read_text())
    assert isinstance(raw, dict)
    return raw


def _labels_by_text(data: dict[str, object]) -> dict[str, dict[str, object]]:
    ccs = data["command_classes"]
    assert isinstance(ccs, dict)
    cc_112 = ccs["112"]
    assert isinstance(cc_112, dict)
    labels = cc_112["labels"]
    assert isinstance(labels, list)
    out: dict[str, dict[str, object]] = {}
    for entry in labels:
        assert isinstance(entry, dict)
        text = entry["label"]
        assert isinstance(text, str)
        out[text] = entry
    return out


def _instances_by_model(
    entry: dict[str, object],
) -> dict[str, dict[str, object]]:
    insts = entry["instances"]
    assert isinstance(insts, list)
    return {i["model"]: i for i in insts}


def test_resolves_imports_and_aggregates(tmp_path: Path) -> None:
    data = _run(tmp_path / "out.json")
    assert data["tag"] == "v-fixture"
    assert data["devices_processed"] == 5

    by_text = _labels_by_text(data)
    # Inline label on DEV-A + DEV-B (ascending 0-8) + DEV-E
    # (descending 8-255, with a direction-bearing description).
    assert "Motion Sensor Sensitivity" in by_text
    sens = by_text["Motion Sensor Sensitivity"]
    assert sens["device_count"] == 3
    insts = _instances_by_model(sens)
    assert insts["DEV-A"]["min"] == 0 and insts["DEV-A"]["max"] == 8
    assert insts["DEV-E"]["min"] == 8 and insts["DEV-E"]["max"] == 255
    # The per-device description -- the only place the inversion is
    # stated -- survives import resolution onto the instance.
    assert insts["DEV-E"]["description"] == "8 = highest, 255 = lowest"
    assert insts["DEV-A"]["description"] is None

    # DEV-A's #3 imports ``humidity_threshold`` with no override;
    # DEV-B's #4 imports ``humidity_threshold_zse44`` which chains to
    # the same base with a maxValue override. Both group under the same
    # resolved label, each as its own instance with its own range.
    assert "Humidity Report Threshold" in by_text
    hum = by_text["Humidity Report Threshold"]
    assert hum["device_count"] == 2
    hinsts = _instances_by_model(hum)
    assert hinsts["DEV-A"]["unit"] == "%"
    assert hinsts["DEV-A"]["max"] == 50 and hinsts["DEV-B"]["max"] == 80

    # DEV-A's #2 imports a label-less base and supplies the label
    # inline; DEV-C's #1 ``~/templates/...`` form does the same. The
    # imported options ride onto each instance.
    assert "Flash LED on Motion" in by_text
    led = by_text["Flash LED on Motion"]
    assert led["device_count"] == 2
    led_inst = _instances_by_model(led)["DEV-A"]
    assert led_inst["min"] == 0 and led_inst["max"] == 1
    led_opts = led_inst["options"]
    assert isinstance(led_opts, list)
    option_labels = [o["label"] for o in led_opts]
    assert option_labels == ["Disable", "Enable"]


def test_import_cycle_breaks_cleanly(tmp_path: Path) -> None:
    """A self-referential template aborts the chain after one step
    rather than recursing until the stack runs out; the device's
    inline override (here, the label) still survives."""

    data = _run(tmp_path / "out.json")
    by_text = _labels_by_text(data)
    assert "Cycle Param" in by_text


def test_output_is_deterministic(tmp_path: Path) -> None:
    """Two runs produce byte-identical output -- a precondition for
    the weekly CI bump-and-PR-if-changed workflow."""

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _run(first)
    _run(second)
    # The ``extracted_at`` timestamp is the only non-deterministic
    # field. Strip it, then compare preserving key order (no sort_keys)
    # so the test actually verifies the fixed key ordering the extractor
    # promises, not just value equality.
    first_doc = json.loads(first.read_text())
    second_doc = json.loads(second.read_text())
    del first_doc["extracted_at"]
    del second_doc["extracted_at"]
    assert json.dumps(first_doc) == json.dumps(second_doc)


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
