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

- Compare the pin *as published* against PyPI. Without ``--base``
  the comparison reads the remote's tree, not the local checkout, so
  a local branch that has drifted ahead cannot make the tool report
  "already current" while the published pin sits still.
- Build the bump in a throwaway worktree branched off the remote
  default branch, never in the main checkout. ``--base`` moves that
  branch point, for a long-lived branch whose work has to be in the
  tree the suite runs against -- a pin bump that needs an API
  migration landing alongside it cannot be verified against a default
  branch that lacks the migration. Such a run verifies only, and the
  verified result is left for a hand merge.
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

The Z-Wave client pin rides along. It is pinned exactly too, but its
value is dictated by the Home Assistant release the HACC pin selects,
so the bump reads it out of that release and rewrites it in the same
commit rather than leaving a coupled pin behind. That value comes from
the release's own component manifest, which is read as a file rather
than imported -- importing ``zwave_js`` requires the very library whose
version is being resolved. If a future Home Assistant release relaxes
that requirement to a range there is nothing exact to read, and the
bump stops instead of guessing; note that this halts the whole weekly
bump, not just its Z-Wave part.

The manifest version is bumped only when a rewrite actually touched
``custom_components/``. ``tests/test_manifest.py`` enforces that
relationship in both directions, and both can happen here: most pin
sites are analysis-only and leave shipped code alone, but the bundled
CLI declares the Z-Wave client in its runtime venv list, so moving that
pin does change what users receive. Asking git what changed, rather
than assuming either answer, is what keeps the suite green whichever
sites a given bump rewrites.
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
from collections.abc import Iterator
from enum import IntEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "pytest-homeassistant-custom-component"
# The Z-Wave client library is pinned exactly too, but its value is not
# a choice: it has to be whatever the pinned Home Assistant release's
# zwave_js component requires. See ``companion_requirement``.
COMPANION = "zwave-js-server-python"
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

# A shell reports these when it cannot execute the command at all:
# 127 not found, 126 found but not executable. Missing ``uv`` on a
# scheduler's PATH lands here, and it is not a test failure.
SHELL_CANNOT_EXEC = frozenset({126, 127})


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


def rewrite_pins(text: str, old: str, new: str, package: str = PACKAGE) -> str:
    """Replace every ``package==old`` occurrence with ``==new``.

    Anchored on the package name so an unrelated dependency that
    happens to share a version string is left alone.
    """
    return re.sub(
        re.escape(f"{package}=={old}") + r"(?!\.?\d)",
        f"{package}=={new}",
        text,
    )


def candidate_files(root: Path) -> Iterator[tuple[Path, str]]:
    """Tracked files a pin could live in, with their contents.

    One walk for every caller that searches for pins, so none can
    disagree with the others about which files exist -- a file this
    skipped but a sibling visited would be rewritten without being
    checked, or checked without being rewritable.
    """
    for rel in git("ls-files", "-z", cwd=root).split("\0"):
        if not rel or not rel.endswith(PIN_SUFFIXES):
            continue
        path = root / rel
        # Rewriting through a tracked symlink would edit the target
        # -- for the shared docs, vendored content under
        # ``_repo_shared/`` that a drift test gates -- while
        # ``git add`` on the link stages nothing.
        if path.is_symlink():
            continue
        yield path, path.read_text()


def pin_sites(root: Path, version: str, package: str = PACKAGE) -> list[Path]:
    """Return tracked files under ``root`` declaring that version.

    Matched on a version boundary so a longer version sharing the
    prefix (``0.13.331`` against ``0.13.33``) is not a hit; a
    substring match there would rewrite it into a malformed one.
    """
    needle = re.compile(re.escape(f"{package}=={version}") + r"(?!\.?\d)")
    return [path for path, text in candidate_files(root) if needle.search(text)]


def declared_sites(root: Path, package: str) -> list[tuple[Path, str]]:
    """Every (file, version) pair ``package`` is pinned to."""
    found = re.compile(re.escape(f"{package}==") + r"(\d+(?:\.\d+)*)")
    return [
        (path, match.group(1))
        for path, text in candidate_files(root)
        for match in found.finditer(text)
    ]


