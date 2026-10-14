#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
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

4. ``.python-version`` satisfies every declared ``requires-python``
   floor -- the PEP 723 blocks plus ``[project]`` -- and agrees with
   the two mypy knobs. The interpreter is pinned for the same reason
   the HACC version is -- it decides what the suite runs against --
   but its failure mode is quieter: ``uv`` ignores a pin it cannot
   satisfy and resolves against the newest interpreter installed,
   exiting zero, so a pin that drifts below a floor silently stops
   pinning anything.

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

7. ``[tool.ruff] target-version`` names
   ``[tool.ha-blueprint-toolkit] shipped-python-version``, and the
   code that runs at that floor parses there. The formatter emits at
   its target, so a target above the floor puts syntax into the
   bundled CLI and the integration modules that the interpreter
   actually running them cannot parse -- and because that
   interpreter belongs to the Terminal & SSH add-on rather than to
   this repo, nothing else in the suite would go red. Every declared
   floor is at or above the shipped floor for the same reason in
   reverse: a script claiming an older one is claiming support it
   cannot deliver the moment it imports a module formatted at the
   floor.
"""

from __future__ import annotations

import ast
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


# A plain ``python3`` shebang stands in for "cannot assume ``uv``",
# which is what every host-side helper needs and what makes it a
# usable marker for off-machine code. These two carry one while still
# running here on the pinned interpreter -- the manifest bumper before
# a commit, the docker driver against a local container -- so they are
# exempt. Any OTHER plain-``python3`` script is treated as
# off-machine, which errs the safe way: a new host-side helper is
# covered the moment it gets its shebang, while a new local one has to
# be exempted deliberately, here, in view of what the exemption costs.
_LOCAL_PLAIN_PYTHON3 = frozenset(
    {
        "scripts/bump-manifest-version.py",
        "tests/docker/test_dev_workflow.py",
    }
)
_PLAIN_PYTHON3_SHEBANG = "#!/usr/bin/env python3"


def _off_machine_sources() -> list[Path]:
    """Tracked sources run on an interpreter this repo cannot choose.

    Everything under ``custom_components/``, which Home Assistant
    imports and whose ``bundled/`` subtree the Terminal & SSH add-on
    runs, plus the host-side helpers outside it -- identified by the
    plain ``python3`` shebang they need because ``uv`` is absent where
    they run.
    """
    sources: list[Path] = []
    for path in _tracked(".py"):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] == "custom_components":
            sources.append(path)
            continue
        if str(rel) in _LOCAL_PLAIN_PYTHON3:
            continue
        if path.read_text().startswith(_PLAIN_PYTHON3_SHEBANG):
            sources.append(path)
    return sources


def _shipped_python_version() -> tuple[int, ...]:
    """The floor the code that runs off this machine is held to."""
    cfg = tomllib.loads(PYPROJECT.read_text())
    declared = cfg["tool"]["ha-blueprint-toolkit"]["shipped-python-version"]
    assert isinstance(declared, str)
    return _parse(declared)


def _declared_python_floors() -> list[tuple[str, tuple[int, ...]]]:
    """Every ``requires-python`` lower bound this repo declares.

    The PEP 723 blocks plus ``[project]``, which governs the venv the
    shared phase runs ``pytest`` in and is a declaration ``uv`` reads
    exactly as it reads a block's.
    """
    floors: list[tuple[str, tuple[int, ...]]] = []
    cfg = tomllib.loads(PYPROJECT.read_text())
    project_floor = cfg["project"]["requires-python"]
    assert isinstance(project_floor, str)
    floors.append(
        (
            "pyproject.toml [project] requires-python",
            _parse_bound(project_floor),
        )
    )
    for path in _tracked(".py"):
        block = _PEP723_BLOCK.search(path.read_text())
        if block is None:
            continue
        found = _REQUIRES_PYTHON.search(block.group(1))
        if found is None:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        floors.append((f"{rel} requires-python", _parse(found.group(1))))
    return floors


def _parse_bound(specifier: str) -> tuple[int, ...]:
    """The lower bound of a ``requires-python`` specifier."""
    found = re.search(r"[^0-9]*(\d+(?:\.\d+)*)", specifier)
    assert found is not None, f"no version in requires-python {specifier!r}"
    return _parse(found.group(1))


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
    def test_pin_satisfies_every_declared_floor(self) -> None:
        """A pin below some floor is silently ignored.

        ``uv`` does not error when ``.python-version`` cannot
        satisfy a ``requires-python``; it falls back to the newest
        interpreter installed, which is the drift the pin exists to
        stop. The fallback exits zero, so nothing but this check
        would notice.
        """
        pinned = _pinned_python_version()
        offenders = [
            f"{name} {_render(floor)} > pinned {_render(pinned)}"
            for name, floor in _declared_python_floors()
            if floor > pinned
        ]

        assert not offenders, (
            "`.python-version` does not satisfy every declared "
            "floor:\n  "
            + "\n  ".join(offenders)
            + "\n\n`uv` resolves against the newest interpreter "
            "installed instead, and reports no error doing it. "
            "Raise `.python-version` to cover the highest floor, "
            "or lower the floor."
        )

    def test_pin_agrees_with_the_mypy_knobs(self) -> None:
        """Both mypy knobs name the interpreter the suite runs on.

        ``mypy-python-version`` and ``[tool.mypy] python_version``
        select the syntax and stub surface mypy checks against. A
        pin that disagrees type-checks one interpreter's semantics
        while the tests exercise another's.

        The formatter's target is deliberately NOT here: it decides
        what gets written into the sources rather than what reads
        them, so it follows the shipped floor instead. See
        ``TestShippedInterpreterFloor``.
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


