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
"""Tests for ``scripts/validate_zwave_mapping_proposal.py``.

Exercises the canonicalize-first short-circuit ("no changes" idle
case) plus the failure modes the SKILL.md validate step exists to
catch: hallucinated labels, ``from_dict`` round-trip failures.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_zwave_mapping_proposal.py"


def _run(
    proposed: Path,
    current: Path,
    extraction: Path,
    reviewed: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        str(SCRIPT),
        "--proposed",
        str(proposed),
        "--current",
        str(current),
        "--extraction",
        str(extraction),
    ]
    # Isolate from the real repo tmp/ sidecar: point --reviewed at a
    # test-controlled path (nonexistent unless the test writes it).
    cmd += ["--reviewed", str(reviewed or (extraction.parent / "none.json"))]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _basic_extraction(labels: dict[str, int]) -> dict[str, object]:
    return {
        "tag": "v-test",
        "command_classes": {
            "112": {
                "name": "Configuration",
                "label_count": len(labels),
                "labels": [
                    {"label": lbl, "device_count": cnt}
                    for lbl, cnt in labels.items()
                ],
            }
        },
    }


def _extraction_with_instances(
    label_instances: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    labels = []
    for label, insts in label_instances.items():
        labels.append(
            {
                "command_class": 112,
                "label": label,
                "device_count": len(insts),
                "instances": insts,
            }
        )
    return {
        "tag": "v-test",
        "command_classes": {"112": {"name": "Configuration", "labels": labels}},
    }


_NEO_DESCENDING = {
    "manufacturer": "NEO",
    "model": "PD01",
    "value_size": 2,
    "min": 8,
    "max": 255,
    "unit": None,
    "options": [],
    "description": "8 = highest, 255 = lowest",
}
_UNKNOWN_INST = {
    "manufacturer": "STEINEL",
    "model": "IS140",
    "value_size": 1,
    "min": 2,
    "max": 100,
    "unit": None,
    "options": [],
    "description": "Moving the potentiometer overwrites the setting.",
}


def test_descending_instance_without_quirk_fails(tmp_path: Path) -> None:
    """motion_sensitivity is RANGE; a device whose description says
    higher raw = lower sensitivity must not ship without an invert
    quirk. verify can't catch this -- the direction net is the gate."""

    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {"Motion Sensitivity": [dict(_NEO_DESCENDING)]}
        ),
    )
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            }
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL direction" in proc.stdout
    assert "NEO PD01" in proc.stdout


def test_descending_instance_with_invert_quirk_passes(tmp_path: Path) -> None:
    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {"Motion Sensitivity": [dict(_NEO_DESCENDING)]}
        ),
    )
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            },
            "quirks": {
                "motion_sensitivity": {"NEO": {"PD01": {"invert": True}}}
            },
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "all checks passed" in proc.stdout


def test_unknown_instance_needs_quirk_or_review(tmp_path: Path) -> None:
    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {"Motion Sensor Sensitivity": [dict(_UNKNOWN_INST)]}
        ),
    )
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensor Sensitivity"]}
            }
        },
    )
    # Unhandled -> fail.
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL direction" in proc.stdout

    # Reviewed-ascending acknowledgement -> passes.
    reviewed = tmp_path / "reviewed.json"
    _write_json(
        reviewed,
        [
            {
                "concept": "motion_sensitivity",
                "manufacturer": "STEINEL",
                "model": "IS140",
            }
        ],
    )
    proc2 = _run(proposed, current, extraction, reviewed=reviewed)
    assert proc2.returncode == 0, proc2.stderr + proc2.stdout
    assert "all checks passed" in proc2.stdout


def test_incompatible_unit_warns_but_passes(tmp_path: Path) -> None:
    """A VALUE-concept label match whose device unit the resolver
    can't convert is reported (UNMAPPABLE is safe + loud) but does not
    fail validation -- unlike a wrong-direction write."""

    odd_unit_inst = {
        "manufacturer": "McoHome",
        "model": "MH10",
        "value_size": 1,
        "min": 0,
        "max": 50,
        "unit": "2%",
        "options": [],
        "description": "Humidity report threshold",
    }
    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {"Humidity Report Threshold": [odd_unit_inst]}
        ),
    )
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "humidity_report_threshold": {
                    "labels": ["Humidity Report Threshold"]
                }
            }
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "UNIT WARNINGS" in proc.stdout
    assert "McoHome MH10" in proc.stdout
    assert "all checks passed" in proc.stdout


