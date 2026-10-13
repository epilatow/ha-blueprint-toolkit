#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "pytest-cov",
# ]
# ///
# This is AI generated code
"""Tests for scripts/hacc_upgrade.py.

Covers what gets rewritten, whether the run proceeds at all, and
what it reports: pin parsing, the anchored rewrite, site
discovery, the guards, and the landing path itself. The landing
tests drive real git against a throwaway upstream / clone pair in
``tmp_path`` and stub ``run_suite``, so they exercise publish and
fast-forward without a multi-minute suite run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Self

import pytest

REPO_ROOT = Path(__file__).parent.parent

# hacc_upgrade is a bare script, imported off a runtime sys.path entry
# the way the other script tests reach render_docs / zwave_network_info.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import hacc_upgrade  # noqa: E402

# Every pin below is built from this rather than written out.
# A literal declaration line in this file would be a real
# declaration site to tests/test_analysis_deps.py, which scans .py
# and requires every site to name the version pyproject.toml pins.
PACKAGE = hacc_upgrade.PACKAGE


def _pyproject(*deps: str) -> str:
    body = "".join(f'    "{d}",\n' for d in deps)
    return f"[tool.repo-shared.code-quality]\nmypy-extra-deps = [\n{body}]\n"


MANIFEST_REL = "custom_components/blueprint_toolkit/manifest.json"
SHIPPED_PIN_REL = "custom_components/blueprint_toolkit/bundled/bin/cli.py"


def _add_shipped_pin_site(root: Path, companion_pin: str) -> None:
    """Give ``root`` a pin site that ships, plus the manifest machinery.

    Mirrors the real repo's shape: the bundled CLI declares the Z-Wave
    client in its runtime venv list, so a bump that moves that pin
    edits shipped code and owes the manifest an increment. The real
    bump script is copied in rather than faked, so the test exercises
    the integration and not a stand-in.
    """
    manifest = root / MANIFEST_REL
    manifest.parent.mkdir(parents=True, exist_ok=True)
    body = {"domain": "blueprint_toolkit", "version": "0.0.1"}
    manifest.write_text(json.dumps(body, indent=2) + "\n")
    shipped = root / SHIPPED_PIN_REL
    shipped.parent.mkdir(parents=True, exist_ok=True)
    shipped.write_text(
        f'VENV_DEPS = [\n    "{hacc_upgrade.COMPANION}=={companion_pin}",\n]\n'
    )
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "scripts" / "bump-manifest-version.py",
        scripts / "bump-manifest-version.py",
    )
    subprocess.run(
        ["git", "add", "custom_components", "scripts"], cwd=root, check=True
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "shipped"], cwd=root, check=True
    )


def _init_repo(root: Path, pin: str) -> None:
    """Create a one-commit git repo pinning ``pin``."""
    subprocess.run(["git", "init", "-b", "main", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "pyproject.toml").write_text(
        _pyproject(f"{PACKAGE}=={pin}", "types-PyYAML")
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


def _clone_pair(
    tmp_path: Path, pin: str, *, shipped_companion: str | None = None
) -> tuple[Path, Path]:
    """Return (bare upstream, clone) both pinning ``pin``.

    The upstream is bare so a push to its checked-out branch is not
    refused, and cloning sets ``origin/HEAD`` the way a real
    checkout has it.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    _init_repo(seed, pin)
    if shipped_companion is not None:
        _add_shipped_pin_site(seed, shipped_companion)
    upstream = tmp_path / "up.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(seed), str(upstream)],
        check=True,
    )
    clone = tmp_path / "work"
    subprocess.run(
        ["git", "clone", "-q", str(upstream), str(clone)], check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=clone, check=True
    )
    return upstream, clone


