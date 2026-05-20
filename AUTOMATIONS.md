# Automations Guide

Conventions and patterns for the automations shipped by this integration. Read
this when writing a new automation, modifying an existing one, or reviewing
such a change.

The companion `DEVELOPMENT.md` covers dev-process content (code review, doc
hygiene, testing, releases). This file documents conventions and patterns
specific to the automations themselves.

## Architecture

Automations come in two shapes:

- **Handler-backed** (the majority) -- a three-layer split: a Home Assistant
  blueprint that dispatches to the integration's service handler, the handler
  that wires HA into business logic, and the logic module that has no HA
  dependencies. The rest of this guide -- schema, argparse, service layer,
  spec/lifecycle, handler tests -- describes this shape.
- **Standalone** -- a self-contained blueprint whose `actions:` chain is plain
  Home Assistant YAML, with no `blueprint_toolkit.<service>` dispatch, no
  handler or logic subpackage, and no schema-drift test. It ships through the
  same bundled blueprints directory and is installed by the reconciler
  identically. See "Standalone blueprints" below for the category contract.

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
|   +-- handler.py             # HA wiring (vol.Schema, service
|                              # handlers, lifecycle mutators,
|                              # spec, register/unregister)
+-- bundled/
    +-- blueprints/automation/blueprint_toolkit/<service>.yaml
    +-- docs/<service>.md
```

Per-subpackage `__init__.py` files are minimal shims (see any of the existing
subpackages for the canonical shape). Per-port orientation (module layout,
public surface, behaviour summary) lives in `bundled/docs/<service>.md`
(user-facing) and the `logic.py` / `handler.py` module docstrings
(developer-facing). The subpackage `__init__.py` deliberately doesn't repeat
that content.

### Three-layer dispatch

The handler always splits responsibilities into three async layers. Each layer
either emits a persistent notification and returns, or calls the next layer
directly -- no layer propagates a return value.

1. **Entrypoint** -- the per-handler `_async_entrypoint(hass, call)` function
   that `helpers.register_blueprint_handler` registers as the
   `blueprint_toolkit.<service>` service callback. Receives the raw
   `ServiceCall`. Sole responsibility is to hand off to argparse.
2. **Argparse** -- runs `vol.Schema` (catching `vol.MultipleInvalid`
   separately from `vol.Invalid` so every error surfaces at once, not just the
   first), then accumulates cross-field + HA-state errors, emits config-error
   notification via `emit_config_error` (which dispatches an
   `active=bool(errors)` spec -- empty errors becomes a dismiss spec, so
   callers call this unconditionally). Builds a `logic.Config` on success.
3. **Service layer** -- reads `hass.states` to populate `logic.Inputs`, calls
   `logic.evaluate(config, inputs)`, applies the `Result` (turn_on/turn_off
   propagating `call.context` for logbook attribution, schedule/cancel
   `async_call_later`, send notification, write diagnostic state via
   `update_instance_state`).

### `BlueprintHandlerSpec` -- per-port lifecycle config

Every handler defines a single `_SPEC = BlueprintHandlerSpec(...)` that the
shared `register_blueprint_handler` / `unregister_blueprint_handler` consume.
Fields:

```python
service: str            # slug; "trigger_entity_controller"
service_tag: str        # short tag for logs/notifs; "TEC"
service_name: str       # human-readable; "Trigger Entity Controller"
blueprint_path: str     # "blueprint_toolkit/<service>.yaml"
service_handler         # async (hass, ServiceCall) -> Any
                        #   (None for void handlers, a ``ServiceResponse``
                        #   mapping for handlers that opt into
                        #   ``supports_response``)
supports_response       # ``homeassistant.core.SupportsResponse`` value or
                        #   None. When set, the dispatcher registers the
                        #   service with ``supports_response=`` so the
                        #   blueprint runner can capture the handler's
                        #   return value via ``response_variable``.
kick_variables          # dict[str, Any] | None  (flat ``automation.trigger``
                        #   variables for restart-recovery)
on_reload               # callback (hass) -> None
on_entity_remove        # callback (hass, entity_id) -> None
on_entity_rename        # callback (hass, old_id, new_id) -> None
on_teardown             # callback (hass) -> None
```

All hooks default to `None` and are independently optional. Watchdogs that
don't track per-instance state pass nothing beyond the four required fields
plus the service handler.

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

## Standalone blueprints

Some automations are simple enough that the three-layer split buys nothing --
the whole behavior fits in blueprint YAML (triggers, conditions, a `repeat`
loop, service calls). These ship as **standalone blueprints**: a single
`.yaml` file under `bundled/blueprints/automation/blueprint_toolkit/` with no
handler, no logic module, and no per-handler test files.

The category contract:

- **Marker.** The file's first line is the exact comment
  `# blueprint-kind: standalone`. This is the machine-readable tag that marks
  the file as handler-less; a future "every blueprint must..." test branches
  on it. Handler-backed blueprints carry no marker -- absence is the default.
- **No service dispatch.** The `actions:` chain is plain HA YAML. It never
  calls `blueprint_toolkit.<service>` -- there is no service to call.
- **Still fully documented.** A standalone blueprint carries the same
  user-facing doc obligations as any other: a `bundled/docs/<stem>.md` source,
  the rendered HTML, the `[Full documentation]` link in its `description`, and
  a README entry. `tests/test_blueprint_docs.py` and
  `tests/test_docs_rendered.py` enforce these for every blueprint regardless
  of shape.
- **Tested by a structure test, not a schema-drift test.** Instead of
  subclassing `BlueprintSchemaDriftBase` (which presumes a handler `_SCHEMA`),
  a standalone blueprint gets a `tests/test_<stem>.py` that loads the YAML and
  pins the marker, the input surface, the `mode`, and the absence of any
  `blueprint_toolkit.<service>` dispatch.
