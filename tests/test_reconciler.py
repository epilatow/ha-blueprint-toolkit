#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.331",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for custom_components/blueprint_toolkit/reconciler.py.

All tests exercise the planning logic against tempdirs;
no HA, no subprocess. Covers every ActionKind transition,
the bundle-marker recognition rule, cli_symlink_dir
behaviour, and each conflict classification.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

from custom_components.blueprint_toolkit.reconciler import (  # noqa: E402
    BUNDLED_MARKER,
    Action,
    ActionKind,
    Conflict,
    ReconcilePlan,
    discover_ours_destinations,
    plan,
)


def _make_bundled(root: Path) -> Path:
    """Build a minimal bundled/ tree with one file per subdir."""
    bundled = root / "custom_components" / "blueprint_toolkit" / "bundled"
    (bundled / "blueprints" / "automation" / "blueprint_toolkit").mkdir(
        parents=True,
    )
    (bundled / "www" / "blueprint_toolkit" / "docs").mkdir(parents=True)
    (bundled / "cli").mkdir(parents=True)

    (
        bundled
        / "blueprints"
        / "automation"
        / "blueprint_toolkit"
        / "demo.yaml"
    ).write_text("blueprint: {}\n")
    (
        bundled
        / "blueprints"
        / "automation"
        / "blueprint_toolkit"
        / "extra.yaml"
    ).write_text("blueprint: {}\n")
    (bundled / "www" / "blueprint_toolkit" / "docs" / "demo.html").write_text(
        "<html>demo</html>\n"
    )
    (bundled / "cli" / "demo_cli.py").write_text(
        "#!/usr/bin/env python3\n",
    )
    return bundled


def _action_for(plan_obj: ReconcilePlan, dest: Path) -> Action | None:
    for a in plan_obj.actions:
        if a.destination == dest:
            return a
    return None


def _kind_for(plan_obj: ReconcilePlan, dest: Path) -> ActionKind | None:
    action = _action_for(plan_obj, dest)
    return None if action is None else action.kind


def _materialize(plan_obj: ReconcilePlan) -> None:
    """Create the symlinks the plan describes."""
    for action in plan_obj.actions:
        assert action.target is not None
        action.destination.parent.mkdir(parents=True, exist_ok=True)
        action.destination.symlink_to(action.target)


# ---------------------------------------------------------------
# Fresh-install path
# ---------------------------------------------------------------


