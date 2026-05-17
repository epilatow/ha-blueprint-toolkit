# This is AI generated code
"""Pure-function planner for the blueprint_toolkit install.

Given the bundled payload and the target config directory,
return a ``ReconcilePlan`` describing the symlink
``install`` / ``update`` / ``remove`` / ``keep`` actions
that should happen next. Destinations occupied by unexpected
content (regular files, foreign symlinks) are surfaced as
``Conflict``s; the installer refuses to overwrite them unless
explicitly forced via the Repairs UI.

Ownership of an existing symlink is determined by its target:
any symlink whose target string (or resolved path) contains
the bundled subtree marker is treated as ours. The bundle
itself is the source of truth -- there is no separate
on-disk allowlist of "what we previously installed", so the
dev-install CLI and the integration agree on what's ours
without sharing state.

No HA imports; no side effects beyond read-only filesystem
probes (``exists``, ``is_symlink``, ``readlink``, directory
enumeration). This module is safe to import outside of HA
and is reused by ``scripts/dev-install.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Path marker that identifies "ours": any symlink whose
# target contains this segment is treated as a
# blueprint_toolkit-owned symlink. The integration's
# directory name is unique to this project, so any path
# ending in ``blueprint_toolkit/bundled/<...>`` necessarily
# points at our private bundle subtree -- regardless of
# whether the parent is ``/custom_components/`` (HACS
# install path), ``/<dev-deploy-workspace>/<timestamp>/``
# (dev-deploy snapshot path), or another layout a future
# dev workflow might introduce.
BUNDLED_MARKER = "/blueprint_toolkit/bundled/"

_BLUEPRINTS_SUBDIR = Path("blueprints/automation/blueprint_toolkit")


class ActionKind(Enum):
    """What the installer should do at a destination."""

    INSTALL = "install"  # dest missing; create a new symlink
    UPDATE = "update"  # dest is our symlink, target changed; replace
    REMOVE = "remove"  # dest is an ours-symlink no longer bundled
    KEEP = "keep"  # dest already correct; no-op


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    destination: Path  # absolute
    target: Path | None = None  # None for REMOVE; relative for others


@dataclass(frozen=True)
class Conflict:
    destination: Path
    kind: str  # "regular_file" | "regular_dir" | "foreign_symlink" | "other"
    details: str  # e.g. readlink output for foreign_symlink


@dataclass(frozen=True)
class ReconcilePlan:
    actions: tuple[Action, ...]
    conflicts: tuple[Conflict, ...]


def _destination_mapping(
    bundled_root: Path,
    config_root: Path,
    cli_symlink_dir: Path | None,
) -> dict[Path, Path]:
    """Return ``{destination: source}`` for every installable file.

    Destinations outside ``config_root`` are valid -- the
    optional ``cli_symlink_dir`` supports an out-of-tree
    install location for the shell CLI.
    """
    mapping: dict[Path, Path] = {}

    # bundled/blueprints/... -> /config/blueprints/...
    src_dir = bundled_root / "blueprints"
    if src_dir.is_dir():
        for src in sorted(src_dir.rglob("*.yaml")):
            rel = src.relative_to(src_dir)
            mapping[config_root / "blueprints" / rel] = src

    # NB: bundled/www/... is NOT installed via the
    # filesystem. HA's /local/ static handler refuses to
    # follow symlinks whose targets escape /config/www/,
    # and is only registered at startup if /config/www/
    # already exists. The integration's async_setup_entry
    # registers its own static route at
    # /local/blueprint_toolkit/docs/ pointing
    # directly into bundled/www/, which neither requires
    # /config/www/ to exist nor needs to traverse a
    # symlink. dev-install users who don't load the HA
    # integration will see broken /local/ doc links;
    # that's documented as a dev-install limitation.

    # bundled/cli/*.py -> <cli_symlink_dir>/*.py (flat; optional)
    if cli_symlink_dir is not None:
        src_dir = bundled_root / "cli"
        if src_dir.is_dir():
            for src in sorted(src_dir.glob("*.py")):
                mapping[cli_symlink_dir / src.name] = src

    return mapping


def _is_ours(destination: Path) -> bool:
    """True if ``destination`` is a symlink whose target points
    into our bundled subtree.

    Checks both the literal target string (catches relative
    symlinks that traverse through the marker) and the
    resolved path (catches absolute symlinks or chains that
    end up inside the bundle through another route).
    """
    if not destination.is_symlink():
        return False
    try:
        current_target = os.readlink(destination)
    except OSError:
        return False
    if BUNDLED_MARKER in current_target:
        return True
    try:
        resolved = (destination.parent / current_target).resolve(strict=False)
    except OSError:
        return False
    return BUNDLED_MARKER in str(resolved)


def _install_roots(
    config_root: Path,
    cli_symlink_dir: Path | None,
) -> list[Path]:
    """Return the directories the integration installs symlinks into.

    Used by the sweep pass to find ours-symlinks the current
    bundled mapping no longer covers (renamed or removed
    bundled files). MUST stay in lockstep with the set of
    destination roots ``_destination_mapping`` writes into;
    a destination installed outside one of these roots
    would never be swept on removal.
    """
    roots = [config_root / _BLUEPRINTS_SUBDIR]
    if cli_symlink_dir is not None:
        roots.append(cli_symlink_dir)
    return roots


def discover_ours_destinations(
    config_root: Path,
    cli_symlink_dir: Path | None = None,
) -> frozenset[Path]:
    """Return every existing ours-symlink under the install roots.

    Caller uses this for the uninstall sweep (where the
    bundled mapping is empty) and the in-process tests.
    Recurses into subdirectories so nested bundled layouts
    (if added later) stay sweep-correct.
    """
    found: set[Path] = set()
    for root in _install_roots(config_root, cli_symlink_dir):
        if not root.is_dir():
            continue
        for child in root.rglob("*"):
            if _is_ours(child):
                found.add(child)
    return frozenset(found)


def _compute_symlink_target(destination: Path, source: Path) -> Path:
    """Compute the relative symlink target from destination to source.

    Relative targets survive Docker path rebinding (where the
    same data appears at different absolute paths inside and
    outside the container) as long as the relative traversal
    stays on the same logical filesystem tree. Falls back to
    an absolute path only when relpath computation fails, which
    on POSIX does not happen for two absolute paths on the same
    root.
    """
    try:
        return Path(os.path.relpath(source, destination.parent))
    except ValueError:
        return source


def _classify_destination(
    destination: Path,
    expected_target: Path,
    *,
    force_overwrite: bool = False,
) -> tuple[ActionKind | None, Conflict | None]:
    """Inspect the current state of ``destination`` and decide.

    Exactly one of the return values is non-None. ``ActionKind``
    values INSTALL, UPDATE, KEEP mean the installer should act
    (or no-op for KEEP); a ``Conflict`` means the destination
    is occupied by something we refuse to overwrite.

    REMOVE actions are not produced here; they're synthesized
    by ``plan`` from the sweep over existing ours-symlinks.

    ``force_overwrite=True`` (used by the Repairs Overwrite
    flow) treats any existing destination as ours-to-replace:
    same-target symlinks are still KEEP, anything else
    (wrong-target symlink, regular file, dir, special) gets
    an UPDATE action. The installer's UPDATE handler unlinks
    + recreates; on a directory destination the unlink raises
    IsADirectoryError, which surfaces as an install_failure
    repair issue rather than silently destroying the dir.
    """
    # Missing destination (including a broken dangling symlink
    # target) counts as absent for install purposes. But a
    # dangling symlink at the destination is_symlink() True
    # while exists() False -- we must detect symlinks before
    # this branch or we'd try to create another in its place.
    if destination.is_symlink():
        current_target = os.readlink(destination)
        if current_target == str(expected_target):
            return ActionKind.KEEP, None

        if force_overwrite or _is_ours(destination):
            return ActionKind.UPDATE, None

        return None, Conflict(
            destination=destination,
            kind="foreign_symlink",
            details=f"target={current_target!r}",
        )

    if not destination.exists():
        return ActionKind.INSTALL, None

    if force_overwrite:
        return ActionKind.UPDATE, None

    # Exists but not a symlink: some kind of real path we
    # will not clobber without an explicit Repairs action.
    if destination.is_file():
        return None, Conflict(
            destination=destination,
            kind="regular_file",
            details="",
        )
    if destination.is_dir():
        return None, Conflict(
            destination=destination,
            kind="regular_dir",
            details="",
        )
    return None, Conflict(
        destination=destination,
        kind="other",
        details="",
    )


def plan(
    *,
    bundled_root: Path,
    config_root: Path,
    cli_symlink_dir: Path | None = None,
    force_destinations: frozenset[Path] = frozenset(),
) -> ReconcilePlan:
    """Compute a reconcile plan.

    Args:
        bundled_root: Absolute path to
            ``.../custom_components/blueprint_toolkit/bundled/``.
        config_root: Absolute path to HA's ``/config/`` dir.
        cli_symlink_dir: If given, install ``bundled/cli/*.py``
            into this directory. If None (default), CLI files
            are not installed.
        force_destinations: Destinations the caller explicitly
            wants to overwrite (the Repairs Overwrite flow
            passes the previously-flagged conflict dests
            here). Any of these that already have something
            other than the expected symlink become UPDATE
            actions instead of conflicts.
    """
    mapping = _destination_mapping(bundled_root, config_root, cli_symlink_dir)

    actions: list[Action] = []
    conflicts: list[Conflict] = []
    install_dests: set[Path] = set()

    for dest in sorted(mapping):
        src = mapping[dest]
        target = _compute_symlink_target(dest, src)
        kind, conflict = _classify_destination(
            destination=dest,
            expected_target=target,
            force_overwrite=dest in force_destinations,
        )
        if conflict is not None:
            conflicts.append(conflict)
            continue
        assert kind is not None
        install_dests.add(dest)
        actions.append(
            Action(kind=kind, destination=dest, target=target),
        )

    # Sweep: any ours-symlink under our install roots that
    # the current bundled mapping no longer covers gets a
    # REMOVE action. We do not REMOVE destinations that are
    # now conflicts; those will be listed in the Repairs UI
    # and the user decides.
    conflict_dests = {c.destination for c in conflicts}
    existing = discover_ours_destinations(config_root, cli_symlink_dir)
    for dest in sorted(existing - install_dests - conflict_dests):
        actions.append(
            Action(
                kind=ActionKind.REMOVE,
                destination=dest,
                target=None,
            ),
        )

    return ReconcilePlan(
        actions=tuple(actions),
        conflicts=tuple(conflicts),
    )