def declared_versions(root: Path, package: str) -> set[str]:
    """Every version ``package`` is pinned to across tracked files."""
    return {version for _, version in declared_sites(root, package)}


def companion_requirement(root: Path, hacc_version: str) -> str:
    """Return the Z-Wave client version the target HACC release needs.

    Home Assistant's own ``zwave_js`` component pins one exact
    ``zwave-js-server-python`` and imports from it, so the version this
    repo declares has to be that one: an older library fails those
    imports and takes every Z-Wave phase down in collection, naming the
    library rather than the pin that chose it. The answer is a property
    of the release being pinned, so it is read out of the release rather
    than tracked by hand -- from the component's own manifest, without
    importing the component, which would need the library present.

    Runs from ``root`` so this throwaway environment resolves against
    the repo's ``.python-version`` like every other one. Without that it
    would take the newest interpreter on the host, which is how a
    resolution silently stops meaning what the suite validates against.
    """
    code = (
        "import json, pathlib, homeassistant;"
        "p = pathlib.Path(homeassistant.__file__).parent"
        " / 'components' / 'zwave_js' / 'manifest.json';"
        "print('\\n'.join(json.loads(p.read_text())['requirements']))"
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "--no-project",
            "--with",
            f"{PACKAGE}=={hacc_version}",
            "python",
            "-c",
            code,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"cannot read Home Assistant's zwave_js requirements at "
            f"{PACKAGE}=={hacc_version}: {result.stderr.strip()[:400]}"
        )
    needle = re.compile(re.escape(f"{COMPANION}==") + r"(\d+(?:\.\d+)*)")
    for line in result.stdout.splitlines():
        found = needle.fullmatch(line.strip())
        if found:
            return found.group(1)
    raise ValueError(
        f"Home Assistant's zwave_js manifest at {PACKAGE}=="
        f"{hacc_version} declares no exact {COMPANION} requirement: "
        f"{result.stdout.strip()[:200]}"
    )


def mismatched_sites(root: Path, expected: str) -> list[tuple[Path, str]]:
    """Return sites declaring some version other than ``expected``.

    The rewrite only finds sites carrying the version being
    replaced, so one that drifted elsewhere earlier passes through
    untouched. Left alone it fails the agreement test inside the
    worktree, where it would surface as an undifferentiated suite
    failure; named here, it points straight at the offending file.
    """
    return [
        (path, version)
        for path, version in declared_sites(root, PACKAGE)
        if version != expected
    ]


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


def sweep_stale_worktrees(keep: str | None = None) -> None:
    """Remove worktrees this tool left behind on earlier attempts.

    A red suite keeps its worktree for inspection, and next week's
    attempt targets a different version and so a different path.
    Without a sweep every failed week leaks another worktree and
    its test venv.

    ``keep`` is a commit the caller is building on. The branch in
    this namespace whose tip is that commit keeps its ref, because a
    verified bump awaiting a hand merge is exactly what ``--base`` is
    pointed at and deleting it would destroy the base mid-run. Only
    the ref is spared: its directory and venv are still reclaimed,
    and a branch no longer checked out anywhere is still a valid base
    for the next ``worktree add``.

    Matching is by resolved commit rather than by branch name, so a
    base spelled as a raw SHA is covered too -- and by the same
    token, any ref in this namespace sitting at that commit is
    spared. A pending bump at some other commit is swept.
    """
    wt_root = REPO_ROOT / ".wt" / WORKTREE_PREFIX
    if not wt_root.is_dir():
        return
    for path in sorted(wt_root.iterdir()):
        if not path.is_dir():
            continue
        branch = f"{WORKTREE_PREFIX}/{path.name}"
        exists = git_ok("rev-parse", "--verify", "--quiet", branch, quiet=True)
        spare = (
            keep is not None
            and exists
            and git("rev-parse", branch).strip() == keep
        )
        print(f"removing stale worktree {path}")
        git_ok("worktree", "remove", "--force", str(path), quiet=True)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        if spare:
            print(f"keeping {branch}; this run builds on it")
        elif exists:
            git_ok("branch", "-D", branch)


