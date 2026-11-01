# Reference Watchdog

## Summary

Scans your Home Assistant configuration for broken entity and device
references. Every automation, script, template helper, config-entry helper,
and dashboard is checked against the live entity registry and device registry.
Each source (automation, script, dashboard, helper, YAML entry) that holds a
broken reference gets its own persistent notification with a direct link into
HA's UI where available, and repair hints when the source can only be edited
by hand. Notifications are cleared automatically when the broken references
are fixed.

Also detects *source orphans* -- entity-registry entries whose backing YAML
block or UI-helper record has been removed or renamed, leaving the registry
entry behind. Those are surfaced in a single summary notification with links
to each orphan's integration-filtered entities page for deletion.

## Features

- Scans automations, scripts, template helpers, config entry helpers, lovelace
  dashboards, and every other YAML file reachable via `!include` directives
  from `configuration.yaml` through a single generic-YAML catch-all adapter
- Per-owner persistent notifications with clickable URLs into the HA config UI
  where possible (automation editor, script editor, helpers page, dashboard
  path)
- YAML-only helpers are tagged `(YAML-only)` in the notification body so users
  know to look at the `Source:` line for the filename to edit
- Three complementary detection mechanisms (structural walk, Jinja AST, string
  sniff) with a service-name negative truth set to eliminate false positives
- Optional detection of references to disabled-but- existing entities
  (toggleable from the blueprint)
- Detection of **source orphans** -- registry entries whose backing YAML or
  UI-helper record has been removed -- with a single summary notification
  linking each entry to its filtered entities page for deletion
- Optional detection of **unused devices** -- devices with no entity
  referenced anywhere in your config and no descendant device that is
  referenced -- with a per-device persistent notification listing the device's
  enabled entities for grep-and-confirm
- Optional detection of **unused deviceless entities** -- entity-registry rows
  with no device binding (utility meters, scripts, helpers) that aren't
  referenced anywhere -- as a per-integration rollup notification
- Unified entity exclusion list that applies to both sides (source owner and
  target value)
- Source integration exclusion for bulk-silencing of specific config-entry
  integrations (also silences unused-devices and unused-deviceless-entities)
- Notification cap to limit the number of per-owner notifications
- Optional debug logging

## Requirements

None.

**Optional**: the **File editor** add-on (`core_configurator`, HA OS /
Supervised installs only). When installed, YAML filenames in notification
bodies render as clickable links that open the file in the editor; without the
add-on the same bodies show the filename as a plain `code-spanned` path. See
**File editor add-on links** below.

## Usage

1. Install the automation (see main README)
2. Go to **Settings > Automations & Scenes > Blueprints**
3. Click **Reference Watchdog**
4. Configure exclusions and cap
5. Save and enable

## Configuration

| Parameter                                               | Description                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exclude integrations                                    | Integrations to skip. Matches the integration shown in each notification's header. Built-in adapters (`automation`, `script`, `template`, `customize`, `lovelace`, `person`) are listed as quick-picks in the blueprint UI; config-entry integration domains (e.g. `group`, `homekit`, or whatever is installed in HA) can be added as custom values. Also silences unused-devices and unused-deviceless-entities for the named integrations. |
| Exclude entities                                        | Entities to exclude, applied symmetrically to source and target sides. Also silences source-orphan findings.                                                                                                                                                                                                                                                                                                                                  |
| Exclude entity regex                                    | Multi-line regex, matched against entity and device reference values, applied symmetrically to source and target sides. Also silences source-orphan findings.                                                                                                                                                                                                                                                                                 |
| Enabled checks                                          | Subset of `broken-references`, `source-orphans`, `unused-devices`, `unused-deviceless-entities`. Default set is `broken-references` + `source-orphans`. The two `unused-*` checks are noisier prune-cleanup signals and require explicit opt-in. An empty selection means "all checks" (DW-style empty-means-all).                                                                                                                            |
| Exclude devices by name (regex, multi-line)             | Multi-line regex patterns matched against device names. A matching device is excluded from the unused-devices check (broken-references and source-orphans are unaffected).                                                                                                                                                                                                                                                                    |
| Exclude voice-assistant exposure from the reference set | When enabled, the `homeassistant.exposed_entities` storage scan is skipped from the reference set. By default an entity exposed to a voice assistant counts as "referenced" for the unused-\* checks; enable this if you want voice-only entities surfaced in the unused-\* findings.                                                                                                                                                         |
| Check disabled entities                                 | When enabled, references to entities that exist in the registry but are disabled are reported as "Disabled-but-existing references".                                                                                                                                                                                                                                                                                                          |
| Check interval (minutes)                                | Minutes between reference-integrity evaluations (default 60 -- reference scans do more file I/O than the other watchdogs).                                                                                                                                                                                                                                                                                                                    |
| Max source notifications                                | Notification cap. Default 10. 0 = unlimited. Applied independently to the broken-references per-owner notifications and the unused-device per-device notifications -- each check gets its own cap-summary slot when the cap is reached. The source-orphan summary and the unused-deviceless per-integration rollups are aggregate notifications bounded by HA-platform cardinality and aren't subject to this cap.                            |
| Validate include / exclude directives                   | Default on. Surface typo'd integrations, removed entities, or stale regex lines as a single informational notification. See **Unmatched include / exclude directives** below.                                                                                                                                                                                                                                                                 |
| Debug logging                                           | Log a warning-level stat line on every evaluation.                                                                                                                                                                                                                                                                                                                                                                                            |

