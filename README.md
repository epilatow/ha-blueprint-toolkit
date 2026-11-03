# Blueprint Toolkit

Home Assistant automations built as HA blueprints. Most dispatch to a custom
integration's service handlers, with business logic in Python modules that
carry no Home Assistant dependencies and are fully testable with pytest. A few
are standalone -- self-contained YAML blueprints with no service handler.

## Automations

- [Sensor Threshold Entity Controller][stec] - Controls switch-like entities
  based on sensor value spikes (e.g., humidity for a bathroom fan), with
  manual override protection and an auto-off timer.

- [Device Watchdog](docs/device_watchdog.md) - Monitors device health across
  integrations, flagging unavailable or stale devices and offering one-click
  Repairs for disabled diagnostic entities.

- [Battery Watchdog](docs/battery_watchdog.md) - Lists every low battery in
  one notification, with its area, a link to its device, and a link to the
  battery's history.

- [Entity Defaults Watchdog](docs/entity_defaults_watchdog.md) - Detects
  entity IDs, entity names, and script keys that have drifted from their
  defaults, plus `switch_as_x` sources left visible, with one-click Repairs
  for the fixes that are deterministic.

- [Trigger Entity Controller](docs/trigger_entity_controller.md) - Controls
  entities with optional trigger-based activation, an auto-off timer, and
  time-of-day gating.

- [Reference Watchdog](docs/reference_watchdog.md) - Scans HA config for
  broken entity and device references, and for registry entries whose backing
  source has been removed.

- [Z-Wave Route Manager](docs/zwave_route_manager.md) - Reconciles Z-Wave
  priority routes against a declarative YAML config file. Requires the
  `core_zwave_js` addon.

- [Z-Wave Parameter Manager](docs/zwave_parameter_manager.md) - Keeps each
  Z-Wave node's settable config parameters aligned with a declarative policy
  file. Requires the Z-Wave JS integration.

- [Trigger Alert Controller](docs/trigger_alert_controller.md) - Responds when
  a binary sensor turns on (water leak, smoke, an open door, etc.) with a
  notification, then a siren and/or repeated notifications until it clears.

## Scripts

- [zwavectl](docs/zwavectl.md) - Z-Wave CLI for the HA host: a per-node view
  of the mesh, plus planning and applying Z-Wave Parameter Manager policies
  from the command line.

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
   **Blueprint Toolkit**. The integration installs the bundled blueprints into
   your `/config/` directory and serves their documentation.

5. Go to **Settings > Automations & Scenes > Blueprints** to create
   automations from the installed blueprints.

To use `zwavectl`, see its [setup instructions](docs/zwavectl.md#usage).

## Development

See [Development Guide](DEVELOPMENT.md) for architecture, coding conventions,
and testing instructions.

[stec]: docs/sensor_threshold_entity_controller.md
