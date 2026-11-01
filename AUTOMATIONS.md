# Automations Guide

Conventions and patterns for the automations shipped by this integration. Read
this when writing a new automation, modifying an existing one, or reviewing
such a change. `DEVELOPMENT.md` covers the dev process.

## Architecture

Automations come in two shapes:

- **Handler-backed** (the majority) -- a three-layer split: a Home Assistant
  blueprint that dispatches to the integration's service handler, the handler
  that wires HA into business logic, and the logic module that has no HA
  dependencies. The rest of this guide -- schema, argparse, service layer,
  spec/lifecycle, handler tests -- describes this shape.
- **Standalone** -- a self-contained blueprint whose `actions:` chain is plain
  Home Assistant YAML. See "Standalone blueprints" below.

### Module layout

Paths use the full service name. The subpackage directory under
`custom_components/blueprint_toolkit/`, the test files under `tests/`, and any
path string in code or docs match `_SERVICE` exactly -- no abbreviations like
`tec/` or `zrm/`. Abbreviations are reserved for log tags
(`_SERVICE_TAG = "TEC"`) and ergonomic Python local aliases
(`from .trigger_entity_controller import handler as tec_handler`).

```text
custom_components/blueprint_toolkit/
+-- __init__.py                # async_setup_entry / async_unload_entry
|                              # initialises entry.runtime_data
|                              # imports + delegates to each handler
+-- helpers.py                 # all shared helpers (see below)
+-- const.py                   # DOMAIN, OPTION_*
+-- <service>/                 # one subpackage per automation
|   +-- __init__.py            # minimal shim: marker + one-line
|   |                          # docstring; no exports
|   +-- logic.py               # decision tree, no HA imports
|   +-- handler.py             # HA wiring (probatio.Schema, service
|                              # handlers, lifecycle mutators,
|                              # spec, register/unregister)
+-- bundled/
    +-- blueprints/automation/blueprint_toolkit/<service>.yaml
    +-- docs/<service>.md
```

Per-port orientation lives in `bundled/docs/<service>.md` (user-facing) and
the `logic.py` / `handler.py` module docstrings (developer-facing), not in the
subpackage `__init__.py`.

### Three-layer dispatch

The handler always splits responsibilities into three async layers. Each layer
either emits a persistent notification and returns, or calls the next layer
directly -- no layer propagates a return value.

1. **Entrypoint** -- the per-handler `_async_entrypoint(hass, call)` function
   that `helpers.register_blueprint_handler` registers as the
   `blueprint_toolkit.<service>` service callback. Sole responsibility is to
   hand off to argparse.
2. **Argparse** -- validates the raw payload and accumulates errors (see
   "Schema + argparse"), emits the config-error notification, and builds a
   `logic.Config` on success.
3. **Service layer** -- reads `hass.states`, calls the pure logic, and applies
   the result (see "Service layer").

### `BlueprintHandlerSpec` -- per-port lifecycle config

Every handler defines a single `_SPEC = BlueprintHandlerSpec(...)` that the
shared `register_blueprint_handler` / `unregister_blueprint_handler` consume.
The dataclass docstring documents each field. All hooks default to `None` and
are independently optional, so set only the ones the handler needs.

### Per-entry runtime data

Per-handler state lives in `entry.runtime_data.handlers[<service>]`, a dict
the shared helpers populate lazily via `spec_bucket(entry, service)`. The
bucket stores:

- `unsubs: list[Callable]` -- bus listener unsubs (the shared dispatcher
  manages this).