See the blueprint UI for default values.

## Usage notes

### Exclusion cheatsheet

Three exclusion axes, each for a specific purpose:

| Want to silence                                      | Use                  |
| ---------------------------------------------------- | -------------------- |
| All config entries from an integration (e.g. `hacs`) | Exclude integrations |
| A specific entity ID you don't want flagged          | Exclude entities     |
| A family of entity IDs matching a pattern            | Exclude entity regex |

**Rule of thumb:** by integration -> integrations. By entity -> entities.

### Owner attribution

Every finding is attributed to an **owner** -- the automation, script, config
block, template entity, dashboard, or generic YAML entry that holds the broken
reference. Notifications are one per owner with a header that includes:

- An `Owner:` line identifying the owner by `config-block[N][.subkey[M]?]`
  position in its file, optionally suffixed with `- <friendly-name>` when a
  human name is available. When the owner has a UI edit page (automations,
  scripts, dashboards, config-entry helpers) the line is a clickable link to
  it; UI-managed `.storage` sources and file-only owners (template entities,
  generic YAML, plants, utility meters) render as plain text and you edit the
  file shown on the `Source:` line
- An `Entity:` line with the registered entity ID when one exists
- An `Integrations:` attribution header when the owner belongs to an adapter
  that knows its integration (automation, script, template, customize,
  lovelace, person, or a config entry domain) -- this is the same value you
  paste into **Exclude integrations** to silence the owner
- A `Source:` line with the source path

Block-path format:

- Top-level YAML list item (automations, template config blocks):
  `config-block[N]`
- Top-level YAML dict entry (scripts, customize, plants, utility meters):
  `config-block[N]` using dict insertion order
- Sub-key list item inside a template config block:
  `config-block[N].<subkey>[M]` (e.g. `config-block[0].sensor[1]`,
  `config-block[0].trigger[0]`)
- Sub-key dict inside a template config block (only `variables:` today):
  `config-block[N].variables`
- JSON-backed sources (`.storage/*`): no block path -- these aren't
  hand-edited

### YAML-only helpers

Some helpers are visible in HA's **Settings > Helpers** page but can only be
edited via YAML -- typically when they're defined in a YAML block like
`utility_meter: !include utility_meters.yaml` rather than through the HA UI's
config flow. The watchdog detects these by checking the entity registry's
`config_entry_id` field: entries with `config_entry_id: null` are YAML-only.

When an owner is YAML-only, its notification body tags the `Entity:` line with
`(YAML-only)` so users know to look at the `Source:` line below for the
filename:

```text
Entity: `sensor.air_filters_energy_monthly` (YAML-only)
Source: `utility_meters.yaml`
```

No clickable URL is generated because HA has no edit page for these helpers.
Open the YAML file in your editor (the `Source:` link opens it directly when
the **File editor** add-on is installed; otherwise the path renders as plain
text), fix the reference, then reload the integration or restart HA.

