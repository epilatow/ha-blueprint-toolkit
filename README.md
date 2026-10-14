# Blueprint Toolkit

Home Assistant automations built as HA blueprints. Most dispatch to a custom
integration's service handlers, with business logic in Python modules that
carry no Home Assistant dependencies and are fully testable with pytest. A few
are standalone -- self-contained YAML blueprints with no service handler.

## Automations

- [Sensor Threshold Entity Controller][stec] - Controls a switch based on
  sensor value spikes (e.g., humidity for a bathroom fan). Includes manual
  override protection, double-off disable, and auto-off timer.

- [Device Watchdog](docs/device_watchdog.md) - Monitors device health across
  integrations. Raises persistent notifications for unavailable or stale
  devices and surfaces disabled diagnostic entities as one-click HA Repairs;
  notifications + repairs auto-clear when devices recover.

- [Entity Defaults Watchdog](docs/entity_defaults_watchdog.md) - Detects
  entity IDs and names that have drifted from their defaults, switch_as_x
  source entities left visible, and scripts whose YAML block key no longer
  matches their entity id. Per-device notifications carry repair instructions;
  entity-ID drift, entity-name drift, visible aliased sources, and script
  YAML-key drift additionally surface as one-click HA Repairs (rename / reset
  the entity, re-hide the source, or rename the script block key). Most
  notifications + repairs auto-clear when the finding is resolved.

- [Trigger Entity Controller](docs/trigger_entity_controller.md) - Controls
  entities (lights, switches, fans, etc.) with optional trigger-based
  activation and auto-off timer. Supports time-of-day gating, trigger
  disabling, force-on, and configurable notifications.

- [Reference Watchdog](docs/reference_watchdog.md) - Scans HA config (YAML
  includes and `.storage` JSON) for broken entity and device references.
  Per-owner persistent notifications with clickable links into the HA config
  UI where available, YAML-only helper marking, and a negative service-name
  truth set to eliminate false positives. Also detects source orphans --
  registry entries whose backing YAML block or UI-helper record has been
  removed -- and lists them in a single summary notification for cleanup.

- [Z-Wave Route Manager](docs/zwave_route_manager.md) - Reconciles Z-Wave
  priority routes against a declarative YAML config file. Reconciles on HA
  startup, on manual trigger, when the YAML config is edited, and periodically
  (default every 5 minutes) to catch out-of-band route changes. Failed
  reconciles retry automatically on the next minute-granularity tick.
  Auto-resolves route speed to the slowest hop's `maxDataRate`. Optional
  clear-unmanaged mode makes the config file the single source of truth.
  Requires the `core_zwave_js` addon.

- [Z-Wave Parameter Manager](docs/zwave_parameter_manager.md) - Keeps each
  Z-Wave node's settable config parameters aligned with a declarative policy
  file. Policies match devices by manufacturer / model / power / type and set
  device-agnostic concepts (motion sensitivity, wake interval, etc.); the
  resolver maps each concept onto the device's real parameter. Runs in-process
  through the Z-Wave JS integration. Issues each write at most once per
  pending cycle and reports devices still waiting to apply (queued until a
  sleeping device next wakes). Requires the Z-Wave JS integration.

- [Trigger Alert Controller](docs/trigger_alert_controller.md) - Responds when
  any of a set of binary sensors turns on (water leak, smoke, an open door,
  etc.): a one-time initial notification, then a siren and/or repeated
  notifications on an interval until every sensor is off. A configurable alert
  name labels the notification body, and optional presence gating keeps an
  empty house quiet. A standalone YAML-only blueprint with no service handler.

## Scripts

Standalone diagnostic and inspection tools that ship alongside the
automations. Live in the bundled payload and run from the HA host.

