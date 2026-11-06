# Development Guide

How this repo is laid out, tested, deployed, and released, layered on
`DEVELOPMENT_SHARED.md`. The companion [AUTOMATIONS.md](AUTOMATIONS.md) covers
conventions and patterns for automations -- read that when adding, modifying,
or reviewing one.

## Repo layout

This repo ships as a HACS-distributed custom integration, and two external
constraints drive the top-level layout:

- Home Assistant looks for custom integrations at
  `/config/custom_components/<domain>/`, so the installable code lives under
  `custom_components/blueprint_toolkit/`.
- HACS only downloads files under `custom_components/<name>/`, so every file
  users should receive has to live inside that subtree too.

Integration code (`__init__.py`, `manifest.json`, `reconciler.py`,
`installer.py`, `config_flow.py`, `repairs.py`, etc.) sits at the
`custom_components/blueprint_toolkit/` level. Each per-automation handler
lives in a subpackage (`<service>/handler.py`, `<service>/logic.py`). The
`bundled/` subdirectory ships blueprints, docs, and CLI scripts to
user-visible `/config/...` paths via symlinks. See
[AUTOMATIONS.md](AUTOMATIONS.md) for the full per-automation layout.

The repo root keeps two committed symlinks into the bundle for path-typing
convenience. They live outside HACS's download path and are never shipped:

```text
blueprints -> custom_components/blueprint_toolkit/bundled/blueprints
docs       -> custom_components/blueprint_toolkit/bundled/docs
```

**POSIX filesystem required for development.** The repo uses mode-120000
symlinks that Windows (with default git settings) checks out as text files
containing the target path, which breaks tests, install scripts, and deploys.
Use macOS or Linux; WSL2 works too.

The integration's icon ships in `custom_components/blueprint_toolkit/brand/`,
where HA looks for a custom integration's brand images before trying its
brands CDN: `icon.png` and `icon@2x.png` are 256 and 512 px renders of
`assets/icon.svg`, the source, which stays out of the shipped tree.

Repo-local Claude Code skills live at `skills/<name>/SKILL.md`, and
`.claude/skills` is a committed symlink to `../skills` so Claude Code finds
them at the standard discovery path. A new skill only needs its directory +
`SKILL.md` under `skills/<name>/`.

## File conventions

### Shebangs

- **Executable scripts** (test files, `run_all.py`, and the uv-run tools under
  `scripts/`) use the PEP 723 shebang
  `#!/usr/bin/env -S uv run --script --exact` with inline dependency
  declarations. `--exact` departs from the shared convention on purpose: `uv`
  keeps one cached environment per script and by default only ever adds to it,
  so a dependency dropped from a script's block stays installed. A dropped
  pytest plugin, for one, still loads itself into every later run. `--exact`
  removes whatever the block no longer declares, and
  `tests/test_analysis_deps.py` gates the form.