class TestFreshInstall:
    def test_installs_every_bundled_file(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()

        result = plan(bundled_root=bundled, config_root=config)

        kinds = {a.kind for a in result.actions}
        assert kinds == {ActionKind.INSTALL}
        assert not result.conflicts
        # bundled/www/ is intentionally NOT installed via
        # the reconciler -- HA's /local/ static handler
        # cannot serve symlinked files; the integration
        # registers an aiohttp static route directly at
        # bundled/www/... instead. The fixture still
        # creates a www/ html file to verify the
        # reconciler ignores it.
        expected_dests = {
            config / "blueprints/automation/blueprint_toolkit/demo.yaml",
            config / "blueprints/automation/blueprint_toolkit/extra.yaml",
        }
        assert {a.destination for a in result.actions} == expected_dests

    def test_cli_not_installed_when_dir_unset(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()

        result = plan(bundled_root=bundled, config_root=config)
        for a in result.actions:
            assert "demo_cli.py" not in str(a.destination)

    def test_cli_installed_when_dir_set(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        cli_dir = tmp_path / "root"
        cli_dir.mkdir()

        result = plan(
            bundled_root=bundled,
            config_root=config,
            cli_symlink_dir=cli_dir,
        )
        cli_dest = cli_dir / "demo_cli.py"
        assert _kind_for(result, cli_dest) == ActionKind.INSTALL


# ---------------------------------------------------------------
# Reinstall / rerun path
# ---------------------------------------------------------------


class TestReinstall:
    def _install_all(self, tmp_path: Path) -> tuple[Path, Path, ReconcilePlan]:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        first = plan(bundled_root=bundled, config_root=config)
        _materialize(first)
        return bundled, config, first

    def test_second_run_is_all_keep(self, tmp_path: Path) -> None:
        bundled, config, _ = self._install_all(tmp_path)

        second = plan(bundled_root=bundled, config_root=config)
        assert not second.conflicts
        assert all(a.kind == ActionKind.KEEP for a in second.actions)

    def test_removed_bundled_file_becomes_remove(self, tmp_path: Path) -> None:
        bundled, config, _ = self._install_all(tmp_path)
        # Remove one source from bundled. The dest symlink
        # is still on disk and still ours (target points
        # into the bundle); the sweep should REMOVE it.
        (
            bundled
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "extra.yaml"
        ).unlink()

        second = plan(bundled_root=bundled, config_root=config)
        rm_dest = config / "blueprints/automation/blueprint_toolkit/extra.yaml"
        assert _kind_for(second, rm_dest) == ActionKind.REMOVE

    def test_retargeted_ours_symlink_is_update(self, tmp_path: Path) -> None:
        """A symlink whose target points into the bundle but is
        not the *expected* target (e.g. dev-deploy switched to
        a new snapshot directory) gets UPDATE, not a conflict.
        """
        bundled, config, _ = self._install_all(tmp_path)
        victim = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        # Repoint to a different path inside a different
        # snapshot of the same bundle subtree.
        new_bundle = _make_bundled(tmp_path / "snapshot-2")
        victim.unlink()
        victim.symlink_to(
            new_bundle
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml",
        )

        second = plan(bundled_root=bundled, config_root=config)
        assert _kind_for(second, victim) == ActionKind.UPDATE
        assert not second.conflicts


# ---------------------------------------------------------------
# Ownership recognition (single, bundle-marker-based)
# ---------------------------------------------------------------


class TestOwnershipRecognition:
    def test_bundled_marker_symlink_is_recognized_on_first_run(
        self,
        tmp_path: Path,
    ) -> None:
        """A symlink pointing into ANY clone of our bundle is
        ours, even if no prior reconcile has run against this
        config dir. Covers the dev-install / HACS upgrade
        path where dev-install installed the symlink and the
        integration's startup reconcile sees it for the first
        time.
        """
        bundled = _make_bundled(tmp_path / "repo-new")
        old_bundled = _make_bundled(tmp_path / "repo-old")
        config = tmp_path / "config"
        config.mkdir()
        dest = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        dest.parent.mkdir(parents=True)
        dest.symlink_to(
            old_bundled
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml",
        )

        result = plan(bundled_root=bundled, config_root=config)
        assert _kind_for(result, dest) == ActionKind.UPDATE
        assert not result.conflicts

    def test_foreign_symlink_is_conflict(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        dest = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        dest.parent.mkdir(parents=True)
        other = tmp_path / "other-place.py"
        other.write_text("#\n")
        # Symlink target does not contain BUNDLED_MARKER.
        dest.symlink_to(other)

        result = plan(bundled_root=bundled, config_root=config)
        assert _action_for(result, dest) is None
        assert any(
            c.destination == dest and c.kind == "foreign_symlink"
            for c in result.conflicts
        )

    def test_dev_deploy_snapshot_layout_is_recognized(
        self,
        tmp_path: Path,
    ) -> None:
        """``scripts/dev-deploy.py`` lays the integration out at
        ``<workspace>/<timestamp>/blueprint_toolkit/bundled/...``
        -- *not* under ``custom_components/``. The marker check
        must still recognise that path as ours, otherwise the
        integration's startup reconcile would treat every
        dev-installed symlink as a foreign symlink and surface
        a Repairs prompt for it.
        """
        bundled = _make_bundled(tmp_path / "repo")
        # Build a path that mimics the dev-deploy snapshot
        # layout: <workspace>/<timestamp>/blueprint_toolkit/bundled/...
        snap_bundle = (
            tmp_path
            / "ha-blueprint-toolkit"
            / "20260517_121743"
            / "blueprint_toolkit"
            / "bundled"
        )
        (snap_bundle / "blueprints" / "automation" / "blueprint_toolkit").mkdir(
            parents=True,
        )
        snap_src = (
            snap_bundle
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml"
        )
        snap_src.write_text("blueprint: {}\n")

        config = tmp_path / "config"
        config.mkdir()
        dest = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        dest.parent.mkdir(parents=True)
        dest.symlink_to(snap_src)

        result = plan(bundled_root=bundled, config_root=config)
        assert _kind_for(result, dest) == ActionKind.UPDATE
        assert not result.conflicts

    def test_force_destinations_overrides_foreign_symlink(
        self,
        tmp_path: Path,
    ) -> None:
        """The Repairs Overwrite flow passes the previously-
        flagged conflict dests in ``force_destinations``;
        these become UPDATE actions, replacing whatever's
        there with our symlink.
        """
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        dest = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        dest.parent.mkdir(parents=True)
        other = tmp_path / "other-place.py"
        other.write_text("#\n")
        dest.symlink_to(other)

        result = plan(
            bundled_root=bundled,
            config_root=config,
            force_destinations=frozenset({dest}),
        )
        assert _kind_for(result, dest) == ActionKind.UPDATE
        assert not result.conflicts


# ---------------------------------------------------------------
# Conflict classification
# ---------------------------------------------------------------


class TestConflicts:
    def test_regular_file_at_destination_is_conflict(
        self,
        tmp_path: Path,
    ) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        dest = config / "blueprints/automation/blueprint_toolkit/extra.yaml"
        dest.parent.mkdir(parents=True)
        dest.write_text("# user file\n")  # regular file

        result = plan(bundled_root=bundled, config_root=config)
        assert any(
            c.destination == dest and c.kind == "regular_file"
            for c in result.conflicts
        )
        assert _action_for(result, dest) is None

    def test_regular_dir_at_destination_is_conflict(
        self,
        tmp_path: Path,
    ) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        # A directory where we want a symlink.
        dest = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        dest.mkdir(parents=True)

        result = plan(bundled_root=bundled, config_root=config)
        assert any(
            c.destination == dest and c.kind == "regular_dir"
            for c in result.conflicts
        )


# ---------------------------------------------------------------
# Symlink target shape
# ---------------------------------------------------------------


class TestTargetShape:
    def test_targets_are_relative(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()

        result = plan(bundled_root=bundled, config_root=config)
        for action in result.actions:
            assert action.target is not None
            assert not action.target.is_absolute(), (
                f"expected relative target, got absolute: {action.target}",
            )

    def test_relative_target_resolves(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()

        result = plan(bundled_root=bundled, config_root=config)
        _materialize(result)
        # Spot-check one resolved path lands in the bundle.
        sample = config / "blueprints/automation/blueprint_toolkit/demo.yaml"
        assert sample.is_symlink()
        resolved = os.path.realpath(sample)
        assert BUNDLED_MARKER in resolved


# ---------------------------------------------------------------
# Sweep (REMOVE) without a prior manifest
# ---------------------------------------------------------------


class TestSweep:
    def test_orphan_ours_symlink_swept(self, tmp_path: Path) -> None:
        """An ours-symlink under our install root whose
        bundled source no longer exists gets REMOVE, even on
        first reconcile of a fresh process.
        """
        bundled = _make_bundled(tmp_path / "repo")
        old_bundle = _make_bundled(tmp_path / "old-repo")
        # Add a file to the OLD bundle that the new bundle
        # doesn't have, then pre-seed its destination.
        (
            old_bundle
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "deleted.yaml"
        ).write_text("blueprint: {}\n")
        config = tmp_path / "config"
        config.mkdir()
        orphan_dest = (
            config / "blueprints/automation/blueprint_toolkit/deleted.yaml"
        )
        orphan_dest.parent.mkdir(parents=True)
        orphan_dest.symlink_to(
            old_bundle
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "deleted.yaml",
        )

        result = plan(bundled_root=bundled, config_root=config)
        assert _kind_for(result, orphan_dest) == ActionKind.REMOVE

    def test_empty_bundled_root_sweeps_all_ours(self, tmp_path: Path) -> None:
        """``bundled/`` exists but contains no installable
        content: every ours-symlink under our install roots
        gets REMOVE, no installs, no conflicts.
        """
        # An old bundle to pre-seed an ours-symlink from.
        old_bundle = _make_bundled(tmp_path / "old-repo")
        bundled = (
            tmp_path
            / "repo"
            / "custom_components"
            / "blueprint_toolkit"
            / "bundled"
        )
        bundled.mkdir(parents=True)
        config = tmp_path / "config"
        config.mkdir()
        stale_dest = config / "blueprints/automation/blueprint_toolkit/old.yaml"
        stale_dest.parent.mkdir(parents=True)
        stale_dest.symlink_to(
            old_bundle
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml",
        )

        result = plan(bundled_root=bundled, config_root=config)
        assert _kind_for(result, stale_dest) == ActionKind.REMOVE
        assert not any(
            a.kind in (ActionKind.INSTALL, ActionKind.UPDATE)
            for a in result.actions
        )

    def test_foreign_symlinks_not_swept(self, tmp_path: Path) -> None:
        """Non-ours symlinks under our install root are
        ignored entirely -- not swept, not conflicted unless
        they sit at one of our destinations.
        """
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        config.mkdir()
        # A foreign symlink at a path the bundle does not
        # cover: not at any destination in the mapping, not
        # ours, must be left alone entirely.
        elsewhere = tmp_path / "elsewhere.yaml"
        elsewhere.write_text("# not ours\n")
        foreign_dest = (
            config / "blueprints/automation/blueprint_toolkit/foreign.yaml"
        )
        foreign_dest.parent.mkdir(parents=True)
        foreign_dest.symlink_to(elsewhere)

        result = plan(bundled_root=bundled, config_root=config)
        assert _action_for(result, foreign_dest) is None
        assert not result.conflicts


class TestDiscoverOursDestinations:
    def test_returns_only_ours_symlinks(self, tmp_path: Path) -> None:
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        (config / "blueprints/automation/blueprint_toolkit").mkdir(parents=True)
        ours = config / "blueprints/automation/blueprint_toolkit/ours.yaml"
        ours.symlink_to(
            bundled
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml",
        )
        elsewhere = tmp_path / "elsewhere.yaml"
        elsewhere.write_text("#\n")
        foreign = (
            config / "blueprints/automation/blueprint_toolkit/foreign.yaml"
        )
        foreign.symlink_to(elsewhere)

        result = discover_ours_destinations(config)
        assert result == frozenset({ours})

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        config = tmp_path / "config"
        config.mkdir()
        result = discover_ours_destinations(config)
        assert result == frozenset()

    def test_finds_ours_symlinks_in_nested_subdirs(
        self, tmp_path: Path
    ) -> None:
        """Discovery recurses into subdirectories so a future
        bundled layout that nests files (e.g. per-mode subfolders)
        stays sweep-correct.
        """
        bundled = _make_bundled(tmp_path / "repo")
        config = tmp_path / "config"
        nested = config / "blueprints/automation/blueprint_toolkit/sub"
        nested.mkdir(parents=True)
        ours = nested / "deep.yaml"
        ours.symlink_to(
            bundled
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "demo.yaml",
        )

        result = discover_ours_destinations(config)
        assert result == frozenset({ours})


# ---------------------------------------------------------------
# Dataclass sanity: plan output is hashable/frozen
# ---------------------------------------------------------------


class TestDataclassShapes:
    def test_action_is_frozen(self) -> None:
        a = Action(kind=ActionKind.KEEP, destination=Path("/x"), target=None)
        with pytest.raises((AttributeError, Exception)):
            a.kind = ActionKind.INSTALL  # type: ignore[misc]

    def test_conflict_is_frozen(self) -> None:
        c = Conflict(destination=Path("/x"), kind="regular_file", details="")
        with pytest.raises((AttributeError, Exception)):
            c.kind = "foreign_symlink"  # type: ignore[misc]


if __name__ == "__main__":
    from conftest import run_tests

    run_tests(
        test_file=__file__,
        script_path=(
            Path(__file__).parent.parent
            / "custom_components"
            / "blueprint_toolkit"
            / "reconciler.py"
        ),
        repo_root=Path(__file__).parent.parent,
    )
