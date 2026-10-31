# zwavectl

## Summary

Z-Wave CLI for the HA host. `zwavectl list` shows the mesh as a per-node
table, and `zwavectl param-manager` plans and applies the Z-Wave Parameter
Manager policy file from the command line. It ships with the integration and
self-bootstraps a venv on first run.

## Requirements

- The **Terminal & SSH** add-on, configured to install `python3`, `py3-pip`,
  and `py3-websockets`. Add them to the add-on's `apks` option (its
  Configuration tab) so they persist across add-on restarts:

  ```yaml
  apks:
    - python3
    - py3-pip
    - py3-websockets
  ```

- That `python3` must be 3.14 or newer, which the add-on's Alpine base
  provides from Alpine 3.24 on. zwavectl runs on the add-on's interpreter
  rather than Home Assistant's, so keep the add-on updated alongside Home
  Assistant. On an older image the CLI does not start: it exits with a
  `SyntaxError` naming one of its own source lines, which is the symptom of
  too old a `python3` rather than a broken install. Check `python3 --version`
  in the add-on's terminal before looking anywhere else.

- An HA token: enable the integration's **Provision a CLI access token**
  option (see below) or pass `--api-key-file <path>`.

## Usage

Both options live in the integration's **Configure** dialog.

**CLI symlink directory** symlinks the bundled `zwavectl.py` into a directory
on your shell's `$PATH`, as `zwavectl` without the extension. The path must be
writable by the Home Assistant process. On Home Assistant OS and Supervised
installs, the integration runs in its own container -- only paths under shared
mounts (`/config`, `/share`, `/media`, `/backup`, `/ssl`, `/addons`,
`/addon_configs`) are visible from the SSH add-on; e.g. `/config` is a safe
default. On Home Assistant Container or Core (no Supervisor), any path the HA
process can write to works. Leave blank to skip.

**Provision a CLI access token** mints a long-lived HA token for `zwavectl`
and writes it to `/config/blueprint_toolkit/cli_token`, revoking and deleting
it when you turn the option off. It is full-access and lands in HA backups, so
it is off by default.

`zwavectl list --help` and `zwavectl param-manager desired --help` give each
command's column list and aliases.

## Usage notes

### `zwavectl list`

A tabular per-node view of the mesh: protocol (Mesh/LR), signal-strength
quality, configured priority routes, and opt-in stat columns (RX/TX counts,
drop counts, drop rates, RTT, battery, status, neighbors, firmware, etc.).
Historical columns pull from HA's recorder; current state comes from
zwave-js-ui.

### `zwavectl param-manager`

`zwavectl param-manager {desired|pending|unused}` plans the live fleet against
the Z-Wave Parameter Manager policy file (the same one the blueprint uses;
override with `--config`) and prints the writes a policy resolves (`desired`),
the not-yet-converged subset (`pending`), or the policies / settings that
matched no device (`unused`). `--cols` reshapes the table (units, the device
parameter identity, wake timing, and more are opt-in, with `defaults` / `all`
aliases).

Each row shows the policy's `desired` value next to the device's `dev-current`
and `dev-pending` values. A row has converged when `dev-current` equals
`dev-pending`. `desired` is the device-agnostic concept value the policy set,
which the resolver maps onto each device's own parameter range, so it
legitimately differs from the device columns on a converged row (a 1-10
sensitivity of 8 resolving to 6 where the range is 1-8).

`zwavectl param-manager apply` issues those writes to the devices (`--dry-run`
previews, `--force` re-issues regardless of what is already pending). It
shares the automation's pending store, so the two never re-queue a command the
other already sent.
