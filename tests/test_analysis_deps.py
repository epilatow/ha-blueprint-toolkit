#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "pytest-cov",
# ]
# ///
# This is AI generated code
"""Analysis-dependency invariants, gating written conventions.

The rules come from ``DEVELOPMENT.md`` "Analysis-dep pinning and
stub suppressions". The first and third gate conventions that were
violated in practice before anything enforced them; the second
gates one that holds today but which no tooling can repair once
broken.

1. Every file carrying a PEP 723 ``# /// script`` block that
   imports ``yaml`` declares ``types-PyYAML``. A PEP 723 block
   *replaces* ``[tool.repo-shared.code-quality] mypy-extra-deps``
   rather than merging with it, so a file that declares its own
   deps and forgets the stubs silently loses them. The failure is
   invisible: ``[[tool.mypy.overrides]]`` sets
   ``ignore_missing_imports`` for ``yaml``, so the module resolves
   to ``Any`` and ``mypy --strict`` checks none of the file's YAML
   code instead of erroring.

2. Every declaration site names the same
   ``pytest-homeassistant-custom-component`` version. A block that
   disagrees type-checks against a different Home Assistant
   release, and ``scripts/hacc_upgrade.py`` cannot repair it: that
   tool rewrites sites carrying the version being replaced, so one
   already drifted elsewhere is invisible to it.

3. The pinned ``pytest-homeassistant-custom-component`` version
   appears only where the dependency is declared, never in prose.
   Automation rewrites the pin literal at every declaration site;
   prose restating it is not rewritten and goes stale silently.
   Enforcing this against the *current* pin is what makes it
   stick: a prose mention gets written with whatever version is
   pinned that day, so it fails here at the moment it is
   introduced, and a stale one never reaches a commit.

4. ``.python-version`` satisfies every PEP 723 ``requires-python``
   floor and agrees with the two mypy knobs. The interpreter is
   pinned for the same reason the HACC version is -- it decides
   what the suite runs against -- but its failure mode is quieter:
   ``uv`` ignores a pin it cannot satisfy and resolves against the
   newest interpreter installed, exiting zero, so a pin that drifts
   below a floor silently stops pinning anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
HACC = "pytest-homeassistant-custom-component"

# Body of a PEP 723 inline-metadata block, per the spec's opening
# and closing sentinel lines.
_PEP723_BLOCK = re.compile(
    r"^# /// script$(.*?)^# ///$", re.MULTILINE | re.DOTALL
)
_YAML_IMPORT = re.compile(r"^\s*(?:import yaml\b|from yaml\b)", re.MULTILINE)


def _tracked(*suffixes: str) -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [
        REPO_ROOT / rel
        for rel in out.split("\0")
        if rel and rel.endswith(suffixes)
    ]


_REQUIRES_PYTHON = re.compile(
    r"^#\s*requires-python\s*=\s*\"[^0-9]*(\d+(?:\.\d+)*)", re.MULTILINE
)


def _render(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().split("."))


def _pinned_python_version() -> tuple[int, ...]:
    text = (REPO_ROOT / ".python-version").read_text().strip()
    return _parse(text)


def _pep723_python_floors() -> list[tuple[Path, tuple[int, ...]]]:
    """Every tracked PEP 723 block's ``requires-python`` lower bound."""
    floors: list[tuple[Path, tuple[int, ...]]] = []
    for path in _tracked(".py"):
        block = _PEP723_BLOCK.search(path.read_text())
        if block is None:
            continue
        found = _REQUIRES_PYTHON.search(block.group(1))
        if found is None:
            continue
        floors.append((path, _parse(found.group(1))))
    return floors


def _pinned_hacc_version() -> str:
    cfg = tomllib.loads(PYPROJECT.read_text())
    deps = cfg["tool"]["repo-shared"]["code-quality"]["mypy-extra-deps"]
    # tomllib hands back ``Any``; narrow before use so the return
    # type is real rather than inferred from an untyped blob.
    assert isinstance(deps, list)
    for dep in deps:
        assert isinstance(dep, str)
        if dep.startswith(f"{HACC}=="):
            return dep.split("==", 1)[1]
    raise AssertionError(
        f"no pinned {HACC} found in "
        "[tool.repo-shared.code-quality] mypy-extra-deps"
    )


