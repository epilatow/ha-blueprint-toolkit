# Entity Defaults Watchdog

## Summary

Detects entity IDs and names that have drifted from their defaults. Covers
both device-attached entities (one notification per drifted device) and
deviceless entities like automations, scripts, helpers, and template sensors
(one aggregate notification). Clears notifications automatically when drift is
resolved.

## Features

- Detect device entity ID drift (when a device is renamed after its entities
  already exist)
- Detect device name-override drift (stale name overrides left behind when an
  integration's naming conventions change)
- Detect deviceless entity ID drift -- automations, scripts, helpers, template
  sensors, scenes, groups, and other user-named entities whose IDs no longer
  match their current names
- Detect stale HA collision suffixes (`_2`, `_3`, ...) left over from naming
  conflicts whose original peers were removed
- Detect redundant name prefixes (overrides that include the device name when
  HA would add it automatically)
- Detect visible aliased entities -- `switch_as_x` wrappers whose source
  entity is no longer hidden, so both rows show up in dashboards, voice
  assistants, and entity pickers
- Detect script YAML-key drift -- YAML scripts whose `scripts.yaml` block key
  (the registered service name `script.<key>`) no longer matches their renamed
  entity id, so the script answers to two names
- Per-device persistent notifications with auto-clear on drift resolution;
  deviceless entities roll up into a single aggregate notification, or (with
  **Create repairs** on) one one-click Repair each
- Selectable drift checks (device entity ID, device entity name, deviceless
  ID, visible aliased entity, script YAML-key, or any combination)
- Include/exclude integration filtering
- Regex-based device and entity exclusion filters
- Notification cap to limit per-device notifications
- Repair instructions tailored to the drift combination (two-cycle fix for
  device name + ID drift)
- Optional debug logging

## Requirements

None.

## Usage

1. Install the automation (see main README)
2. Go to **Settings > Automations & Scenes > Blueprints**
3. Click **Entity Defaults Watchdog**
4. Configure integrations and exclusions
5. Save and enable

## Configuration

| Parameter                             | Description                                                                                                                                                                                                                                                      |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Drift checks                          | Which checks to run: `device-entity-id`, `device-entity-name`, `entity-id` (deviceless), `visible-aliased-entity`, `script-yaml-key`, or any combination. Empty means all.                                                                                       |
| Include integrations                  | Integration IDs to check. Empty means all integrations. Applies to device-backed entities, registry-backed deviceless entries (e.g. `template`, `rachio`), visible-aliased sources, and scripts. State-only entities have no platform to filter on.              |
| Exclude integrations                  | Integration IDs to skip even if included. Same scope as Include integrations, and also skips every device they have an entity on.                                                                                                                                |
| Device name exclude regex             | Skip devices whose name matches. One pattern per line.                                                                                                                                                                                                           |
| Exclude entities                      | Specific entities to exclude from all checks.                                                                                                                                                                                                                    |
| Entity ID exclude regex               | Skip entities whose ID matches. One pattern per line.                                                                                                                                                                                                            |
| Entity name exclude regex             | Skip entities whose name matches. One pattern per line.                                                                                                                                                                                                          |
| Check interval (minutes)              | Minutes between drift evaluations.                                                                                                                                                                                                                               |
| Max device notifications              | Cap on per-device notifications. Default 10. 0 = unlimited.                                                                                                                                                                                                      |
| Create repairs for fixable findings   | Default on. Routes entity-ID drift, entity-name drift, visible-aliased, and script YAML-key findings to HA's Repairs UI as one-click Fix issues instead of persistent notifications. Script YAML-key drift surfaces ONLY when this is on. See **Repairs** below. |
| Max repairs                           | Cap on per-run repair issues. Default 5. 0 = unlimited. Applies only when **Create repairs** is on.                                                                                                                                                              |
| Validate include / exclude directives | Default on. Surface typo'd integrations, removed entities, or stale regex lines as a single informational notification. See **Unmatched include / exclude directives** below.                                                                                    |
| Debug Logging                         | Log debug info to HA logs.                                                                                                                                                                                                                                       |

See the blueprint UI for default values.

## Usage notes

### What is entity drift?

Home Assistant assigns entity IDs and names when entities are first created.
These can drift from their expected values over time:

- **Device entity ID drift** -- when a device is renamed after its entities
  already exist, the entity IDs still reflect the original device name. For
  example, renaming "Kitchen Multisensor" to "Kitchen Sensor" leaves
  `sensor.kitchen_multisensor_temperature` instead of
  `sensor.kitchen_sensor_temperature`.
- **Device entity name drift** -- when an integration changes its naming
  conventions (e.g., during an upgrade), HA preserves the old name as a "name
  override" to avoid breaking automations. The override becomes stale when the
  integration's new name is what you actually want.
- **Legacy entity name drift** -- some integrations (Lutron Caseta, for
  example) build each entity's name from the device's name. When you rename
  such a device, HA stores a matching name on the entity. Without it, HA shows
  the new device name in front of the old name ("Fan Main Bath Fan"), so the
  watchdog flags an entity missing that name, or still holding one from an
  earlier rename, and reports its entity ID only once the name is right, since
  the expected ID depends on it. Where that name is just the device name, the
  watchdog wants **Use device name** on instead. An entity with **Use device
  name** on is never flagged for its name, because HA leaves you no name to
  change.
- **Deviceless ID drift** -- automations, scripts, helpers, template sensors,
  and similar user-named entities have entity IDs derived from their name at
  creation. Renaming the entity later doesn't update the entity ID, leaving
  (for example) `automation.foo` still running after you renamed its alias to
  "Bar".

### Two-cycle fix sequence

When a device has both name overrides and non-default entity IDs, the fix must
happen in two steps:

1. **First cycle**: clear or edit name overrides in each entity's settings, or
   turn on **Use device name** where the watchdog says to. The watchdog
   re-evaluates and may surface new non-default entity IDs (because clearing
   the name override changes the expected ID).
2. **Second cycle**: use **Recreate entity IDs** on the device page repeatedly
   until no more changes occur. Collisions between entity IDs can cause
   temporary numeric suffixes (e.g., `_2`) that resolve on subsequent passes
   as other entities free up their IDs.

The watchdog notification explains this sequence when both types of drift are
present, and will continue to flag non-default IDs until all collisions are
resolved.

### Disabled entities

The watchdog only checks enabled entities. Disabled entities (e.g., diagnostic
entities disabled by their integration) may also have drifted IDs or names but
are not flagged. When you use **Recreate entity IDs** on a device page, HA
will also rename disabled entities, so the number of renames shown may be
higher than what the watchdog reported.

### Notification format

Device-attached drift creates one persistent notification per device. Every
notification leads with an attribution header -- the automation that emitted
it, the device's integration(s), and a link to the device with its area when
it has one -- so you can click straight through to the source. The body below
contains up to five sections depending on what kind of drift was found:

**Name overrides to clear** -- entities where the name override should be
removed:

```text
- `sensor.kitchen_temp`: "Old Temp"
```

**Name overrides with redundant device name** -- the override includes the
device name, which HA already adds automatically:

```text
- `sensor.kitchen_co2`: "Kitchen Sensor CO2" -> "CO2"
```

**Name overrides to set** -- legacy entities on a renamed device, with the
name HA stores at a rename:

```text
- `button.kitchen_remote_off`: set to "Remote Off"
```

**Names to unset** -- legacy entities on a renamed device whose name should
match the default. Turn on **Use device name** in each entity's settings:

```text
- `switch.main_bath_fan`: "Fan Main Bath Fan"
```

**Non-default entity IDs** -- entities whose ID does not match what HA would
assign today:

```text
- `sensor.old_kitchen_temperature`
```

Deviceless drift is reported as a single aggregate notification (when **Create
repairs** is off) with up to two sections. When **Create repairs** is on, each
drifted deviceless entity instead surfaces as its own one-click **Regenerate
entity IDs?** Repair (see **Repairs** below) -- one per entity, since
deviceless entities have no device to group under.

**Entity IDs do not match their names** -- one bullet per drifted entity, with
a pointer to the most useful edit surface:

```text
- `automation.driveway_lights_on_at_sunset` -> expected `automation.auto_on_sunset_lights_sunset_to_8pm`
  [Auto-On: Sunset Lights: Sunset to 8pm](/config/automation/edit/1669687974816)
- `sensor.template_sensor` -> expected `sensor.grid_import_power`
  Grid Import Power  -  integration [template](/config/integrations/integration/template)
- `sensor.old_yaml_thing` -> expected `sensor.grid_import_power`
  Grid Import Power  -  add `unique_id:` to make this entity manageable
```

For automations and scripts the friendly name itself is the link to that
entity's editor. Registry-backed entries from other integrations show the
friendly name in plain text followed by the owning integration's name as a
link to its config page -- scan the integration column to see when several
flagged entities share a single source (e.g. five rows all tagged
`-  integration rachio`) and can be suppressed together via **Exclude
integrations**. State-only entities (YAML blocks without `unique_id:`) have no
owning integration, so they show a nudge to add one instead.

**Stale collision suffixes** -- entities whose ID ends in `_N` (N >= 2) with
no un-suffixed peer. In a chain of suffixes, only the highest is flagged:

```text
- `automation.front_porch_light_2` -> rename to `automation.front_porch_light`
  [Front Porch Light](/config/automation/edit/1234567890)
```

### Recommendation: add `unique_id:` to YAML entities

The deviceless check only catches YAML-defined entities that have an
`entry.name` + entity registry entry, which only exists when the block has a
`unique_id:` set. For `template:`, `rest:`, `mqtt:`, `command_line:`, etc.,
adding `unique_id:` on every block has two benefits:

- The entity is persisted in the registry, so renames, customizations, and
  cross-restart stability just work.
- The watchdog can compare names to entity IDs and flag drift -- without a
  registry entry, it has no authoritative name to compare against.

### Visible aliased entities

`switch_as_x` is HA core's wrapper integration. When a user exposes (for
example) `switch.kitchen_fan` as `fan.kitchen_fan`, switch_as_x sets
`hidden_by="integration"` on the source entity once at config-entry creation,
so the source row hides from dashboards / voice assistants / the entities
picker while the wrapper row takes over.

