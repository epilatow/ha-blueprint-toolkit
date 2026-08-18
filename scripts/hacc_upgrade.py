#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# This is AI generated code
"""Bump the pinned HACC version, verify it, and land it.

``pytest-homeassistant-custom-component`` (HACC) ships Home
Assistant core as a transitive dependency, so its pin decides which
HA API surface ``mypy --strict`` and the integration tests validate
against. This tool moves that pin to the newest release and proves
the suite still passes before the change reaches the default
branch.

Run weekly from a scheduler. The whole point is that a green bump
lands unattended: a bump that only ever opens a proposal is a bump
nobody merges, and the pin then sits still while the HA surface it
claims to validate against moves on.

The flow mirrors ``repo-shared upgrade``:

- Compare the pin *as published* against PyPI. The comparison reads
  the remote's tree, not the local checkout, so a local branch that
  has drifted ahead cannot make the tool report "already current"
  while the published pin sits still.
- Build the bump in a throwaway worktree branched off the remote
  default branch, never in the main checkout.
- Rewrite every site declaring the version being replaced. There
  are many: each HACC-coupled test file repeats the pin in its own
  PEP 723 block, and a block that disagrees with ``pyproject.toml``
  would silently type-check against a different HA version. A site
  that has already drifted to some third version is not found by
  this, which is why ``tests/test_analysis_deps.py`` gates the
  blocks against ``pyproject.toml`` independently.
- Run the full suite there. A red suite means the new pin is not
  safe to land, so the worktree is kept for inspection and the exit
  status is non-zero.
- Publish the bump and fast-forward the default branch, with
  ``--push``. Without it the bump stays on its branch.

The manifest version is deliberately not bumped. No pin site lives
under ``custom_components/``, and ``tests/test_manifest.py``
requires the version to stay equal when nothing there changed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from enum import IntEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "pytest-homeassistant-custom-component"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
NETWORK_TIMEOUT_SECONDS = 30

# Every file kind that may carry a declaration. Markdown is
# included because a declaration-style mention is legitimate there
# (tests/test_analysis_deps.py forbids naming the version in prose
# but permits a dependency line), and a permitted mention left
# unrewritten would go stale the moment the pin moved.
PIN_SUFFIXES = (".py", ".toml", ".md")

WORKTREE_PREFIX = "hacc-upgrade"

# tests/run_all.py reserves this for "the run could not complete",
# as distinct from its exit 1 for a real test failure.
RUN_ALL_INFRA_ERROR = 2


class Exit(IntEnum):
    """Process exit statuses, meaningful to the scheduler."""

    SUCCESS = 0
    USAGE = 2
    DIRTY = 3
    ERROR = 4
    TESTS_FAILED = 5


def git(*args: str, cwd: Path | None = None) -> str:
    """Run git and return stdout, raising on a non-zero status."""
    return subprocess.check_output(
        ["git", *args],
        cwd=cwd or REPO_ROOT,
        text=True,
    )


def git_ok(*args: str, cwd: Path | None = None, quiet: bool = False) -> bool:
    """Run git for its status, reporting both streams on failure.

    An unattended run leaves only what it printed, so a failing git
    step has to surface git's own diagnosis rather than just the
    fact that something failed. ``quiet`` suppresses that for calls
    that ask a question rather than perform a step, where a
    non-zero status is an expected answer.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not quiet:
        print(f"git {' '.join(args)} -> {result.returncode}", file=sys.stderr)
        for stream in (result.stdout, result.stderr):
            if stream.strip():
                print(stream.rstrip(), file=sys.stderr)
    return result.returncode == 0


def pinned_version(pyproject_text: str) -> str:
    """Return the HACC version pinned in ``mypy-extra-deps``."""
    cfg = tomllib.loads(pyproject_text)
    deps = cfg["tool"]["repo-shared"]["code-quality"]["mypy-extra-deps"]
    if not isinstance(deps, list):
        raise TypeError("mypy-extra-deps is not a list")
    for dep in deps:
        if isinstance(dep, str) and dep.startswith(f"{PACKAGE}=="):
            return dep.split("==", 1)[1]
    raise ValueError(f"no pinned {PACKAGE} in mypy-extra-deps")


def latest_version() -> str:
    """Return the newest HACC version published to PyPI."""
    with urllib.request.urlopen(
        PYPI_URL, timeout=NETWORK_TIMEOUT_SECONDS
    ) as response:
        payload = json.load(response)
    version = payload["info"]["version"]
    if not isinstance(version, str):
        raise TypeError("PyPI returned a non-string version")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        # A pre-release or post-release string would flow straight
        # into a branch name and a filesystem path.
        raise ValueError(f"PyPI returned an unexpected version {version!r}")
    return version