- [zwavectl][zc] - Z-Wave CLI for the HA host. `zwavectl list` gives a tabular
  per-node view of the mesh: protocol (Mesh/LR), signal-strength quality,
  configured priority routes, and opt-in stat columns (RX/TX counts, drop
  counts, drop rates, RTT, battery, status, neighbors, firmware, etc.).
  Historical columns pull from HA's recorder; current state comes from
  zwave-js-ui. `zwavectl param-manager {desired|pending|unused}` plans the
  live fleet against the Z-Wave Parameter Manager policy file (the same one
  the blueprint uses; override with `--config`) and prints the writes a policy
  resolves (`desired`), the not-yet-converged subset (`pending`), or the
  policies / settings that matched no device (`unused`). Each row shows the
  policy's `desired` value next to the device's `dev-current` and
  `dev-pending` values; `--cols` reshapes the table (units, the device
  parameter identity, wake timing, and more are opt-in, with `defaults` /
  `all` aliases). `zwavectl param-manager apply` issues those writes to the
  devices (`--dry-run` previews, `--force` re-issues regardless of what is
  already pending); it shares the automation's pending store, so the two never
  re-queue a command the other already sent. Self-bootstraps a venv on first
  run; see `zwavectl list --help` and `zwavectl param-manager desired --help`
  for each command's column list and aliases. Host requirements: the
  **Terminal & SSH** add-on must be installed and configured to install
  `python3`, `py3-pip`, and `py3-websockets` -- add them to the add-on's
  `apks` option (its Configuration tab) so they persist across add-on
  restarts:

  ```yaml
  apks:
    - python3
    - py3-pip
    - py3-websockets
  ```

  That `python3` must be 3.14 or newer, which the add-on's Alpine base
  provides from Alpine 3.24 on. zwavectl runs on the add-on's interpreter
  rather than Home Assistant's, so keep the add-on updated alongside Home
  Assistant. On an older image the CLI does not start: it exits with a
  `SyntaxError` naming one of its own source lines, which is the symptom of
  too old a `python3` rather than a broken install. Check `python3 --version`
  in the add-on's terminal before looking anywhere else.

  zwavectl also needs an HA token -- enable the integration's **Provision a
  CLI access token** option (writes `/config/blueprint_toolkit/cli_token`) or
  pass `--api-key-file <path>`.

## Prerequisites

- Home Assistant 2026.10 or newer
- Python 3.14+
- [uv](https://docs.astral.sh/uv/) (for development)

## Installation

1. In Home Assistant, go to HACS, then the menu in the top right and choose
   **Custom repositories**. Add this repo's URL with the **Integration** type.

2. Find **Blueprint Toolkit** in HACS and click **Download**.

3. Restart Home Assistant.

4. Go to **Settings > Devices & Services > Add Integration** and add
   **Blueprint Toolkit**. The integration installs the bundled blueprints and
   rendered docs into your `/config/` directory.

5. Optionally, open the integration's **Configure** dialog to set **CLI
   symlink directory** if you want the `zwavectl` shell tool symlinked into a
   directory on your shell's `$PATH` (the bundled `zwavectl.py` installs under
   that directory as `zwavectl`, without the extension). The path must be
   writable by the Home Assistant process. On Home Assistant OS and Supervised
   installs, the integration runs in its own container -- only paths under
   shared mounts (`/config`, `/share`, `/media`, `/backup`, `/ssl`, `/addons`,
   `/addon_configs`) are visible from the SSH add-on; e.g. `/config` is a safe
   default. On Home Assistant Container or Core (no Supervisor), any path the
   HA process can write to works. Leave blank to skip. The same dialog has a
   **Provision a CLI access token** toggle: enable it to mint a long-lived HA
   token for `zwavectl` and write it to `/config/blueprint_toolkit/cli_token`
   (revoked + deleted when you turn it off). It is full-access and lands in HA
   backups, so it is off by default.

6. Go to **Settings > Automations & Scenes > Blueprints** to create
   automations from the installed blueprints.

## Development

See [Development Guide](DEVELOPMENT.md) for architecture, coding conventions,
and testing instructions.

[stec]: docs/sensor_threshold_entity_controller.md
[zc]: custom_components/blueprint_toolkit/bundled/bin/zwavectl.py
