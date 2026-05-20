# Trigger Alert Controller

## Summary

Watches a set of binary sensors and responds when any of them turns on. It
fires a one-time initial notification, then repeats a configurable response --
a siren and/or repeated notification actions -- on an interval for as long as
the condition persists. The repeated response can be gated on presence so an
empty house stays quiet.

It works with any binary sensor: a water leak, smoke, an open door, motion, or
anything else that reports `on` for the condition you want to be alerted
about. A short **Alert name** label is woven into the notification body so the
same blueprint reads naturally for each use.

This is a standalone blueprint: the whole automation lives in the blueprint
YAML, with no `blueprint_toolkit` service handler behind it.

## Features

- **Any binary sensors**: takes any number of `binary_sensor` entities,
  regardless of device class. A trigger on any one of them starts the
  response; it continues until all of them are `off`.
- **Custom alert name**: a short label (e.g. "Water leak", "Smoke") is
  interpolated into the notification body the automation builds.
- **Detection delay**: a configurable hold time filters out momentary sensor
  blips before the automation fires.
- **One-time initial notification**: runs a user-supplied action chain once,
  the moment a sensor turns on -- ungated, so you hear about it even when
  nobody is home.
- **Repeated response**: sounds a siren and/or runs a second action chain on a
  configurable interval for as long as the condition persists.
- **Presence gate**: the repeated response only runs while a presence entity
  is `on`, so a siren never sounds in an empty house. Presence coming and
  going is handled while the condition is still active.
- **Siren at full volume**: when a siren is configured it plays at maximum
  volume on every repeat, with an optional tone.

## Requirements

- One or more `binary_sensor` entities (any device class).
- Optionally, a `siren` entity (tones are optional; if it supports them, e.g.
  a Zooz ZSE50, you can name one).
- Optionally, a presence/occupancy `binary_sensor` or `input_boolean`.
- Optionally, one or more notification services, scripts, or other actions to
  run for the initial and/or repeated notifications.

## Usage

1. Go to **Settings > Automations & Scenes > Blueprints**.
2. Find **Trigger Alert Controller** and click **Create Automation**.
3. Set an alert name, pick your trigger sensors, set the detection delay and
   repeat interval, configure the initial and repeated notification actions,
   and pick a siren and/or presence entities as needed.
4. Save.

## Configuration

### Trigger detection

| Parameter           | Default      | Description                                                                                                       |
| ------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------- |
| **Alert name**      | `Alert`      | Short label for what this alert is about (e.g. "Water leak", "Smoke"). Interpolated into the notification body.   |
| **Trigger sensors** | *(required)* | One or more binary sensors. Any one going to `on` triggers the automation; the response runs until all are `off`. |
| **Detection delay** | 30s          | How long a sensor must continuously report `on` before the automation fires. Set to zero to react immediately.    |

### Initial notification

| Parameter                       | Default   | Description                                                                                                                                      |
| ------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Initial notification action** | *(empty)* | Action(s) to run once when a sensor first turns on. Receives the message body via `{{ message }}`. Always runs, regardless of the presence gate. |

### Repeated response

| Parameter                        | Default   | Description                                                                                                                                 |
| -------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Repeat interval**              | 30s       | Wait time between each repeated response while the condition persists.                                                                      |
| **Siren**                        | *(empty)* | Optional siren to sound on every repeat. Plays at full volume. Leave empty for no siren.                                                    |
| **Siren tone**                   | *(empty)* | Optional tone -- numeric ID or full name from the siren's `available_tones` attribute. Leave empty to play the siren's default tone.        |
| **Presence entities**            | *(empty)* | Optional gate: the siren and repeated action only run while at least one of these is `on`. Leave empty to always run the repeated response. |
| **Repeated notification action** | *(empty)* | Action(s) to run on every repeat, alongside the siren. Subject to the presence gate. Receives the message body via `{{ message }}`.         |

## Usage notes

### The `{{ message }}` variable

Both action inputs run with a `message` variable in scope, so each step can
reference `{{ message }}` in its `data:` block. The body is built from the
**Alert name** label:

- Initial notification: `<alert name> detected by <sensor name>.`
- Repeated notification: `<alert name> still detected (<on sensor names>).`

For an alert name of `Water leak`, that reads
`Water leak detected by Kitchen Sensor.` A typical initial notification action
is a single **Call service** step on `notify.mobile_app_<your phone>` with
`message: "{{ message }}"`.

### Presence gating

The presence gate is a *permission* check, not a suppression list: the
repeated response runs only while at least one presence entity is `on`. Point
it at a whole-home occupancy sensor so the siren never sounds in an empty
house. The gate is re-checked on every repeat, so if everyone leaves mid-event
the siren goes quiet within one interval, and if they return while the
condition is still active it resumes. The initial notification is never gated
-- a trigger while you are away is exactly when you want the push.

### Finding the siren tone

In **Developer Tools > States**, open your siren entity and read the
`available_tones` attribute. It maps each tone ID to a name. Put either the ID
or the exact name into the **Siren tone** field. The Zooz ZSE50's default
sound library, for example, puts "Leak detected" at ID `7`. Leave the field
empty to let the siren play whatever tone it defaults to.

### Example: water leak

```text
Alert name:       Water leak
Trigger sensors:  binary_sensor.main_bath_leak_sensor_1_water_leak_detected
                  binary_sensor.main_bath_leak_sensor_2_water_leak_detected
                  binary_sensor.main_bath_leak_sensor_3_water_leak_detected
                  binary_sensor.main_bath_leak_sensor_4_water_leak_detected
Detection delay:  30 seconds
Initial action:   notify.mobile_app_phone  (message: "{{ message }}")
Repeat interval:  30 seconds
Siren:            siren.main_bath_alarm_play_tone
Siren tone:       7
Presence:         binary_sensor.polaris_occupied
```

When any sensor is `on` for 30 seconds, you get a phone notification
immediately. Then, while anyone is home, the siren plays the "Leak detected"
tone every 30 seconds until every sensor is `off`.

## Developer notes

### Standalone blueprint

This blueprint is **standalone** -- the marker comment
`# blueprint-kind: standalone` on the first line records that. Its `actions:`
block is plain Home Assistant YAML and does not dispatch to a
`blueprint_toolkit.<service>` handler, so there is no handler/logic
subpackage, no `_SCHEMA`, and no schema-drift test. It still ships through the
same bundled blueprints directory and is installed by the reconciler exactly
like the handler-backed blueprints. See `AUTOMATIONS.md` for the
standalone-blueprint category contract.

### Behavior details

- **Mode `single`.** A second sensor tripping while the repeat loop is running
  does not start a second loop -- the running loop's `while` check already
  covers every sensor.
- **Loop structure.** The `repeat.while` condition is "any sensor still on".
  The presence gate is checked *inside* the loop body, not in the `while`, so
  presence transitions are handled without the loop exiting early.
- **Optional siren tone.** The siren service data is built inline so the
  `tone` key is only sent when **Siren tone** is set; a blank tone lets the
  siren play its own default rather than dispatching an empty value.
- **Siren cleanup.** When the loop exits (all sensors `off`), the automation
  calls `siren.turn_off` in case a tone is still playing.
- **Empty action inputs.** Both notification action inputs default to an empty
  list; an empty list runs as a no-op, so leaving either unset is safe.
- **Restart recovery.** Because this is a standalone blueprint (no integration
  handler), an HA restart mid-event would otherwise leave the repeat loop
  stopped and any sounding tone stuck on -- a sustained `on` state never
  re-fires a `state` trigger across a restart. A second trigger
  (`homeassistant: start`) gated on a top-level "any sensor currently on"
  condition re-enters the loop after a restart only when the condition is
  still active. On that path the actions first wait the configured **Detection
  delay** and re-check the sensors, mirroring the `for:` debounce on the
  regular state trigger so a transient `on` reading right as HA comes up
  cannot fire a false alarm; if every sensor is `off` by then the automation
  exits. The initial-notification step is suppressed on the restart path
  (matched via `trigger.id`) so you don't get a duplicate first-detection
  push.
