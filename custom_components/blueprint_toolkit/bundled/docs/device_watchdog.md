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
- Diagnostic entity check: notifies when recommended diagnostic entities
  (e.g., Last seen, Node status, Signal strength) are disabled
- Per-check selection so exclusion lists can be scoped per check (instantiate
  the blueprint once per check)
- Optional debug logging

## Usage

1. Install the automation (see main README)
2. Go to **Settings > Automations & Scenes > Blueprints**
3. Click **Device Watchdog**
4. Configure integrations and thresholds
5. Save and enable

## Configuration

| Parameter                             | Description                                                                                                                                                   |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Include integrations                  | Integration IDs to monitor. Empty means all.                                                                                                                  |
| Exclude integrations                  | Integration IDs to skip even if included.                                                                                                                     |
| Device name exclude regex             | Skip devices whose name matches. One pattern per line.                                                                                                        |
| Entity ID exclude regex               | Skip entities whose ID matches. One pattern per line.                                                                                                         |
| Entity domains to monitor             | Only check entities in these domains                                                                                                                          |
| Check interval (minutes)              | Minutes between watchdog evaluations                                                                                                                          |
| Dead device threshold (minutes)       | Staleness threshold for state reports                                                                                                                         |
| Enabled checks                        | Which checks to run (`unavailable-entities`, `device-updates`, `disabled-diagnostics`). Empty means all.                                                      |
| Max device notifications              | Cap on per-device notifications. Default 10. 0 = unlimited.                                                                                                   |
| Create repairs for fixable findings   | Default on. Routes disabled-diagnostic-entity findings to HA's Repairs UI as one-click Fix issues instead of persistent notifications. See **Repairs** below. |
| Max repairs                           | Cap on per-run repair issues. Default 5. 0 = unlimited. Applies only when **Create repairs** is on.                                                           |
| Validate include / exclude directives | Default on. Surface typo'd integrations or stale regex lines as a single informational notification. See **Unmatched include / exclude directives** below.    |
| Debug logging                         | Log debug info to HA logs                                                                                                                                     |

See the blueprint UI for default values.

## Usage notes

### Notifications

Each device with health issues gets its own persistent notification.
Notifications are automatically dismissed when devices recover.

### Notification panel ordering

The order of notifications in the HA notification panel may change between
evaluation runs. This is because each run re-creates all active notifications
(to update content if health changed), which updates their timestamps. Since
all creates happen within milliseconds, the panel's display order is
effectively random. The same devices are shown -- only the panel ordering
varies.

### Unmatched include / exclude directives

When **Validate include / exclude directives** is enabled (default), every
include / exclude entry is checked against the live truth set after each scan.
Anything that doesn't bind -- a typo'd integration name like `zwavejs` instead
of `zwave_js`, a regex line in **Device name exclude regex** or **Entity ID
exclude regex** that catches no current device or entity -- shows up in a
single "Unmatched include / exclude directives" notification with one bullet
per offending entry, the field it came from, and a short reason. Fix the typo
or remove the stale entry and the notification clears on the next scan. The
notification is informational, not a config error. Disable the toggle to skip
the check; any prior unmatched-directives notification dismisses on the next
scan.

### Repairs

When **Create repairs for fixable findings** is enabled (default), each
disabled-recommended-diagnostic-entity finding surfaces as an HA Repair with a
one-click Fix button instead of (or alongside) the per-device summary
notification. Submit clears `disabled_by` on the named entity so it goes back
to monitoring.

Other finding categories (unavailable / stale devices) keep using
notifications regardless of the toggle -- those don't have a deterministic
single-click fix.

The repair issue auto-clears once the entity is re-enabled (next scan no
longer flags it and the dispatcher's sweep removes the stale issue).

**Cap.** Repairs are not bulk-dismissable in HA's UI, so the **Max repairs**
input limits per-run issue count (default 5; 0 = unlimited). When the cap is
exceeded, a single cap-summary repair surfaces telling the user how many
findings were suppressed; raise the cap or fix the visible issues to surface
more.

Disable **Create repairs** to keep today's notification-only behavior on this
instance.

## Developer notes

### Entity attributes

After each evaluation, attributes are written to
`blueprint_toolkit.dw_<slug>_state` where `<slug>` derives from the automation
entity_id. Search for `blueprint_toolkit.dw_*_state` in Developer Tools >
States to find it.

- `last_run`: ISO timestamp of last evaluation
- `runtime`: Evaluation time in seconds
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
**Settings > System > Logs**. Uses `log.warning` level (HA's default for
custom components).

Example output for an automation named "Device Watchdog":

```text
[DW: Device Watchdog] integrations=12 devices=45
  entities=320 device_issues=2 entity_issues=5 stale=1
  unmatched_directives=0
```