class TestPinnedVersion:
    def test_returns_the_pinned_version(self) -> None:
        text = _pyproject(f"{PACKAGE}==1.2.3", "types-PyYAML")
        assert hacc_upgrade.pinned_version(text) == "1.2.3"

    def test_unpinned_entry_is_not_a_pin(self) -> None:
        """A bare entry carries no version to bump."""
        text = _pyproject(PACKAGE, "types-PyYAML")
        with pytest.raises(ValueError, match="no pinned"):
            hacc_upgrade.pinned_version(text)

    def test_missing_dep_raises(self) -> None:
        text = _pyproject("types-PyYAML")
        with pytest.raises(ValueError, match="no pinned"):
            hacc_upgrade.pinned_version(text)

    def test_non_list_raises(self) -> None:
        text = (
            '[tool.repo-shared.code-quality]\nmypy-extra-deps = "not-a-list"\n'
        )
        with pytest.raises(TypeError):
            hacc_upgrade.pinned_version(text)


class TestRewritePins:
    def test_replaces_the_anchored_pin(self) -> None:
        text = f'#     "{PACKAGE}==1.2.3",\n'
        out = hacc_upgrade.rewrite_pins(text, "1.2.3", "4.5.6")
        assert out == f'#     "{PACKAGE}==4.5.6",\n'

    def test_a_longer_version_sharing_the_prefix_is_not_a_match(
        self,
    ) -> None:
        """Rewriting 1.2.3 must not maul 1.2.31 into 4.5.61."""
        text = f"{PACKAGE}==1.2.31"
        assert hacc_upgrade.rewrite_pins(text, "1.2.3", "4.5.6") == text

    def test_leaves_other_packages_on_the_same_version(self) -> None:
        """The version string alone is not enough to match on.

        An unrelated dependency pinned to the same version must
        survive untouched, which is why the rewrite is anchored on
        the package name.
        """
        text = f"{PACKAGE}==1.2.3\nsomething-else==1.2.3\n"
        out = hacc_upgrade.rewrite_pins(text, "1.2.3", "4.5.6")
        assert f"{PACKAGE}==4.5.6" in out
        assert "something-else==1.2.3" in out

    def test_rewrites_a_declaration_ending_a_sentence(self) -> None:
        """Markdown is in scope, so a trailing period must not block.

        The boundary excludes only a continuation into a longer
        version; too strict a one would leave a legitimate
        markdown declaration permanently unrewritable, and the
        agreement test would then flag it forever.
        """
        text = f"Pinned to {PACKAGE}==1.2.3."
        out = hacc_upgrade.rewrite_pins(text, "1.2.3", "4.5.6")
        assert out == f"Pinned to {PACKAGE}==4.5.6."

    def test_absent_pin_is_a_no_op(self) -> None:
        text = "nothing to see here\n"
        assert hacc_upgrade.rewrite_pins(text, "1.2.3", "4.5.6") == text


class TestPinSites:
    def test_finds_the_real_declaration_sites(self) -> None:
        current = hacc_upgrade.pinned_version(
            (REPO_ROOT / "pyproject.toml").read_text()
        )
        sites = hacc_upgrade.pin_sites(REPO_ROOT, current)

        assert REPO_ROOT / "pyproject.toml" in sites
        assert len(sites) > 1, (
            "every HACC-coupled test file repeats the pin in its own "
            "PEP 723 block; finding only one site means discovery is "
            "broken and a bump would leave blocks disagreeing"
        )
        assert all(p.suffix in hacc_upgrade.PIN_SUFFIXES for p in sites)

    def test_markdown_is_in_scope(self) -> None:
        """A declaration line in markdown must be rewritable.

        The prose ban permits a dependency line in a doc, so one
        left unrewritten would go stale the moment the pin moved.
        """
        assert ".md" in hacc_upgrade.PIN_SUFFIXES

    def test_unknown_version_matches_nothing(self) -> None:
        assert hacc_upgrade.pin_sites(REPO_ROOT, "0.0.0") == []


