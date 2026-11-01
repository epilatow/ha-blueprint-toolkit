# Device Watchdog

## Summary

Monitors device health across Home Assistant integrations. Raises a persistent
notification whenever monitored devices have unavailable entities or stop
reporting state within a configurable window. Clears notifications
automatically when devices recover.

## Features

- Monitor devices across multiple integrations (Z-Wave, Matter, BLE, Shelly,
  etc.)
- Detect unavailable or unknown entity states
- Detect stale devices (no state report within threshold)
- Per-device persistent notifications with auto-clear on recovery
- Include/exclude integration filtering (empty include means all integrations)
- Regex-based device and entity exclusion filters
- Configurable entity domain filtering
- Configurable check interval and staleness threshold
- Notification cap to limit per-device notifications
- Diagnostic entity check: notifies when recommended diagnostic entities are
  disabled (for Z-Wave JS: Last seen, Node status, Signal strength, Battery
  level, plus the per-node network-health statistics -- round trip time,
  successful / dropped commands, timed-out responses)
- Per-check selection so exclusion lists can be scoped per check (instantiate
  the blueprint once per check)
- Optional debug logging

## Requirements

None.

## Usage

1. Install the automation (see main README)
2. Go to **Settings > Automations & Scenes > Blueprints**
3. Click **Device Watchdog**
4. Configure integrations and thresholds
5. Save and enable

## Configuration

| Parameter                             | Description                                                                                                                                                             |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Include integrations                  | Integration IDs to monitor. Empty means all.                                                                                                                            |
| Exclude integrations                  | Integration IDs to skip even if included. Also skips every device they have an entity on, including entities another integration adds, such as a `switch_as_x` wrapper. |
| Device name exclude regex             | Skip devices whose name matches. One pattern per line.                                                                                                                  |
| Entity ID exclude regex               | Skip entities whose ID matches. One pattern per line.                                                                                                                   |
| Monitored entity domains              | Only check entities in these domains                                                                                                                                    |
| Check interval (minutes)              | Minutes between watchdog evaluations                                                                                                                                    |
| Dead device threshold (minutes)       | Staleness threshold for state reports                                                                                                                                   |
| Enabled checks                        | Which checks to run (`unavailable-entities`, `device-updates`, `disabled-diagnostics`). Empty means all.                                                                |
| Max device notifications              | Cap on per-device notifications. Default 10. 0 = unlimited.                                                                                                             |
| Create repairs for fixable findings   | Default on. Routes disabled-diagnostic-entity findings to HA's Repairs UI as one-click Fix issues instead of persistent notifications. See **Repairs** below.           |
| Max repairs                           | Cap on per-run repair issues. Default 5. 0 = unlimited. Applies only when **Create repairs** is on.                                                                     |
| Validate include / exclude directives | Default on. Surface typo'd integrations or stale regex lines as a single informational notification. See **Unmatched include / exclude directives** below.              |
| Debug Logging                         | Log debug info to HA logs                                                                                                                                               |

See the blueprint UI for default values.

## Usage notes

### Notifications

Each device with health issues gets its own persistent notification. Every
notification leads with an attribution header -- the automation that emitted
it, the device's integration(s), and a link to the device -- so you can click
straight through to the source. Notifications are automatically dismissed when
devices recover.

### Unmatched include / exclude directives

With **Validate include / exclude directives** on (default), any include /
exclude entry that matches nothing in the live scan -- a typo'd integration
like `zwavejs` instead of `zwave_js`, or a regex line that catches no current
device or entity -- appears in a single informational notification. It clears
on the next scan once the entry is fixed or removed, or when you turn the
toggle off.

### Repairs

When **Create repairs for fixable findings** is enabled (default), each
disabled-recommended-diagnostic-entity finding surfaces as an HA Repair with a
one-click Fix button instead of a notification. Submit clears `disabled_by` on
the named entity so it goes back to monitoring. The Fix dialog leads with the
same attribution header the notifications carry -- the automation, the
device's integration(s), and a link to the device.

Other finding categories (unavailable / stale devices) keep using
notifications regardless of the toggle -- those don't have a deterministic
single-click fix.

**Clearing a finding.** A repair or notification stays until its finding is
fixed or excluded. Once the device recovers or the entity is re-enabled, or
**Exclude integrations**, **Device name exclude regex**, or **Entity ID
exclude regex** covers the finding, the next scan removes it. HA's **Ignore**
on a repair and dismissing a notification don't clear the finding, so either
one comes back on the next scan.

**Cap.** Repairs can't be dismissed in bulk in HA's UI, so **Max repairs**
limits the per-run issue count (default 5; 0 = unlimited). Findings over the
cap are counted in a single summary notification; raise the cap, or fix or
exclude the visible issues, to surface more.

Disable **Create repairs** to keep notification-only behavior on this
instance.

## Developer notes

### Entity attributes

After each evaluation, attributes are written to
`blueprint_toolkit.dw_<slug>_state` where `<slug>` derives from the automation
entity_id. Search for `blueprint_toolkit.dw_*_state` in Developer Tools >
States to find it.

- `last_run`: ISO timestamp of last evaluation
- `runtime`: Evaluation time in seconds
- `last_trigger`: `periodic` for a scheduled scan, otherwise `manual`
- `integrations`: Total integrations discovered
- `devices`: Total devices discovered
- `entities`: Total entities discovered for included devices
- `integrations_excluded`: Integrations excluded by filters
- `devices_excluded`: Devices excluded by device filters
- `entities_excluded`: Entities excluded by entity filters
- `device_issues`: Devices with issues
- `entity_issues`: Entities with issues
- `device_stale_issues`: Devices flagged as stale
- `unmatched_directives`: Include / exclude directives that bound to zero live
  candidates this run (zero unless **Validate include / exclude directives**
  surfaced something)

### Debug logging

Enable the **Debug Logging** toggle in the blueprint. Debug output appears in
**Settings > System > Logs**, logged at WARNING level (HA's default for custom
components).

Example output for an automation named "Device Watchdog":

```text
[DW: Device Watchdog] integrations=12 devices=45
  entities=320 device_issues=2 entity_issues=5 stale=1
  unmatched_directives=0
```
