#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     # voluptuous: importing the watchdogs' logic modules (for
#     # their ``ISSUES``) pulls ``helpers_runtime``, which imports
#     # voluptuous at module scope.
#     "voluptuous",
#     # types-PyYAML so the per-file ``mypy --strict`` run has real
#     # yaml stubs: importing the package follows (via ``__init__``'s
#     # lazy handler imports) into reference_watchdog's
#     # ``yaml.SafeLoader`` subclass, which errors under
#     # ``disallow_subclassing_any`` when yaml resolves to ``Any``.
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Issue-contract drift test.

Locks each module's ``Issue`` contracts (gathered from their
``ISSUES`` exports) against the ``issues`` entries in
``strings.json`` / ``translations/en.json`` so a renamed key,
an added / removed ``{placeholder}`` token, or a new issue
added on only one side fails a test instead of silently
shipping a broken Repairs dialog (HA renders an unfilled
``{token}`` literally, or drops a placeholder value).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit import (  # noqa: E402
    ISSUES as _install_issues,
)
from custom_components.blueprint_toolkit.device_watchdog import (  # noqa: E402
    logic as dw_logic,
)
from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E402, E501
    logic as edw_logic,
)
from custom_components.blueprint_toolkit.helpers_logic import (  # noqa: E402
    Issue,
)

# Every module that raises repair issues exports an ``ISSUES``
# tuple; the drift checks below run against the union. A new
# issue-raising module is added here (the same explicit coupling
# as test_integration's service-registration set).
ALL_ISSUES: tuple[type[Issue], ...] = (
    *edw_logic.ISSUES,
    *dw_logic.ISSUES,
    *_install_issues,
)


def expected_issue_tokens(cls: type[Issue]) -> set[str]:
    """The ``{placeholder}`` token set an issue's strings must use.

    The dataclass fields, plus ``attribution`` for ``ATTRIBUTED``
    issues (the dispatcher injects that token, so it is not a
    constructor field).
    """
    names = {f.name for f in fields(cls)}
    if cls.ATTRIBUTED:
        names |= {"attribution"}
    return names


_INTEGRATION = REPO_ROOT / "custom_components" / "blueprint_toolkit"
_STRINGS = _INTEGRATION / "strings.json"
_EN = _INTEGRATION / "translations" / "en.json"
_TOKEN_RE = re.compile(r"{(\w+)}")


def _issues(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text())["issues"])


def _all_tokens(entry: Any) -> set[str]:
    """Every ``{token}`` referenced anywhere in an issue entry.

    HA fills title / description / fix-flow strings from one
    placeholder dict, so the union across the entry is what
    must be supplied.
    """
    tokens: set[str] = set()
    if isinstance(entry, str):
        tokens.update(_TOKEN_RE.findall(entry))
    elif isinstance(entry, dict):
        for value in entry.values():
            tokens |= _all_tokens(value)
    return tokens


def _confirm_title(entry: dict[str, Any]) -> str:
    step = entry.get("fix_flow", {}).get("step", {})
    title = step.get("confirm", {}).get("title", "")
    return title if isinstance(title, str) else ""


@pytest.mark.parametrize(
    "cls",
    ALL_ISSUES,
    ids=[c.KEY for c in ALL_ISSUES],
)
@pytest.mark.parametrize("path", [_STRINGS, _EN], ids=["strings", "en"])
def test_placeholder_tokens_match_json(
    cls: type[Issue],
    path: Path,
) -> None:
    issues = _issues(path)
    assert cls.KEY in issues, (
        f"{cls.__name__}.KEY '{cls.KEY}' has no issues entry in {path.name}"
    )
    tokens = _all_tokens(issues[cls.KEY])
    expected = set(expected_issue_tokens(cls))
    assert tokens == expected, (
        f"{cls.__name__} ({cls.KEY}) placeholder mismatch in {path.name}: "
        f"only-in-json={tokens - expected}, "
        f"only-in-contract={expected - tokens}"
    )


@pytest.mark.parametrize(
    "cls",
    ALL_ISSUES,
    ids=[c.KEY for c in ALL_ISSUES],
)
@pytest.mark.parametrize("path", [_STRINGS, _EN], ids=["strings", "en"])
def test_confirm_title_is_static(
    cls: type[Issue],
    path: Path,
) -> None:
    # Confirm-step titles must carry no {placeholder} (they
    # render in a fixed-height dialog header that wraps badly).
    title = _confirm_title(_issues(path)[cls.KEY])
    assert _TOKEN_RE.findall(title) == [], (
        f"{cls.KEY} confirm title in {path.name} has tokens: {title!r}"
    )


@pytest.mark.parametrize("path", [_STRINGS, _EN], ids=["strings", "en"])
def test_every_json_issue_has_a_contract(path: Path) -> None:
    # Bidirectional: a new issues entry added to the JSON
    # without a registered placeholder contract is a gap.
    registered = {c.KEY for c in ALL_ISSUES}
    json_keys = set(_issues(path))
    assert json_keys == registered, (
        f"{path.name} issues vs contracts mismatch: "
        f"only-in-json={json_keys - registered}, "
        f"only-in-contracts={registered - json_keys}"
    )


def test_strings_and_en_issue_keys_match() -> None:
    assert set(_issues(_STRINGS)) == set(_issues(_EN))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