class TestGuards:
    def test_malformed_version_is_a_usage_error(self) -> None:
        args = hacc_upgrade.parse_args(["--to", "not-a-version"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.USAGE

    def test_matching_version_is_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)

        args = hacc_upgrade.parse_args(["--to", "1.2.3"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

    def test_dry_run_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)
        before = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=tmp_path, text=True
        )

        args = hacc_upgrade.parse_args(["--dry-run", "--to", "99.99.99"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        after = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=tmp_path, text=True
        )
        assert before == after

    def test_push_without_a_remote_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.USAGE

    def test_remote_without_default_branch_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unresolvable origin/HEAD must not fall back.

        Falling back to the current branch would make the
        wrong-branch guard compare a value against itself, so an
        unattended --push could land on a feature branch.
        """
        _init_repo(tmp_path, "1.2.3")
        subprocess.run(
            ["git", "remote", "add", "origin", str(tmp_path / "nowhere")],
            cwd=tmp_path,
            check=True,
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)

        args = hacc_upgrade.parse_args(["--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR

    def test_dirty_checkout_refuses_the_landing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The landing step fast-forwards this checkout."""
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        (clone / "scratch.txt").write_text("uncommitted\n")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.DIRTY

    def test_dirty_checkout_is_fine_without_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No landing step, so this checkout is never touched."""
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        (clone / "scratch.txt").write_text("uncommitted\n")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)

        args = hacc_upgrade.parse_args(["--dry-run", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

    def test_wrong_branch_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bump lands on the branch it was built against.

        Parked on a feature branch, the run must refuse rather than
        base the bump on that branch and push the result there.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature"], cwd=clone, check=True
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.DIRTY


class TestLatestVersion:
    def test_unexpected_version_shape_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shape is load-bearing, not cosmetic.

        The version becomes a branch name and a path component,
        and the downgrade guard compares it numerically.
        """

        class _Response:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"info": {"version": "1.2.3.post1"}}'

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *_a, **_k: _Response(),
        )
        with pytest.raises(ValueError, match="unexpected version"):
            hacc_upgrade.latest_version()

    def test_non_string_version_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PyPI's payload is external input, not a trusted shape."""

        class _Response:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"info": {"version": 13}}'

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *_a, **_k: _Response(),
        )
        with pytest.raises(TypeError):
            hacc_upgrade.latest_version()