### Plants and other legacy YAML integrations

Some legacy YAML integrations -- notably older versions of `plant` -- don't
register their entities in the entity registry at all, so adding the
integration name to **Exclude integrations** can miss findings whose owners
end up with `integration=None`. The fallback is **Exclude entity regex** (e.g.
`^sensor\.plant_sensor_`) which silences findings by ref value rather than by
source.

### Source orphans

A *source orphan* is a registry entry whose backing YAML block (or UI-helper
storage record) has been removed or renamed, leaving the registry entry
behind. These entries are invisible to the broken-reference scan because they
still resolve -- the dead entity is still in `entity_ids` -- but nothing
currently creates them.

The watchdog emits a single summary notification titled "Source orphans (N)"
(the dispatcher prepends the automation's friendly name). Orphans are grouped
by `platform` (e.g. `utility_meter`, `input_boolean`, `automation`); larger
groups are shown first. Disabled entities are tagged *(disabled)* next to the
link.

Each orphan links to its integration's filtered entities page (HA has no
single-entity deep link, so the integration filter is the closest one-click
landing). Find your orphan in the narrowed list, click it to open the settings
dialog, and click Delete.

The detector restricts to registry entries with `config_entry_id = null` --
entries managed via the HA config flow are never flagged. The `pyscript`
platform is excluded unconditionally because pyscript-created entities live in
runtime state and don't have a file-based definer.

To silence specific findings:

| Want to silence                        | Use                  |
| -------------------------------------- | -------------------- |
| A single orphan you want to keep       | Exclude entities     |
| A family of orphans matching a pattern | Exclude entity regex |

There's no per-platform silencing toggle -- the full set of known UI-helper
storage files (`input_boolean`, `input_number`, `input_text`, `input_select`,
`input_datetime`, `input_button`, `counter`, `timer`, `person`, `zone`,
`schedule`, and the less-common `automation` / `script` / `scene` / `group`
storage records) is loaded unconditionally on every run. Missing files are
silently skipped.

### Unused-device detection

Off by default. When `unused-devices` is in **Enabled checks**, RW flags
devices with no live reference path. A device is "unused" when ALL of:

- No enabled entity on the device is referenced anywhere RW scans (config
  files, voice exposures, energy dashboard, person card bindings, etc.).
- The device's own `device_id` isn't referenced (e.g. via a `device_id:`-keyed
  automation trigger).
- No descendant device (`via_device_id` chain) is referenced. Cascade-up
  rescues a parent when a child has a reference; cascade-DOWN does NOT rescue
  siblings (Picos on a Lutron Smart Bridge are independent things).

Heuristic guards baked in regardless of opt-in:

- Devices that HA's device registry classifies as service-typed are skipped
  (`DeviceEntry.entry_type == DeviceEntryType.SERVICE`). Integrations set this
  on agents, conversation backends, and other non-hardware "devices" -- the
  reference graph is the wrong question for them by design. Catches `hassio`,
  `hacs`, `homekit`, `spotify`, `anthropic`, `backup`, `sun`, `met`,
  `cert_expiry`, and any future service-style integration without
  per-integration changes.
- Devices on a small fixed set of integrations are skipped explicitly because
  they're hub / transport / companion-app shape but use `entry_type=None` (HA
  classifies them as physical hardware). The set:
  - `homeassistant_sky_connect`, `homeassistant_connect_zbt2`,
    `homeassistant_yellow` -- HA-shipped radio dongles / onboard radios. The
    actual Zigbee / Thread / Matter devices live on `zha` / `matter` without a
    `via_device_id` link back to the dongle, so cascade-up rescue never
    reaches the dongle.
  - `bluetooth` -- Bluetooth adapter integration. Devices here are physical
    adapters; BLE peripherals live on `bthome`, `xiaomi_ble`, etc.
  - `mobile_app` -- HA Companion devices. Most users install the app to access
    HA from their phone rather than to wire the phone's sensors into
    automations.
  - `music_assistant` -- MA registers a device per discovered speaker or
    streaming endpoint, often wrapping an underlying integration's device
    (Sonos, AirPlay, Spotify Connect) without setting `via_device_id`, so
    cascade-up rescue can't reach them. The MA sidebar panel "uses" every MA
    device for its own UI, but that consumer isn't visible to RW's YAML /
    `.storage` scans.