def report_companion_drift(root: Path, target: str, branch_point: str) -> None:
    """Print what the coupled pin would become, for ``--dry-run``.

    Reports rather than raises: a reporting run should not fail over
    a resolution problem a real run would stop on, and the resolution
    costs a download, so the reason for skipping it is printed too.

    Reads ``root``, the local checkout, because a dry run builds no
    worktree -- so it says which tree it read. A checkout that has
    drifted from the branch point can declare different sites than the
    ones a real run would rewrite.
    """
    declared = declared_versions(root, COMPANION)
    if not declared:
        print(f"no {COMPANION} pin declared; nothing coupled to move")
        return
    print(
        f"reading {COMPANION} sites from this checkout; a real run "
        f"rewrites them in a worktree built from {branch_point}"
    )
    if len(declared) > 1:
        print(
            f"warning: {COMPANION} already disagrees across sites "
            f"({', '.join(sorted(declared))}); a real run would stop "
            "rather than guess which to replace"
        )
        return
    try:
        wanted = companion_requirement(root, target)
    except ValueError as exc:
        print(f"warning: cannot resolve {COMPANION} for {target}: {exc}")
        return
    current = declared.pop()
    if current == wanted:
        print(f"{COMPANION}: {current} already matches {PACKAGE}=={target}")
        return
    sites = pin_sites(root, current, COMPANION)
    print(
        f"would also move {COMPANION}: {current} -> {wanted} "
        f"across {len(sites)} site(s):"
    )
    for path in sites:
        print(f"  {path.relative_to(root)}")


def shipped_code_changed(worktree: Path) -> bool:
    """Whether anything staged in ``worktree`` ships to users.

    Asked of git rather than inferred from which packages were
    rewritten, so a declaration site that moves into or out of the
    shipped tree later needs no change here.
    """
    staged = git(
        "diff",
        "--cached",
        "--name-only",
        "--",
        "custom_components",
        cwd=worktree,
    )
    return bool(staged.strip())