class TestPep723YamlStubs:
    def test_yaml_importers_declare_types_pyyaml(self) -> None:
        offenders: list[str] = []
        for path in _tracked(".py"):
            text = path.read_text()
            block = _PEP723_BLOCK.search(text)
            if block is None or not _YAML_IMPORT.search(text):
                continue
            if "types-PyYAML" not in block.group(1):
                offenders.append(str(path.relative_to(REPO_ROOT)))

        assert not offenders, (
            "PEP 723 file(s) import `yaml` without declaring "
            "`types-PyYAML`:\n  "
            + "\n  ".join(offenders)
            + "\n\nA PEP 723 block replaces the project-wide "
            "mypy-extra-deps fallback instead of merging with it, so "
            "these files' YAML code is not type-checked at all -- "
            "`yaml` resolves to `Any` and `mypy --strict` passes "
            "vacuously. Add `types-PyYAML` to each block's "
            "dependencies."
        )


class TestPinAgreement:
    def test_every_declaration_site_agrees(self) -> None:
        """A PEP 723 block that disagrees type-checks against a
        different Home Assistant version than the project claims,
        and the upgrade tool cannot repair it: that tool rewrites
        sites carrying the version being replaced, so one already
        drifted to some third version is invisible to it.
        """
        expected = _pinned_hacc_version()
        # Match version digits only. A greedy ``[\w.]+`` would
        # swallow the period ending a markdown sentence, reporting
        # a site the upgrade tool's boundary-anchored match treats
        # as fine -- a permanent red with no automated repair.
        pattern = re.compile(re.escape(f"{HACC}==") + r"(\d+(?:\.\d+)*)")
        offenders: list[str] = []
        for path in _tracked(".py", ".toml", ".md"):
            for lineno, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                found = pattern.search(line)
                if found is None or found.group(1) == expected:
                    continue
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: pins {found.group(1)}")

        assert not offenders, (
            f"declaration site(s) disagree with the pinned {expected}:"
            "\n  " + "\n  ".join(offenders) + "\n\nEvery site must "
            "name the same version; a stray one silently type-checks "
            "against a different Home Assistant release."
        )


class TestPinnedVersionNotInProse:
    def test_hacc_version_only_at_declaration_sites(self) -> None:
        version = _pinned_hacc_version()
        offenders: list[str] = []
        for path in _tracked(".md", ".toml"):
            for lineno, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                if version not in line or f"{HACC}==" in line:
                    continue
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            f"the pinned {HACC} version ({version}) appears outside a "
            "dependency declaration:\n  "
            + "\n  ".join(offenders)
            + "\n\nThe pin literal is the single source of truth for "
            "the version, and automation rewrites it at every "
            "declaration site. Prose naming the version is not "
            "rewritten, so it goes stale as soon as the pin moves. "
            "Refer to the pin instead of restating it."
        )


class TestInterpreterPin:
    def test_pin_satisfies_every_pep723_floor(self) -> None:
        """A pin below some script's floor is silently ignored.

        ``uv`` does not error when ``.python-version`` cannot
        satisfy a script's ``requires-python``; it falls back to
        the newest interpreter installed, which is the drift the
        pin exists to stop. The fallback exits zero, so nothing
        but this check would notice.
        """
        pinned = _pinned_python_version()
        offenders: list[str] = []
        for path, floor in _pep723_python_floors():
            if floor > pinned:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(
                    f"{rel}: requires-python floor "
                    f"{_render(floor)} > pinned {_render(pinned)}"
                )

        assert not offenders, (
            "`.python-version` does not satisfy every PEP 723 "
            "floor:\n  "
            + "\n  ".join(offenders)
            + "\n\n`uv` resolves such a script against the newest "
            "interpreter installed instead, and reports no error "
            "doing it. Raise `.python-version` to cover the "
            "highest floor, or lower the floor."
        )

    def test_pin_agrees_with_the_analysis_knobs(self) -> None:
        """mypy analyses what the suite actually runs on.

        ``mypy-python-version`` and ``[tool.mypy] python_version``
        select the syntax and stub surface mypy checks against. A
        pin that disagrees type-checks one interpreter's semantics
        while the tests exercise another's.
        """
        pinned = _render(_pinned_python_version())
        cfg = tomllib.loads(PYPROJECT.read_text())
        code_quality = cfg["tool"]["repo-shared"]["code-quality"]
        knobs = {
            "[tool.repo-shared.code-quality] mypy-python-version": (
                code_quality["mypy-python-version"]
            ),
            "[tool.mypy] python_version": cfg["tool"]["mypy"]["python_version"],
        }
        disagreeing = {
            name: value for name, value in knobs.items() if value != pinned
        }

        assert not disagreeing, (
            f"`.python-version` pins {pinned}, but:\n  "
            + "\n  ".join(
                f"{name} = {value!r}" for name, value in disagreeing.items()
            )
            + "\n\nmypy would analyse a different interpreter than "
            "the one the suite runs on. Move them together."
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