def rewrite_pins(text: str, old: str, new: str) -> str:
    """Replace every ``PACKAGE==old`` occurrence with ``==new``.

    Anchored on the package name so an unrelated dependency that
    happens to share a version string is left alone.
    """
    return re.sub(
        re.escape(f"{PACKAGE}=={old}") + r"(?!\.?\d)",
        f"{PACKAGE}=={new}",
        text,
    )


def pin_sites(root: Path, version: str) -> list[Path]:
    """Return tracked files under ``root`` declaring that version.

    Matched on a version boundary so a longer version sharing the
    prefix (``0.13.331`` against ``0.13.33``) is not a hit; a
    substring match there would rewrite it into a malformed one.
    """
    needle = re.compile(re.escape(f"{PACKAGE}=={version}") + r"(?!\.?\d)")
    listing = git("ls-files", "-z", cwd=root).split("\0")
    hits: list[Path] = []
    for rel in listing:
        if not rel or not rel.endswith(PIN_SUFFIXES):
            continue
        path = root / rel
        # Rewriting through a tracked symlink would edit the target
        # -- for the shared docs, vendored content under
        # ``_repo_shared/`` that a drift test gates -- while
        # ``git add`` on the link stages nothing.
        if path.is_symlink():
            continue
        if needle.search(path.read_text()):
            hits.append(path)
    return hits


def mismatched_sites(root: Path, expected: str) -> list[tuple[Path, str]]:
    """Return sites declaring some version other than ``expected``.

    The rewrite only finds sites carrying the version being
    replaced, so one that drifted elsewhere earlier passes through
    untouched. Left alone it fails the agreement test inside the
    worktree, and that failure would otherwise be reported as a
    verdict on the new pin.
    """
    found = re.compile(re.escape(f"{PACKAGE}==") + r"(\d+(?:\.\d+)*)")
    listing = git("ls-files", "-z", cwd=root).split("\0")
    stale: list[tuple[Path, str]] = []
    for rel in listing:
        if not rel or not rel.endswith(PIN_SUFFIXES):
            continue
        path = root / rel
        if path.is_symlink():
            continue
        for match in found.finditer(path.read_text()):
            if match.group(1) != expected:
                stale.append((path, match.group(1)))
    return stale


def version_key(version: str) -> tuple[int, ...]:
    """Return a sortable key for an ``X.Y.Z`` version."""
    return tuple(int(part) for part in version.split("."))


def default_branch() -> str:
    """Return the branch the bump is based on and lands on.

    With a remote, that is the remote's default branch. An
    unresolvable ``origin/HEAD`` raises rather than falling back to
    the current branch: the fallback would make the wrong-branch
    guard compare a value against itself, so an unattended
    ``--push`` could base a bump on whatever feature branch the
    checkout was parked on and push the result there.
    """
    if not git_ok("remote", "get-url", "origin", quiet=True):
        return current_branch()
    try:
        ref = git("rev-parse", "--abbrev-ref", "origin/HEAD").strip()
    except subprocess.CalledProcessError:
        raise ValueError(
            "origin records no default branch; run "
            "`git remote set-head origin -a` so the bump has a branch "
            "to base on and land on"
        ) from None
    # ``origin/release/v2`` -> ``release/v2``: only the remote
    # prefix comes off, so a slashed branch name survives.
    return ref.split("/", 1)[-1]


def current_branch() -> str:
    """Return the checkout's current branch, or ``HEAD`` detached."""
    return git("rev-parse", "--abbrev-ref", "HEAD").strip()


def sweep_stale_worktrees() -> None:
    """Remove worktrees this tool left behind on earlier attempts.

    A red suite keeps its worktree for inspection, and next week's
    attempt targets a different version and so a different path.
    Without a sweep every failed week leaks another worktree and
    its test venv.
    """
    wt_root = REPO_ROOT / ".wt" / WORKTREE_PREFIX
    if not wt_root.is_dir():
        return
    for path in sorted(wt_root.iterdir()):
        if not path.is_dir():
            continue
        print(f"removing stale worktree {path}")
        git_ok("worktree", "remove", "--force", str(path), quiet=True)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        branch = f"{WORKTREE_PREFIX}/{path.name}"
        if git_ok("rev-parse", "--verify", "--quiet", branch, quiet=True):
            git_ok("branch", "-D", branch)