class TestCompanionPin:
    """The Z-Wave client pin is derived, so the bump moves it too."""

    def _repo_with_companion(self, tmp_path: Path) -> tuple[Path, Path]:
        upstream, clone = _clone_pair(tmp_path, "1.2.3")
        (clone / "pyproject.toml").write_text(
            _pyproject(
                f"{PACKAGE}==1.2.3",
                f"{hacc_upgrade.COMPANION}==0.70.0",
                "types-PyYAML",
            )
        )
        subprocess.run(
            ["git", "commit", "-aqm", "declare the companion"],
            cwd=clone,
            check=True,
        )
        subprocess.run(["git", "push", "-q"], cwd=clone, check=True)
        return upstream, clone

    def test_bump_moves_the_companion_to_the_required_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A coupled pin left behind breaks the Z-Wave phases."""
        _upstream, clone = self._repo_with_companion(tmp_path)
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.1",
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        landed = (clone / "pyproject.toml").read_text()
        assert f"{PACKAGE}==4.5.6" in landed
        assert f"{hacc_upgrade.COMPANION}==0.73.1" in landed
        assert "0.70.0" not in landed
        message = subprocess.check_output(
            ["git", "log", "-1", "--format=%B"], cwd=clone, text=True
        )
        assert "Z-Wave client pin moves with it" in message

    def test_message_claims_the_coupled_move_only_when_it_happened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pin can be declared and already right for the target.

        The landed message is permanent, so it must not describe a
        rewrite that did not occur.
        """
        _upstream, clone = self._repo_with_companion(tmp_path)
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.70.0",
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        message = subprocess.check_output(
            ["git", "log", "-1", "--format=%B"], cwd=clone, text=True
        )
        assert f"Bump {PACKAGE} to 4.5.6" in message
        assert "Z-Wave" not in message

    def test_undeclared_companion_is_never_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolving it costs a dependency download, so skip it.

        A repo that does not declare the client library has nothing to
        move, and the resolution would fail there anyway.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)

        def _explode(_root: Path, _version: str) -> str:
            raise AssertionError("resolved a pin the repo never declared")

        monkeypatch.setattr(hacc_upgrade, "companion_requirement", _explode)

        args = hacc_upgrade.parse_args(["--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

    def test_disagreeing_companion_sites_stop_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Which of the two to replace would be a guess."""
        _upstream, clone = self._repo_with_companion(tmp_path)
        (clone / "extra.toml").write_text(
            f'dep = "{hacc_upgrade.COMPANION}==0.71.0"\n'
        )
        subprocess.run(["git", "add", "extra.toml"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-qm", "drift"], cwd=clone, check=True)
        subprocess.run(["git", "push", "-q"], cwd=clone, check=True)
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.1",
        )

        args = hacc_upgrade.parse_args(["--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR


class TestDeclaredVersions:
    def test_collects_every_pinned_version(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, "1.2.3")
        (tmp_path / "other.md").write_text(
            f"- `{hacc_upgrade.COMPANION}==0.70.0`\n"
        )
        subprocess.run(["git", "add", "other.md"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "doc"], cwd=tmp_path, check=True
        )

        assert hacc_upgrade.declared_versions(tmp_path, PACKAGE) == {"1.2.3"}
        assert hacc_upgrade.declared_versions(
            tmp_path, hacc_upgrade.COMPANION
        ) == {"0.70.0"}
        assert hacc_upgrade.declared_versions(tmp_path, "absent-pkg") == set()

    def test_sites_carry_the_file_each_version_came_from(
        self, tmp_path: Path
    ) -> None:
        """The failure message names files, so the walk must keep them."""
        _init_repo(tmp_path, "1.2.3")

        sites = hacc_upgrade.declared_sites(tmp_path, PACKAGE)

        assert [
            (path.relative_to(tmp_path).as_posix(), version)
            for path, version in sites
        ] == [("pyproject.toml", "1.2.3")]


class TestCompanionRequirement:
    """The one new boundary that talks to the outside world.

    Its result drives an unattended rewrite, so both failure paths
    and the parse itself are exercised against a stubbed ``uv``
    rather than only through callers that monkeypatch it away.
    """

    @staticmethod
    def _stub(
        monkeypatch: pytest.MonkeyPatch,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        def _run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=["uv"],
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

        monkeypatch.setattr(subprocess, "run", _run)

    def test_reads_the_exact_requirement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(
            monkeypatch,
            stdout=f"pyserial==3.5\n{hacc_upgrade.COMPANION}==0.73.1\n",
        )

        assert (
            hacc_upgrade.companion_requirement(tmp_path, "0.13.372") == "0.73.1"
        )

    def test_failed_resolution_raises_naming_the_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A download or resolve failure must not read as "no pin"."""
        self._stub(monkeypatch, returncode=1, stderr="no such version")

        with pytest.raises(ValueError, match="cannot read Home Assistant"):
            hacc_upgrade.companion_requirement(tmp_path, "9.9.9")

    def test_inexact_requirement_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A range gives nothing to pin, so the bump stops.

        Matching is anchored: a requirement that merely contains the
        package name is not an exact pin and must not be read as one.
        """
        self._stub(
            monkeypatch,
            stdout=f"{hacc_upgrade.COMPANION}>=0.73.0,<0.74\n",
        )

        with pytest.raises(ValueError, match="no exact"):
            hacc_upgrade.companion_requirement(tmp_path, "0.13.372")


class TestCompanionDriftReport:
    """What a dry run tells a human about the coupled pin.

    The rewrite itself is covered elsewhere. This is the report
    someone reads before authorizing an unattended bump, so every
    branch has to say something true -- including the branches that
    decline to resolve.
    """

    @staticmethod
    def _repo(tmp_path: Path, *versions: str) -> Path:
        """A clone declaring the companion at each given version."""
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        paths = []
        for index, version in enumerate(versions):
            rel = f"site{index}.md"
            (clone / rel).write_text(
                f"- `{hacc_upgrade.COMPANION}=={version}`\n"
            )
            paths.append(rel)
        if paths:
            subprocess.run(["git", "add", *paths], cwd=clone, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "sites"], cwd=clone, check=True
            )
        return clone

    def test_says_so_when_nothing_is_coupled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        clone = self._repo(tmp_path)

        hacc_upgrade.report_companion_drift(clone, "4.5.6", "origin/main")

        assert "nothing coupled to move" in capsys.readouterr().out

    def test_declines_to_resolve_when_sites_disagree(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A real run stops here, so the report must not imply a move.

        Resolution is also pointless before the disagreement is
        settled, and it costs a download, so it must not be attempted.
        """
        clone = self._repo(tmp_path, "0.70.0", "0.73.0")

        def _never(*_a: object, **_k: object) -> str:
            raise AssertionError("resolved despite disagreeing sites")

        monkeypatch.setattr(hacc_upgrade, "companion_requirement", _never)
        hacc_upgrade.report_companion_drift(clone, "4.5.6", "origin/main")

        out = capsys.readouterr().out
        assert "already disagrees" in out
        assert "0.70.0" in out
        assert "0.73.0" in out

    def test_reports_a_failed_resolution_without_failing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A reporting run must not die on a resolve problem."""
        clone = self._repo(tmp_path, "0.70.0")

        def _raise(*_a: object, **_k: object) -> str:
            raise ValueError("declares no exact requirement")

        monkeypatch.setattr(hacc_upgrade, "companion_requirement", _raise)
        hacc_upgrade.report_companion_drift(clone, "4.5.6", "origin/main")

        assert "cannot resolve" in capsys.readouterr().out

    def test_reports_an_already_correct_pin(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        clone = self._repo(tmp_path, "0.73.0")
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.0",
        )

        hacc_upgrade.report_companion_drift(clone, "4.5.6", "origin/main")

        assert "already matches" in capsys.readouterr().out

    def test_lists_the_sites_a_move_would_rewrite(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Names the files, and which tree it read them from.

        A dry run builds no worktree, so it reports the local
        checkout -- which can declare different sites than the branch
        point the real run would rewrite.
        """
        clone = self._repo(tmp_path, "0.70.0")
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.1",
        )

        hacc_upgrade.report_companion_drift(clone, "4.5.6", "origin/main")

        out = capsys.readouterr().out
        assert "would also move" in out
        assert "0.70.0 -> 0.73.1" in out
        assert "site0.md" in out
        assert "worktree built from origin/main" in out

    def test_dry_run_wires_the_report_in(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The report is only useful if --dry-run actually reaches it."""
        clone = self._repo(tmp_path, "0.70.0")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.1",
        )

        args = hacc_upgrade.parse_args(["--dry-run", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS
        assert "would also move" in capsys.readouterr().out


class TestCompanionResolutionFailure:
    def test_a_real_run_stops_and_keeps_the_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stop-rather-than-guess outcome on the write path.

        Guessing would rewrite a shipped runtime pin to a version the
        target release does not use, so the bump refuses. The suite
        must not run either -- it would attribute the failure to the
        pin under test.
        """
        _upstream, clone = _clone_pair(
            tmp_path, "1.2.3", shipped_companion="0.70.0"
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)

        def _raise(*_a: object, **_k: object) -> str:
            raise ValueError("declares no exact requirement")

        monkeypatch.setattr(hacc_upgrade, "companion_requirement", _raise)

        def _never(_wt: Path) -> int:
            raise AssertionError("ran the suite despite an unresolved pin")

        monkeypatch.setattr(hacc_upgrade, "run_suite", _never)

        args = hacc_upgrade.parse_args(["--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR


class TestShippedCodeChanged:
    """Whether the bump owes the manifest a version increment.

    One pin site is the bundled CLI's runtime dep list, which ships
    to users, and ``tests/test_manifest.py`` requires the version to
    move exactly when something under that tree does.
    """

    def test_true_when_a_staged_path_ships(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, "1.2.3")
        shipped = tmp_path / "custom_components" / "blueprint_toolkit"
        shipped.mkdir(parents=True)
        (shipped / "bundled.py").write_text("VENV_DEPS = []\n")
        subprocess.run(
            ["git", "add", "custom_components"], cwd=tmp_path, check=True
        )

        assert hacc_upgrade.shipped_code_changed(tmp_path) is True

    def test_false_for_analysis_only_changes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, "1.2.3")
        (tmp_path / "pyproject.toml").write_text(
            _pyproject(f"{PACKAGE}==1.2.4", "types-PyYAML")
        )
        subprocess.run(
            ["git", "add", "pyproject.toml"], cwd=tmp_path, check=True
        )

        assert hacc_upgrade.shipped_code_changed(tmp_path) is False


class TestPinSitesSymlinks:
    def test_symlinks_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rewriting through a link would edit its target.

        Several tracked docs are symlinks into vendored trees a
        drift test gates, and `git add` on the link stages nothing,
        so a rewrite there is silently partial.
        """
        _init_repo(tmp_path, "1.2.3")
        real = tmp_path / "real.md"
        real.write_text(f"{PACKAGE}==1.2.3\n")
        (tmp_path / "link.md").symlink_to(real)
        subprocess.run(
            ["git", "add", "real.md", "link.md"], cwd=tmp_path, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "links"], cwd=tmp_path, check=True
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)

        sites = hacc_upgrade.pin_sites(tmp_path, "1.2.3")
        names = {p.name for p in sites}
        assert "real.md" in names
        assert "link.md" not in names


class TestSweepStaleWorktrees:
    def test_removes_directories_and_ignores_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sweep force-deletes, so its scope must be exact.

        A stray file under the worktree root is not a worktree;
        trying to remove one would fail silently on every run of an
        unattended job.
        """
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)
        root = tmp_path / ".wt" / hacc_upgrade.WORKTREE_PREFIX
        root.mkdir(parents=True)
        (root / "9.9.9").mkdir()
        stray = root / "stray.txt"
        stray.write_text("not a worktree\n")

        hacc_upgrade.sweep_stale_worktrees()

        assert not (root / "9.9.9").exists()
        assert stray.exists()

    def test_absent_root_is_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)
        hacc_upgrade.sweep_stale_worktrees()


class TestDefaultBranch:
    def test_resolves_the_remote_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slashed default branch must survive resolution."""
        upstream = tmp_path / "up"
        upstream.mkdir()
        _init_repo(upstream, "1.2.3")
        subprocess.run(
            ["git", "checkout", "-q", "-b", "release/v2"],
            cwd=upstream,
            check=True,
        )
        clone = tmp_path / "work"
        subprocess.run(
            ["git", "clone", "-q", str(upstream), str(clone)], check=True
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)

        assert hacc_upgrade.default_branch() == "release/v2"

    def test_no_remote_falls_back_to_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", tmp_path)
        assert hacc_upgrade.default_branch() == "main"


class TestLanding:
    def test_push_publishes_then_fast_forwards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The remote must carry the bump, and local must follow."""
        upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        published = subprocess.check_output(
            ["git", "show", "main:pyproject.toml"],
            cwd=upstream,
            text=True,
        )
        assert f"{PACKAGE}==4.5.6" in published
        local = subprocess.check_output(
            ["git", "show", "main:pyproject.toml"], cwd=clone, text=True
        )
        assert f"{PACKAGE}==4.5.6" in local

    def test_red_suite_lands_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing suite must leave both sides on the old pin."""
        upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 1)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.TESTS_FAILED

        published = subprocess.check_output(
            ["git", "show", "main:pyproject.toml"],
            cwd=upstream,
            text=True,
        )
        assert f"{PACKAGE}==1.2.3" in published

    def test_infra_failure_is_reported_apart_from_a_failed_suite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A suite that could not start is not a suite that failed."""
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(
            hacc_upgrade,
            "run_suite",
            lambda _wt: hacc_upgrade.RUN_ALL_INFRA_ERROR,
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR

    def test_branch_ahead_of_origin_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unpushed local commits make the bump un-fast-forwardable.

        Landing anyway would leave the branch diverged from origin,
        where every later run fails --ff-only identically.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        (clone / "local.txt").write_text("unpushed\n")
        subprocess.run(["git", "add", "local.txt"], cwd=clone, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "local"], cwd=clone, check=True
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.DIRTY

    def test_rewriting_shipped_code_bumps_the_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise the bump's own commit fails the manifest rule.

        The bundled CLI's runtime list is a pin site under
        ``custom_components/``, so moving the coupled pin changes
        shipped code. ``tests/test_manifest.py`` then requires the
        integration version to increment in that same commit, and the
        bump has no human to do it.
        """
        upstream, clone = _clone_pair(
            tmp_path, "1.2.3", shipped_companion="0.70.0"
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.73.1",
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        shipped = subprocess.check_output(
            ["git", "show", f"main:{SHIPPED_PIN_REL}"],
            cwd=upstream,
            text=True,
        )
        assert f"{hacc_upgrade.COMPANION}==0.73.1" in shipped
        manifest = json.loads(
            subprocess.check_output(
                ["git", "show", f"main:{MANIFEST_REL}"],
                cwd=upstream,
                text=True,
            )
        )
        assert manifest["version"] == "0.0.2"

    def test_analysis_only_rewrite_leaves_the_manifest_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The manifest rule binds in both directions.

        A bump that touches no shipped file must not move the version,
        or it fails the same test from the other side.
        """
        upstream, clone = _clone_pair(
            tmp_path, "1.2.3", shipped_companion="0.70.0"
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)
        # The coupled pin is already what the target release wants, so
        # only analysis-only sites move.
        monkeypatch.setattr(
            hacc_upgrade,
            "companion_requirement",
            lambda _root, _version: "0.70.0",
        )

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS

        manifest = json.loads(
            subprocess.check_output(
                ["git", "show", f"main:{MANIFEST_REL}"],
                cwd=upstream,
                text=True,
            )
        )
        assert manifest["version"] == "0.0.1"

    def test_published_pin_beats_the_local_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drift is judged against origin, not the local checkout.

        A checkout carrying a newer pin than origin must not report
        "already current" while the published pin sits still.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        (clone / "pyproject.toml").write_text(
            _pyproject(f"{PACKAGE}==4.5.6", "types-PyYAML")
        )
        subprocess.run(["git", "add", "pyproject.toml"], cwd=clone, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "local bump"],
            cwd=clone,
            check=True,
        )
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)

        # Without --push the ahead-of-origin guard does not apply,
        # so this reaches the comparison itself.
        args = hacc_upgrade.parse_args(["--dry-run", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS


class TestPreexistingDrift:
    def test_site_drifted_elsewhere_is_named(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A site the rewrite cannot reach must be named as such.

        It carries neither the old nor the new version, so it
        survives untouched and fails the agreement test inside the
        worktree. Left to surface that way it is one more
        undifferentiated suite failure; named here, it points
        straight at the file to repair.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        drifted = clone / "drifted.toml"
        drifted.write_text(f'dep = "{PACKAGE}==9.9.9"\n')
        subprocess.run(["git", "add", "drifted.toml"], cwd=clone, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "drift"], cwd=clone, check=True
        )
        subprocess.run(["git", "push", "-q"], cwd=clone, check=True)
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)

        def _unreached(_wt: Path) -> int:
            raise AssertionError("suite must not run with a drifted site")

        monkeypatch.setattr(hacc_upgrade, "run_suite", _unreached)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR
        err = capsys.readouterr().err
        assert "drifted.toml pins 9.9.9" in err


class TestDowngradeGuard:
    def test_older_latest_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A yanked latest must not be landed unattended."""
        _upstream, clone = _clone_pair(tmp_path, "4.5.6")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "latest_version", lambda: "1.2.3")

        args = hacc_upgrade.parse_args(["--push"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR

    def test_explicit_to_still_allows_a_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard is about unattended runs, not deliberate ones."""
        upstream, clone = _clone_pair(tmp_path, "4.5.6")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 0)

        args = hacc_upgrade.parse_args(["--push", "--to", "1.2.3"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.SUCCESS
        published = subprocess.check_output(
            ["git", "show", "main:pyproject.toml"], cwd=upstream, text=True
        )
        assert f"{PACKAGE}==1.2.3" in published


class TestMainFunnel:
    def test_unexpected_exception_becomes_a_documented_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scheduler reads the status, so 1 must not escape.

        `--help` documents 0/2/3/4/5; a bare traceback would exit
        1, which means nothing in that contract.
        """

        def _boom(_args: object) -> int:
            raise OSError("disk gone")

        monkeypatch.setattr(hacc_upgrade, "run", _boom)
        assert hacc_upgrade.main(["--to", "1.2.3"]) == int(
            hacc_upgrade.Exit.ERROR
        )


class TestFailureMessage:
    """The only claim the tool itself makes about a failure.

    The suite's own output says more, but this line is what the
    tool asserts and what rides with the exit status the scheduler
    keys on. Nothing else pins its text, so a claim that is false
    on one branch reaches the reader unnoticed.
    """

    def _run_and_capture(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        suite_status: int,
    ) -> str:
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: suite_status)
        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        hacc_upgrade.run(args)
        return capsys.readouterr().err

    def test_failed_suite_does_not_attribute_a_cause(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        err = self._run_and_capture(tmp_path, monkeypatch, capsys, 1)
        assert "the suite failed while verifying 4.5.6" in err
        assert "not decidable" in err
        assert "broke an interface" not in err

    def test_infra_failure_claims_nothing_about_phases(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Nothing ran, so nothing about the run can be inferred.

        run_all.py's infra status fires before the first phase, so
        any guidance about which phase failed would be guaranteed
        false on this branch.
        """
        err = self._run_and_capture(
            tmp_path, monkeypatch, capsys, hacc_upgrade.RUN_ALL_INFRA_ERROR
        )
        assert "could not complete" in err
        assert "not decidable" not in err
        # No phase ran, so nothing may point the reader at one.
        sentence = err.split("Worktree")[0]
        assert "phase" not in sentence

    def test_unrunnable_suite_is_not_a_test_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """127 means the runner never started, not that tests failed.

        A scheduler without ``uv`` on PATH produces exactly this,
        and reporting it as a suite failure would point at the new
        pin for something that never exercised it.
        """
        _upstream, clone = _clone_pair(tmp_path, "1.2.3")
        monkeypatch.setattr(hacc_upgrade, "REPO_ROOT", clone)
        monkeypatch.setattr(hacc_upgrade, "run_suite", lambda _wt: 127)

        args = hacc_upgrade.parse_args(["--push", "--to", "4.5.6"])
        assert hacc_upgrade.run(args) == hacc_upgrade.Exit.ERROR
        err = capsys.readouterr().err
        assert "could not complete" in err
        assert "not decidable" not in err

    def test_both_branches_name_the_kept_worktree(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        for status in (1, hacc_upgrade.RUN_ALL_INFRA_ERROR):
            root = tmp_path / str(status)
            root.mkdir()
            err = self._run_and_capture(root, monkeypatch, capsys, status)
            assert "kept for inspection" in err
            # The branches supply their own text and the suffix
            # supplies the punctuation joining them; a branch that
            # also terminates itself doubles the period.
            assert ". Worktree " in err
            assert ".. Worktree" not in err


class TestHelpEpilog:
    def test_epilog_attributes_no_cause_to_exit_five(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The epilog carried the claim this tool no longer makes.

        It is the other place the exit statuses are described, so
        an attribution deleted from the failure message can quietly
        reappear here.
        """
        with pytest.raises(SystemExit):
            hacc_upgrade.parse_args(["--help"])
        out = capsys.readouterr().out

        assert "5" in out
        assert "does not by itself implicate the new pin" in out
        assert "evidence about" not in out
        assert "broke an interface" not in out

    def test_epilog_lists_every_exit_status(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The scheduler keys on these, so none may go undocumented."""
        with pytest.raises(SystemExit):
            hacc_upgrade.parse_args(["--help"])
        out = capsys.readouterr().out

        for code in hacc_upgrade.Exit:
            assert f"  {int(code)}  " in out


class TestExitCodes:
    def test_success_is_zero(self) -> None:
        """The scheduler reads the exit status, so 0 must mean 0."""
        assert int(hacc_upgrade.Exit.SUCCESS) == 0

    def test_failure_codes_are_distinct(self) -> None:
        codes = [int(c) for c in hacc_upgrade.Exit]
        assert len(codes) == len(set(codes))
        assert all(c != 0 for c in codes if c != hacc_upgrade.Exit.SUCCESS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