- Devices with zero **visible** enabled entities are skipped. "Visible" =
  enabled in the registry AND not silenced by `exclude_entities` /
  `exclude_entity_id_regex`. Drops BLE proxies, RF radios, and event-only Pico
  remotes (referenced via device_id, never entity_id), plus any device whose
  entire enabled-entity surface the user has already excluded for notification
  purposes.
- Cycle protection on `via_device_id` walks. Real registries have been seen
  containing self-referencing or A-B-C-A cycles; the walk stops on a repeat.

Each per-device notification leads with the shared attribution header --
automation name, the device's integration(s), the device (linked to its
settings page, with its area when it has one), and a config-entry line
carrying the config-entry title (disambiguates multi-instance integrations)
plus manufacturer / model. The body below lists every **visible** enabled
entity on the device. A partially-excluded device's body lists only the
entities the user hasn't already silenced.

To silence false positives:

- **Exclude devices by name (regex, multi-line)** -- per-line regex matched
  against the effective device name (case-insensitive).
- **Exclude integrations** -- silences both unused-devices AND unused-
  deviceless-entities for that integration.
- **Exclude entities** / **Exclude entity regex** -- per-entity silencing also
  drops the owning device once every visible entity is excluded. Useful when
  the same regex you'd use to silence broken-references notifications already
  covers the device's whole entity surface, since a reference to a
  now-invisible device would be a no-op anyway. References to user-excluded
  entities still count as "activity" for the device's rescue check (a
  reference is a reference), so the entity-level exclusion doesn't
  accidentally promote a referenced device to "unused".

### Unused-deviceless-entity detection

Off by default. When `unused-deviceless-entities` is in **Enabled checks**, RW
flags entity-registry rows with `device_id is None` that aren't referenced
anywhere. Output is a **per-integration rollup** notification (one
notification per entity-registry platform: `utility_meter`, `template`,
`script`, `automation`, `input_boolean`, etc.). Each rollup's attribution
header carries the automation name plus a clickable `Integrations:` link to a
useful list-all surface for that integration; the body lists every flagged
entity plus its source. Grouping by integration (rather than by entity domain)
makes the next action obvious -- if an entire rollup is noise for you, add the
integration name to **Exclude integrations**.

Each entity in the rollup body is a clickable link where HA exposes a usable
landing page for it (automation / script editors, a helper's config-entry
entities page); YAML-only entities that HA can't deep-link stay as plain
code-spanned entity_ids, and the `Source:` label points at the file to edit.

Skip-lists baked in regardless of opt-in (these platforms / domains are
user-interactive surfaces or voice-pipeline plumbing, not consumed by other
config):

- Platforms `automation`, `group`, `cloud` are skipped.
- Domains `stt`, `tts` are skipped.

Source resolution priority for each flagged entity:

- Config-entry title when the entity is config-entry-owned.
- A built-in `<platform> -> <yaml-file>` map for YAML-defined entities
  (`utility_meter` -> `utility_meters.yaml`, `script` -> `scripts.yaml`,
  etc.).
- Generic fallback: `(YAML-defined; file not auto-detected)`.

To silence false positives:

- **Exclude entities** -- exact entity_id match (also silences broken-
  references for that target).
- **Exclude entity regex** -- regex match against entity IDs.
- **Exclude integrations** -- silences both unused-\* checks for that
  platform.

### Voice-assistant exposure

By default, an entity exposed to a voice assistant via HA's Voice Assistants
UI (`homeassistant.exposed_entities` storage with at least one
`should_expose: true` entry) counts as "referenced" for the unused-\* checks
-- otherwise every voice-only entity would surface as unused.

Enable **Exclude voice-assistant exposure from the reference set** to drop
that scan, so voice-only entities get flagged. The other extended sources
(`.storage/energy`, `.storage/person`) always run -- they're authoritative
config the user controls directly.