def run_suite(worktree: Path) -> int:
    """Run the repo's own suite inside ``worktree``.

    Separate from the caller so the landing path can be exercised
    without a real multi-minute suite run.
    """
    return subprocess.run(
        [str(worktree / "tests" / "run_all.py")],
        cwd=worktree,
        check=False,
    ).returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bump the pinned HACC version, run the suite against it, "
            "and fast-forward the default branch when it passes."
        ),
        epilog=(
            "Exit status:\n"
            "  0  success, or already on the newest release\n"
            "  2  usage error\n"
            "  3  dirty checkout, wrong branch, or unpushed commits\n"
            "  4  the run could not complete\n"
            "  5  the suite failed against the new pin\n"
            "\nOnly 5 is evidence about the new pin itself."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--push",
        action="store_true",
        help=(
            "On a green suite, fast-forward the default branch onto "
            "the bump and push it. Without this the bump is left on "
            "its branch for inspection."
        ),
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report the drift and exit. Fetches, so the comparison "
            "is against the published pin, but changes no working "
            "tree or branch."
        ),
    )
    parser.add_argument(
        "--to",
        metavar="X.Y.Z",
        help=(
            "Bump to this version instead of the newest on PyPI. "
            "Skips the PyPI lookup."
        ),
    )
    return parser.parse_args(argv)


def _fail(message: str, code: Exit) -> Exit:
    print(f"error: {message}", file=sys.stderr)
    return code