- **Restart resilience is the blueprint's responsibility.** Handler-backed
  automations get the integration's `recover_at_startup` for free; standalone
  blueprints do not. When a standalone blueprint has state that should survive
  an HA restart (an in-flight `repeat` loop, an active timer, etc.), add a
  `homeassistant: start` trigger and gate the actions so the recovery path
  only runs when appropriate. `trigger_alert_controller` uses this pattern to
  re-enter its repeat loop after a restart if a sensor is still on.

`trigger_alert_controller` is the reference example. Reach for a standalone
blueprint only when there is genuinely no business logic worth unit-testing in
isolation -- anything with a non-trivial decision tree, cross-field
validation, or state that must survive a restart belongs in the handler-backed
shape.

## Shared helpers (`helpers.py`)

All handlers consume these. Don't reimplement; if a new pattern keeps
recurring, hoist it here.

Behind the shim, helpers live in three flavour files per their HA-dependency
profile: `helpers_logic.py` (pure -- no HA imports of any kind, including
`TYPE_CHECKING`), `helpers_runtime.py` (runtime-HA -- takes a runtime `hass`
argument; HA imports only under `TYPE_CHECKING`, no module-scope or
function-body HA imports), and `helpers_lifecycle.py` (lifecycle / setup --
function-body HA imports OK; module-scope HA imports must be `TYPE_CHECKING`).
Add a new helper to whichever file matches its HA-dependency profile and
re-export from `helpers.py`. Callers `from .helpers import X` and don't need
to track the split; the structural tests in `tests/test_helpers_lifecycle.py`
enforce the no-HA-imports / `TYPE_CHECKING`-only / lifecycle-OK rules and the
shim re-export contract.

Schema validators:

- `cv_ha_domain_list(value)` -- voluptuous validator for a list-of-string
  blueprint input where each item must match HA's actual domain charset
  (`homeassistant.core.valid_domain`). Rejects hyphens, uppercase,
  leading/trailing underscores, and double-underscores; accepts leading-digit
  names like `3_day_blinds`. Produces a config-error message that names the
  offending value(s) and explains the charset.
- `CONTROLLABLE_DOMAINS` (frozenset) -- the shared set of HA domains that
  respond to `homeassistant.turn_on` / `turn_off` (switch / fan / light /
  input_boolean / climate / cover / etc.). Authoritative argparse-time guard
  for every on/off-driving handler.
- `validate_controlled_entity_domains(entity_ids, field_name)` -- per-entity
  validator that returns one config-error bullet per offender (each bullet
  names the field and lists the valid domains). Called from any on/off-driving
  handler's argparse to reject selector-bypassing YAML edits before the
  service layer dispatches a silent no-op against an unsupported entity.

Cross-handler accessors:

- `entry_for_domain(hass)` -- returns the integration's lone config entry
  (single-entry integration) or `None`. Used by every native handler to scope
  task lifecycle to the entry.
- `notification_prefix(service, instance_id)` -- returns
  `blueprint_toolkit_{service}__{instance_id}__`, the per-instance prefix
  every notification ID under a handler shares. Per-category suffix is
  appended at each call site.
- `all_integration_ids(hass)` -- distinct integration IDs across the entity
  registry. Watchdog truth-set seed.
