# Z-Wave Route Manager

## Summary

Reconciles Z-Wave priority routes (controller\<->node) against a declarative
YAML config file. Reconciles on HA startup, on manual trigger, when the YAML
config is edited, and periodically (default every 5 minutes) to catch
out-of-band route changes. Failed reconciles retry automatically on the next
minute-granularity tick. See "Reconcile trigger semantics" under Developer
notes for the full gate. Surfaces broken config, unreachable API, and apply
failures as persistent notifications.

## Features

- Declarative YAML config: one source of truth for every route you want
  managed
- Two Z-Wave route directions managed per configured device: controller->node
  (application route) AND node->controller (priority SUC return route)
- Automatic route-speed resolution (picks the slowest max rate across all hops
  in the route)
- Per-entry and group overrides for speed
- Unmanaged-route cleanup: removes routes not in the config so editing the
  file is authoritative
- Pending-state tracking for sleeping nodes whose route commands queue until
  wake
- Generates configuration errors for devices that don't support routing
  (Z-Wave Long Range devices)
- Distinct notification categories: config errors, API unavailable, apply
  failures, pending timeouts

## Requirements

Home Assistant **Z-Wave JS** addon (`core_zwave_js`), which bundles
`zwave-js-ui`. The socket.io backend on port 8091 is the automation's target
-- tested against addon v1.2.0 (bundling zwave-js-ui v11.16.0).

## Usage

1. Install the integration (see main README).
2. Create `/config/zwave_route_manager.yaml` with your route definitions (see
   Configuration below).
3. Go to **Settings -> Automations & Scenes -> Create Automation -> From
   blueprint -> Z-Wave Route Manager**.
4. Fill in the inputs. Most installations only need to set **Clear routes not
   in config** if you want manually-set routes to persist.
5. Save the automation. The next reconcile tick picks up your config and
   applies routes.

## Configuration

| Parameter                    | Description                                                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Config file path             | YAML file path relative to `/config` (default `zwave_route_manager.yaml`)                                                                  |
| Z-Wave JS UI host            | Usually `core-zwave-js` (default)                                                                                                          |
| Z-Wave JS UI port            | Usually `8091` (default)                                                                                                                   |
| Z-Wave JS UI auth token      | Leave empty unless you've enabled auth                                                                                                     |
| Clear routes not in config   | If true, removes routes on nodes not listed in the config file                                                                             |
| Reconcile interval (minutes) | How often to check for out-of-band route drift (e.g. someone editing a route via the zwave-js-ui web UI). Lower values catch drift sooner. |
| Pending timeout (hours)      | Time before raising a notification on a node whose route hasn't been reflected                                                             |
| Default route speed          | `auto`, `100k`, `40k`, or `9600` (used when neither repeater nor client specifies one)                                                     |
| Max notifications            | Cap on per-run issue notifications. Default 10. 0 = unlimited                                                                              |
| Debug logging                | Per-reconcile WARNING log line under `[ZRM: ...]`                                                                                          |

## Usage notes

### Config file format

```yaml
# /config/zwave_route_manager.yaml
routes:
  # A single repeater with three clients. The repeater default
  # is 100k; one client overrides to 40k; a group of two
  # shares their own 40k override.
  - repeater: sensor.hallway_extender_node_status
    route_speed: 100k
    clients:
      # Bare string form -> inherits repeater default.
      - lock.front_door
      # Dict form with an override.
      - entity: sensor.porch_motion
        route_speed: 40k
      # Group form: one override, multiple entities.
      - entities:
          - binary_sensor.back_door
          - binary_sensor.side_door
        route_speed: 40k

  - repeater: sensor.loft_repeater_node_status
    clients:
      - binary_sensor.kitchen_motion
```

**Supported value forms for `route_speed`:** `"auto"` | `"9600"` | `"40k"` |
`"100k"` | bare integers `9600`, `40000`, `100000`.

### Entity conventions

Any entity on the target Z-Wave device works -- the automation resolves entity
-> device -> node ID internally. Suggested conventions for stability:

- **Repeaters:** use `sensor.<name>_node_status` -- always present for
  zwave_js devices, diagnostic category so rarely disabled by users, and its
  name is predictable.
- **Client devices:** use the "primary" entity: `lock.X` for locks,
  `binary_sensor.X_contact` for door/window sensors, `binary_sensor.X_motion`
  for motion sensors.

Disabling an entity used in the config breaks that config line (surfaces as a
config-error notification). Pick another entity on the same device to fix it.

### Route-speed precedence

Most specific wins:

```text
per-client override
  > group override (dict with `entities:`)
    > repeater `route_speed:`
      > blueprint `Default route speed`
        > auto: min(maxDataRate across source, repeater(s), controller)
```

`auto` fails with a config error if any hop has an unknown maxDataRate.
Explicit speed values skip that check -- use them if you have an older device
that reports an unusual rate but you know what works.

### Line-powered nodes vs. sleepy nodes

Only line-powered nodes (extenders, plug-in sensors, wall switches) can act as
repeaters. Battery devices and FLiRS ("frequently listening routing slave" --
most locks) can't repeat for others. The automation validates this upfront.

Route commands to sleeping battery nodes queue in zwave-js until the node
wakes. During that window the automation tracks the command as **pending** and
suppresses retries. If the node doesn't wake within the configured pending
timeout (default 24h) a persistent notification surfaces. FLiRS nodes like
locks wake every second, so commands typically apply within seconds.

A UI edit to a sleeping node's SUC return route takes up to two wake cycles to
revert: we can't see the queued UI command, so only after the device wakes and
accepts the new route do we notice the drift and issue another update. That
update then has to wait for the next wake.

### Clear routes not in config caveat

When **Clear routes not in config** is enabled, the reconcile iterates
**every** Z-Wave node and removes any application route and any SUC return
route that isn't covered by your config.

**Important:** The zwave-js-ui API for clearing SUC return routes
(`deleteSUCReturnRoutes`) is blunt -- it clears **all** SUC return routes on
the node, including custom routes you set manually via the Z-Wave JS UI's
*Return routes -> ADD* button. Once you commit to **Clear routes not in
config**, treat the config file as the single source of truth and stop using
the UI panels to set routes.

If you need to temporarily edit routes via the UI, disable **Clear routes not
in config** first, edit, then re-enable once you've mirrored your changes in
the config file.

### Notification categories

Four distinct categories of persistent notification:

- **Config error.** YAML parse problems and entity- resolution problems
  (missing devices, devices that don't support routing, etc.) bundled into one
  notification per reconcile. Clears automatically once the config and entity
  registry agree.

- **API unavailable.** Surfaced when the Z-Wave JS UI socket.io API can't be
  reached or returns an incompatible response. Clears automatically once the
  addon is back.

- **Apply failed.** One per node that returned an error when sending a route
  command. Clears automatically once a later reconcile sends the same route
  successfully.

- **Pending timeout.** Each time a route command sits pending longer than the
  configured timeout, the route is re-issued automatically and a *new*
  notification is emitted for that timeout event. These notifications stay
  until you dismiss them -- they're a stream of "this route isn't landing"
  events, not a single status.

  The `Pending timeout (hours)` blueprint input doubles as the retry interval:
  a route that's been pending that long is re-sent, and the timer starts over.
  If a device is permanently unable to accept the route (e.g. it's been
  removed from the network, or it's a device class that silently drops
  priority-route commands), each retry will fail again and another
  notification will appear. The way to stop the noise is to remove that device
  from the YAML config.

### Recovering a wedged controller

If the controller stops responding and the "controller unresponsive"
notification keeps returning, escalate in this order:

1. Restart the add-on (`ha addons restart core_zwave_js`). It's cheap, but it
   did not clear the one recorded wedge and left the driver worse off.
2. Stop the add-on and leave the stick idle for about 30 seconds. Toggle its
   USB port with `echo 0 > /sys/bus/usb/devices/<port>/authorized`, wait at
   least 10 seconds, and `echo 1` to the same file, then start the add-on. A
   1-second gap was not reliable.
3. Run `ha host reboot`. This is untested for this failure.
4. Unplug and replug the stick.

These steps come from a single incident, so treat them as a starting point.
The [incident record][wedge] has the details.

## Developer notes

### Two route requests per configured route

Most YAML route entries managed by the automation result in *two* underlying
Z-Wave route requests -- one for each direction:

- **Controller -> node** (priority application route): how the controller
  reaches the device when sending commands
- **Node -> controller** (priority SUC return route): how the device reaches
  the controller when reporting state

Both directions are managed, tracked, and counted independently. Hence a YAML
config with 5 routes typically shows `routes_in_config: 10`, the `pending` and
`applied` state attributes can each carry up to two entries per node (one per
direction), and a device with one direction landed but the other still in
flight ("half-applied") appears in *both* the `applied` and `pending` dicts.

("Most" rather than "always" because future YAML knobs may opt a device into
one-way-only management -- devices that won't accept one of the two route
types fall into this category.)

### Entity attributes

Attributes written to `blueprint_toolkit.zrm_<slug>_state`, where `<slug>` is
the automation's entity_id stripped of its `automation.` prefix:

- `instance_id`: the automation entity_id

- `last_run`: ISO timestamp of the most recent tick

- `runtime`: evaluation time in seconds

- `last_reconcile`: ISO timestamp of the last reconcile

- `last_config_mtime`: the mtime seen last run (drives file-change detection)

- `last_trigger`: trigger ID (`"periodic"` for integration- scheduled ticks,
  `"manual"` for everything else: dev-tools calls, the integration's startup +
  reload kicks)

- `reconcile_pending`: true when a reconcile is deferred (config error, API
  unreachable, controller not ready, or the previous reconcile had apply
  failures)

- `routes_in_config`: count of route directions after parsing + resolving
  (typically 2 x number of YAML route entries)

- `routes_applied`: count of route directions currently applied

- `routes_pending`: count of route directions that have been requested but not
  yet confirmed

- `routes_errored`: count of route directions whose apply failed

- `pending` / `applied`: nested dicts keyed by node ID, keeping the
  per-direction state alive across reconciles:

  ```yaml
  "<node_id>":
    entity_id: lock.front_door
    paths:
      - type: priority_app   # or priority_suc
        repeaters:
          - id: 23
            entity_id: sensor.hallway_extender_node_status
        speed: auto          # or 9600 / 40k / 100k
        requested_at: "2026-04-21T12:00:00+00:00"
        confirmed_at: ""     # empty while pending
        timeout_count: 0     # bumped on each timeout retry
  ```

  The same node can appear in both `pending` and `applied` when only one of
  the two directions has landed. Once a set lands, `timeout_count` carries
  forward into the applied entry so you can see how many retries it took.

  `pending` also carries *clear* requests issued by the **Clear routes not in
  config** path. A clear entry has an empty `repeaters` list and `speed: "-"`.
  Clears fall out of `pending` entirely once they land -- they do not enter
  `applied`, since `applied` tracks only routes currently at a specific
  non-default value.

- Error-state diagnostic fields (zeroed/empty on a successful reconcile):
  `config_errors`, `resolve_errors`, `api_error`, `bridge_error`. Useful for
  figuring out why `reconcile_pending` is true when no notification is up.

- Circuit-breaker fields: `bridge_error_streak` (consecutive reconciles that
  ended with a bridge-timeout error) and `circuit_open_until` (ISO timestamp
  -- the circuit is open until this time; empty when closed). Both persist
  across reconciles so other error paths don't reset them.

### Bridge-timeout circuit breaker

The Z-Wave controller's serial interface has been observed to wedge under a
burst of priority-route queries, and each reconcile's own burst re-triggers
the wedge on the next recovery attempt (see the [incident record][wedge]). The
circuit breaker in the reconcile wrapper stops this amplification:

- After `CIRCUIT_BREAKER_THRESHOLD` (3) consecutive reconciles end with a
  bridge-timeout error (matched by `TimeoutError` in the captured error
  string), the breaker opens for `CIRCUIT_BREAKER_COOLDOWN` (15 min).
- While the breaker is open, the reconcile returns early without calling the
  bridge. `bridge_error: "circuit breaker open"` is written to the state
  entity so the skip reason is visible.
- A manual trigger (service tool / dev tools) bypasses the breaker so the user
  can force a retry at any point.
- On the first successful bridge call after the cooldown, the breaker resets
  (streak = 0, `circuit_open_until = ""`) and the notification is cleared by
  the normal notification sweep.
- Non-timeout bridge errors (`ConnectionError`, `OSError`) don't count toward
  the streak, since those are usually transient addon-boot conditions.

When the breaker opens, a persistent notification titled "Z-Wave Route
Manager: controller unresponsive" is raised with the cooldown duration and
absolute resume time. If the controller stays wedged and the cooldown slides
forward, the notification is re-emitted in place with the new resume time --
the user never sees a stale "resume at HH:MM" that has already passed. Its ID
(`<prefix>circuit_breaker`) is outside the notification sweep's
`keep_pattern`, so it is auto-cleared by the first successful reconcile after
the cooldown.

### Debug logging

Set the blueprint's *Debug logging* to on. Output appears in Settings ->
System -> Logs with the tag `[ZRM: <automation alias>]`.

Example:

```text
[ZRM: Z-Wave Route Manager] configured=6 applied=4 pending=2
  errored=0 new_timeouts=0 actions_executed=2
```

### Reconcile trigger semantics

The blueprint has no triggers of its own -- the integration owns scheduling
and recovery. Periodic reconciles fire `automation.trigger` with
`trigger_id == "periodic"`, keyed off the **Reconcile interval (minutes)**
input. Manual triggers and the integration's restart and reload kicks all
arrive as `trigger_id == "manual"`. The service handler's gate then decides
whether each call warrants a full reconcile:

| Signal                                                    | Action                       |
| --------------------------------------------------------- | ---------------------------- |
| `trigger_id == "manual"` (dev tools, startup, reload)     | Reconcile                    |
| Config file mtime changed since last run                  | Reconcile                    |
| Time since last reconcile exceeds the configured interval | Reconcile                    |
| `reconcile_pending == true` from prior tick               | Reconcile                    |
| Otherwise                                                 | Update `last_run` only, exit |

### Why zwave-js-ui and not zwave-js-server directly?

The priority-route command family arrived in zwave-js-server schema 47, which
has since shipped, but `zwave-js-server-python` still exposes no typed wrapper
for it -- its `Controller` has no `setPriorityRoute` equivalent, so reaching
those commands through the Python client would mean hand-rolling raw schema
messages. The HA Z-Wave JS addon bundles zwave-js-ui, which drives zwave-js
core's route APIs directly via its own socket.io `ZWAVE_API` event -- no
schema negotiation, and the APIs we need (`setPriorityRoute`,
`assignPrioritySUCReturnRoute`, etc.) are all allow-listed in its ZwaveClient.
Shipping through zwave-js-ui avoids waiting for the Python client to catch up.

When `zwave-js-server-python` grows those wrappers and HA core surfaces
priority-route services natively, migration is one file:
`custom_components/blueprint_toolkit/zwave_route_manager/bridge.py`. Its
public API (ZwaveJsUiClient + typed methods) stays the same; the
implementation swaps from socket.io to the HA client.

### Future work

- N-hop repeater chains. The logic module's data structures already accept
  `repeater_node_ids: list[NodeID]`; v1 just enforces `len == 1`.

- `direction:` override (controller->node only vs. node->controller only). v1
  always sets both.

- `defaults:` top-level YAML block. Reserved by having `routes:` as the only
  recognised top-level key.

- Migration from the socket.io bridge to `zwave-js-server-python` once that
  client wraps the priority-route commands.

- Auto-reset of a wedged controller. The [incident record][wedge] carries the
  design.

[wedge]: https://github.com/epilatow/ha-blueprint-toolkit/blob/main/ZWAVE_CONTROLLER_WEDGE.md
