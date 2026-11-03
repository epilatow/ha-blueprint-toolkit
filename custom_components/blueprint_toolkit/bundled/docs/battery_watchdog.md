# Battery Watchdog

## Summary

Watches every battery Home Assistant knows about and raises one persistent
notification listing the low ones. Each line names the battery's area, links
to its device, and links to the battery's history, so you can find it and see
how fast it is draining. The notification clears automatically once no battery
is low.

## Features

- Finds batteries by their `battery` device class, on both numeric battery
  sensors (a percentage) and binary battery sensors (low or normal)
- One notification for every low battery, sorted by area and then device
- Device and battery-history links on every line
- Include/exclude integration filtering (empty include means all
  integrations); excluding an integration skips every device it has an entity
  on
- Regex-based device name, entity ID, and entity name exclusion filters
- Exclude specific batteries, or watch only a chosen few
- Optional validation that flags include / exclude entries matching no battery
- Optional debug logging

## Requirements

None.

## Usage

1. Install the automation (see main README)
2. Go to **Settings > Automations & Scenes > Blueprints**
3. Click **Battery Watchdog**
4. Set the warning level and exclude batteries you don't want reported, such
   as phones and tablets
5. Save and enable

## Configuration

| Parameter                             | Default | Description                                                                                                                                           |
| ------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Battery warning level                 | `25`    | A battery at or below this percentage is low.                                                                                                         |
| Include integrations                  | empty   | Integrations whose batteries to watch. Empty means all.                                                                                               |
| Exclude integrations                  | empty   | Integrations whose batteries to skip even if included. Also skips every device they have an entity on, including batteries another integration adds.  |
| Device name exclude regex             | empty   | Skip batteries on a device whose name matches. One pattern per line.                                                                                  |
| Include entities                      | empty   | Watch only these batteries. When set, every other include / exclude input must be empty.                                                              |
| Exclude entities                      | empty   | Batteries to skip, such as phones and tablets.                                                                                                        |
| Entity ID exclude regex               | empty   | Skip batteries whose entity ID matches. One pattern per line.                                                                                         |
| Entity name exclude regex             | empty   | Skip batteries whose friendly name matches. One pattern per line.                                                                                     |
| Check interval (minutes)              | `5`     | Minutes between battery checks.                                                                                                                       |
| Validate include / exclude directives | `true`  | Surface include / exclude entries that match no battery as a single informational notification. See **Unmatched include / exclude directives** below. |
| Debug logging                         | `false` | Log a summary line per check to HA's logs.                                                                                                            |

## Usage notes

### What counts as low

A numeric battery sensor is low when its level is at or below the warning
level. A binary battery sensor is low whenever it reads low (`on`). A battery
that is unavailable, unknown, or not reporting a number is not listed; Device
Watchdog reports unavailable entities.

### The notification

All low batteries share one notification, one line per battery, sorted by area
and then device:

```text
- Kitchen -> Window, Left: 20%
- Office -> Motion Sensor: low
- Spare Remote: 15%
```

The device name links to the device's page, and the level links to the
battery's history. A battery with no area leaves the area out and is listed
after the rest. A battery with no device shows its own name, unlinked. When
one device has more than one low battery, each line also names the battery.

The notification updates whenever a listed level changes, which moves it back
to the top of the notification list. Once no battery is low it is dismissed.
Dismissing it while batteries are still low doesn't stick: the next check
brings it back. To stop reporting a battery, exclude it.

### Include entities

**Include entities** turns the watchdog into a watch list: only those
batteries are checked. Because the list already says exactly which batteries
to watch, combining it with any other include / exclude input is a
configuration error.

### Unmatched include / exclude directives

With **Validate include / exclude directives** on (default), any include /
exclude entry that matches no battery -- a typo'd integration, an entity that
isn't a battery, or a regex line that catches no battery -- appears in a
single informational notification. Each entry is checked against every
battery, so an entry another filter happens to shadow is not flagged. It
clears on the next check once the entry is fixed or removed, or when you turn
the toggle off.

## Developer notes

### Entity attributes

After each check, attributes are written to
`blueprint_toolkit.bw_<slug>_state` where `<slug>` derives from the automation
entity_id.

- `last_run`: ISO timestamp of the last check
- `runtime`: Check time in seconds
- `last_trigger`: `periodic` for a scheduled check, otherwise `manual`
- `batteries`: Battery entities seen
- `batteries_excluded`: Batteries the include / exclude inputs skipped
- `low_batteries`: Batteries reported as low
- `low_battery_entities`: Entity IDs of the low batteries
- `unmatched_directives`: Include / exclude directives that matched no battery

### Debug logging

Enable the **Debug logging** toggle in the blueprint. Output appears in
**Settings > System > Logs** at WARNING level (HA's default for custom
components).

Example output for an automation named "Battery Watchdog":

```text
[BW: Battery Watchdog] batteries=136 excluded=7 low=5 unmatched_directives=0
```
