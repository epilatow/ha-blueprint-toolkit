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
"""Smoke test for the checked-in mapping.json.

Guards against typo / shape drift in the mapping data the resolver
consumes, and against accidental removal of a catalog concept's
locator. Doesn't pin specific labels (those evolve as the mapping is
regenerated) -- just that every concept has a locator and the file
round-trips through ``MappingTable.from_dict``.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))


from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    GenericParamNames,
    MappingTable,
)

_MAPPING = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "zwave_parameter_manager"
    / "mapping.json"
)
_CANONICALIZE = REPO_ROOT / "scripts" / "canonicalize_zwave_mapping.py"
_FIXTURE_EXTRACTION = (
    REPO_ROOT / "tests" / "fixtures" / "zwave_mapping_canonical_extraction.json"
)


def test_mapping_json_loads_and_covers_every_concept() -> None:
    raw = json.loads(_MAPPING.read_text(encoding="utf-8"))
    table = MappingTable.from_dict(raw)
    missing = [n for n in GenericParamNames if n not in table.locators]
    assert not missing, f"mapping.json missing locator(s): {missing}"


def test_mapping_json_is_canonical() -> None:
    """``mapping.json`` must byte-match its canonical form.

    The fixture extraction carries the (label, device_count) pairs
    used to sort each locator's labels by frequency; it lives in the
    repo so this check runs deterministically in CI without needing
    the full extraction in ``tmp/``. When ``mapping.json`` gains a
    new label, the fixture gets the same entry in the same commit.
    """

    proc = subprocess.run(
        [
            str(_CANONICALIZE),
            "--mapping",
            str(_MAPPING),
            "--extraction",
            str(_FIXTURE_EXTRACTION),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
