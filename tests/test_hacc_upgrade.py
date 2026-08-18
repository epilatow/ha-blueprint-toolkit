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

Covers the parts that decide what gets rewritten and whether the
run proceeds at all -- pin parsing, the anchored rewrite, site
discovery, and the guards that must refuse before touching a
worktree. The landing path (worktree, suite, fast-forward, push)
is deliberately not exercised here: it mutates real git state, and
the pieces it composes are covered above.
"""

from __future__ import annotations

import subprocess
import sys
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


def _clone_pair(tmp_path: Path, pin: str) -> tuple[Path, Path]:
    """Return (bare upstream, clone) both pinning ``pin``.

    The upstream is bare so a push to its checked-out branch is not
    refused, and cloning sets ``origin/HEAD`` the way a real
    checkout has it.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    _init_repo(seed, pin)
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
            hacc_upgrade.urllib.request,
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
            hacc_upgrade.urllib.request,
            "urlopen",
            lambda *_a, **_k: _Response(),
        )
        with pytest.raises(TypeError):
            hacc_upgrade.latest_version()


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

    def test_infra_failure_is_not_a_pin_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a real test failure is evidence about the new pin."""
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
    def test_site_drifted_elsewhere_is_not_a_pin_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A site the rewrite cannot reach must be named as such.

        It carries neither the old nor the new version, so it
        survives untouched and fails the agreement test inside the
        worktree. Reported as a suite failure it would read as a
        verdict on the new release, which is the one thing the exit
        statuses promise it is not.
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
