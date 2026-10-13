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
stub suppressions". Several were violated in practice before
anything enforced them; the rest hold today but share a failure
mode that makes them worth gating anyway -- each breaks quietly,
either passing a check vacuously or surfacing far from its cause,
and some cannot be repaired by the automation that owns the pins
once broken.

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

5. Every site pinning ``zwave-js-server-python`` names the same
   version. That pin's value is dictated by the Home Assistant
   release the HACC pin selects -- HA's ``zwave_js`` component
   requires one exact client and imports from it -- so a site left
   behind runs against a client that release does not use, and says
   so as a missing name in ``zwave_js`` rather than as a pin
   problem. ``scripts/hacc_upgrade.py`` moves these together; this
   gates the result, for a pin that moved by some other route.
   Agreement is all it checks: whether the agreed version is the
   right one is settled by the Z-Wave phases, which import the
   component for real.

6. No file under ``custom_components/`` carries a PEP 723 block.
   Home Assistant imports those modules and runs them on its own
   interpreter against the packages it installed, so a block there
   declares an environment the shipped code never resolves -- and,
   because a block replaces the fallback rather than extending it,
   it also has to restate the pins the fallback already carries,
   giving the repo more sites to keep in agreement for no analysis
   benefit. The bundled CLI's runtime ``VENV_DEPS`` list is not a
   PEP 723 block and is unaffected.
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
ZWAVE_CLIENT = "zwave-js-server-python"

# Body of a PEP 723 inline-metadata block, per the spec's opening
# and closing sentinel lines.
_PEP723_BLOCK = re.compile(
    r"^# /// script$(.*?)^# ///$", re.MULTILINE | re.DOTALL
)
_YAML_IMPORT = re.compile(r"^\s*(?:import yaml\b|from yaml\b)", re.MULTILINE)


def _tracked(*suffixes: str) -> list[Path]:
    """Tracked files with these suffixes, symlinks excluded.

    Skipping links matches what ``scripts/hacc_upgrade.py`` rewrites:
    it refuses to edit through a tracked symlink, because the target
    is vendored content a drift test owns and ``git add`` on the link
    stages nothing. A gate that read through them could flag a pin the
    tool structurally cannot repair -- a permanent red with no
    automated fix. Vendored content is covered by its own drift test.
    """
    out = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [
        path
        for rel in out.split("\0")
        if rel and rel.endswith(suffixes)
        if not (path := REPO_ROOT / rel).is_symlink()
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


def _declared_version(package: str) -> str | None:
    """The version the shared fallback pins ``package`` to, if any."""
    cfg = tomllib.loads(PYPROJECT.read_text())
    deps = cfg["tool"]["repo-shared"]["code-quality"]["mypy-extra-deps"]
    # tomllib hands back ``Any``; narrow before use so the return
    # type is real rather than inferred from an untyped blob.
    assert isinstance(deps, list)
    for dep in deps:
        assert isinstance(dep, str)
        if dep.startswith(f"{package}=="):
            return dep.split("==", 1)[1]
    return None


def _pinned_version(package: str) -> str:
    """As above, for a pin whose absence is itself a failure."""
    version = _declared_version(package)
    if version is None:
        raise AssertionError(
            f"no pinned {package} found in "
            "[tool.repo-shared.code-quality] mypy-extra-deps"
        )
    return version


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
        expected = _pinned_version(HACC)
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
    @pytest.mark.parametrize("package", [HACC, ZWAVE_CLIENT])
    def test_version_only_at_declaration_sites(self, package: str) -> None:
        """Both pins are automation-moved, so both have this hazard.

        ``scripts/hacc_upgrade.py`` rewrites every declaration site
        for both packages in one commit. Prose naming either version
        is not a declaration site, so the rewrite leaves it behind.

        Skips a package the fallback does not declare, matching the
        tool, which resolves nothing where there is no such pin. Only
        the Z-Wave client is optional in practice, but hard-coding
        which one would make this disagree with the tool the moment
        that changes.
        """
        version = _declared_version(package)
        if version is None:
            pytest.skip(f"{package} is not declared in mypy-extra-deps")
        offenders: list[str] = []
        for path in _tracked(".md", ".toml"):
            for lineno, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                if version not in line or f"{package}==" in line:
                    continue
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            f"the pinned {package} version ({version}) appears outside "
            "a dependency declaration:\n  "
            + "\n  ".join(offenders)
            + "\n\nThe pin literal is the single source of truth for "
            "the version, and automation rewrites it at every "
            "declaration site. Prose naming the version is not "
            "rewritten, so it goes stale as soon as the pin moves. "
            "Refer to the pin instead of restating it."
        )


class TestCompanionPinAgreement:
    def test_zwave_client_names_one_version(self) -> None:
        """Disagreeing sites break Home Assistant's own imports.

        ``scripts/hacc_upgrade.py`` derives this pin from the Home
        Assistant release the HACC pin selects and rewrites every site
        in the same commit. This gates the result: a site left behind
        type-checks and runs against a client the pinned Home Assistant
        does not use, and the failure surfaces as a missing name in
        ``zwave_js``, naming the library rather than the pin.

        It gates agreement only, not correctness against Home
        Assistant. Checking the latter here would mean resolving the
        pinned release on every run; the suite's Z-Wave phases import
        ``zwave_js`` for real and fail if the agreed version is the
        wrong one, so a uniformly stale pin is caught there.
        """
        pattern = re.compile(
            re.escape(f"{ZWAVE_CLIENT}==") + r"(\d+(?:\.\d+)*)"
        )
        sites: dict[str, list[str]] = {}
        for path in _tracked(".py", ".toml", ".md"):
            for found in pattern.finditer(path.read_text()):
                rel = str(path.relative_to(REPO_ROOT))
                sites.setdefault(found.group(1), []).append(rel)

        assert len(sites) <= 1, (
            f"{ZWAVE_CLIENT} is pinned to several versions:\n  "
            + "\n  ".join(
                f"{version}: {', '.join(sorted(paths))}"
                for version, paths in sorted(sites.items())
            )
            + "\n\nEvery site must name the version Home Assistant's "
            "`zwave_js` component requires at the pinned HACC release. "
            "`scripts/hacc_upgrade.py` moves them together; a site it "
            "missed is one it could not match."
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


class TestShippedCodeTakesTheFallback:
    def test_no_pep723_block_under_custom_components(self) -> None:
        """A block there declares an environment nothing resolves.

        Home Assistant imports these modules and runs them against
        the packages it installed, so the block's dependency set is
        never consulted at runtime. It is consulted by ``mypy``,
        which is the trap: because a block replaces the fallback
        instead of extending it, adding one silently drops every
        dep the fallback carried and obliges the file to restate
        the pins, adding sites that then have to be kept in
        agreement by hand.
        """
        offenders: list[str] = []
        for path in _tracked(".py"):
            rel = path.relative_to(REPO_ROOT)
            if rel.parts[0] != "custom_components":
                continue
            if _PEP723_BLOCK.search(path.read_text()):
                offenders.append(str(rel))

        assert not offenders, (
            "file(s) under `custom_components/` carry a PEP 723 "
            "block:\n  "
            + "\n  ".join(offenders)
            + "\n\nShipped integration code takes "
            "`[tool.repo-shared.code-quality] mypy-extra-deps` "
            "instead -- a block replaces that fallback rather than "
            "extending it, so it drops the deps the fallback "
            "carries and has to restate its pins. Move whatever "
            "the file needs into the fallback and delete the block."
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