- `integration_entity_ids(hass, integration_id)` -- entity IDs registered by
  `integration_id` (matches the entity-registry entry's `platform` field).
  Companion to `all_integration_ids` for watchdogs that want a per-integration
  entity list keyed off the same registry walk.
- `resolve_target_integrations(all, include, exclude)` -- apply include /
  exclude filters; empty `include` means "all" (matches the watchdog
  blueprints' documented behaviour).
- `file_editor_addon_ingress_url(hass)` -- returns the per-installation
  ingress URL prefix for the `core_configurator` add-on
  (`/api/hassio_ingress/<uuid>/`) when installed; empty string otherwise.
  Handlers thread the URL through `Config` to `file_editor_link`, which uses
  it to build clickable notification-body links. The ingress URL -- not the
  `/core_configurator/` panel URL -- is what callers want, because HA's panel
  route consumes query strings on its way through the frontend router. Returns
  the empty string on Container / Core installs (no Supervisor), while the
  Supervisor is still warming up post-restart, when the add-on isn't
  installed, or when its `ingress_url` field is `None`. The probe is a single
  `hass.data` lookup, so handlers call it per-evaluation -- install /
  uninstall events propagate on the next scan with no reload required.

Notification + formatting:

- `format_timestamp(template, dt)` -- `YYYY/MM/DD/HH/mm/ss` token expansion in
  user-supplied prefix/suffix strings.
- `format_notification(text, prefix, suffix, current_time)` -- wrap a
  notification body with a formatted prefix + suffix.
- `md_escape(s)` -- escape `\\`, `[`, `]` for safe interpolation into
  notification bodies; apply to every user-controlled string.
- `device_header_line(name, device_id)` -- render the canonical
  `Device: [<name>](/config/devices/device/<device_id>)` header line used as
  the first body line of every per-device watchdog notification (DW
  unavailable / stale, DW disabled-diagnostics, EDW per-device drift).
  Resolves the URL via `device_link` internally so the line shape stays
  consistent with the URL-helper convention in the "URL generation" section
  below.
- `slugify(text)` -- derive an HA-safe slug from arbitrary text (used to build
  state-entity IDs).
- `matches_pattern(text, pattern)` -- case-insensitive substring or regex
  pattern test; safe on bad regex (returns False).
- `validate_and_join_regex_patterns(raw, field_name)` -- the canonical
  multi-line regex parser for blueprint fields with
  `selector: text: { multiline: true }`. Returns a `JoinedRegexResult`
  (`.joined` -- pipe-joined alternation; `.errors` -- config-error bullets the
  caller appends to its argparse errors list; `.lines` -- per-valid-line
  tracking with `(line_number, raw, compiled)`). Use for every regex-list
  input -- a naive single `re.compile(raw)` substitute silently fails on
  multi-line input. The `.lines` field feeds `validate_directives_regex` for
  per-line "matched no candidates" attribution.
- `JoinedRegexResult` / `JoinedRegexLine` (dataclasses) -- shapes returned by
  `validate_and_join_regex_patterns`. Re-exported for handler typing.

Directive validation (watchdogs):

- `validate_directives_item(*, field, directives, candidates, reason)` --
  membership-check helper for include / exclude inputs whose values are exact
  string identifiers (integration names, entity IDs). Each directive not in
  `candidates` becomes an `UnmatchedDirective` with the supplied `field` and
  `reason`.

- `validate_directives_regex(*, field, lines, candidates, reason=...)` --
  per-line regex check; flags any line whose compiled pattern doesn't match a
  candidate. Carries `UnmatchedDirective.line_number` so the body can render
  "line 3". Default reason: `"regex matched no candidates"`.

- `UnmatchedDirective` (frozen dataclass) -- one bullet for the unmatched-
  directives notification. Fields: `field`, `value`, `reason`, `line_number`
  (set for regex-derived bullets so the body can render "line 3" for
  multi-line regex inputs).

- `make_unmatched_directives_notification(*, service, instance_id, unmatched)`
  -- spec builder. Empty list -> inactive spec keyed to the same notification
  ID, so handlers dispatch unconditionally and the toggle-off / no-unmatched
  paths both auto-clear prior notifications.

Per-handler logic modules compose these helpers in their own
`_validate_<service>_directives` function called from `run_evaluation`,
keeping the orchestration alongside the rest of the watchdog's pure evaluation
logic. The handler passes only the user-supplied directive lists plus the
enabled toggle, via the per-handler `DirectiveInputs` dataclass. The validator
derives its candidate sets from the same data the actual exclusion code
operates on -- the `devices` list, the `deviceless_entities` list,
`truth_set.entity_ids`, `paths_walked`, etc. -- so the "matches no candidates"
signal stays aligned with what the watchdog actually scans: a regex line gets
flagged as unmatched precisely when it wouldn't filter anything.

Notifications:

- `PersistentNotification` (dataclass) -- spec for create/dismiss;
  `instance_id` field drives the `Automation: [name](edit-link)\n` prefix the
  dispatcher prepends. Optional `repair_callback` / `translation_key` /
  `translation_placeholders` fields opt the spec into the Repairs surface (see
  "Repairs" below).
- `FixService` (frozen dataclass) -- the wire payload a repair-marked
  `PersistentNotification` carries: `service_name` (the HA service the fix
  flow dispatches to) + `notification_id` (the repair-issue id the fix service
  uses to look up its rich payload). One generic class, not a subclass per fix
  -- every fix service has the same wire shape. The rich per-repair data
  (entity lists, rename targets) stays off the wire on the handler's instance
  state, keyed by `notification_id`; the issue registry's `data` holds only
  flat JSON primitives (the service name + that id), which the fix flow
  reconstructs into the service call. Each handler's `logic.py` defines a
  `FixServices(StrEnum)` of its service names and builds `FixService`
  instances directly.
- `process_persistent_notifications(hass, [spec])` -- dispatcher;
  create/dismiss + automation-link prefix. Skips `create` calls whose new
  title + message would be byte-identical to the currently-active
  notification's content, and skips `dismiss` calls whose ID isn't currently
  active. Per-scan churn-prevention so unchanged notifications don't bubble to
  the top of HA's panel on every periodic invocation.
- `process_persistent_notifications_with_sweep(...)` -- sweep variant;
  dismisses any prior-run notifications matching `sweep_prefix` not in the
  current batch.
- `process_repairs_with_sweep(...)` -- routes a per-instance batch by
  `repair_callback`. Kwargs: `sweep_prefix`, `create_repairs: bool`,
  `repair_cap: int = 0`. With `create_repairs=False` repair-marked specs drop
  entirely (the logic builds the finding as a `repair_callback=None`
  notification spec instead); with `True` they route to the issue registry
  while non-repair specs continue to the notification path. See "Repairs"
  below.
- `make_config_error_notification(...)` -- builder; `md_escape`s every error
  bullet; empty errors -> dismiss spec.
- `emit_config_error(...)` -- builder + dispatcher convenience wrapper; safe
  to call unconditionally.
- `make_emit_config_error(*, service, service_tag)` -- factory returning a
  per-handler `_emit_config_error(hass, instance_id, errors)` closure.
- `validate_payload_or_emit_config_error(hass, raw, schema, emit)` -- run a
  `vol.Schema` over `raw`; on `MultipleInvalid` / `Invalid`, emit a
  config-error notification and return `None`; caller short-circuits.
- `prepare_notifications(...)` -- sort + cap helper consuming `CappableResult`
  objects; emits clean-result notifications when the cap is exceeded; always
  emits a cap-summary slot.

Diagnostic state:

- `instance_state_entity_id(service_tag, instance_id)` -- derive
  `blueprint_toolkit.<service_tag>_<slug>_state`.
- `update_instance_state(hass, ...)` -- write diagnostic state. Common attrs:
  `instance_id`, `last_run`, `runtime`. Per-handler adds via
  `extra_attributes`.
- `automation_friendly_name(hass, instance_id)` -- resolve automation
  entity_id to user-set friendly name (used for `[ZRM: My Cool Automation]`
  log tags).

Lifecycle wiring:

- `BlueprintHandlerSpec` (dataclass) -- per-handler config.
- `spec_bucket(entry, service)` -- per-handler slot under
  `entry.runtime_data.handlers[service]`.
- `register_blueprint_handler(hass, entry, spec)` -- wire up service +
  listeners + restart-recovery; idempotent. Also surfaces any unhandled
  handler exception as a per-instance `__crash` persistent notification
  (auto-cleared on the next successful run) so silently-broken automations are
  visible to the operator.
- `unregister_blueprint_handler(hass, entry, spec)` -- tear down service +
  listeners + on_teardown.
- `schedule_periodic_with_jitter(...)` -- per-instance jittered periodic
  scheduling that hands the action through an entry-scoped task.
- `make_periodic_trigger_callback(...)` -- canonical `automation.trigger`
  callback (`trigger_id="periodic"` plus optional flat extra variables) for
  handlers that run a periodic scan. Drops silently if the instance has been
  removed between scheduling and firing. See "Spec + lifecycle" below for the
  kwargs handlers pass.
- `make_lifecycle_mutators(...)` -- factory returning a `LifecycleMutators`
  bundle (`on_reload`, `on_entity_remove`, `on_entity_rename`, `on_teardown`)
  bound for the `BlueprintHandlerSpec`. Reads the cancel- callable via
  `getattr(s, cancel_field, None)` so the same helper works for both
  `cancel_timer` and `cancel_wakeup`-flavoured state objects.

## Schema + argparse

### Aggregate, never bail-on-first

Every validation path in argparse must accumulate problems into a single
`errors` list and emit them all in one `config_error` notification. Bailing on
the first failure forces the user to play whack-a-mole.

- Schema-level errors come back via `vol.MultipleInvalid.errors` -- iterate
  the whole list. Catch `vol.MultipleInvalid` BEFORE `vol.Invalid`.
  (Voluptuous accumulates all field-level errors automatically; `vol.All`
  within a single field is short-circuit, which is fine.)
- Cross-field validation (no overlapping entity sets, etc.) appends to
  `errors`; never `return` mid-validation.
- HA-state validation (entities exist, sun.sun is available if any time-of-day
  input is non-`always`) appends to the same list.
- Single `await emit_config_error(...)` at the end of argparse with the
  accumulated `errors`. Empty list dismisses any prior notification.

### Schema shape

Use `vol.Schema({...}, extra=vol.ALLOW_EXTRA)`. `extra=vol.ALLOW_EXTRA` is
intentional for forward-compat with future blueprint inputs -- document, don't
silently flip to `PREVENT_EXTRA`.

Schema covers shape only. Cross-field rules + HA-state validation belong in
argparse, not in the schema.

Period / event / enum value lists derive from the logic-side enums (no
hardcoded duplicate string lists).

Run schema validation through
`helpers.validate_payload_or_emit_config_error(hass, raw, _SCHEMA, _emit_config_error)`
and short-circuit on `None`. Don't write the try / except block manually --
the helper catches `vol.MultipleInvalid` BEFORE `vol.Invalid` so the user sees
every schema error in one notification, not just the first.

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
- **Synthetic-trigger `variables` overrides.** HA's `automation.trigger`
  strips the `trigger` key from caller- supplied variables. Pass overrides as
  flat top-level keys, NOT under `trigger.*`. See "Synthetic-trigger
  overrides" below.
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
       state=result.action.name,           # or "ok"
       extra_attributes={...},             # per-handler
   )
   ```

### Action dispatch

`homeassistant.turn_on` / `turn_off` calls propagate `context=call.context`
(`blocking=False`); inline the call (no per-handler `_do_call` wrapper).

Auto-off scheduling (if applicable) cancels the prior wakeup before arming a
new one.

Notify dispatch is owned by the calling blueprint, not by the handler.
Handlers that produce a user-facing notification body register with
`supports_response=SupportsResponse.OPTIONAL` on their `BlueprintHandlerSpec`
and return a `ServiceResponse` mapping carrying `notification_message`. The
blueprint captures the response via `response_variable`, then runs the
user-supplied `notify_action` action chain against it (the user picks
`notify.*`, a notify group, a script, or any combination). No-op evaluations
return an empty / absent message so the blueprint's `choose` short-circuits.

The state save runs BEFORE the handler returns, so a notify-action failure
inside the blueprint runner cannot lose the controller state -- HA invokes the
user's action sequence after the response is captured.

### Diagnostic state

After every evaluation, call:

```python
update_instance_state(
    hass,
    service_tag=_SERVICE_TAG,
    instance_id=...,
    last_run=now,
    runtime=time.monotonic() - started,
    state=...,
    extra_attributes={...},
)
```

Per-handler attrs go in `extra_attributes`.

Common state attrs are exactly three: `instance_id`, `last_run`, `runtime`.
Everything else is per-handler.

State value defaults to `"ok"`. Trigger-driven handlers override with the
decision name (e.g. `result.action.name`); periodic / watchdog handlers leave
it alone.

### Service-layer exit ordering

Every handler's service layer composes the same five operations (PN sweep,
state write, action dispatch, debug log, response), and the canonical order
across the integration is:

1. **Sweep PNs.** Dispatch the per-instance persistent-notification set for
   this run via `process_persistent_notifications_with_sweep` (or
   `process_repairs_with_sweep` when the handler emits a mix of repair +
   notification specs -- EDW + DW). Clears stale config-error / per-finding
   entries from prior runs and emits the current findings.
2. **Update state.** Write the diagnostic state entity via
   `update_instance_state`. Records what we did this run.
3. **Action dispatch.** `homeassistant.turn_on` / `turn_off` / etc, for
   handlers that drive entities.
4. **Debug log.** A single `_LOGGER.warning(...)` line, gated on the
   per-instance `debug_logging` toggle, summarising the decision. One line, at
   the end -- not interleaved through the scan.
5. **Return ServiceResponse.** Handlers that opt into `supports_response`
   (STSC + TEC today) return a mapping carrying `notification_message` -- the
   blueprint captures it via `response_variable` and runs the user-supplied
   `notify_action` step against it. Watchdog handlers return `None` from this
   slot (the dispatcher's wrapper returns whatever the handler hands back).

Handlers that don't need a step (no response, no action dispatch, nothing to
log) just skip it. The remaining steps stay in the order above.

#### Response-variable convention

Handlers that hand notify dispatch off to a user-supplied action chain set
`supports_response=SupportsResponse.OPTIONAL` on their `BlueprintHandlerSpec`
and return `{"notification_message": "<body>"}` from their service entrypoint
-- empty string on no-op evaluations. The blueprint pairs the call with
`response_variable: result` and a `choose` that fires `!input notify_action`
only when `result.notification_message` is non-empty, with `message` exposed
as a top-level variable inside the user's action sequence so each step can
reference `{{ message }}`.

This is the canonical choice for any handler whose notification surface is
"call the user's notify endpoint with a pre-built body". It moves the choice
of notify endpoint (notify group, mobile_app target, script, any combination)
entirely into the blueprint UI's action picker -- the handler stays out of
HA-specific dispatch entirely. STSC + TEC use it; watchdog handlers (DW, EDW,
RW, ZRM) do not because their notification surface is
`persistent_notification` (an HA-side render, not a user-side notify call) and
is therefore handler-owned.

### Async tasks must be entry-scoped

Async tasks scheduled by the handler must be entry-scoped, not hass-scoped.
Use `entry.async_create_background_task(hass, coro, name)` so HA cancels
in-flight work on entry unload; never `hass.async_create_task(coro)` (which
leaves work running detached against a torn-down service registration).

Every native handler with a periodic timer (DW, EDW, RW, STSC, ZRM) arms it
via `helpers.schedule_periodic_with_jitter`, which both wraps each tick in
`entry.async_create_background_task` (so an entry unload mid-tick cancels the
in-flight call) and adds per-instance jitter (so multiple instances on the
same configured interval don't fire on the exact same wall-clock tick after HA
boot or an integration reload). TEC has no periodic timer -- only a one-shot
`async_call_later` auto-off wakeup. Reaching for raw
`async_track_time_interval` is **not** the canonical pattern -- the helper is.
If a future case genuinely needs the raw call (none today), pass a sync
`@callback` wrapper that creates the entry-scoped task yourself -- passing the
async action directly routes subsequent ticks through HA's internal
`hass.async_create_task`, defeating the scoping.

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
  `helpers.schedule_periodic_with_jitter`. The helper bakes in the
  swallow-and-WARN-log behavior for transient `automation.trigger` failures (a
  single failed tick is self-healing -- the next tick fires anyway).
  Per-handler `_make_periodic_callback` shims have been removed; call the
  helper directly.
- **Restart-recovery kick** -- handlers that need restart-recovery set
  `kick_variables=` on `_SPEC` to a flat `automation.trigger` variables dict
  (e.g. `{"trigger_id": "manual"}` for the watchdogs, TEC's synthetic TIMER
  `{"trigger_entity_id": "timer", "trigger_to_state": ""}`). The dispatcher
  fires `automation.trigger` with that payload against every discovered
  automation on HA-started + reload events. The blueprint action reads the
  flat top-level keys; HA's `automation.trigger` strips any nested `trigger.*`
  overrides.
- **Mutator callbacks** -- one `helpers.make_lifecycle_mutators(...)` call
  (kwargs: `instances_getter=_instances`, `cancel_field=...`,
  `service_tag=_SERVICE_TAG`, `logger=_LOGGER`, optional
  `reset_armed_interval_on_reload=`) returns a `LifecycleMutators` dataclass
  with `on_reload`, `on_entity_remove`, `on_entity_rename`, `on_teardown`.
  Bind each to a module-level alias (`_on_reload = _MUTATORS.on_reload`, etc.)
  and reference the aliases from `_SPEC` -- the aliases keep per-handler unit
  tests that call `handler._on_reload(h)` working without each having to reach
  into `_MUTATORS`. Don't hand-roll the four `@callback` functions; the helper
  already wraps them.
- **`_SPEC = BlueprintHandlerSpec(...)`** -- only set the hooks the handler
  actually needs.
- **`async_register(hass, entry)`** and **`async_unregister(hass, entry)`**
  are one-line delegations to `register_blueprint_handler` /
  `unregister_blueprint_handler`.

`make_lifecycle_mutators`'s `cancel_field` parameter is the attribute name of
the cancel-callable on the per-instance state object;
`reset_armed_interval_on_reload=True` clears `armed_interval_minutes` to 0 on
reload (set for handlers whose `_ensure_timer` re-arm decision compares
against that field).

## Blueprint YAML

- **Periodic scheduling is integration-owned, not blueprint-owned.** Don't add
  `time_pattern` / `time` triggers to the blueprint -- the handler arms its
  own periodic timer via `helpers.schedule_periodic_with_jitter`. When a
  blueprint has only synthetic triggers (no reactive `state` / `event` / etc.
  triggers), still emit an empty `triggers: []` block: a blueprint with no
  `triggers:` key at all parses but HA renders the resulting automations as
  `unavailable`, the recovery kick never fires, and no scan runs after deploy.
- **No `homeassistant: start` / `homeassistant: shutdown` triggers** in
  handler-backed blueprints. The integration's startup-recovery hook already
  kicks every discovered automation when HA fires
  `EVENT_HOMEASSISTANT_STARTED`, and the reload listener handles
  `EVENT_AUTOMATION_RELOADED`. Standalone blueprints don't get the
  integration's recovery, so `homeassistant: start` is a valid re-entry hook
  there -- see "Standalone blueprints".
- **Handler-backed blueprints: `action:` calls
  `blueprint_toolkit.<service>`.** Standalone blueprints have no service call
  -- see "Standalone blueprints".
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
  `automation.trigger` call site (periodic callback, restart-recovery kick,
  any other synthetic invocation): assert the `variables` payload's shape AND
  that `"trigger"` is NOT a key in it. Locks down the fix so a future refactor
  can't silently re-introduce the broken nesting.
- **`automation.trigger` re-fire MUST NOT pass `context=`**. HA's automation
  runner needs to generate a fresh per-run context for proper logbook
  attribution.
- **Document any `mode: queued` / `max:` in a YAML comment.** Silent drops
  above the cap surprise users.
- **Selector restrictions are UI-only; argparse validates domains
  independently.** A blueprint's
  `selector: entity: { domain: [switch, light, fan] }` restricts what the HA
  UI shows in the entity picker, but a hand-edited automation YAML can pass
  any entity. Argparse must independently validate the domain of every entity
  input -- either via `vol.In([...])` against the expected domain set in the
  schema, or via a cross-field check that walks `hass.states.get(entity_id)`
  and inspects its domain. For on/off-driving handlers (anything that
  dispatches `homeassistant.turn_on` / `turn_off`), call
  `helpers.validate_controlled_entity_domains(entity_ids, field_name)` which
  checks each entity against the shared `helpers.CONTROLLABLE_DOMAINS`
  frozenset (switch / fan / light / input_boolean / climate / cover / etc.)
  and returns a per-entity config-error bullet for each offender. Trigger /
  disabling / observed entities are NOT subject to this check (they're
  observed, not actuated). Skipping the runtime check means a YAML-edited
  entity gets passed through to `homeassistant.turn_on` and silently no-ops.

## Notifications

- Use friendly names (not raw entity IDs) in all user-facing notification
  messages. Resolve via `helpers.automation_friendly_name(hass, instance_id)`
  for log tags.
- **Every `PersistentNotification` spec sets
  `instance_id=<the automation entity_id>`.** The dispatcher uses it to
  prepend `Automation: [name](edit-link)\n` to every active notification body
  so users can click through to the automation that emitted the notification;
  an unset `instance_id` silently skips the prefix.
- **Apply `helpers.md_escape(...)` to every user-controlled string going into
  a notification body.** Persistent notifications render through
  `<ha-markdown>`, so stray `[` / `]` / `\` in body text can corrupt the
  rendering -- garbled markdown, dropped content, or a chunk of body rewritten
  as a link the user didn't expect. Apply to friendly_names, vol.Invalid
  messages (which can echo the offending input value back), error messages
  from external APIs, YAML location strings, etc. Constants and values inside
  backtick code spans are exempt (constrained character set / markdown
  suppressed). Notification TITLES are exempt -- HA renders titles as plain
  text, only `message` goes through markdown.
- **Notification IDs follow
  `blueprint_toolkit_{service}__{instance_id}__{kind}`.** `__` is the reserved
  field separator; HA entity_ids can never contain `__` so the format stays
  parseable. Two `{kind}` slots are shared infrastructure that fires for every
  handler: `__config_error` (schema / cross-field validation failure; managed
  by `emit_config_error`) and `__crash` (unhandled handler exception; managed
  by `register_blueprint_handler`). Other `{kind}` values are per-handler.
  Repair fix-service crashes (registered directly via
  `hass.services.async_register`, not through `register_blueprint_handler`)
  use a separate scheme: `blueprint_toolkit__{service_name}__crash__{target}`
  (no `instance_id`; the crash means the fix service is broken, not the
  automation that emitted the repair).
- **Pick the right dispatcher.** `process_persistent_notifications_with_sweep`
  is the right choice when the caller is asserting the COMPLETE per-instance
  notification state for this run -- it dismisses any prior-run notifications
  matching the per-instance prefix that aren't in the current batch. Use the
  bare `process_persistent_notifications` when touching a single known
  notification ID (e.g. `emit_config_error` against a fixed `__config_error`
  slot), so the call doesn't collateral-dismiss findings emitted by other
  categories.

## Repairs

Findings whose fix is deterministic + automatable can route to HA's Repairs UI
as one-click Fix issues instead of as persistent notifications.

- **One surface per finding.** The logic chooses notification-vs-repair at
  build time from `config.create_repairs`, so a fixable finding is emitted on
  exactly one surface -- never both. With `create_repairs` on, the finding
  becomes a repair-carrying `PersistentNotification` (`repair_callback` set +
  `translation_key` + `translation_placeholders`); with it off, the same
  finding renders as the per-device notification body. The per-backend sweep
  clears the other surface when the toggle flips.
- **Repair spec.** `PersistentNotification.repair_callback` (a `FixService` or
  `None`) is what marks a spec as a repair. The `FixService` (see "Shared
  helpers") carries the service name + the repair's `notification_id`; the
  rich per-repair payload (entity lists, rename targets) lives on the
  handler's instance state keyed by that id.
- **Dispatcher.** `process_repairs_with_sweep` replaces
  `process_persistent_notifications_with_sweep` for handlers emitting fixable
  findings. Specs with `repair_callback` route to the issue registry when
  `create_repairs=True` (else they're dropped -- the logic doesn't build them
  in that case); plain specs route to notifications. The per-instance sweep
  removes prior-run issues / notifications under the prefix not in the current
  batch from their respective backend. Returns the set of published repair
  `notification_id`s so handlers can prune their per-repair state to what's
  reachable.
- **Cap.** `repair_cap > 0` keeps the visible repair count manageable (HA's
  Repairs UI has no bulk-dismiss). Specs above the cap coalesce into a single
  per-instance cap-summary **notification** -- not a repair issue --
  (`{prefix}cap_summary`). The cap-summary slot is always dispatched (active
  when over cap, inactive otherwise) so a previously-active summary
  auto-dismisses when the next run is back under cap.
- **Fix services.** Each repairable finding kind backs a per-device service
  registered from each handler's `async_register_fix_services` via the shared
  `helpers.register_fix_service(hass, service_name, handler)`, which owns the
  whole fix-service contract: the `notification_id` schema, the idempotent
  `has_service` guard, the crash-PN wrap, and decoding the id out of the
  `ServiceCall`. A handler supplies only
  `async def (notification_id: str) -> None`. The logic builds the repair
  specs plus the rich payloads; the fix service looks up its payload by
  `notification_id` and applies it verbatim (no re-scoping -- the scan that
  built the payload had the user's full filter configuration in scope).
  Per-device grouping: a device with N drifted entities is one Submit, not N
  (EDW emits up to two, one per drift kind).
- **Issue ID format.**
  `blueprint_toolkit_{service}__{instance_id}__repair_{fix_service_name}__{device_id}`
  -- the same `__` separator convention as notifications, built via the shared
  `helpers.repair_notification_id(notification_prefix, fix_service_name, device_id)`.
  That helper injects the `repair_` token (callers pass their `FixServices`
  value + device id and stay agnostic of it), so the resulting id carries the
  `__repair_` substring that `repairs.async_create_fix_flow` routes on to pick
  the `WatchdogFixFlow` over the install-time `InstallConflictsFlow` /
  `InstallFailureFlow`.
- **Translations.** Each repair spec sets `translation_key=<kind>`; the
  entries in `strings.json` / `translations/en.json` carry the user-visible
  title + description with `{placeholder}` fields filled via
  `translation_placeholders`. Every fixable finding passes an `{entities}`
  placeholder -- a markdown list of the affected entities the confirm modal
  renders, mirroring the per-device notification body. The list shows
  `old -> new` for renames (EDW id-drift entity IDs, EDW name-drift names) and
  `` `<entity_id>` (<name>) `` for DW disabled diagnostics; the DW
  notification body and repair use identical entity-line text.

## URL generation

Every URL emitted in a notification body, log line, or stored data field goes
through a helper in `helpers.py`. No inline `f"/config/.../{x}"` templates --
per-call-site URL guessing has shipped multiple regressions because HA's
frontend routing doesn't accept the obvious entity-id-style filters.

Two flavours of helper, both public:

- **`*_link(name, ...)` wrappers** return markdown-ready `[name](url)` text,
  with `name` `md_escape`d. Use this whenever the call site's output is a
  notification-body link. Concrete helpers: `device_link`,
  `device_entity_link`, `config_entry_link`, `domain_entities_link`,
  `integration_link`, `automation_edit_link`, `script_edit_link`,
  `dashboard_link`, plus `deviceless_entity_link` (a prose link plus
  search-the-list instructions for entities that have no deep-linkable URL
  form). `file_editor_link(path, ingress_url)` is shaped differently from the
  rest -- callers always invoke it for source-file paths and the helper
  returns either `` [`<file>`](<ingress_url>?loadfile=<file>) `` (when
  `ingress_url` is non-empty AND the path is user-editable, i.e. not under
  `.storage/`) or the bare `` `<file>` `` form. The URL prefix argument is the
  per-installation `/api/hassio_ingress/<uuid>/` form populated by
  `file_editor_addon_ingress_url(hass)` -- HA's panel route
  (`/core_configurator/`) consumes query strings on the way through the
  frontend router, so the configurator never sees `loadfile`; the direct
  ingress URL forwards it intact. Centralising the decision keeps call sites
  agnostic of whether file-editor links are supported.
- **`*_url(...)` raw URL functions** return just the URL string. Reserved for
  the narrow cases that need a URL separated from its rendering -- e.g.
  storing a URL on a dataclass for later assembly (`Owner.url_path` in RW), or
  building a link whose visible text is a code-span (backtick-wrapped
  entity_id) rather than an `md_escape`d friendly name.

The `helpers_logic.py` "URL + link helpers" section enumerates the
verified-working URL forms HA's frontend accepts and what each helper
produces. When adding a new URL form: put both the raw `*_url` and the
markdown-wrapping `*_link` in `helpers_logic.py`, re-export both from
`helpers.py`, and use the `*_link` variant at call sites.

Notable: HA's frontend has no entity-id URL filter -- a single deviceless
entity can't be deep-linked to a one-row view. `deviceless_entity_link`
returns prose with a link to `/config/entities/` plus "search for `<eid>`"
instructions; that is the best the routing surface allows.

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

Per-instance state lives in memory. Each handler keeps its state in
`_instances(hass)` -- a dict on
`entry.runtime_data.handlers[<service>]["instances"]` -- and the dict is
volatile across HA restarts. The mutator callbacks (`_on_reload`,
`_on_teardown`, etc.) tear down + rebuild it predictably.

The diagnostic state entity (`update_instance_state`) is for
**observability**, not authoritative state. Operators read it to confirm a run
completed (`last_run`, `runtime`) and to see the latest decision context. Its
`data` attribute is sometimes used to round-trip state across calls (STSC's
controller-state JSON blob is the example), but most handlers treat it as
write-only.

When the in-memory state is lost (HA restart, integration reload), handlers
re-bootstrap on the next call. The bootstrap path should:

1. Recognise the lost-state condition (typically the instance isn't in
   `_instances(hass)`, or the persisted blob in the diagnostic entity is
   `None` / malformed).
2. Re-arm any safety-relevant timers (e.g. STSC's auto-off bootstrap-arm: if
   the controlled entity is currently `on` and auto-off is enabled, arm
   `auto_off_started_at` immediately so the device doesn't get stuck on
   indefinitely).
3. Continue with the normal evaluation.

If the bootstrap path schedules anything (e.g. arming `async_call_later` for
an auto-off wakeup), the entry-scoping rule from "Async tasks must be
entry-scoped" above still applies -- use `entry.async_create_background_task`
(or a helper that does so internally), never `hass.async_create_task`.

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
  `vol.Required` keys.
- `test_blueprint_action_targets_registered_service` -- blueprint's `action:`
  line is `blueprint_toolkit.{_SERVICE}`.

This is the single test that catches the most bugs across the handlers; add it
to every new handler.

### Cross-port service-registration test

Add `<service>` to the `expected` set in
`tests/test_integration.py::TestSetupEntry::test_setup_registers_services`.
That test asserts every handler's service registers on `async_setup_entry`.
The set is hard-coded so each new handler has to update it.

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

### Code quality

- Every `.py` file under the repo is automatically picked up by the
  parametrized `_repo_shared/tests/test_code_quality.py` sweep -- new files
  need no pyproject edit to be lint + format + `mypy --strict` checked.
- HA-coupled module files (`__init__.py`, `config_flow.py`, `repairs.py`,
  `helpers_lifecycle.py`, `helpers_runtime.py`) carry a PEP 723 `# /// script`
  block declaring
  `dependencies = ["pytest-homeassistant-custom-component==..."]` plus
  `requires-python = ">=3.14"`. `resolve_files` reads these blocks and the
  per-file mypy run spawns
  `uvx --python 3.14 --with <hacc-pin> mypy --strict <file>` so
  `homeassistant.*` resolves against real HA types. When adding a new
  HA-coupled module file, add the same PEP 723 block.
- Files without an HA dependency need no PEP 723 block; they type-check under
  plain `mypy --strict` in the project venv, with `[[tool.mypy.overrides]]`
  rules in `pyproject.toml` covering voluptuous / jinja2 / socketio / yaml.
- No `# mypy: ignore-errors` in handler.py before considering complete.

## Naming conventions

- `_SERVICE` -- snake_case slug, e.g. `"trigger_entity_controller"`.
- `_SERVICE_TAG` -- short tag for log lines + notification titles, e.g.
  `"TEC"`.
- `_SERVICE_NAME` -- human-readable, e.g. `"Trigger Entity Controller"`.
- Subpackage directory matches `_SERVICE` exactly:
  `trigger_entity_controller/`.
- Test file basename matches `_SERVICE` exactly:
  `tests/test_trigger_entity_controller_*.py`.
- Notification ID: `blueprint_toolkit_{service}__{instance_id}__{kind}`, e.g.
  `blueprint_toolkit_dw__automation.bath_fan__config_error`.
- State entity ID: `blueprint_toolkit.{service_tag}_{slug}_state`, e.g.
  `blueprint_toolkit.tec_kitchen_lights_state`. The helper lowercases
  `service_tag` internally so callers pass the uppercase `_SERVICE_TAG`
  constant directly. HA's entity-id regex bans `__`, so single `_` is the only
  viable separator.
- `_raw` suffix applied to schema-validated input fields whose parsed form is
  rebound without the suffix in argparse, e.g. `default_route_speed_raw` ->
  `default_route_speed`.
- Watchdog include / exclude blueprint inputs use the prefix-style
  `include_<thing>` / `exclude_<thing>` naming (NOT
  `<thing>_exclude_<thing>`). When two blueprints take a directive that
  matches the same underlying thing -- entity IDs, regex patterns, integration
  names -- they use the SAME variable name (e.g. DW, EDW, and RW all use
  `exclude_entity_id_regex`).

Booleans use `helpers`-side coercion via `cv.boolean`; never hand-roll string
comparison.

Time units in input names + variable names use full words: `_seconds`,
`_minutes`. Never `_s` / `_m` / `_min`.

User-facing enum values (exposed in blueprints) use dashes: `"night-time"`,
`"day-time"`, `"triggered-on"`, `"auto-off"`.

## User-facing docs

Each automation has a user-facing markdown doc at
`custom_components/blueprint_toolkit/bundled/docs/<service>.md`, rendered to
HTML at `bundled/www/blueprint_toolkit/docs/<service>.html` and served from
the HA frontend at `/local/blueprint_toolkit/docs/<service>.html` so the
blueprint can link to it from its `description`. After editing any `*.md`
source under `bundled/docs/`, re-run `scripts/render_docs.py` and commit the
regenerated HTML in the same commit (the `tests/test_docs_rendered.py` drift
check enforces this).

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
7. **Developer notes** -- state attributes, debug log format,
   detection-mechanism internals, known limitations, and follow-ups.

User-facing sections come first so users don't have to scroll past developer
notes to find their config. Developers read the whole file, so the ordering
has no cost for them.

Don't introduce new top-level sections. Anything that doesn't fit an existing
bucket goes under "Usage notes" (if user-facing) or "Developer notes" (if
internal) as a sub-heading.

### Tables in user docs

Configuration / attribute reference tables in user docs stay as markdown
tables; they render cleanly in HTML and on GitHub, which is where users read
them. (The "prefer lists over tables" rule in `DEVELOPMENT.md` applies to
developer-facing docs that are read in plain text more often than in a
browser.)
