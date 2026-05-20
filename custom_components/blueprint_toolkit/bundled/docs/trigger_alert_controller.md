# Water Leak Alert

## Summary

Watches a set of water leak sensors and responds when any of them detects
water. It fires a one-time initial notification, then repeats a configurable
response -- a siren and/or repeated notification actions -- on an interval for
as long as the leak persists. The repeated response can be gated on presence
so an empty house stays quiet.

This is a standalone blueprint: the whole automation lives in the blueprint
YAML, with no `blueprint_toolkit` service handler behind it.

## Features

- **Multiple leak sensors**: takes any number of `moisture` binary sensors. A
  leak on any one of them starts the response; it continues until all of them
  are dry.
- **Detection delay**: a configurable hold time filters out momentary sensor
  blips before the automation fires.
- **One-time initial notification**: runs a user-supplied action chain once,
  the moment a leak is detected -- ungated, so you hear about a leak even when
  nobody is home.
- **Repeated response**: sounds a siren and/or runs a second action chain on a
  configurable interval for as long as the leak persists.
- **Presence gate**: the repeated response only runs while a presence entity
  is `on`, so a siren never sounds in an empty house. Presence coming and
  going is handled while the leak is still active.
- **Siren at full volume**: when a siren is configured it plays the chosen
  tone at maximum volume on every repeat.

## Requirements

- One or more `binary_sensor` entities with `device_class: moisture` (water
  leak sensors).
- Optionally, a `siren` entity that supports tones (e.g. a Zooz ZSE50).
- Optionally, a presence/occupancy `binary_sensor` or `input_boolean`.
- Optionally, one or more notification services, scripts, or other actions to
  run for the initial and/or repeated notifications.

## Usage

1. Go to **Settings > Automations & Scenes > Blueprints**.
2. Find **Water Leak Alert** and click **Create Automation**.
3. Pick your leak sensors, set the detection delay and repeat interval,
   configure the initial and repeated notification actions, and pick a siren
   and/or presence entities as needed.
4. Save.

## Configuration

### Leak detection

| Parameter           | Default      | Description                                                                                                            |
| ------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **Leak sensors**    | *(required)* | One or more `moisture` binary sensors. Any one going to `on` triggers the automation; the response runs until all dry. |
| **Detection delay** | 30s          | How long a sensor must continuously report water before the automation fires. Set to zero to react immediately.        |

### Initial notification

| Parameter                       | Default   | Description                                                                                                                                       |
| ------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Initial notification action** | *(empty)* | Action(s) to run once when a leak is first detected. Receives the message body via `{{ message }}`. Always runs, regardless of the presence gate. |

### Repeated response

| Parameter                        | Default   | Description                                                                                                                                 |
| -------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Repeat interval**              | 30s       | Wait time between each repeated response while the leak persists.                                                                           |
| **Siren**                        | *(empty)* | Optional siren to sound on every repeat. Plays at full volume. Leave empty for no siren.                                                    |
| **Siren tone**                   | `7`       | Tone to play -- numeric ID or full name from the siren's `available_tones` attribute. On a Zooz ZSE50, ID `7` is "Leak detected".           |
| **Presence entities**            | *(empty)* | Optional gate: the siren and repeated action only run while at least one of these is `on`. Leave empty to always run the repeated response. |
| **Repeated notification action** | *(empty)* | Action(s) to run on every repeat, alongside the siren. Subject to the presence gate. Receives the message body via `{{ message }}`.         |

## Usage notes

### The `{{ message }}` variable

Both action inputs run with a `message` variable in scope, so each step can
reference `{{ message }}` in its `data:` block:

- Initial notification: `Water leak detected by <sensor name>.`
- Repeated notification: `Water leak still detected (<wet sensor names>).`

A typical initial notification action is a single **Call service** step on
`notify.mobile_app_<your phone>` with `message: "{{ message }}"`.

### Presence gating

The presence gate is a *permission* check, not a suppression list: the
repeated response runs only while at least one presence entity is `on`. Point
it at a whole-home occupancy sensor so the siren never sounds in an empty
house. The gate is re-checked on every repeat, so if everyone leaves mid-leak
the siren goes quiet within one interval, and if they return while the leak is
still active it resumes. The initial notification is never gated -- a leak
while you are away is exactly when you want the push.

### Finding the siren tone

In **Developer Tools > States**, open your siren entity and read the
`available_tones` attribute. It maps each tone ID to a name. Put either the ID
or the exact name into the **Siren tone** field. The Zooz ZSE50's default
sound library puts "Leak detected" at ID `7`.

### Example: main bathroom

```text
Leak sensors:     binary_sensor.main_bath_leak_sensor_1_water_leak_detected
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

When any sensor is wet for 30 seconds, you get a phone notification
immediately. Then, while anyone is home, the siren plays the "Leak detected"
tone every 30 seconds until every sensor is dry.

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
- **Loop structure.** The `repeat.while` condition is "any sensor still wet".
  The presence gate is checked *inside* the loop body, not in the `while`, so
  presence transitions are handled without the loop exiting early.
- **Siren cleanup.** When the loop exits (all sensors dry), the automation
  calls `siren.turn_off` in case a tone is still playing.
- **Empty action inputs.** Both notification action inputs default to an empty
  list; an empty list runs as a no-op, so leaving either unset is safe.
- **Restart recovery.** Because this is a standalone blueprint (no integration
  handler), an HA restart mid-leak would otherwise leave the repeat loop
  stopped and any sounding tone stuck on -- a sustained leak never re-fires a
  `state` trigger across a restart. A second trigger (`homeassistant: start`)
  gated on a top-level "any sensor currently wet" condition re-enters the loop
  after a restart only when a leak is still active. On that path the actions
  first wait the configured **Detection delay** and re-check the sensors,
  mirroring the `for:` debounce on the regular state trigger so a transient
  wet reading right as HA comes up cannot fire a false alarm; if every sensor
  is dry by then the automation exits. The initial-notification step is
  suppressed on the restart path (matched via `trigger.id`) so you don't get a
  duplicate first-detection push.