The hide is applied **once**. If `hidden_by` is later cleared on the source,
both rows become visible everywhere again, and switch_as_x does not notice or
self-heal. Users typically see the symptom as "every aliased switch is
suddenly showing up twice in voice control".

The watchdog flags every switch_as_x source whose `hidden_by` and
`disabled_by` are both `None` (and whose wrapper entity exists in the
registry). The notification body lists each flagged source with a per-entity
link to **Settings > Entities > <source>** so you can re-toggle visibility off
in one click.

Manual fix: open the per-entity Settings page from the notification body,
toggle **Visible** off. The toggle sets `hidden_by="user"` rather than
`hidden_by="integration"` -- this sticks even if you later remove the
switch_as_x wrapper, whereas an integration-managed hide would be cleaned up
when the wrapper goes away. For most users the difference is moot; if you need
the integration-managed behavior, remove and re-add the switch_as_x config
entry instead (the integration reapplies its hide on creation).

### Script YAML-key drift

A script defined in `scripts.yaml` under the block key `K` registers with
`unique_id = K` and the service name `script.K`. If you later rename the
script's entity id to `script.<slug>` (where `<slug>` differs from `K`), the
script ends up with two names: it still answers to the service `script.K` (the
YAML block key never changed) while its entity id and friendly-name slug say
`script.<slug>`. Calls, references, and the UI disagree about what the script
is called.