`.storage/person` plays a second, independent role: it is also scanned as a
broken-references owner source (one owner per person), so a person whose
`device_trackers` binding points at a deleted `device_tracker` surfaces as a
broken reference attributed to that person (with the person-management page as
its `Integrations:` link). The extended-reference-set role above (rescuing a
still-valid bound tracker from the unused-\* checks) and this
broken-references role are separate: a valid binding rescues, a dangling one
is flagged.

### File editor add-on links

Every `Source: <path>` line in a notification body is plain text by default,
or a link that opens the file when the **File editor** add-on (slug
`core_configurator`) is installed. Detection is automatic on every scan, with
no toggle or restart. On HA Container / Core, paths stay plain.

`.storage/<x>` paths, which HA's docs warn against hand-editing, and non-file
labels (config-entry titles, the `(YAML-defined; file not auto-detected)`
fallback) always stay plain. The add-on can't deep-link to a line, so the link
opens the file at the top.

### Unmatched include / exclude directives

With **Validate include / exclude directives** on (default), any exclusion
entry that matches nothing in the live scan -- a typo'd integration like
`zwavejs` instead of `zwave_js`, a `sensor.removed_thing` left behind after
deleting the entity, or a regex line that catches nothing -- appears in a
single informational notification. It clears on the next scan once the entry
is fixed or removed, or when you turn the toggle off.

## Developer notes

`custom_components/blueprint_toolkit/reference_watchdog/logic.py` documents
how detection works: its module docstring covers the three mechanisms behind
the `refs_*` counters and the service-name truth set, and source-orphan
detection is documented beside its code.

### Entity attributes

After each evaluation, attributes are written to
`blueprint_toolkit.rw_<slug>_state`. Search for `blueprint_toolkit.rw_*` in
**Developer Tools > States** to find it.

| Attribute                  | Meaning                                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `last_run`                 | ISO timestamp of the most recent successful evaluation                                                                                                                           |
| `runtime`                  | Wall-clock seconds the evaluation took                                                                                                                                           |
| `last_trigger`             | `periodic` for a scheduled scan, otherwise `manual`                                                                                                                              |
| `paths_walked`             | Number of source files the scanner walked this run                                                                                                                               |
| `owners_total`             | Total owners discovered across scanned sources (including owners with zero refs)                                                                                                 |
| `owners_with_refs`         | Owners where at least one reference was detected                                                                                                                                 |
| `owners_without_refs`      | Owners scanned but no references detected -- surfaces detection gaps                                                                                                             |
| `owners_with_issues`       | Owners with at least one broken-or-disabled finding                                                                                                                              |
| `total_findings`           | Broken-or-disabled findings across all owners                                                                                                                                    |
| `broken_entity_count`      | Findings where the target entity is missing from the registry + states                                                                                                           |
| `broken_device_count`      | Findings where the target device ID is missing                                                                                                                                   |
| `disabled_entity_count`    | Findings where the target exists but is disabled (only populated when **Check disabled entities** is enabled)                                                                    |
| `refs_total`               | All references detected (valid + broken + disabled)                                                                                                                              |
| `refs_structural`          | References found via the `_ENTITY_KEYS` structural walk                                                                                                                          |
| `refs_jinja`               | References found via the Jinja AST extraction pass                                                                                                                               |
| `refs_sniff`               | References found via the string sniff pass                                                                                                                                       |
| `refs_service_skipped`     | Sniff- and Jinja-emitted entity-kind refs whose value names a registered service (dropped by the negative truth set; structural emissions at entity-key slots are still flagged) |
| `source_orphan_count`      | Source orphans detected this run                                                                                                                                                 |
| `source_orphan_candidates` | Registry entries eligible for orphan evaluation (`config_entry_id=null`, platform not in the runtime-excluded list). `source_orphan_count` is always a subset.                   |
| `unmatched_directives`     | Include / exclude directives that bound to zero live candidates this run (zero unless **Validate include / exclude directives** surfaced something)                              |
| `unused_devices`           | Devices in the unused-devices candidate pool this run -- registry rows that passed the hardcoded skip list and have at least one enabled entity                                  |
| `unused_devices_excluded`  | Subset of `unused_devices` that the user's `exclude_integrations` or `exclude_device_name_regex` silenced                                                                        |
| `unused_device_count`      | Devices flagged by the unused-devices check this run (a strict subset of `unused_devices - unused_devices_excluded`, after the activity / cascade-rescue check)                  |
| `unused_deviceless_count`  | Deviceless entities flagged by the unused-deviceless-entities check this run, summed across all integrations                                                                     |