def run(args: argparse.Namespace) -> Exit:
    if not git_ok("rev-parse", "--git-dir", quiet=True):
        return _fail(f"{REPO_ROOT} is not a git repository", Exit.ERROR)

    if args.to and not re.fullmatch(r"\d+\.\d+\.\d+", args.to):
        return _fail(
            f"--to {args.to!r} is not an X.Y.Z version",
            Exit.USAGE,
        )

    try:
        branch = default_branch()
    except ValueError as exc:
        return _fail(str(exc), Exit.ERROR)
    has_origin = git_ok("remote", "get-url", "origin", quiet=True)
    # Fetch on every path, dry-run included: comparing against a
    # stale remote-tracking ref would not be comparing against the
    # published pin, which is the whole point of reading it there.
    if has_origin and not git_ok("fetch", "origin"):
        return _fail("git fetch origin failed", Exit.ERROR)
    branch_point = f"origin/{branch}" if has_origin else branch

    # The published pin is the one that matters. Reading it from the
    # local checkout would let a checkout sitting ahead of the remote
    # report "already current" every week while the published pin
    # never moved -- the exact silent-success failure this tool
    # exists to remove.
    try:
        current = pinned_version(git("show", f"{branch_point}:pyproject.toml"))
    except (
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        return _fail(
            f"cannot read the pin at {branch_point}: {exc}", Exit.ERROR
        )

    try:
        target = args.to or latest_version()
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return _fail(f"cannot resolve the latest release: {exc}", Exit.ERROR)

    if current == target:
        print(f"{branch_point} pinned at {current}; already current.")
        return Exit.SUCCESS

    if not args.to and version_key(target) < version_key(current):
        # A yanked latest would otherwise be verified and landed as
        # a downgrade with nobody in the loop. An explicit --to
        # stays unconstrained so a deliberate rollback still works.
        return _fail(
            f"PyPI's newest {target} is older than the pinned "
            f"{current}; refusing to downgrade unattended. Pass "
            f"--to {target} to do it deliberately.",
            Exit.ERROR,
        )

    print(f"drift on {branch_point}: {current} -> {target}")
    if args.dry_run:
        local = pin_sites(REPO_ROOT, current)
        if local:
            print(f"would rewrite {len(local)} declaration site(s):")
            for path in local:
                print(f"  {path.relative_to(REPO_ROOT)}")
        else:
            print(
                f"note: this checkout does not pin {current}, so the "
                "site list above is unavailable; the real run rewrites "
                f"sites in a worktree built from {branch_point}."
            )
        return Exit.SUCCESS

    # Sweep before the guards, not after: a run that refuses would
    # otherwise leave the previous attempt's worktree and its test
    # venv behind indefinitely. Past the dry-run return, so a
    # reporting run still changes nothing.
    sweep_stale_worktrees()

    # Everything below guards the landing step only. Without
    # --push the bump is built in a worktree off the branch point
    # and this checkout is never touched, so a dirty tree on a
    # feature branch is harmless and must not be refused.
    if args.push and current_branch() != branch:
        return _fail(
            f"{REPO_ROOT} is on {current_branch()!r}, not {branch!r}; "
            "refusing to land a bump onto a branch this run did not "
            "build against",
            Exit.DIRTY,
        )

    if args.push and git("status", "--porcelain").strip():
        return _fail(
            f"{REPO_ROOT} has uncommitted changes; the landing step "
            "fast-forwards this checkout and cannot with them present",
            Exit.DIRTY,
        )

    if args.push and not has_origin:
        return _fail(
            "--push needs a remote to publish to; this checkout has no origin",
            Exit.USAGE,
        )

    if args.push and has_origin:
        ahead = git("rev-list", "--count", f"origin/{branch}..{branch}").strip()
        if ahead != "0":
            return _fail(
                f"{branch} is ahead of origin/{branch} by {ahead} "
                "commit(s). The bump is built on origin, so it could "
                "never fast-forward onto them; push or drop them "
                "first.",
                Exit.DIRTY,
            )

    bump_branch = f"{WORKTREE_PREFIX}/{target}"
    worktree = REPO_ROOT / ".wt" / WORKTREE_PREFIX / target

    git_ok("worktree", "prune")
    if git_ok("rev-parse", "--verify", "--quiet", bump_branch, quiet=True):
        git_ok("branch", "-D", bump_branch)

    if not git_ok(
        "worktree", "add", "-b", bump_branch, str(worktree), branch_point
    ):
        return _fail(f"cannot create worktree at {worktree}", Exit.ERROR)

    sites = pin_sites(worktree, current)
    if not sites:
        return _fail(
            f"no declaration site pins {current} in {worktree}; "
            "nothing to rewrite (worktree kept)",
            Exit.ERROR,
        )
    for path in sites:
        path.write_text(rewrite_pins(path.read_text(), current, target))
    print(f"rewrote {len(sites)} declaration site(s)")

    stale = mismatched_sites(worktree, target)
    if stale:
        listed = ", ".join(
            f"{p.relative_to(worktree)} pins {v}" for p, v in stale
        )
        return _fail(
            f"declaration site(s) disagree after the rewrite: {listed}. "
            "These drifted before this run and carry neither the old "
            "nor the new version, so the rewrite could not find them. "
            "Reconcile them by hand; this is not a verdict on "
            f"{target}. Worktree {worktree} kept.",
            Exit.ERROR,
        )

    rel_sites = [str(p.relative_to(worktree)) for p in sites]
    if not git_ok("add", *rel_sites, cwd=worktree):
        return _fail(
            f"cannot stage the rewritten pins (worktree {worktree} kept)",
            Exit.ERROR,
        )

    message = (
        f"- deps: Bump {PACKAGE} to {target}.\n"
        "\n"
        "Automated weekly bump. The pin decides which Home Assistant\n"
        "API surface the suite validates against, so it tracks the\n"
        "newest release rather than a version chosen by hand.\n"
    )
    if not git_ok("commit", "-m", message, cwd=worktree):
        return _fail(
            f"cannot commit the bump (worktree {worktree} kept)",
            Exit.ERROR,
        )

    print("running tests/run_all.py against the bump")
    status = run_suite(worktree)
    if status != 0:
        # run_all.py separates a real test failure from its own
        # infrastructure error, and the two mean different things
        # to whoever reads the scheduler's report: only the first
        # is evidence about the new pin.
        infra = status == RUN_ALL_INFRA_ERROR
        return _fail(
            (
                f"the test run could not complete against {target}"
                if infra
                else f"the suite failed against {target}, which is the "
                "early warning that a new HA release broke an "
                "interface we depend on"
            )
            + f" (run_all.py exit {status}); worktree "
            f"{worktree} kept for inspection until the next run, "
            "which rebuilds from scratch and sweeps it.",
            Exit.ERROR if infra else Exit.TESTS_FAILED,
        )
    print("suite passed")

    if not args.push:
        print(f"bump left on {bump_branch}; pass --push to land it.")
        return Exit.SUCCESS

    # Publish before touching the local branch. The suite takes
    # minutes, so origin can move while it runs; a rejected push
    # then leaves nothing locally to unwind and the next run
    # rebuilds from the new base. Fast-forwarding first and pushing
    # second would strand the local branch ahead of origin, and
    # every later run would fail --ff-only forever.
    if not git_ok("push", "origin", f"{bump_branch}:{branch}"):
        return _fail(
            f"cannot publish {target} onto origin/{branch}; origin "
            "moved while the suite ran. Nothing landed locally, so "
            "the next run rebuilds from the new base.",
            Exit.ERROR,
        )
    if not git_ok("merge", "--ff-only", bump_branch):
        return _fail(
            f"published {target}, but cannot fast-forward the local "
            f"{branch} onto it; reconcile this checkout by hand.",
            Exit.ERROR,
        )
    print(f"landed {target} on {branch} and pushed.")

    git_ok("worktree", "remove", "--force", str(worktree))
    git_ok("branch", "-D", bump_branch)
    return Exit.SUCCESS


def main(argv: list[str] | None = None) -> int:
    try:
        return int(run(parse_args(argv)))
    except (
        subprocess.CalledProcessError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        # Keep every exit inside the documented status set; a bare
        # traceback would reach the scheduler as an undocumented 1.
        print(f"error: {exc}", file=sys.stderr)
        return int(Exit.ERROR)


if __name__ == "__main__":
    sys.exit(main())
