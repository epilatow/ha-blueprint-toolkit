# Z-Wave Parameter Manager

## Summary

Z-Wave Parameter Manager (ZPM) keeps each Z-Wave node's settable configuration
parameters aligned with a declarative policy file. You describe intent in
device-agnostic terms -- "battery motion sensors wake every hour", "all motion
sensors at maximum sensitivity" -- and ZPM resolves each concept onto the
concrete parameter every matched device actually exposes, then writes it. It
runs in-process through Home Assistant's Z-Wave JS integration: it reads live
values straight off the driver and applies changes through the standard
`zwave_js` services, so there is no separate connection to configure.

A sleeping (battery) device receives queued writes only when it next wakes, so
ZPM tracks what it has issued and reports what is still pending rather than
re-sending the same command on every pass.

## Features

- Declarative policy file: match devices by manufacturer, model, power source,
  or device type, and set device-agnostic concepts.
- Concept resolver maps each concept onto the device's real parameter,
  rescaling ranges and converting units per device.
- In-process via the Z-Wave JS integration -- no host, port, or token to
  configure.
- Reconciles on startup, on manual trigger, when the policy file is edited,
  and periodically to pick up newly-joined devices.
- Issues each command at most once per pending cycle; re-issues only after the
  Z-Wave JS add-on restarts (which flushes the device queue).