This check is **repair-only**: it does nothing unless **Create repairs for
fixable findings** is on. There is no notification fallback -- the only
sensible resolution is the automated rename, so when repairs are off the
finding is suppressed entirely. When repairs are on, each drifted script
surfaces as a one-click Repair. Submitting it renames the `scripts.yaml` block
key to match the entity-id slug (writing a timestamped `scripts.yaml.*.bak`
backup first, then reloading scripts), so the service name and entity id
converge on `<slug>`.

After the rename, any automation or script still calling the old
`service: script.<old_key>` becomes a stale reference. The Reference Watchdog
flags those so you can update the callers -- that hand-off is intentional.

### Exclusion configuration

Use exclusion settings to suppress drift findings for entities with
intentionally customized names or IDs. An excluded finding's repair or
notification clears on the next scan:

- **Exclude entities**: pick specific entity IDs from a list.
- **Entity ID exclude regex**: match entity IDs by pattern (e.g., `battery` to
  skip all battery entities).
- **Entity name exclude regex**: match entity names by pattern.
- **Device name exclude regex**: skip entire devices by name.
- **Include / Exclude integrations**: keep or skip everything an integration
  owns. Excluding an integration skips every device it has an entity on,
  including entities another integration adds to that device, such as a
  `switch_as_x` wrapper, and any visible-aliased finding for a source on it.
  Otherwise a visible-aliased finding belongs to its source entity's
  integration, and a script YAML-key finding to the `script` integration, so
  an include list without `script` drops script YAML-key findings.

### Unmatched include / exclude directives

With **Validate include / exclude directives** on (default), any include /
exclude entry that matches nothing in the live scan -- a typo'd integration
like `zwavejs` instead of `zwave_js`, an **Exclude entities** entry for an
entity that no longer exists, or a regex line that catches no current row --
appears in a single informational notification. It clears on the next scan
once the entry is fixed or removed, or when you turn the toggle off.