def test_no_changes_exits_zero(tmp_path: Path) -> None:
    """When the proposal canonicalizes to the current mapping byte-for-byte,
    validate exits clean -- the weekly idle case."""

    extraction = tmp_path / "e.json"
    _write_json(extraction, _basic_extraction({"X": 1}))

    canonical = {
        "locators": {"motion_sensitivity": {"labels": ["X"]}},
        "quirks": {},
        "off_labels": [],
        "on_labels": [],
        "low_tokens": [],
        "high_tokens": [],
    }
    current = tmp_path / "current.json"
    _write_json(current, canonical)
    # Same content, intentionally re-ordered to exercise the
    # canonicalize-first equality check.
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "high_tokens": [],
            "off_labels": [],
            "locators": {"motion_sensitivity": {"labels": ["X"]}},
            "quirks": {},
            "on_labels": [],
            "low_tokens": [],
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "no changes" in proc.stdout


def test_hallucinated_label_fails(tmp_path: Path) -> None:
    extraction = tmp_path / "e.json"
    _write_json(extraction, _basic_extraction({"Real Label": 1}))
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {"motion_sensitivity": {"labels": ["Made-Up Label"]}},
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL no-hallucinations" in proc.stdout
    assert "Made-Up Label" in proc.stdout


def test_round_trip_failure_propagates(tmp_path: Path) -> None:
    """A proposed mapping that violates the disjoint-label-token
    invariant fails the from_dict round-trip check."""

    extraction = tmp_path / "e.json"
    _write_json(extraction, _basic_extraction({}))
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {},
            "off_labels": ["overlap"],
            "on_labels": ["overlap"],
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL round-trip" in proc.stdout


def test_legitimate_diff_passes_all_checks(tmp_path: Path) -> None:
    """A clean addition to the locators -- new label is in the
    extraction, mapping round-trips, no fleet provided -- exits 0."""

    extraction = tmp_path / "e.json"
    _write_json(extraction, _basic_extraction({"New Label": 2}))
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {"motion_sensitivity": {"labels": ["New Label"]}},
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "all checks passed" in proc.stdout


def test_dropped_quirk_fails_preservation(tmp_path: Path) -> None:
    """A quirk in the current mapping that the proposal drops fails:
    quirks are additive like labels, and a dropped flagger-blind invert
    would otherwise be a silent wrong-direction write."""

    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {"Motion Sensitivity": [dict(_NEO_DESCENDING)]}
        ),
    )
    quirk = {"motion_sensitivity": {"NEO": {"PD01": {"invert": True}}}}
    current = tmp_path / "current.json"
    _write_json(
        current,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            },
            "quirks": quirk,
        },
    )
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            },
            "quirks": {},
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL quirk-preservation" in proc.stdout
    assert "NEO PD01" in proc.stdout


def test_preserved_quirk_passes(tmp_path: Path) -> None:
    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances(
            {
                "Motion Sensitivity": [dict(_NEO_DESCENDING)],
                "Motion Sensor Sensitivity": [
                    {
                        "manufacturer": "ACME",
                        "model": "A1",
                        "value_size": 1,
                        "min": 0,
                        "max": 10,
                        "unit": None,
                        "options": [],
                        "description": "0 = low, 10 = high",
                    }
                ],
            }
        ),
    )
    quirk = {"motion_sensitivity": {"NEO": {"PD01": {"invert": True}}}}
    current = tmp_path / "current.json"
    _write_json(
        current,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            },
            "quirks": quirk,
        },
    )
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {
                    "labels": [
                        "Motion Sensitivity",
                        "Motion Sensor Sensitivity",
                    ]
                }
            },
            "quirks": quirk,
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "all checks passed" in proc.stdout


def test_mapping_tokens_honored_by_flagger(tmp_path: Path) -> None:
    """The flagger's option check honors the mapping's low/high tokens,
    so a descending device whose option labels use vocabulary present
    only in the mapping (not the flagger's built-in word set) is still
    caught -- editing the vocab strengthens the gate, not just runtime."""

    inst = {
        "manufacturer": "ACME",
        "model": "X1",
        "value_size": 1,
        "min": None,
        "max": None,
        "unit": None,
        "options": [
            {"value": 1, "label": "Strong"},
            {"value": 2, "label": "Medium"},
            {"value": 3, "label": "Weak"},
        ],
        "description": None,
    }
    extraction = tmp_path / "e.json"
    _write_json(
        extraction,
        _extraction_with_instances({"Motion Sensitivity": [inst]}),
    )
    current = tmp_path / "current.json"
    _write_json(current, {"locators": {}})
    proposed = tmp_path / "proposed.json"
    _write_json(
        proposed,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["Motion Sensitivity"]}
            },
            "low_tokens": ["weak"],
            "high_tokens": ["strong"],
        },
    )
    proc = _run(proposed, current, extraction)
    assert proc.returncode == 1, proc.stdout
    assert "FAIL direction" in proc.stdout
    assert "ACME X1" in proc.stdout


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