- A pending report tracks devices that have not yet applied their writes (with
  each device's wake interval and estimated next wake); it appears as soon as
  something is pending, refreshes on a configurable interval, and clears on
  full convergence. A desired-config report fires when the policy file changes
  or a new device becomes configured.
- An unused-config report flags policies and settings that match no device --
  a selector typo, a mis-scoped policy, or a setting no matched device
  exposes.

## Requirements

- The **Z-Wave JS** integration, loaded and connected to its driver. ZPM reads
  and writes through it in-process; it does not talk to zwave-js-ui directly.
- A policy file under `/config` (see
  [Policy file format](#policy-file-format)). A missing file simply means no
  policies yet.

## Usage

1. In **Settings > Automations & Scenes > Blueprints**, create an automation
   from the **Z-Wave Parameter Manager** blueprint.
2. Set the **Policy file path** (default `zwave_parameter_manager.yaml`,
   relative to `/config`) and, optionally, the reconcile and pending-report
   intervals.
3. Create the policy file (see below) and save it. ZPM picks up edits on its
   next reconcile.

## Configuration

| Input                           | Default                        | Description                                                                                                                               |
| ------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Policy file path                | `zwave_parameter_manager.yaml` | Path to the policy YAML, relative to `/config` (absolute paths accepted). A missing file means none.                                      |
| Reconcile interval (minutes)    | `5`                            | How often to re-read the live fleet, pick up newly-joined devices, and re-issue not-yet-applied writes.                                   |
| Pending report interval (hours) | `24`                           | How often to re-publish the pending-configuration notification while devices are still waiting to apply. `0` disables the pending report. |
| Debug logging                   | `false`                        | Emit one `WARNING` summary line per reconcile to **Settings > System > Logs**.                                                            |

## Usage notes

### Policy file format

The file is a mapping with a single `policies` list. Each policy has a `name`,
a `match` selector, a `settings` map of concept values, and an optional
`exclude` list of selectors:

```yaml
policies:
  - name: battery motion sensors
    match:
      device_type: motion
      power: battery
    settings:
      motion_sensitivity: 10
      wake_up_interval: 3600
    exclude:
      - model: ZSE99

  - name: mains repeaters wake check
    match:
      power: mains
    settings:
      wake_up_interval: 43200
```

A device must satisfy every field present in `match` and none of the `exclude`
selectors. Two policies setting the same concept on one device is a hard error
(surfaced as a notification) -- there is no implicit ordering.

Selector fields: `manufacturer` and `model` (matched case-insensitively
against the Z-Wave config-DB identity), `power` (`battery` or `mains`, derived
from the node's listening flag), and `device_type` (one of `motion`,
`contact`, `moisture`, `humidity`, `temperature`, `illuminance`, `smoke`,
`carbon_monoxide`, `lock`, `siren`, derived from the device's Home Assistant
entities).

### Concepts

| Concept                     | Value          | Meaning                                                          |
| --------------------------- | -------------- | ---------------------------------------------------------------- |
| `motion_sensitivity`        | `1`-`10`       | Motion / PIR sensitivity, rescaled onto each device's own range. |
| `light_on_motion`           | `true`/`false` | Whether the status LED illuminates on motion.                    |
| `humidity_report_threshold` | percent        | Minimum humidity change before an unsolicited report.            |
| `threshold_check_interval`  | seconds        | How often the device samples its sensors.                        |
| `wake_up_interval`          | seconds        | How often a battery device wakes to receive queued commands.     |

A concept that a matched device does not expose is reported as a warning, not
applied -- the device simply lacks that parameter. When *no* matched device
exposes a setting (or a policy matches no device at all), it is additionally
flagged on the unused-config report as a whole specified setting that landed
on nothing.

### How writes reach sleeping devices

A battery device only receives a queued write when it next wakes (on its
`wake_up_interval`, or a manual button wake). ZPM cannot force a wake; it
keeps the command queued and reports the device as pending until it applies.
Shortening `wake_up_interval` is the only unattended way to make future writes
land sooner -- and that change is itself queued, so it takes effect only after
the device's next wake.

## Developer notes

### Architecture

The handler composes pure modules in the `zwave_parameter_manager` subpackage:
`config.parse_policies` (validate the policy file), `source.read_fleet`
(assemble each node's identity, settable parameters, live values, and wake
context off the in-process driver, the registries, and the recorder),
`logic.evaluate_policies` (plan writes against the shipped `mapping.json`),
`apply.select_writes` (which writes to issue this cycle), and `report` +
`notification` (render the reports).

### Apply model

Pending state -- the writes ZPM has issued but not yet seen converge -- is
kept in `/config/blueprint_toolkit/zpm_pending.json`, a file the automation
and the `zwavectl` CLI share so the two never re-issue a command the other
already queued. A write is suppressed while the store already holds its value,
so a periodic reconcile never piles duplicate commands into a sleeping
device's queue. ZPM does not depend on the add-on de-duplicating its queue.

A driver / add-on restart flushes the wake-up queue, so ZPM must re-issue
after one. It detects a restart from the Z-Wave JS controller's message
counters, which reset to zero on restart: an integration service records them
(with the time a reset was last seen) in
`/config/blueprint_toolkit/zwave-js-info.json`, and every command in the
pending store is tagged with when it was issued. A command issued before the
last driver restart was flushed, so it is re-issued; one issued after is still
queued and stays suppressed. Because the restart time is derived from the
counters rather than observed live, a restart that happened while Home
Assistant Core was down is still detected on the next reconcile after Core
returns.

### Reporting

The pending report (`...__pending`) lists every device still waiting to apply
its writes. It appears as soon as a parameter is pending and dismisses on full
convergence; while anything stays pending it re-publishes on the **Pending
report interval (hours)** cadence (default 24, `0` disables it). Its body
annotates each sleeping device with an estimated next wake, and that estimate
drifts forward every time a device wakes, so publishing on an interval rather
than every reconcile keeps the notification from bubbling to the top of the
panel continuously; a longer interval quiets a slow-waking fleet further. The
desired-config report (`...__desired`) re-fires only when the policy file
changes or a newly-configured node appears, so convergence progress does not
re-bubble it. The unused-config report (`...__unused`) lists each policy or
setting that applied to no device (a selector matching nothing, or a setting
no matched device exposes). It re-evaluates every reconcile, but its body
carries no live values, so the notification updates only when the unused set
actually changes and dismisses when every policy and setting lands somewhere.
Policy conflicts and unmappable concepts surface as their own notification; a
config-file parse error and a "Z-Wave JS unavailable" state each have theirs.

### Diagnostic state entity

`blueprint_toolkit.zpm_<slug>_state` carries, per reconcile: `last_run`,
`runtime`, `last_trigger`, `last_config_mtime`, `devices`, `writes_planned`,
`writes_issued`, `pending`, `converged`, `pending_params`, `plan_warnings`,
`plan_errors`, `unused`, and a human-readable `pending_writes` list.

### Debug log format

With debug logging on, one line per reconcile:

```text
[ZPM: <automation name>] trigger=<id> devices=N planned=N issued=N pending=N converged=N
```