- **Anything that runs where `uv` is absent** uses plain
  `#!/usr/bin/env python3` with stdlib-only imports (or imports HA provides):
  the Docker harness helpers under `tests/docker/_harness/`, the host-side
  `scripts/ha_ws_fetch.py`, the bundled CLI, and
  `custom_components/blueprint_toolkit/scripts/dev-install.py`.

  That shebang is load-bearing. `tests/test_analysis_deps.py` reads it as the
  marker for code that runs on an interpreter this repo does not choose, and
  parses every file carrying it at the shipped floor (see "Two interpreter
  floors, and neither is this machine's"). A new host-side helper is covered
  the moment it gets the shebang.

  Two scripts carry it while still running here on the pinned interpreter, so
  the test exempts them by name. An exemption has a cost worth understanding
  before adding a third: the file is still *formatted* at `target-version`,
  but nothing then checks it against the interpreter it runs on, so it can
  acquire syntax its `python3` cannot parse.

- **Module files** (handler.py, logic.py, helpers.py, etc.) have no shebang.
  Those under `custom_components/` are covered by the floor check regardless,
  since Home Assistant imports them.

### Test files

`tests/run_all.py` runs each `tests/test_*.py` as a subprocess and passes it
`--verbose` / `--coverage`, so every test file is executable (`chmod +x`) and
ends with the block that hands those flags to pytest:

```python
if __name__ == "__main__":
    from conftest import run_tests

    run_tests(__file__, _SCRIPT_PATH, REPO_ROOT)
```

`_SCRIPT_PATH` names the code under test, which `--coverage` measures. A file
that always needs a pytest option passes it as `pytest_args=`, as the files
that stub the `homeassistant` modules do with `-p no:homeassistant`.
`tests/test_run_all.py` gates that every discovered file ends with this call.

`tests/docker/test_dev_workflow.py` is the exception: its standalone entry
point calls `pytest.main()` directly so it can force the otherwise excluded
`docker` marker and select the Docker test path.

## Doc-sync rule

A doc that describes code changes in the same commit as that code (the shared
"Update relevant docs" rule). The docs this repo keeps:

- `bundled/docs/<service>.md` -- when an automation's inputs, attributes, or
  behavior change. Re-run `scripts/render_docs.py`; the drift test
  (`tests/test_docs_rendered.py`) enforces the markdown + HTML pair.
- `AUTOMATIONS.md` -- when conventions, shared helpers, naming rules, or
  per-automation file layout change.
- `DEVELOPMENT.md` -- when dev-process tooling changes: test conventions, lint
  rules, required steps in the develop / test / commit cycle, or the workflow
  of `dev-deploy.py`, `dev-install.py`, `release.py`, or `hacc_upgrade.py`.
- `DEVELOPMENT_AGENT.md` -- when agent-specific workflow changes (file
  markers, the dev-deploy verification checklist, etc.).
- `README.md` -- when an automation is added, removed, or its one-line blurb
  changes.

## Per-automation docs

The per-automation user-doc structure lives in `AUTOMATIONS.md`. This section
covers the rendering pipeline.

### Rendered HTML

The markdown sources are rendered to HTML that ships alongside the integration
so HACS users can click a "Full documentation" link from each blueprint
directly to a local page.

- Source: `custom_components/blueprint_toolkit/bundled/docs/*.md` (also
  reachable via the `docs/` symlink at the repo root).
- Rendered:
  `custom_components/blueprint_toolkit/bundled/www/blueprint_toolkit/docs/*.html`.
  Committed alongside the source.
- Renderer: `scripts/render_docs.py`. After editing any `*.md`, re-run it and
  commit the regenerated HTML in the same commit.

`tests/test_docs_rendered.py` fails if the committed HTML is out of date, if a
markdown source is missing its HTML counterpart, or if an orphan HTML has no
matching source.

#### How rendered HTML reaches the user's browser

The rendered HTML is **not** installed under `/config/www/`. HA's default
`/local/` static handler is only registered at startup if `/config/www/`
already exists (our integration runs after that), and it refuses to follow
symlinks whose targets escape `/config/www/`, which an installed
symlink-into-bundled would do.

Instead, the integration's `async_setup_entry` registers its own aiohttp
static route at `/local/blueprint_toolkit/docs/` pointing directly at the
bundled docs directory.

**dev-install limitation**: users on the `scripts/dev-install.py` path don't
load the HA integration, so the static route is never registered and the
blueprints' `/local/.../docs/...html` links 404. Read the markdown sources
under `bundled/docs/` directly during dev work.

## Markdown style

`DEVELOPMENT_SHARED.md` owns the tooling and conventions. This repo differs in
one way: it wraps at 78 columns rather than 79
(`[tool.repo-shared.markdown] wrap` in `pyproject.toml`), so re-canonicalise a
doc with:

```bash
uvx --with mdformat-gfm --with mdformat-frontmatter \
    mdformat --wrap=78 --number <path>
```

The shared bases under `_repo_shared/tests/` gate `mdformat` and
`markdownlint-cli2`. `.markdownlint.json` is a symlink into
`_repo_shared/dotfiles/`; the shared markdown infra is adopted as-is.

## Testing

### Running tests

```bash
# All tests (fast, mock-based)
./tests/run_all.py
./tests/run_all.py --verbose
./tests/run_all.py --coverage

# Single test file; other arguments pass through to pytest
./tests/test_<service>_logic.py
./tests/test_<service>_logic.py --verbose
./tests/test_<service>_logic.py -k <pattern>

# Shared suite only
uv run pytest _repo_shared/tests
```

`./tests/run_all.py` runs the shared suite at the end of its per-handler
sweep, and a bare `uv run pytest` runs both this repo's tests and the shared
suite.

### Docker test harness (opt-in, slow)

`tests/docker/` spins up a real HA container and exercises
`scripts/dev-install.py` and `scripts/dev-deploy.py` end-to-end. It is not run
by `tests/run_all.py`; see `tests/docker/README.md`.

### pytest-homeassistant-custom-component harness

`tests/test_hacc_harness.py` uses
[`pytest-homeassistant-custom-component`](https://pypi.org/project/pytest-homeassistant-custom-component/)
(HACC) to stand up an in-process HA instance. `tests/test_integration.py` and
the per-automation `tests/test_<service>_integration.py` files use the same
harness to exercise the integration's async lifecycle and each handler's full
call path. All of them run in the default suite; the first run downloads HA
into a uv-script env (about a minute), and later runs are cached.

The HACC pin is exact, so the suite won't notice a future HA release breaking
an interface we depend on until the pin moves. `scripts/hacc_upgrade.py` moves
it and verifies the suite against the bump in a throwaway worktree; its module
docstring covers the flow, and `--help` the flags and exit statuses.

```bash
scripts/hacc_upgrade.py --dry-run    # report drift, change nothing
scripts/hacc_upgrade.py              # build + verify, leave on its branch
scripts/hacc_upgrade.py --push       # ... and land it on green
scripts/hacc_upgrade.py --to X.Y.Z   # target a version other than latest
scripts/hacc_upgrade.py --base REF   # verify on REF, not the default branch
```

A red suite blocks the bump and keeps the worktree for inspection. The failing
phase is a reasonable first look -- most phases install the pin themselves,
which makes the new release the first thing to check there, though those
blocks also resolve `pytest` and the stubs unpinned -- but the `repo-shared`
phase does not localize at all, since it carries both the HA-typed mypy pass
and the markdown gate.

`--base` handles a bump that only passes with code changes landing beside it.
When a Home Assistant release removes an API the integration uses, the
migration and the pin are each red without the other, so point `--base` at the
branch carrying the migration. Such a run verifies only, and the result is
merged by hand. Two things to know about the handoff:

- The base is taken as a committed ref, so commit any work still sitting in
  the checkout first.
- The verified bump is left on a `hacc-upgrade/<version>` branch, the
  namespace every later run sweeps. Merge it before the next run, or pass it
  as the next run's `--base`, which spares its ref (not its worktree). Only
  refs at the base commit are spared, so a second pending bump in that
  namespace is swept either way. A base that *is* the branch the next run
  rebuilds is refused rather than clobbered; merge or rename it first.

The `--push` form is built to run unattended, so it can be run from a
scheduler. The repo carries no schedule of its own. A scheduled run has a few
requirements and consequences:

- It runs the whole suite, so the host needs `uv` and, for the markdown gate's
  `markdownlint-cli2`, `npx`. A scheduler's environment is not a login shell,
  so the job has to put them on `PATH` itself. Missing tooling blocks every
  bump the same way, with nothing pointing at the host.
- Silence is ambiguous: "no drift" and "the job never ran" look identical from
  the repo. A pin that stops moving for a long stretch is worth checking
  against PyPI by hand.
- The bump is verified on the host that runs it, not across the `test.yml`
  matrix. `test.yml` runs on push, so a landed bump gets the full matrix
  immediately afterward.
- A scheduled `--push` is the one push in the repo not gated on a human. The
  shared "never push without approval" rule addresses agent sessions, which
  must still ask; it does not govern such a job.

### The interpreter is pinned too

`.python-version` pins the interpreter `uv` resolves against: every PEP 723
script env, the project venv the `repo-shared` phase runs `pytest` in, the
`uvx` gate tools, and the throwaway environment `scripts/hacc_upgrade.py`
resolves the Z-Wave client requirement in (which is why that call runs from
the repo root). Without it `uv` selects the newest interpreter installed, so a
host that gains a newer Python silently changes environment. Home Assistant's
native dependencies publish no wheels for a brand-new release, so such a host
builds them from source and most phases fail at once, with a compiler error
that doesn't mention the interpreter.

Cached envs hide a moved pin, because only a *fresh* resolution picks the new
interpreter: an existing checkout keeps passing while a new worktree, a new
machine, or CI fails. `uv` also ignores a pin it cannot satisfy and resolves
against the newest interpreter anyway, exiting zero, so
`tests/test_analysis_deps.py` gates the pin against every declared
`requires-python` floor and the two mypy knobs. Raise it deliberately when the
project moves to a newer Python, and expect the first run afterwards to
rebuild every script env.

The pin governs this machine's analysis and test environments only. The
host-side scripts carry plain `python3` shebangs and never see `uv`.

### Two interpreter floors, and neither is this machine's

What the code has to RUN on is a separate declaration,
`[tool.ha-blueprint-toolkit] shipped-python-version`. Its comment in
`pyproject.toml` explains the two interpreters it answers to -- Home
Assistant's own, which imports the integration modules, and the Terminal & SSH
add-on's, which runs the bundled CLI and `dev-install.py` -- and carries the
checklist for raising it.

The add-on is the binding one, and the invisible one: nothing declared here
can constrain it. `ruff format` rewrites to its `target-version` -- at `py314`
a parenthesized multi-type `except` becomes the PEP 758 unparenthesized form
-- so that knob decides which syntax gets written into the bundled CLI and the
`zwave/` + `zwave_parameter_manager/` modules it shares with the HA side. So
`target-version` is gated against `shipped-python-version`, never against
`.python-version`, which is free to move ahead of it.

`tests/test_analysis_deps.py` also parses every off-machine source -- all of
`custom_components/` plus the plain-`python3` host helpers -- at the declared
floor. That constrains the grammar, the half the formatter moves. Semantics
are not covered: a newer stdlib call, or an annotation that resolves only
under deferred evaluation, parses clean and fails later or not at all. That is
safe only while the declared floor really is the lowest interpreter in play,
which is why the floor is read off those two platforms rather than chosen
here, and why it only ever rises. Every `requires-python` in the repo must sit
at or above it.

An add-on image below the floor does not refuse politely: the CLI dies on a
`SyntaxError` before any statement in `zwavectl.py` runs, so the CLI cannot
guard against it. `docs/zwavectl.md` states the add-on requirement where the
`apks` list is configured, because that is where a user can act on it, and it
is the whole of the warning.

### Manifest version bump rule

The integration version in `custom_components/blueprint_toolkit/manifest.json`
must increment with every commit that changes anything under
`custom_components/`, and stay equal otherwise. `tests/test_manifest.py`
enforces both this rule and the canonical formatting.

Before committing any change under `custom_components/`, bump the patch:

```bash
scripts/bump-manifest-version.py
```

The script rewrites `manifest.json` and re-stages it. For a deliberate minor
or major graduation, edit the manifest by hand instead -- the test only checks
that the version is strictly greater than the parent's.

### Releasing (tag + GitHub release)

HACS shows only GitHub Releases as version candidates, so commits pushed to
main are invisible to users until the next Release is published. Tagging and
releasing are kept separate from `git push` so a manifest bump can sit on main
without auto-publishing -- run `scripts/release.py` only when you want HACS
users to see the new version:

```bash
git push                       # land commits on origin
scripts/release.py             # then publish the version at HEAD
scripts/release.py --dry-run   # see what it would do
```

The script reads the version from HEAD's `manifest.json`, creates the local
annotated tag `vX.Y.Z` if missing, pushes the tag, and creates the GitHub
release via `gh` (release notes default to HEAD's commit body). Each step is
idempotent, so re-running after a partial failure picks up where the previous
run stopped. It refuses if HEAD isn't reachable from `origin/main`, and exits
cleanly without a duplicate release when HEAD is a non-bumping commit whose
version is already tagged.

### Code quality

Lint, format, and type checks run as the parametrized
`_repo_shared/tests/test_code_quality.py` suite, one case per discovered `.py`
file. For a single file, use
`pytest _repo_shared/tests/test_code_quality.py -k <path/to/file>`. Ruff also
runs standalone (`uvx ruff check .`, `uvx ruff format .`); bare `uvx mypy`
cannot resolve `homeassistant.*` without HA installed.

Ruff follows the current default rules and keeps the canonical `E`, `F`, `W`,
`I`, `B`, `UP`, and `ARG` categories enabled through
`[tool.ruff.lint] extend-select`. The vendored `_repo_shared` tree is
excluded; the shared drift test covers its exact content.

Prefer fixing a rule's complaint over adding a
`[tool.ruff.lint.per-file-ignores]` entry; the existing entries carry their
reasons in `pyproject.toml`. Suppress a one-off inline with
`# noqa: <rule> - <reason>`, as `scripts/zwave_db_extract.py` does.

mypy `--strict` deps come from each file's PEP 723 `# /// script` block when
present, otherwise from `[tool.repo-shared.code-quality] mypy-extra-deps` in
`pyproject.toml`. Per-file blocks are kept only where a file needs more than
the fallback -- e.g. the HACC test files under `tests/` add `pytest` /
`pytest-cov`. Other files fall through to plain `mypy --strict` in the project
venv; `pyproject.toml`'s `[[tool.mypy.overrides]]` covers transitive imports a
checkout may not have installed.

**Nothing under `custom_components/` carries a PEP 723 block.** The
integration modules there are imported by Home Assistant, which runs them on
its own interpreter against the packages it installed, so a dependency pin
written beside them describes a dev-machine analysis environment the shipped
code never resolves. They take the fallback instead, and
`tests/test_analysis_deps.py` gates the rule.

The bundled CLI under `bundled/bin/` ships through the same tree but runs
outside Home Assistant, on a plain `python3` with a venv it bootstraps itself,
so its `VENV_DEPS` list is a genuine runtime dependency set rather than an
analysis one. It pins `zwave-js-server-python` to the version the fallback
names, because the integration modules it imports are only type-checked
against that one.

#### Analysis-dep pinning and stub suppressions

The three kinds of analysis dep are pinned on different policies, and the
differences are deliberate. The comment on `mypy-extra-deps` in
`pyproject.toml` carries the reasoning.

- **`pytest-homeassistant-custom-component`** is an exact pin that decides
  which HA API surface the code type-checks against. `scripts/hacc_upgrade.py`
  owns bumping it; don't move it by hand. The pin says what the code is
  *validated* against, not what users run: `hacs.json` declares the supported
  HA floor.
- **`zwave-js-server-python`** is an exact pin whose value is derived: it has
  to be whatever HA's `zwave_js` component requires at the pinned release, or
  every Z-Wave phase dies in collection on a missing name that points at the
  library rather than the pin. `hacc_upgrade.py` reads it out of the release
  and rewrites every site in the same commit, stopping rather than guessing if
  the sites already disagree. One site is the bundled CLI's runtime list, so
  that rewrite changes shipped code and also bumps the integration version.
- **Type stubs** (`types-PyYAML`) are unpinned at every site, so every run
  resolves whatever typeshed published last. "Latest" is the only
  configuration the checks have to satisfy, at the cost that a typeshed
  release can turn CI red on an unrelated change.

Two rules keep the pins honest. Neither this section nor `pyproject.toml`
names a pinned version in prose, because automation moves the literal and
prose would not follow. And every declaration site must name the *same*
version: `hacc_upgrade.py` only rewrites sites carrying the version it is
replacing, so a site that has drifted to a third version is invisible to it.
`tests/test_analysis_deps.py` gates that agreement separately.

When a stub release annotates something previously bare, the
`# type: ignore[...]` guarding it becomes an unused ignore and `--strict`
fails. **Fix that by deleting the suppression**, not by pairing it with
`unused-ignore`: no configured run selects the older release, and a
suppression that outlives its condition describes the stubs as they were.

The `[<code>,unused-ignore]` pairs under `custom_components/` are the other
case. Those guard Home Assistant's own stubs, which arrive with the *pinned*
HACC dep and change only when that pin is bumped, so the pairing lets a bump
land without breaking the build.

## HA deployment testing

Two scripts move local edits onto a running HA host for iterative dev work:
`scripts/dev-deploy.py` (run from the dev machine) and
`scripts/dev-install.py` (run on the HA host, invoked by `dev-deploy.py`).
End-user installs go through HACS instead. Each script's module docstring
covers how it works, and `--help` its flags.

### `scripts/dev-deploy.py` (dev-machine side)

Builds a fresh timestamped copy of the integration on the HA host, flips
`/config/custom_components/blueprint_toolkit` to it, and restarts HA. The
first run preserves the HACS-installed integration, and `--restore` reinstates
it, leaving the host as if dev-deploy had never run.

HA is **always restarted** after a deploy or restore: integration code changes
need a Python-level reload the config-entry reload API doesn't provide. The
working tree must be clean unless you pass `--allow-dirty`, which is for
iterative dev only.

### `scripts/dev-install.py` (HA-host side)

Plain Python (no uv). Reconciles the bundled payload beside it into
`/config/blueprints/` (and optionally `<cli-symlink-dir>/`) as symlinks
pointing back into the bundled subtree. It is idempotent: any symlink whose
target contains `/custom_components/blueprint_toolkit/bundled/` counts as
ours, stale ones from renamed or removed bundled files get swept, and it
refuses to overwrite regular files. It can also be run directly on the host
during debugging.

It cannot filter by what git tracks: it runs against a payload already copied
to the host, with no repository to consult. Selecting tracked content is
`dev-deploy.py`'s job (`git ls-files`), so the reconciler screens the payload
by name as well -- see "macOS sidecars in a shipped payload" below.

### macOS sidecars in a shipped payload

macOS `tar` writes a file's extended attributes into an extra `._<name>`
AppleDouble member, and every file in a macOS checkout carries at least
`com.apple.provenance`. Two properties make that easy to miss:

- Apple's `tar` merges those members back when reading, so `tar -tf` shows a
  clean archive locally, while the host's `tar` writes them out as ordinary
  files.
- A sidecar keeps the real file's extension, and Home Assistant's blueprint
  scan is `glob("**/*.yaml")`, which matches a leading dot -- so HA tries to
  parse an AppleDouble blob as a blueprint.

Two guards, because they fail differently. `dev-deploy.py` sets
`COPYFILE_DISABLE=1` for the shipping `tar`, which keeps sidecars out at the
source; `tests/test_dev_deploy.py` reads the stream with `tarfile` so the
check sees what the host would. And `reconciler.py` skips `._*` wherever it
discovers a source by extension, which covers a payload that arrived by
another route and sweeps sidecars a previous deploy already installed.

`.gitignore` here is a shared template, so an ignore rule for `._*` belongs
upstream in `repo-shared` rather than as a local divergence.

### Reading state from a deployed instance

Each blueprint-backed automation writes a diagnostic state entity on every
successful run with `last_run`, `runtime`, and per-automation attributes. The
entity ID lives under `blueprint_toolkit.<service_tag>_<slug>_state`:

```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  http://$HA_HOST:8123/api/states/blueprint_toolkit.<service_tag>_<slug>_state
```

Persistent notifications aren't exposed as `/api/states` entities in HA
2026.4+; fetch them via the websocket `persistent_notification/get` command.
`scripts/ha_ws_fetch.py` wraps that handshake -- a plain-`python3` (no-uv)
helper meant to run on the HA host (see `DEVELOPMENT_AGENT.md` "Reaching the
HA API").

## Commit messages

Don't restate the manifest version bump in the commit message; the bump is
automatic and restating is noise.