class TestShippedInterpreterFloor:
    def test_the_floor_checks_cover_something(self) -> None:
        """Both floor checks pass trivially over an empty set.

        Each one asserts that no member offends, so a discovery that
        silently stopped finding members -- a moved tree, a reworded
        shebang, a renamed table -- reports success having checked
        nothing. Naming one member that must always be found turns
        that into a failure. The bundled CLI and the websocket helper
        are the anchors because they are the two the add-on's
        interpreter runs, which is the floor's whole reason to exist.
        """
        off_machine = {
            str(p.relative_to(REPO_ROOT)) for p in _off_machine_sources()
        }
        for anchor in (
            "custom_components/blueprint_toolkit/bundled/bin/zwavectl.py",
            "scripts/ha_ws_fetch.py",
        ):
            assert anchor in off_machine, (
                f"{anchor} is no longer discovered as off-machine code, so "
                "the parse check no longer covers it. Fix the discovery in "
                "`_off_machine_sources`, or move the anchor if the file was "
                "deliberately renamed."
            )

        floors = dict(_declared_python_floors())
        assert "pyproject.toml [project] requires-python" in floors, (
            "the `[project]` floor is no longer discovered, so the "
            "cover-the-floor check no longer reads it. Fix "
            "`_declared_python_floors`."
        )
        assert len(floors) > 1, (
            "no PEP 723 `requires-python` floor was discovered, so the "
            "cover-the-floor check only reads `[project]`. Fix the block "
            "match in `_declared_python_floors`."
        )

    def test_formatter_target_matches_the_shipped_floor(self) -> None:
        """The formatter must not emit above the floor it ships to.

        ``ruff format`` rewrites to its ``target-version``: at py314
        a parenthesized multi-type ``except`` becomes the PEP 758
        unparenthesized form, which is a ``SyntaxError`` on 3.13. A
        target above ``shipped-python-version`` therefore puts syntax
        into the bundled CLI and the integration modules that the
        interpreter running them cannot parse, and that interpreter
        is the add-on's -- nothing else in this suite would notice.
        One below it silently withholds the upgrades the floor allows.
        """
        shipped = _render(_shipped_python_version())
        cfg = tomllib.loads(PYPROJECT.read_text())
        target = cfg["tool"]["ruff"]["target-version"]
        assert isinstance(target, str)
        rendered = (
            f"{target[2]}.{target[3:]}" if target.startswith("py") else target
        )

        assert rendered == shipped, (
            f"`[tool.ruff] target-version` is {target!r} ({rendered}) "
            f"but the shipped floor is {shipped}.\n\n"
            "`ruff format` emits at its target, so this decides which "
            "syntax lands in code Home Assistant and the Terminal & SSH "
            "add-on run. Move it with "
            "`[tool.ha-blueprint-toolkit] shipped-python-version`, "
            "never with `.python-version`."
        )

    def test_declared_floors_cover_the_shipped_floor(self) -> None:
        """A floor below the shipped one claims unreachable support.

        Every script here can import the integration package, which
        is formatted at the shipped floor, so a block declaring an
        older interpreter is declaring support that the first such
        import removes. The failure surfaces as a parse error inside
        the package rather than at the block that invited it.
        """
        shipped = _shipped_python_version()
        offenders = [
            f"{name} {_render(floor)} < shipped {_render(shipped)}"
            for name, floor in _declared_python_floors()
            if floor < shipped
        ]

        assert not offenders, (
            "declared floor(s) sit below the shipped floor:\n  "
            + "\n  ".join(offenders)
            + "\n\nCode here is formatted for the shipped floor, so a "
            "lower declaration is not support -- it fails on the first "
            "import of a module written at the floor. Raise the "
            "declaration to cover the floor. The floor itself names the "
            "lowest interpreter this code is run on, so it tracks those "
            "platforms rather than what a declaration here would prefer."
        )

    def test_off_machine_code_parses_at_the_shipped_floor(self) -> None:
        """The floor is exercised, not merely declared.

        Matching the formatter's target to the floor governs what the
        formatter writes; it does not stop a hand-written construct
        from needing something newer, and the interpreters this code
        runs on belong to Home Assistant and to the Terminal & SSH
        add-on, so neither would turn the suite red. Parsing the
        sources at the declared floor is what closes that gap.

        ``feature_version`` restricts the grammar, so this catches a
        construct the floor cannot parse -- which is what the
        formatter emits -- and nothing else. A construct whose
        *semantics* need a newer interpreter parses clean and is not
        caught: a newer stdlib call, or an annotation that resolves
        only under deferred evaluation. Those are sound here only
        because the floor names the interpreters this code actually
        runs on, so no supported platform sits below it; they would
        bite a floor that understated reality, which is why the floor
        is declared from those platforms rather than discovered here.
        """
        shipped = _shipped_python_version()
        offenders: list[str] = []
        for path in _off_machine_sources():
            rel = path.relative_to(REPO_ROOT)
            try:
                ast.parse(
                    path.read_text(),
                    filename=str(rel),
                    feature_version=shipped[:2],  # type: ignore[arg-type]
                )
            except SyntaxError as exc:
                offenders.append(f"{rel}:{exc.lineno}: {exc.msg}")

        assert not offenders, (
            f"source(s) do not parse on Python {_render(shipped)}:\n  "
            + "\n  ".join(offenders)
            + "\n\nThis code runs on Home Assistant's interpreter or the "
            "Terminal & SSH add-on's, not on this machine's, and "
            "`[tool.ha-blueprint-toolkit] shipped-python-version` is "
            "the floor it claims. Rewrite the construct, or raise that "
            "floor (a compatibility decision; see the comment on that "
            "key)."
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