**Invariants:**

- `owners_total = owners_with_refs + owners_without_refs`
- `owners_with_issues is a subset of owners_with_refs`
- `total_findings = broken_entity_count + broken_device_count + disabled_entity_count`
- `refs_total = refs_structural + refs_jinja + refs_sniff` (sniff- and
  Jinja-origin service-skipped hits are not counted)

### Debug logging

Enable the **Debug logging** toggle in the blueprint. Debug output appears in
**Settings > System > Logs**, logged at WARNING level (HA's default for custom
components).

Example output for an automation named "Reference Watchdog":

```text
[RW: Reference Watchdog] owners=338 with_issues=43
  findings=85 refs=819 (struct=641 jinja=59 sniff=119
  svc_skipped=13) orphans=9/184 unmatched_directives=0
  unused_devices=12 unused_devices_excluded=3
  unused_device_count=2 unused_deviceless=4
```

`orphans=9/184` means 9 of 184 orphan-eligible registry entries were flagged
as source orphans. The `unused_devices` / `unused_devices_excluded` /
`unused_device_count` triple matches the `total + excluded + flagged` shape
used by DW and EDW: 12 devices entered the candidate pool, 3 were silenced by
`exclude_integrations` or `exclude_device_name_regex`, and 2 of the surviving
9 were flagged as actually unused. `unused_deviceless=4` is the total number
of deviceless entities flagged across the per-integration rollups.

### Known limitations

Documented gaps that won't be fixed in v1 without a design change:

- **Runtime-computed entity IDs** embedded as string literals inside a YAML
  scalar (e.g. a multi-line Python-list-literal
  `monitored_automations: "['automation.foo', 'automation.bar', ...]"` that's
  consumed via a runtime `in` check) aren't caught. Neither the sniff nor the
  Jinja AST pass matches substrings inside non-template strings. Catching them
  would require a regex fallback that introduces false positives in comments
  and descriptions -- we intentionally draw the line at "constant strings we
  can prove statically."
- **`!include` content substitution** is not performed --
  `!include`/`!include_dir_*`/`!secret`/`!env_var` tags are replaced by opaque
  placeholder strings in the parsed tree. However, `!include` and
  `!include_dir_*` targets are followed recursively to discover and scan the
  referenced files as their own sources.
- **Domains absent from the entity registry won't seed refs.** Sniff and Jinja
  walks classify a string as an entity-id only when its domain prefix matches
  a domain HA's entity registry has reported. An integration whose entities
  live under a domain not yet in the registry (a custom integration that
  hasn't created any entities yet, or one whose entities haven't been loaded
  this run) will silently fail to emit refs to those entity_ids. Once the
  integration loads and the registry sees the domain, subsequent runs pick up
  the refs.
- **Voice-exposure scan reads the unified store only.** The voice-exposure
  reference set is harvested from `.storage/homeassistant.exposed_entities`,
  the unified store HA writes for every assistant. Per-assistant cloud configs
  (Google Assistant, Alexa, etc.) maintained as separate storage blobs aren't
  consulted. An entity exposed only via a per-assistant config that bypasses
  the unified store won't be rescued from the unused-\* checks via voice
  exposure -- add it to **Exclude entities** if needed.
- **Some source-orphan false positives.** Object_ids derived by slugifying a
  scene or group `name:` aren't harvested, so a `scene:` block without an
  explicit `id:` appears as an orphan. Give it an `id:` (recommended) or add
  it to **Exclude entities**. A custom integration that stores its identifier
  under a key other than `id`, `unique_id`, or `object_id` false-positives the
  same way.

### Follow-ups

Features worth adding in a later pass:

- **Label and area reference validation.** Walk
  `label_id:`/`labels:`/`area_id:`/`areas:` keys and validate against the
  respective registries.
- **Per-view dashboard attribution.** Drill down inside lovelace configs to
  attribute findings to the specific view rather than the whole dashboard.
