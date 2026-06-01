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
"""Tests for ``scripts/canonicalize_zwave_mapping.py``.

Exercises the deterministic-ordering invariants the script promises:
top-level key order, locator order by catalog declaration, label
order by extraction frequency, idempotence, and the ``--check`` mode.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "canonicalize_zwave_mapping.py"


def _run(
    mapping: Path,
    output: Path | None = None,
    extraction: Path | None = None,
    check: bool = False,
    reviewed: Path | None = None,
    emit_fixture: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [str(SCRIPT), "--mapping", str(mapping)]
    if extraction is not None:
        cmd += ["--extraction", str(extraction)]
    if output is not None:
        cmd += ["--output", str(output)]
    if reviewed is not None:
        cmd += ["--reviewed", str(reviewed)]
    if emit_fixture is not None:
        cmd += ["--emit-fixture", str(emit_fixture)]
    if check:
        cmd += ["--check"]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _write_extraction(path: Path, freq: dict[str, int]) -> None:
    """Build a tiny extraction JSON whose only contents are
    CC 112 labels with the given device-count map."""

    _write(
        path,
        {
            "tag": "v-test",
            "command_classes": {
                "112": {
                    "name": "Configuration",
                    "label_count": len(freq),
                    "labels": [
                        {"label": lbl, "device_count": cnt}
                        for lbl, cnt in freq.items()
                    ],
                }
            },
        },
    )


def test_top_level_key_order(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    out = tmp_path / "o.json"
    _write(
        src,
        {
            "high_tokens": [],
            "off_labels": [],
            "locators": {},
            "metadata": {"zwave_js_tag": "v1.0.0"},
            "quirks": {},
            "low_tokens": [],
            "on_labels": [],
        },
    )
    proc = _run(src, output=out)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(out.read_text())
    assert list(parsed) == [
        "metadata",
        "locators",
        "quirks",
        "off_labels",
        "on_labels",
        "low_tokens",
        "high_tokens",
    ]


def test_locator_order_matches_catalog_declaration(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    out = tmp_path / "o.json"
    _write(
        src,
        {
            "locators": {
                "wake_up_interval": {
                    "command_class": 132,
                    "property": "wakeUpInterval",
                },
                "motion_sensitivity": {"labels": ["X"]},
                "light_on_motion": {"labels": ["Y"]},
            }
        },
    )
    proc = _run(src, output=out)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(out.read_text())
    # GenericParamNames declaration order puts motion_sensitivity
    # before light_on_motion before wake_up_interval.
    assert list(parsed["locators"]) == [
        "motion_sensitivity",
        "light_on_motion",
        "wake_up_interval",
    ]


def test_label_order_by_extraction_frequency(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    extraction = tmp_path / "e.json"
    out = tmp_path / "o.json"
    _write_extraction(
        extraction,
        {
            "PIR Sensitivity": 23,
            "Motion Sensor Sensitivity": 18,
            "Motion Sensitivity": 16,
        },
    )
    _write(
        src,
        {
            "locators": {
                "motion_sensitivity": {
                    "labels": [
                        "Motion Sensitivity",
                        "Motion Sensor Sensitivity",
                        "PIR Sensitivity",
                    ]
                }
            }
        },
    )
    proc = _run(src, output=out, extraction=extraction)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(out.read_text())
    assert parsed["locators"]["motion_sensitivity"]["labels"] == [
        "PIR Sensitivity",
        "Motion Sensor Sensitivity",
        "Motion Sensitivity",
    ]


def test_label_order_alphabetic_without_extraction(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    out = tmp_path / "o.json"
    _write(
        src,
        {"locators": {"motion_sensitivity": {"labels": ["b", "a", "c"]}}},
    )
    proc = _run(src, output=out)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(out.read_text())
    # Without frequency info, labels fall back to alphabetical.
    assert parsed["locators"]["motion_sensitivity"]["labels"] == ["a", "b", "c"]


def test_canonicalize_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"
    _write(
        src,
        {
            "locators": {
                "motion_sensitivity": {"labels": ["b", "a"]},
                "wake_up_interval": {
                    "command_class": 132,
                    "property": "wakeUpInterval",
                },
            },
            "off_labels": ["off", "disable"],
            "on_labels": ["on", "enable"],
        },
    )
    _run(src, output=out1)
    _run(out1, output=out2)
    assert out1.read_text() == out2.read_text()


def test_check_mode_passes_on_canonical_input(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    out = tmp_path / "o.json"
    _write(src, {"locators": {}})
    _run(src, output=out)
    # ``out`` is canonical by construction.
    proc = _run(out, check=True)
    assert proc.returncode == 0, proc.stderr


def test_check_mode_fails_on_non_canonical_input(tmp_path: Path) -> None:
    src = tmp_path / "m.json"
    _write(
        src,
        {
            "high_tokens": ["high"],
            "locators": {},
        },
    )
    proc = _run(src, check=True)
    assert proc.returncode == 1
    assert "not in canonical form" in proc.stderr


def test_reviewed_companion_canonicalized(tmp_path: Path) -> None:
    """--reviewed sorts the companion by concept (declaration order),
    then manufacturer, then model, and normalizes entry key order so two
    runs produce byte-identical companions."""

    src = tmp_path / "m.json"
    _write(src, {"locators": {}})
    reviewed = tmp_path / "reviewed.json"
    _write(
        reviewed,
        [
            {"model": "1", "manufacturer": "Z", "concept": "light_on_motion"},
            {
                "concept": "motion_sensitivity",
                "manufacturer": "B",
                "model": "2",
            },
            {
                "concept": "motion_sensitivity",
                "manufacturer": "A",
                "model": "9",
            },
        ],
    )
    proc = _run(src, reviewed=reviewed)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(reviewed.read_text())
    assert parsed == [
        {"concept": "motion_sensitivity", "manufacturer": "A", "model": "9"},
        {"concept": "motion_sensitivity", "manufacturer": "B", "model": "2"},
        {"concept": "light_on_motion", "manufacturer": "Z", "model": "1"},
    ]
    # --check passes on the now-canonical companion.
    proc2 = _run(src, reviewed=reviewed, check=True)
    assert proc2.returncode == 0, proc2.stderr


def test_emit_fixture_drives_canonical_check(tmp_path: Path) -> None:
    """--emit-fixture writes the (label, device_count) slice the
    canonical-form check needs, so the canonicalized mapping passes
    --check against the emitted fixture alone -- keeping the fixture in
    lockstep with the mapping instead of hand-maintained."""

    extraction = tmp_path / "e.json"
    _write_extraction(
        extraction,
        {
            "PIR Sensitivity": 23,
            "Motion Sensitivity": 16,
            "Flash LED on Motion": 4,
        },
    )
    src = tmp_path / "m.json"
    _write(
        src,
        {
            "locators": {
                "motion_sensitivity": {
                    "labels": ["Motion Sensitivity", "PIR Sensitivity"]
                },
                "light_on_motion": {"labels": ["Flash LED on Motion"]},
            }
        },
    )
    fixture = tmp_path / "fixture.json"
    proc = _run(src, extraction=extraction, emit_fixture=fixture)
    assert proc.returncode == 0, proc.stderr
    # The emitted fixture carries each located label's device_count.
    f = json.loads(fixture.read_text())
    counts = {
        e["label"]: e["device_count"]
        for e in f["command_classes"]["112"]["labels"]
    }
    assert counts == {
        "PIR Sensitivity": 23,
        "Motion Sensitivity": 16,
        "Flash LED on Motion": 4,
    }
    # Re-checking the now-canonical mapping against ONLY the emitted
    # fixture passes -- the frequency sort is reproducible from it.
    proc2 = _run(src, extraction=fixture, check=True)
    assert proc2.returncode == 0, proc2.stderr


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