- Per-handler keys (e.g. TEC's `instances` map) added by the handler via the
  same bucket accessor.

Cross-reload state (Repairs flow handoff for force-confirmed destinations)
lives separately at `hass.data[DOMAIN]` because it must survive entry unload.

### Z-Wave driver-session monitor

`session_monitor.py` runs one always-on, component-level task (started from
`async_setup_entry`, not per handler) that keeps
`/config/blueprint_toolkit/zwave-js-info.json` current, whether or not any
Z-Wave automation is configured. That module and `zwave/driver_session.py`
document how. The record's `last_reset_at` is the shared source of truth for
"was the driver's queue flushed since I issued a command": a consumer treats
an issued-but-unconverged write as still queued only while it was issued after
the last reset, rather than comparing counters it sampled itself.

Both in-process consumers of the driver select their controller through
`helpers.zwave_js_entry`, so the record's `home_id` and the fleet ZPM
reconciles always name the same controller. A second controller is left
unmanaged. ZRM is not one of these: it reaches zwave-js-ui over HTTP and keys
devices to nodes by `node_id` alone, so it is unscoped by entry. The atomic
write + advisory lock that back both this record and the ZPM pending store
live in `zwave/atomic_json.py`.

## Standalone blueprints

Some automations are simple enough that the three-layer split buys nothing --
the whole behavior fits in blueprint YAML. These ship as **standalone
blueprints**: a single `.yaml` file under
`bundled/blueprints/automation/blueprint_toolkit/` with no handler, no logic
module, and no per-handler test files. The reconciler installs them like any
other blueprint.

The category contract:

- **Marker.** The file's first line is the exact comment
  `# blueprint-kind: standalone`. Handler-backed blueprints carry no marker.
- **No service dispatch.** The `actions:` chain never calls
  `blueprint_toolkit.<service>`.
- **Still fully documented.** A standalone blueprint carries the same
  user-facing doc obligations as any other: a `bundled/docs/<stem>.md` source,
  the rendered HTML, the `[Full documentation]` link in its `description`, and
  a README entry. `tests/test_blueprint_docs.py` and
  `tests/test_docs_rendered.py` enforce these regardless of shape.
- **Tested by a structure test, not a schema-drift test.** Instead of
  subclassing `BlueprintSchemaDriftBase`, a standalone blueprint gets a
  `tests/test_<stem>.py` that loads the YAML and pins the marker, the input
  surface, the `mode`, and the absence of any `blueprint_toolkit.<service>`
  dispatch.
- **Restart resilience is the blueprint's responsibility.** Handler-backed
  automations get the integration's `recover_at_startup` for free; standalone
  blueprints do not. When a standalone blueprint has state that should survive
  an HA restart (an in-flight `repeat` loop, an active timer, etc.), add a
  `homeassistant: start` trigger and gate the actions so the recovery path
  only runs when appropriate.

`trigger_alert_controller` is the reference example. Reach for a standalone
blueprint only when there is genuinely no business logic worth unit-testing in
isolation -- anything with a non-trivial decision tree, cross-field
validation, or state that must survive a restart belongs in the handler-backed
shape.

## Shared helpers (`helpers.py`)

All handlers consume these. Don't reimplement; if a new pattern keeps
recurring, hoist it here. Each helper's docstring is its contract; this list
is for finding the right one.

Behind the shim, helpers live in three flavour files per their HA-dependency
profile: `helpers_logic.py` (pure -- no HA imports of any kind, including
`TYPE_CHECKING`), `helpers_runtime.py` (runtime-HA -- takes a runtime `hass`
argument; HA imports only under `TYPE_CHECKING`), and `helpers_lifecycle.py`
(lifecycle / setup -- function-body HA imports OK; module-scope HA imports
must be `TYPE_CHECKING`). Add a new helper to the file matching its profile.
Only when an automation consumes it, add it to both that file's `__all__` and
`helpers.py`; framework-internal and test-only symbols stay out of both and
are imported directly from the flavour file. `tests/test_helpers_lifecycle.py`
enforces the import rules and that the shim's `__all__` is the union of the
flavour files'.

Schema + validation:

- `cv_ha_domain_list` -- probatio validator for a list of HA domain names.
- `validate_and_join_regex_patterns` -- the canonical multi-line regex parser;
  returns a `JoinedRegexResult` (`JoinedRegexLine` per valid line).
- `validate_payload_or_emit_config_error` -- run a `probatio.Schema`; on
  failure, emit the config error and return `None`.
- `CONTROLLABLE_DOMAINS` / `validate_controlled_entity_domains` -- the domains
  that respond to `homeassistant.turn_on` / `turn_off`, and the per-entity
  config-error check against them.

Cross-handler accessors:

- `entry_for_domain` -- the integration's lone config entry, or `None`.
- `zwave_js_entry` -- the first *loaded* `zwave_js` config entry, or `None`.
- `notification_prefix` -- the per-instance notification ID prefix.
- `all_integration_ids` / `integration_entity_ids` -- entity-registry walks
  that seed watchdog truth sets.
- `integration_device_ids` -- the devices an integration has an entity on. An
  excluded integration excludes the whole device, not just its own entities.
- `device_area_name` -- the name of a device's area, or `None`. Handlers pass
  it to logic for `DeviceRef.area`.
- `voice_exposed_entity_ids` -- the entities exposed to any voice assistant.
  Reference Watchdog counts them as referenced.
- `resolve_target_integrations` -- apply include / exclude filters; empty
  `include` means "all".
- `filter_on_entities` -- the subset of entities currently `on`, so a turn-off
  targets and reports only what it changes.
- `entity_friendly_names` -- map entities to friendly names, omitting those
  without one.
- `file_editor_addon_ingress_url` -- the File editor add-on's ingress URL
  prefix, or an empty string. Cheap, so call it per evaluation.

Notification + formatting:

- `format_timestamp` / `format_notification` -- `YYYY/MM/DD/HH/mm/ss` token
  expansion, and wrapping a body with a formatted prefix + suffix.
- `md_escape` -- escape a user-controlled string for a notification body.
- `slugify` -- derive an HA-safe slug from arbitrary text.
- `matches_pattern` -- case-insensitive substring or regex test, safe on a bad
  regex.

Directive validation (watchdogs):

- `validate_directives_item` / `validate_directives_regex` -- check exact
  identifiers or per-line regexes against candidates, each mismatch becoming
  an `UnmatchedDirective`.
- `make_unmatched_directives_notification` -- spec builder; an empty list
  gives an inactive spec, so handlers dispatch unconditionally.

Per-handler logic modules compose these in their own
`_validate_<service>_directives` function called from `run_evaluation`. The
validator derives its candidate sets from the same data the actual exclusion
code operates on, so a regex line gets flagged as unmatched precisely when it
wouldn't filter anything.

Notifications + repairs:

- `PersistentNotification` / `DeviceRef` -- the spec for a create or dismiss,
  and the resolved device context for its attribution header.
- `attribution_lines` / `integration_attribution_link` -- the dispatcher-side
  header renderers; handlers set spec fields rather than calling these.
- `FixService` / `Issue` -- the wire payload a repair carries, and the typed
  base for its translation contract (see "Repairs").
- `process_persistent_notifications` -- dispatcher; skips a create whose title
  and message are unchanged, so unchanged notifications don't bubble up the
  panel on every scan.
- `process_persistent_notifications_with_sweep` -- also dismisses prior-run
  notifications under the prefix that aren't in the current batch.
- `process_repairs_with_sweep` -- routes a batch between the issue registry
  and notifications (see "Repairs").
- `make_config_error_notification` / `emit_config_error` /
  `make_emit_config_error` -- spec builder, builder + dispatcher (safe to call
  unconditionally), and the per-handler closure factory.
- `prepare_notifications` -- sort + cap `CappableResult` objects; always emits
  a cap-summary slot.

Diagnostic state:

- `instance_state_entity_id` / `update_instance_state` -- derive the state
  entity ID, and write it.
- `automation_friendly_name` -- automation entity_id to user-set friendly name
  (used for `[ZRM: My Cool Automation]` log tags).

Lifecycle wiring:

- `BlueprintHandlerSpec` / `spec_bucket` -- per-handler config, and its slot
  under `entry.runtime_data.handlers[service]`.
- `register_blueprint_handler` / `unregister_blueprint_handler` -- wire up and
  tear down service, listeners, and restart-recovery. Registration also
  surfaces any unhandled handler exception as a per-instance `__crash`
  notification, auto-cleared on the next successful run.
- `schedule_periodic_with_jitter` -- per-instance jittered periodic scheduling
  through an entry-scoped task.
- `make_periodic_trigger_callback` -- the canonical periodic
  `automation.trigger` callback.
- `make_lifecycle_mutators` -- the `LifecycleMutators` bundle for a spec.

## Schema + argparse

### Aggregate, never bail-on-first

Every validation path in argparse accumulates problems into a single `errors`
list and emits them all in one `config_error` notification. Bailing on the
first failure forces the user to play whack-a-mole.

- Run schema validation through
  `helpers.validate_payload_or_emit_config_error(hass, raw, _SCHEMA, _emit_config_error)`
  and short-circuit on `None`. Don't write the try / except block manually;
  the helper surfaces every schema error in one notification.
- Cross-field validation (no overlapping entity sets, etc.) appends to
  `errors`; never `return` mid-validation.
- HA-state validation (entities exist, sun.sun is available if any time-of-day
  input is non-`always`) appends to the same list.
- Single `await emit_config_error(...)` at the end of argparse with the
  accumulated `errors`. An empty list dismisses any prior notification.

### Schema shape

Use `probatio.Schema({...}, extra=probatio.ALLOW_EXTRA)`.
`extra=probatio.ALLOW_EXTRA` is intentional for forward-compat with future
blueprint inputs -- document, don't silently flip to `PREVENT_EXTRA`.

Schema covers shape only. Cross-field rules + HA-state validation belong in
argparse. Period / event / enum value lists derive from the logic-side enums
(no hardcoded duplicate string lists).

### Common argparse landmines

Each one of these shipped a regression in at least one automation:

- **Multi-line text inputs.** Blueprint fields backed by
  `selector: text: { multiline: true }` arrive as a single string with literal
  `\n` chars. Naive parses (`re.compile(raw)` for a regex list,
  `raw.split(",")` for a comma list) silently fail because the whole
  multi-line string is treated as one token. Use
  `helpers.validate_and_join_regex_patterns` for regex lists; for other
  multi-line inputs split + strip + drop empties explicitly, then validate
  each line.
- **Regex inputs that match the empty string.** `.*`, `|||||`, `a?` all match
  `""` and would silently exclude every entity.
  `helpers.validate_and_join_regex_patterns` rejects these.
- **Solution-oriented error messages.** When a missing dependency can be
  installed (sun.sun, an addon), tell the user *how* to fix it. "X is missing"
  is bad; "X is missing -- to fix, install Y or change Z" is good.

## Service layer

The service layer's call flow is uniform across handlers:

1. Capture `started = time.monotonic()` at top, for the `runtime` diagnostic
   attr.

2. Read `hass.states` into a `logic.Inputs` dataclass.

3. Call `logic.evaluate(config, inputs)`. The logic layer is pure; this call
   is synchronous and never reaches HA.

4. Apply the returned `Result`: dispatch `homeassistant.turn_on` / `turn_off`,
   schedule / cancel auto-off via `async_call_later`, post any notification.

5. Persist the outcome via `update_instance_state` (the only diagnostic-state
   write):

   ```python
   update_instance_state(
       hass,
       service_tag=_SERVICE_TAG,
       instance_id=instance_id,
       last_run=now,
       runtime=time.monotonic() - started,
       state=result.action.name,  # or "ok"
       extra_attributes={...},  # per-handler
   )
   ```

Common state attrs are exactly three: `instance_id`, `last_run`, `runtime`.
Everything else is per-handler. The state value defaults to `"ok"`;
trigger-driven handlers override it with the decision name.

### Action dispatch

`homeassistant.turn_on` / `turn_off` calls propagate `context=call.context`
(`blocking=False`); inline the call rather than adding a per-handler wrapper.
Auto-off scheduling (if applicable) cancels the prior wakeup before arming a
new one.

### Service-layer exit ordering

Every handler's service layer composes the same five operations in the same
order. A handler that doesn't need a step skips it.

1. **Sweep PNs.** Dispatch the per-instance notification set for this run via
   `process_persistent_notifications_with_sweep`, or
   `process_repairs_with_sweep` when the handler emits a mix of repair +
   notification specs (EDW + DW).
2. **Update state.** Write the diagnostic state entity.
3. **Action dispatch.** `homeassistant.turn_on` / `turn_off` / etc, for
   handlers that drive entities.
4. **Debug log.** A single line at the end, not interleaved through the scan
   (see "Debug logging").
5. **Return ServiceResponse.** See below. Watchdog handlers return `None`.

#### Response-variable convention

Notify dispatch is owned by the calling blueprint, not the handler. A handler
whose notification surface is "call the user's notify endpoint with a
pre-built body" (STEC, TEC) sets `supports_response=SupportsResponse.OPTIONAL`
on its spec and returns `{"notification_message": "<body>"}` -- an empty
string on no-op evaluations. The blueprint pairs the call with
`response_variable: result` and a `choose` that fires `!input notify_action`
only when `result.notification_message` is non-empty, with `message` exposed
as a top-level variable so each step can reference `{{ message }}`.

That leaves the choice of endpoint (`notify.*`, a notify group, a script, any
combination) to the blueprint UI's action picker. The state save runs before
the handler returns, so a notify-action failure cannot lose controller state.
Watchdog handlers (DW, EDW, RW, ZRM, ZPM) don't use this: their surface is
`persistent_notification`, an HA-side render, and is therefore handler-owned.

### Async tasks must be entry-scoped

Async tasks scheduled by the handler must be entry-scoped, not hass-scoped.
Use `entry.async_create_background_task(hass, coro, name)` so HA cancels
in-flight work on entry unload; never `hass.async_create_task(coro)` (which
leaves work running detached against a torn-down service registration).

Every handler with a periodic timer (DW, EDW, RW, STEC, ZRM, ZPM) arms it via
`helpers.schedule_periodic_with_jitter`, which wraps each tick in that
entry-scoped task and adds per-instance jitter. TEC has no periodic timer --
only a one-shot `async_call_later` auto-off wakeup. Raw
`async_track_time_interval` is **not** the canonical pattern in a handler. If
a case genuinely needs it, pass a sync `@callback` wrapper that creates the
entry-scoped task yourself -- passing the async action directly routes
subsequent ticks through HA's internal `hass.async_create_task`, defeating the
scoping.

## Spec + lifecycle

- **Per-instance state dataclass** (e.g. `<Service>InstanceState`) with
  `instance_id`, the cancel-callable for any pending work (`cancel_timer` for
  periodic handlers, `cancel_wakeup` for one-shot TEC), and ONLY transient
  state. Diagnostic fields go through `update_instance_state`, not on the
  dataclass.
- **`_instances(hass)` accessor** that resolves the single entry via
  `hass.config_entries.async_entries(DOMAIN)[0]`, then
  `spec_bucket(entry, _SERVICE).setdefault("instances", {})`. Returns `{}`
  when no entry is loaded.
- **Periodic-tick callback** -- if the handler runs a periodic scan, call
  `helpers.make_periodic_trigger_callback(...)` (kwargs:
  `instances_getter=_instances`, `service_tag=_SERVICE_TAG`, `logger=_LOGGER`,
  optional `extra_variables=`) inside `_ensure_timer` and hand the result to
  `helpers.schedule_periodic_with_jitter`. A single failed tick is
  self-healing, so the helper logs it and carries on.
- **Restart-recovery kick** -- handlers that need restart-recovery set
  `kick_variables=` on `_SPEC` to a flat `automation.trigger` variables dict
  (e.g. `{"trigger_id": "manual"}` for the watchdogs, TEC's synthetic TIMER
  `{"trigger_entity_id": "timer", "trigger_to_state": ""}`). The dispatcher
  fires it against every discovered automation on HA-started + reload events,
  skipping any that are currently disabled.
- **Mutator callbacks** -- one `helpers.make_lifecycle_mutators(...)` call
  (kwargs: `instances_getter=_instances`, `cancel_field=...`,
  `service_tag=_SERVICE_TAG`, `logger=_LOGGER`, optional
  `reset_armed_interval_on_reload=`) returns a `LifecycleMutators` dataclass.
  Bind each mutator to a module-level alias
  (`_on_reload = _MUTATORS.on_reload`, etc.) and reference the aliases from
  `_SPEC`; per-handler unit tests call them directly. Don't hand-roll the four
  `@callback` functions.
- **`_SPEC = BlueprintHandlerSpec(...)`** -- only set the hooks the handler
  actually needs.
- **`async_register(hass, entry)`** and **`async_unregister(hass, entry)`**
  are one-line delegations to `register_blueprint_handler` /
  `unregister_blueprint_handler`.

`reset_armed_interval_on_reload=True` is for handlers whose `_ensure_timer`
re-arm decision compares against `armed_interval_minutes`.

`cancel_field` cancels exactly ONE callable. A handler that holds a second
teardownable resource per instance -- e.g. ZPM's `cancel_dispatcher`
unsubscribe alongside `cancel_timer` -- keeps `on_entity_rename` as the bare
`_MUTATORS` alias and defines thin `@callback` wrappers for `on_reload` /
`on_entity_remove` / `on_teardown` that cancel the extra callable(s) first and
then delegate to the matching `_MUTATORS` method.

### Disabled automations

Scans are integration-driven (the per-instance periodic timer and the
restart/reload recovery kick), not driven by the blueprint's own triggers.
HA's `automation.trigger` runs an automation's action sequence regardless of
the automation's on/off state, so without an explicit guard a disabled
watchdog would keep scanning and emitting notifications. Every
synthetic-trigger call site therefore gates on
`automation_enabled(hass, instance_id)` (False only when the automation's
entity state is explicitly `"off"`):

- The periodic tick (`make_periodic_trigger_callback`) no-ops while disabled
  -- the steady-state timer keeps ticking, so a mid-session re-enable resumes
  on the next tick.
- The recovery kick (`recover_at_startup`) skips disabled automations, so a
  disabled watchdog does not scan once per HA restart.

Because HA fires no reload event on an enable/disable toggle (only a state
change), `register_blueprint_handler` also arms an
`async_track_state_change_event` tracker that re-kicks an automation on an
`off -> on` transition. That is the only resume path for a watchdog left
disabled across a restart, where the skipped recovery kick armed no timer.
Disabling stops new scans but does not sweep prior findings, and a manual
`automation.trigger` (UI "Run") on a disabled automation still runs, since it
reaches the handler entrypoint directly.

## Blueprint YAML

- **Periodic scheduling is integration-owned, not blueprint-owned.** Don't add
  `time_pattern` / `time` triggers to the blueprint. When a blueprint has only
  synthetic triggers, still emit an empty `triggers: []` block: a blueprint
  with no `triggers:` key at all parses but HA renders the resulting
  automations as `unavailable`, the recovery kick never fires, and no scan
  runs after deploy.
- **No `homeassistant: start` / `homeassistant: shutdown` triggers** in
  handler-backed blueprints. The integration's startup-recovery hook and
  reload listener already kick every discovered automation.
- **Handler-backed blueprints: `action:` calls
  `blueprint_toolkit.<service>`.**
- **Synthetic-trigger overrides are flat top-level variables.** HA's
  `automation.trigger` service unconditionally overwrites the `trigger` key in
  caller-supplied `variables` with `{"platform": None}` (see
  `homeassistant/components/automation/__init__.py`'s
  `trigger_service_handler`), so anything passed as
  `variables: {"trigger": {...}}` is silently dropped. Pass flat keys instead
  (e.g. `trigger_id`, `trigger_entity_id`); have the blueprint action read
  them via `is defined` / `default(...)` patterns, falling back to `trigger.*`
  for real native-trigger paths. Concrete examples: ZRM's
  `trigger_id: "{{ trigger_id | default('manual', true) }}"`; TEC's
  `trigger_entity_id` / `trigger_to_state` is-defined chain.
- **Add a regression test** in `tests/test_<service>_handler.py` for every
  `automation.trigger` call site: assert the `variables` payload's shape AND
  that `"trigger"` is NOT a key in it.
- **`automation.trigger` re-fire MUST NOT pass `context=`**. HA's automation
  runner needs to generate a fresh per-run context for proper logbook
  attribution.
- **Document any `mode: queued` / `max:` in a YAML comment.** Silent drops
  above the cap surprise users.
- **Selector restrictions are UI-only; argparse validates domains
  independently.** A `selector: entity: { domain: [switch, light, fan] }`
  restricts the HA UI's entity picker, but a hand-edited automation YAML can
  pass any entity. Argparse must validate the domain of every entity input --
  via `probatio.In([...])` in the schema or a cross-field check. For on/off-
  driving handlers, call `helpers.validate_controlled_entity_domains`;
  otherwise a YAML-edited entity reaches `homeassistant.turn_on` and silently
  no-ops. Trigger / disabling / observed entities are not subject to that
  check (they're observed, not actuated).

## Notifications

- Use friendly names (not raw entity IDs) in all user-facing notification
  messages.
- **Attribution header.** Every spec sets `instance_id` (the automation
  entity_id); findings about a device or integration also set `integrations=`
  and / or `device=<DeviceRef>`. The dispatcher prepends a shared header --
  `Automation:` / `Integrations:` / `Device:` / `Config Entry:`, each line
  present only when its field is set -- to the notification body, and feeds
  the same header into the repair confirm modal's `{attribution}` placeholder.
  `integrations` is independent of `device`, so a deviceless finding reports
  its integration with no device id. Handlers set fields, not body lines.
- **Apply `helpers.md_escape(...)` to every user-controlled string going into
  a notification body.** Persistent notifications render through
  `<ha-markdown>`, so stray `[` / `]` / `\` can corrupt the rendering. Apply
  it to friendly_names, probatio.Invalid messages (which can echo the
  offending input back), error messages from external APIs, YAML location
  strings, etc. Constants, values inside backtick code spans, and notification
  TITLES (HA renders those as plain text) are exempt.
- **Notification IDs follow
  `blueprint_toolkit_{service}__{instance_id}__{kind}`**, e.g.
  `blueprint_toolkit_dw__automation.bath_fan__config_error`. `__` is the
  reserved field separator; HA entity_ids can never contain `__` so the format
  stays parseable. Two `{kind}` slots fire for every handler: `__config_error`
  (managed by `emit_config_error`) and `__crash` (managed by
  `register_blueprint_handler`). Other `{kind}` values are per-handler. Repair
  fix-service crashes use a separate scheme:
  `blueprint_toolkit__{service_name}__crash__{target}` (no `instance_id`; the
  crash means the fix service is broken, not the automation that emitted the
  repair).
- **Pick the right dispatcher.** Use
  `process_persistent_notifications_with_sweep` when the caller is asserting
  the COMPLETE per-instance notification state for this run. Use the bare
  `process_persistent_notifications` when touching a single known ID (e.g.
  `emit_config_error`), so the call doesn't collateral-dismiss findings from
  other categories.

## Repairs

Findings whose fix is deterministic + automatable can route to HA's Repairs UI
as one-click Fix issues instead of as persistent notifications.

- **One surface per finding.** The logic chooses notification-vs-repair at
  build time from `config.create_repairs`, so a fixable finding is emitted on
  exactly one surface -- never both. The per-backend sweep clears the other
  surface when the toggle flips.
- **Repair spec.** A `FixService` in `PersistentNotification.repair_callback`
  marks a spec as a repair. It carries only the service name + the repair's
  `notification_id`, because the issue registry's `data` holds flat JSON
  primitives; the rich payload (entity lists, rename targets) lives on the
  handler's instance state keyed by that id. Each handler's `logic.py` defines
  a `FixServices(StrEnum)` of its service names.
- **Dispatcher.** `process_repairs_with_sweep` replaces
  `process_persistent_notifications_with_sweep` for handlers emitting fixable
  findings. It returns the set of published repair `notification_id`s so
  handlers can prune their per-repair state to what's reachable.
- **Cap.** `repair_cap > 0` keeps the visible repair count manageable (HA's
  Repairs UI has no bulk-dismiss). Specs above the cap coalesce into a single
  per-instance cap-summary **notification**, not a repair issue
  (`{prefix}cap_summary`), which is always dispatched so it auto-dismisses
  when the next run is back under cap.
- **A finding stays until it is fixed or excluded.** A watchdog's exclude
  inputs are the only supported way to suppress a finding, so every check
  honors every exclude input that applies to it, and the next scan clears what
  an exclude newly covers. HA's Ignore and notification dismissal are not
  suppression: an ignored repair or dismissed notification comes back on the
  next scan.
- **Fix services.** Each repairable finding kind backs a service registered
  from each handler's `async_register_fix_services` via
  `helpers.register_fix_service(hass, service_name, handler)`, which owns the
  whole fix-service contract. A handler supplies only
  `async def (notification_id: str) -> None`, which looks up its payload and
  applies it verbatim (no re-scoping -- the scan that built the payload had
  the user's full filter configuration in scope). A device with N drifted
  entities is one Submit, not N. Deviceless findings have no device to group
  under, so they emit one repair per entity, and both shapes can share one fix
  service.
- **Issue ID format.**
  `blueprint_toolkit_{service}__{instance_id}__repair_{fix_service_name}__{target}`,
  built via `helpers.repair_notification_id`. The final `{target}` is the
  grouping key: a `device_id` for device-grouped repairs, or the `entity_id`
  for ungrouped ones. The `__repair_` substring is what
  `repairs.async_create_fix_flow` routes on to pick the `WatchdogFixFlow` over
  the install-time flows.
- **Attribution.** A repair spec carries the same `instance_id` /
  `integrations=` / `device=` as a notification. Every repair's `confirm`
  description in `strings.json` / `translations/en.json` must lead with
  `{attribution}\n\n`.
- **Confirm-step titles stay short and static** -- a plain action phrase
  (`Re-enable diagnostic entities?`, `Rename the scripts.yaml block key?`)
  with NO `{placeholder}` values. HA renders the fix-flow title in a
  fixed-height dialog header; a long or interpolated title wraps and renders
  over the subtitle. Per-finding specifics go in the confirm description.
- **Translations.** Each issue is codified by a frozen `helpers.Issue`
  subclass in the module that raises it (a watchdog's `logic.py`, or
  `__init__.py` for the install issues) and exported there in an `ISSUES`
  tuple. The subclass sets `KEY` and one `str` field per `{placeholder}`.
  Builders pass `translation_key=<Cls>.KEY` and
  `translation_placeholders=asdict(<Cls>(...))` rather than a raw key and
  dict, so a mistyped placeholder is a `mypy` error. `tests/test_issues.py`
  checks each `ISSUES` entry against both JSON files. When adding an issue,
  define its subclass, add it to the module's `ISSUES` (and the test's union
  if it's a new module), and add the matching `issues.<key>` entry to both
  JSON files.
- **Placeholder content.** Per-device findings pass an `{entities}`
  placeholder -- a markdown list of the affected entities, mirroring the
  per-device notification body. Single-entity findings pass the fields they
  need instead.

## URL generation

Every URL emitted in a notification body, log line, or stored data field goes
through a helper in `helpers.py`. No inline `f"/config/.../{x}"` templates --
per-call-site URL guessing has shipped multiple regressions because HA's
frontend routing doesn't accept the obvious entity-id-style filters.

Two flavours of helper:

- **`*_link(name, ...)` wrappers** return markdown-ready `[name](url)` text,
  with `name` `md_escape`d. Use these for notification-body links.
  `file_editor_link(path, ingress_url)` is called for every source-file path
  and returns either a link or a bare code span, so call sites stay agnostic
  of whether the add-on is installed. `deviceless_entity_link` returns prose,
  because HA's frontend has no entity-id URL filter: a single deviceless
  entity can't be deep-linked to a one-row view.
- **`*_url(...)` raw URL functions** are reserved for call sites that need a
  URL separated from its rendering -- e.g. storing a URL on a dataclass for
  later assembly, or a link whose visible text is a code span.

The `helpers_logic.py` "URL + link helpers" section enumerates the
verified-working URL forms. When adding one, put both the raw `*_url` and the
`*_link` in `helpers_logic.py`, re-export both from `helpers.py`, and use the
`*_link` variant at call sites.

## Debug logging

Each handler honours a per-instance `debug_logging` blueprint input. When
true, the service layer emits one `_LOGGER.warning` line summarising the run
-- event, action, key state values, reason -- using the service's tag prefix:

```python
auto_name = automation_friendly_name(hass, instance_id)
tag = f"[{_SERVICE_TAG}: {auto_name}]"
if debug_logging:
    _LOGGER.warning("%s event=%s ...", tag, ...)
```

Log level is `WARNING` because Home Assistant's default log level for custom
components is `WARNING`; `_LOGGER.info` would be silenced by default and the
user wouldn't see the toggle's effect.

## State persistence

Per-instance state lives in memory, in `_instances(hass)`, and is volatile
across HA restarts. The diagnostic state entity is for **observability**, not
authoritative state, though its `data` attribute is sometimes used to
round-trip state across calls (STEC's controller-state JSON blob is the
example).

When the in-memory state is lost (HA restart, integration reload), handlers
re-bootstrap on the next call. The bootstrap path should:

1. Recognise the lost-state condition (typically the instance isn't in
   `_instances(hass)`, or the persisted blob is `None` / malformed).
2. Re-arm any safety-relevant timers (e.g. STEC's auto-off bootstrap-arm: if
   the controlled entity is currently `on` and auto-off is enabled, arm
   `auto_off_started_at` immediately so the device doesn't get stuck on
   indefinitely).
3. Continue with the normal evaluation.

## Testing

### File layout per handler

```text
tests/
+-- test_<service>_logic.py          # logic.py unit tests
+-- test_<service>_handler.py        # handler-side wiring + mutators
+-- test_<service>_integration.py    # pytest-HACC end-to-end
```

### Schema-drift test

In `tests/test_<service>_handler.py`, subclass `BlueprintSchemaDriftBase` from
`tests/conftest.py`. Two class vars: `handler = handler` and
`blueprint_filename = "<service>.yaml"`. The base provides both tests:

- `test_yaml_data_keys_match_schema_required_keys` -- symmetric set diff
  between blueprint YAML's first `action: data:` keys and `_SCHEMA`'s
  `probatio.Required` keys.
- `test_blueprint_action_targets_registered_service` -- blueprint's `action:`
  line is `blueprint_toolkit.{_SERVICE}`.

This is the single test that catches the most bugs across the handlers; add it
to every new handler.

### Cross-port service-registration test

Add `<service>` to the `expected` set in
`tests/test_integration.py::TestSetupEntry::test_setup_registers_services`.

### Integration test coverage

For each handler, `tests/test_<service>_integration.py` should cover at
minimum:

- Schema-rejection emits persistent notification.
- Cross-field overlap / missing-entity all emit notifications with the right
  ID + message.
- Successful call dismisses any prior config-error notification.
- Notification body starts with
  `Automation: [name](/config/automation/edit/<id>)\n` when the automation
  entity is registered.
- `md_escape` lands end-to-end (e.g. `[` in friendly name becomes `\[` in
  body).
- Service layer dispatches the right downstream call (`homeassistant.turn_on`,
  etc.).
- Diagnostic state entity created with common attrs (`instance_id`,
  `last_run`, `runtime`) + per-handler extras.
- `EVENT_AUTOMATION_RELOADED` triggers a fresh discovery scan.
- `EVENT_HOMEASSISTANT_STARTED` recovery log fires on setup.

A handler that emits repairs also subclasses `WatchdogFindingLifecycleBase`
from `tests/conftest.py`, which gates "a finding stays until it is fixed or
excluded" (see "Repairs") on both surfaces against HA's real registries. List
every `exclude_*` input the handler offers in its `exclusions`.

### Code quality

- No `# mypy: ignore-errors` in handler.py before considering complete.

## Naming conventions

- `_SERVICE` -- snake_case slug, e.g. `"trigger_entity_controller"`.
- `_SERVICE_TAG` -- short tag for log lines + notification titles, e.g.
  `"TEC"`.
- `_SERVICE_NAME` -- human-readable, e.g. `"Trigger Entity Controller"`.
- State entity ID: `blueprint_toolkit.{service_tag}_{slug}_state`, e.g.
  `blueprint_toolkit.tec_kitchen_lights_state`. Pass the uppercase
  `_SERVICE_TAG`; the helper lowercases it. HA's entity-id regex bans `__`, so
  single `_` is the only viable separator.
- `_raw` suffix applied to schema-validated input fields whose parsed form is
  rebound without the suffix in argparse, e.g. `default_route_speed_raw` ->
  `default_route_speed`.
- Watchdog include / exclude blueprint inputs use the prefix-style
  `include_<thing>` / `exclude_<thing>` naming (NOT
  `<thing>_exclude_<thing>`). When two blueprints take a directive that
  matches the same underlying thing they use the SAME variable name (e.g. DW,
  EDW, and RW all use `exclude_entity_id_regex`).

Booleans use `helpers`-side coercion via `cv.boolean`; never hand-roll string
comparison.

Time units in input names + variable names use full words: `_seconds`,
`_minutes`. Never `_s` / `_m` / `_min`.

User-facing enum values (exposed in blueprints) use dashes: `"night-time"`,
`"day-time"`, `"triggered-on"`, `"auto-off"`.

## User-facing docs

Each automation has a user-facing markdown doc at
`custom_components/blueprint_toolkit/bundled/docs/<service>.md`, rendered to
HTML and served at `/local/blueprint_toolkit/docs/<service>.html` so the
blueprint can link to it from its `description`. `DEVELOPMENT.md` covers the
rendering pipeline.

### Section order

Every automation doc follows the same top-level section order so users find
the same information in the same place across automations:

1. **Summary** -- one paragraph describing what the automation does.
2. **Features** -- bulleted list of capabilities.
3. **Requirements** -- prerequisite HA config.
4. **Usage** -- install + enable steps.
5. **Configuration** -- blueprint input table.
6. **Usage notes** -- examples, exclusion cheatsheets, behavior gotchas, and
   any user-facing detail that doesn't fit under Configuration.
7. **Developer notes** -- state attributes, debug log format, known
   limitations, follow-ups, and short design notes that help interpret them.
   The full account of a detection or reconcile mechanism belongs in its
   module docstring, so summarize it here at most. A standalone blueprint has
   no module, so its doc carries those details.

User-facing sections come first so users don't have to scroll past developer
notes to find their config.

Don't introduce new top-level sections. Anything that doesn't fit an existing
bucket goes under "Usage notes" (if user-facing) or "Developer notes" (if
internal) as a sub-heading.

Configuration / attribute reference tables stay as markdown tables; the
"prefer lists over tables" rule exempts docs read mainly in HTML.