def bump_manifest(worktree: Path) -> bool:
    """Increment the integration version and stage the manifest.

    Delegates to the repo's own script, and specifically to
    ``worktree``'s copy of it: that script derives the manifest it
    edits from its own location, so running this checkout's copy
    against the worktree would bump the wrong tree's manifest. It
    stages the file itself.
    """
    return (
        subprocess.run(
            [str(worktree / "scripts" / "bump-manifest-version.py")],
            cwd=worktree,
            check=False,
        ).returncode
        == 0
    )


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
            "  4  the bump could not be built or verified at all --\n"
            "     a git, resolution, or rewrite problem, including\n"
            "     declaration sites that already disagree\n"
            "  5  the suite failed while verifying the new pin\n"
            "\n5 does not by itself implicate the new pin: the suite\n"
            "covers more than the API surface the pin selects. To tell,\n"
            "re-run the suite in the kept worktree against the branch\n"
            "point and compare."
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
            "tree or branch. Where a coupled pin is declared it also "
            "resolves the target release to report that pin, which "
            "downloads into uv's cache."
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
    parser.add_argument(
        "--base",
        metavar="REF",
        help=(
            "Build and verify the bump on this ref instead of the "
            "published default branch. For a long-lived branch whose "
            "work has to be in the tree the suite runs against. "
            "Cannot be combined with --push, which lands on the "
            "default branch."
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

    # An empty value is a wrapper script passing an unset variable
    # through. The ref check below would reject it too, but only as
    # an unresolvable ref, which sends the reader looking for a
    # misspelled branch instead of an unset variable.
    if args.base is not None and not args.base.strip():
        return _fail("--base needs a ref; got an empty value", Exit.USAGE)

    # Refused here with the other shape checks, ahead of any network
    # work, so an unreachable origin cannot report a usage error as
    # an infrastructure one.
    if args.base is not None and args.push:
        return _fail(
            "--base builds the bump somewhere other than the "
            "default branch, so --push has nothing to fast-forward; "
            "verify on the base, then land the result yourself",
            Exit.USAGE,
        )

    has_origin = git_ok("remote", "get-url", "origin", quiet=True)
    # Fetch on every path, dry-run included: comparing against a
    # stale remote-tracking ref would not be comparing against the
    # published pin, which is the whole point of reading it there.
    if has_origin and not git_ok("fetch", "origin"):
        return _fail("git fetch origin failed", Exit.ERROR)

    base_commit: str | None = None
    if args.base is not None:
        # Resolved after the fetch so a base naming a remote-tracking
        # ref reads the ref this run just updated. The resolved commit
        # is what the sweep below is told to spare, so a base in this
        # tool's own namespace survives the run built on it.
        if not git_ok(
            "rev-parse",
            "--verify",
            "--quiet",
            f"{args.base}^{{commit}}",
            quiet=True,
        ):
            return _fail(
                f"--base {args.base!r} is not a commit in this repository",
                Exit.USAGE,
            )
        base_commit = git("rev-parse", f"{args.base}^{{commit}}").strip()
        branch_point = args.base
        # A sentinel, never read: every use of ``branch`` below is
        # --push-gated and --push is refused above. Leaving it
        # unresolved is what lets this mode run on a checkout whose
        # origin/HEAD was never recorded -- resolving it would refuse
        # the one mode that has no use for it.
        branch = ""
    else:
        try:
            branch = default_branch()
        except ValueError as exc:
            return _fail(str(exc), Exit.ERROR)
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
        # Report the coupled pin too. A reader deciding whether to let
        # a bump land wants the whole diff it would produce, and this
        # is the part that can also move shipped code.
        report_companion_drift(REPO_ROOT, target, branch_point)
        return Exit.SUCCESS

    # Sweep before the guards, not after: a run that refuses would
    # otherwise leave the previous attempt's worktree and its test
    # venv behind indefinitely. Past the dry-run return, so a
    # reporting run still changes nothing.
    sweep_stale_worktrees(keep=base_commit)

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
    bump_exists = git_ok(
        "rev-parse", "--verify", "--quiet", bump_branch, quiet=True
    )
    # The branch this run rebuilds is deleted first, which would
    # destroy a base that happens to be that same ref -- the sweep
    # spares it only to have it deleted here. Refuse instead: the
    # caller has to merge or rename it, since this run cannot both
    # preserve and rewrite one ref.
    if (
        base_commit is not None
        and bump_exists
        and git("rev-parse", bump_branch).strip() == base_commit
    ):
        return _fail(
            f"--base {args.base!r} is {bump_branch}, the branch this run "
            f"rebuilds for {target}; merge or rename it first",
            Exit.USAGE,
        )
    if bump_exists:
        git_ok("branch", "-D", bump_branch)

    # Built from the resolved commit, not the ref: the ref can have
    # been swept or deleted between resolution and here, and the
    # commit cannot move under the run.
    build_from = base_commit if base_commit is not None else branch_point
    if not git_ok(
        "worktree", "add", "-b", bump_branch, str(worktree), build_from
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
            "Reconcile them by hand; the suite was not reached, so "
            f"this says nothing about {target}. Worktree {worktree} "
            "kept.",
            Exit.ERROR,
        )

    rel_sites = [str(p.relative_to(worktree)) for p in sites]

    # The Z-Wave client pin is derived from the target release, so it
    # moves in the same commit. Left behind, it fails the Z-Wave phases
    # on an import error that names the library instead of the pin.
    companion_declared = declared_sites(worktree, COMPANION)
    companion_current = {version for _, version in companion_declared}
    if len(companion_current) > 1:
        # An unattended run leaves only what it printed, so name the
        # files rather than just the versions that disagree.
        listing = "\n  ".join(
            f"{path.relative_to(worktree)} pins {version}"
            for path, version in sorted(
                companion_declared, key=lambda site: str(site[0])
            )
        )
        return _fail(
            f"{COMPANION} is pinned to several versions; reconcile them "
            f"by hand before a bump can move them (worktree {worktree} "
            f"kept):\n  {listing}",
            Exit.ERROR,
        )
    companion_moved = False
    if companion_current:
        # Exactly one version, per the guard above.
        stale_companion = companion_current.pop()
        try:
            companion_target = companion_requirement(worktree, target)
        except ValueError as exc:
            return _fail(f"{exc} (worktree {worktree} kept)", Exit.ERROR)
        if companion_target != stale_companion:
            companion_moved = True
            print(
                f"{COMPANION}: {stale_companion} -> {companion_target} "
                f"(required by {PACKAGE}=={target})"
            )
            companion_sites = pin_sites(worktree, stale_companion, COMPANION)
            for path in companion_sites:
                path.write_text(
                    rewrite_pins(
                        path.read_text(),
                        stale_companion,
                        companion_target,
                        COMPANION,
                    )
                )
            rel_sites.extend(
                str(p.relative_to(worktree))
                for p in companion_sites
                if str(p.relative_to(worktree)) not in rel_sites
            )

    if not git_ok("add", *rel_sites, cwd=worktree):
        return _fail(
            f"cannot stage the rewritten pins (worktree {worktree} kept)",
            Exit.ERROR,
        )

    if shipped_code_changed(worktree):
        print("rewrite touched custom_components/; bumping the manifest")
        if not bump_manifest(worktree):
            return _fail(
                f"cannot bump the manifest version (worktree {worktree} kept)",
                Exit.ERROR,
            )

    # The body states how this run was driven, because it is
    # permanent history on the default branch and the three modes are
    # not interchangeable: only the unattended one can claim the pin
    # followed the newest release on its own.
    if args.to is None:
        provenance = (
            "Automated weekly bump. The pin decides which Home\n"
            "Assistant API surface the suite validates against, so it\n"
            "tracks the newest release rather than a version chosen by\n"
            "hand.\n"
        )
    else:
        provenance = (
            f"Bumped to {target} deliberately rather than to whatever\n"
            "PyPI published last. The pin decides which Home Assistant\n"
            "API surface the suite validates against.\n"
        )
    if args.base is not None:
        provenance += (
            "\n"
            "Verified against a chosen base rather than the default\n"
            "branch, for a pin whose accompanying code changes are not\n"
            "landed yet, so this was merged by hand.\n"
        )
    message = f"- deps: Bump {PACKAGE} to {target}.\n\n{provenance}"
    # Only claim the coupled move when it happened. The pin can be
    # declared and already correct for the target release, and these
    # messages are permanent.
    if companion_moved:
        message += (
            "\n"
            "The Z-Wave client pin moves with it. That version is not\n"
            "a choice: Home Assistant's own zwave_js component requires\n"
            "one exact client and imports from it, so it is read out of\n"
            "the release being pinned.\n"
        )
    if not git_ok("commit", "-m", message, cwd=worktree):
        return _fail(
            f"cannot commit the bump (worktree {worktree} kept)",
            Exit.ERROR,
        )

    print("running tests/run_all.py against the bump")
    status = run_suite(worktree)
    if status != 0:
        # Separate a suite that ran and failed from one that never
        # started -- run_all.py's own infra status, a shell that
        # could not exec the runner, or a signal. Only the first is
        # about the tests at all. Neither settles whether the new pin
        # is at fault, so the message points at a comparison the
        # reader can run instead of guessing.
        infra = (
            status == RUN_ALL_INFRA_ERROR
            or status in SHELL_CANNOT_EXEC
            or status < 0
        )
        if infra:
            detail = (
                "the test run could not complete while verifying "
                f"{target} (run_all.py exit {status})"
            )
        else:
            detail = (
                f"the suite failed while verifying {target} "
                f"(run_all.py exit {status}). Whether the new pin is "
                "at fault is not decidable from this run: re-run the "
                "suite in the kept worktree against the branch point "
                "and compare. A failure that reproduces there is "
                "independent of the bump"
            )
        return _fail(
            f"{detail}. Worktree {worktree} kept for inspection until "
            "the next run, which rebuilds from scratch and sweeps it.",
            Exit.ERROR if infra else Exit.TESTS_FAILED,
        )
    print("suite passed")

    if args.base is not None:
        # The merge is the only instruction left, and it is
        # perishable: the next run sweeps this namespace and spares
        # only the one branch it is itself handed.
        print(
            f"bump left on {bump_branch}; merge it before the next "
            "run sweeps it."
        )
        return Exit.SUCCESS

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
