#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "pytest-cov",
# ]
# ///
# This is AI generated code
"""Analysis-dependency invariants, gating two written conventions.

Both rules come from ``DEVELOPMENT.md`` "Analysis-dep pinning and
stub suppressions", and both exist because the convention was
violated in practice before it was gated.

1. Every file carrying a PEP 723 ``# /// script`` block that
   imports ``yaml`` declares ``types-PyYAML``. A PEP 723 block
   *replaces* ``[tool.repo-shared.code-quality] mypy-extra-deps``
   rather than merging with it, so a file that declares its own
   deps and forgets the stubs silently loses them. The failure is
   invisible: ``[[tool.mypy.overrides]]`` sets
   ``ignore_missing_imports`` for ``yaml``, so the module resolves
   to ``Any`` and ``mypy --strict`` checks none of the file's YAML
   code instead of erroring.

2. The pinned ``pytest-homeassistant-custom-component`` version
   appears only where the dependency is declared, never in prose.
   Automation rewrites the pin literal at every declaration site;
   prose restating it is not rewritten and goes stale silently.
   Enforcing this against the *current* pin is what makes it
   stick: a prose mention gets written with whatever version is
   pinned that day, so it fails here at the moment it is
   introduced, and a stale one never reaches a commit.
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