### Repairs

When **Create repairs for fixable findings** is enabled (default), each drift
finding with a deterministic fix surfaces as an HA Repair with a one-click Fix
button instead of as a persistent notification. Four finding categories
convert:

- **Entity-ID drift** -- "Regenerate entity IDs?". Submit calls the entity
  registry's rename API. Device-attached drift groups all of a device's
  renames into one Repair; deviceless entities (automations, template / helper
  entities, ...) get one Repair each, since they have no device to group
  under.
- **Entity-name drift** -- "Update entity names?". One Repair per device,
  listing each entity's current name and its target. Submit clears a stale
  override. For a legacy entity on a renamed device, it stores the name HA
  uses there or turns on **Use device name**.
- **Visible aliased entity** -- "re-hide `<source_entity_id>`". One repair per
  flagged `switch_as_x` source whose row is still visible; Submit sets
  `hidden_by=integration` on the source, restoring the original wrapper
  behaviour. With the toggle off, these instead surface as the single
  aggregate visible-aliased notification.
- **Script YAML-key drift** -- "rename the `scripts.yaml` block key
  `<old_key>` to `<new_slug>`". One repair per drifted YAML script; Submit
  rewrites the block key (with a timestamped backup) and reloads scripts so
  the service name matches the entity id. Unlike the other categories this is
  repair-only: with the toggle off it surfaces on no surface at all (see
  **Script YAML-key drift** above).

Each Fix dialog leads with the same attribution header the notifications carry
-- always the automation that emitted it, the owning integration(s) when
known, and a link to the device with its area when it has one for
device-attached findings. Deviceless findings (deviceless entity-ID drift,
script YAML-key drift) carry the owning integration but no device line -- the
script YAML-key fix, for instance, shows the built-in `script` integration
linked to the script-list dashboard.

Each fixable finding surfaces in one place: as a Repair with the toggle on, or
in a notification with it off (script YAML-key drift has no notification
form). Unmatched include / exclude directives surface as a notification
regardless of the toggle.

**Clearing a finding.** A repair or notification stays until its finding is
fixed or excluded. Once the entity is back at its default ID / name, or an
exclude input covers the finding (see **Exclusion configuration** above), the
next scan removes it. HA's **Ignore** on a repair and dismissing a
notification don't clear the finding, so either one comes back on the next
scan.

**Cap.** Repairs can't be dismissed in bulk in HA's UI, so **Max repairs**
limits the per-run issue count (default 5; 0 = unlimited). Findings over the
cap are counted in a single summary notification; raise the cap, or fix or
exclude the visible issues, to surface more.

Disable **Create repairs** to keep notification-only behavior on this
instance.

## Developer notes

### Entity attributes

After each evaluation, attributes are written to
`blueprint_toolkit.edw_<slug>_state` where `<slug>` derives from the
automation entity_id. Search for `blueprint_toolkit.edw_*_state` in Developer
Tools > States to find it.

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
- `entity_name_issues`: Entities with name drift
- `entity_id_issues`: Entities with ID drift
- `deviceless_entities`: Deviceless entities scanned
- `deviceless_excluded`: Deviceless entities skipped by exclusion filters
- `deviceless_drift`: Deviceless entities flagged as drifted (excludes
  stale-suffix cases)
- `deviceless_stale`: Deviceless entities with stale collision suffixes
- `visible_aliased_total`: Total `switch_as_x` config entries walked
- `visible_aliased_excluded`: Visible-aliased entries skipped via exclusions
  or defensive checks (entry disabled, malformed options, wrapper entity
  missing, source disabled, source already hidden)
- `visible_aliased_flagged`: Visible-aliased findings emitted this run
- `script_yaml_key_flagged`: Scripts flagged for YAML-key drift this run (set
  whether or not **Create repairs** is on, even though the finding only
  surfaces as a repair)
- `unmatched_directives`: Include / exclude directives that bound to zero live
  candidates this run (zero unless **Validate include / exclude directives**
  surfaced something)

### Debug logging

Enable the **Debug Logging** toggle in the blueprint. Debug output appears in
**Settings > System > Logs**, logged at WARNING level (HA's default for custom
components).

Example output for an automation named "Entity Defaults Watchdog":

```text
[EDW: Entity Defaults Watchdog] integrations=12
  devices=45 entities=320 device_issues=2
  entity_issues=5 deviceless_drift=3 deviceless_stale=0
  unmatched_directives=0
```
