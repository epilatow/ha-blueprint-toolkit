# Development Guide for Agent Sessions

Agent guidance specific to this repo, layered on
`DEVELOPMENT_SHARED_AGENT.md`. `DEVELOPMENT.md` and `AUTOMATIONS.md` cover the
repo's dev process and automation conventions.

## File markers

All agent-generated Python files begin with the literal comment
`# This is AI generated code` directly under the shebang (or at the top of the
file for non-shebang modules). The marker identifies which files in the repo
are agent-generated for future audit / review purposes.

## Dev-deploy verification

When the user asks for a `./scripts/dev-deploy.py` test cycle, the deploy is
NOT verified until each step below has cleared. Skipping any step risks a
"clean deploy" that silently changed user-visible behavior.

### Reaching the HA API

Run every authenticated REST / websocket call in the steps below **from the HA
host over SSH**, not from the dev machine. This host's inbound path to port
8123 -- both the LAN name `homeassistant.local` and the Tailscale name
`homeassistant` -- strips the `Authorization` header before it reaches HA
core, so an authenticated call from the dev machine returns
`401: Unauthorized` regardless of token validity. The same token reaches HA
core intact over the internal supervisor network (the `homeassistant` name as
resolved on the host). Unauthenticated routes (`/manifest.json`) still return
200 from the dev machine, so HA looks healthy -- only authed calls fail, which
is easy to misread as a bad token.

- **REST** (states, services, `automation.trigger`):

  ```bash
  API_KEY=$(tr -d ' \t\r\n' < ~/tmp/ha-api-key)
  ssh root@homeassistant \
    "curl -s -H 'Authorization: Bearer $API_KEY' \
     http://homeassistant:8123/api/states/<entity_id>"
  ```

- **Websocket** (persistent notifications -- there is no REST form): copy
  `scripts/ha_ws_fetch.py` to the host and run it there. The host's system
  `python3` has `websockets` importable; `uv` is not assumed present, so the
  helper is plain Python (no PEP 723 block).

  ```bash
  scp scripts/ha_ws_fetch.py root@homeassistant:/tmp/
  ssh root@homeassistant \
    "HA_TOKEN='$API_KEY' python3 /tmp/ha_ws_fetch.py \
     persistent_notification/get"
  ```

  The command type defaults to `persistent_notification/get`; pass any other
  (e.g. `get_config`) as the first positional argument. The token comes from
  `$HA_TOKEN` or `--token-file`; the result prints as indented JSON; the
  helper exits non-zero on auth rejection, a failed command, or a connection
  failure.

### Pre-deploy: baselines

Before running `./scripts/dev-deploy.py`, capture two snapshots for the
post-deploy diffs in steps 6 + 7, using the access methods above:

- **Persistent notifications** to `tmp/dev-deploy-pn-baseline.json`.
- **Diagnostic state entity attributes** to
  `tmp/dev-deploy-state-baseline.json`: the full attribute dict of every
  `blueprint_toolkit.*_state` entity.

### Post-deploy

Run all seven checks in order. Checks 1-4 are integration-level sanity; 5-7
are user-visible-behavior validation against the pre-deploy baselines.

1. **HA back online.** Poll via SSH+internal-HTTP (the dev-machine HTTPS path
   fails during restart). Probe an unauthed endpoint -- `/manifest.json`
   returns 200 without a bearer token, while `/api/` returns 401 to an
   unauthed request, so a `curl -sf` probe against it loops forever even after
   HA is back:

   ```bash
   until ssh root@homeassistant \
       curl -sf http://homeassistant:8123/manifest.json >/dev/null; do
       sleep 2
   done
   ```

2. **Config entry loaded.** `blueprint_toolkit` config entry shows
   `state: loaded` with no `reason` set. `setup_error` here means the
   integration raised at setup.

3. **Symlinks correct.** `/config/custom_components/blueprint_toolkit` points
   at the new timestamped snapshot; the
   `/config/blueprints/automation/blueprint_toolkit/*.yaml` symlinks point at
   bundle paths under the same snapshot.

4. **No new HA log errors.** Read the live HA log via
   `ssh root@homeassistant 'ha core logs --lines 5000'` -- NOT by tailing
   `/homeassistant/home-assistant.log*` on the host, which is stale. Pass a
   `--lines` window that spans the restart timestamp and a few minutes of
   post-restart activity, and filter for `custom_components.blueprint_toolkit`
   at WARNING / ERROR / EXCEPTION level since the restart.

   Expected baseline noise that is NOT a regression:

   - `homeassistant.loader` WARNING "We found a custom integration
     blueprint_toolkit which has not been tested by Home Assistant", on every
     restart.
   - Per-handler WARNING summaries from any automation configured with
     `debug_logging=true` (e.g.
     `[ZRM: ...] configured=N applied=N pending=0 errored=0 ...`).
   - Pre-existing unrelated errors that survived the deploy. Compare against
     the pre-deploy log capture: an entry already present and unchanged is not
     a regression. New stack traces or "failed to register service" messages
     from `custom_components.blueprint_toolkit` ARE regressions.

5. **All diagnostic state entities populated.** Every
   `blueprint_toolkit.<service_tag>_<slug>_state` entity has a `last_run`
   post-restart and a valid `state`:

   - Watchdog handlers (DW, EDW, RW, ZRM, ZPM): `state="ok"` with non-zero
     `runtime`.
   - Trigger-driven handlers (STEC, TEC): `state` is one of the handler's
     `Action` enum values (`NONE`, `TURN_ON`, `TURN_OFF`, ...); `runtime` may
     be `0.0` for no-op evaluations.

   Force a run via `automation.trigger` instead of waiting for periodic ticks.
   The state entity is the per-instance liveness signal -- a loaded config
   entry can still leave individual handlers broken (recovery kick failed,
   periodic timer didn't arm, instance state never built).

6. **Persistent notifications match baseline.** After every blueprint-backed
   automation has run at least once, re-fetch `blueprint_toolkit_*` PNs and
   diff against the pre-deploy baseline:

   - **In post but not pre** (newly fired): regression UNLESS the deploy added
     a new check or notification category. Verify the new body shape matches
     the design.
   - **In pre but not post** (cleared): regression UNLESS the deploy removed a
     check or fixed a bug whose finding cleared.
   - **In both, content changed**: investigate. Usually a notification-body or
     instance-ID-prefix drift.

   This catches regressions that steps 1-5 miss. A common case: a
   notification-ID prefix change orphans the old PN and emits a new one, so
   the user sees two notifications where there was one while everything "ran
   cleanly".

7. **Diagnostic state attributes match baseline (sanity check).** Step 5 only
   confirms the entities are populated; this step confirms the values make
   sense. After every blueprint-backed automation has run, re-fetch all
   `blueprint_toolkit.*_state` entities and diff their attribute dicts against
   `tmp/dev-deploy-state-baseline.json`. Any change should be explainable by
   the deploy:

   - **For watchdogs** (DW, EDW, RW, ZRM, ZPM): per-handler stat counters
     should be unchanged unless the deploy modified detection / scan /
     reconcile logic. Concrete examples of expected drift:
     - DW's `device_issues` drops by 1 -> a deploy that changed a check, OR a
       device recovered between baseline and now.
     - RW's `refs_total` jumps by 467 -> a deploy that added new reference-set
       sources.
     - ZRM's `routes_applied` increments by 1 -> a deploy that fixed a
       reconcile bug AND a route was successfully applied this run.
   - **For trigger-driven handlers** (STEC, TEC): only compare `last_run` and
     `runtime`. Their state attributes change naturally on every trigger and
     aren't a regression signal across a deploy.

   Unexpected drift is a regression signal in the same class as a new
   notification appearing. If the code path that moved the value isn't
   immediately clear, the deploy isn't verified -- it just looks clean.

### Feature-specific verification

On top of the seven standard checks, exercise the specific code path the
deploy carries, for the components it actually changed:

- **ZRM**: add or remove a priority route on a FLiRS or non-battery-powered
  device, then wait for the next reconcile (or trigger manually) and confirm
  ZRM applied or cleared the route as expected. Battery-powered devices don't
  work for this test -- their route changes don't apply until the device wakes
  up, which can be hours. The user's environment has FLiRS locks (preferred)
  and Z-Wave repeaters available.
- **DW / EDW / RW**: trigger a synthetic finding (disable a diagnostic entity
  for DW; rename an entity to drift it for EDW; introduce a broken reference
  in a YAML file for RW), then verify the expected notification fires with the
  right ID and body.
- **STEC / TEC**: trigger the sensor or state change that should fire the
  controller, then verify the right action (`turn_on` / `turn_off` / no-op)
  ran and the diagnostic state entity reflects the decision.

### Blueprint-compatibility breakage during dev-deploy testing

If a deploy lands a blueprint-input rename or schema change that breaks the
user's existing automation YAML, **update the automation config on the host to
match the new blueprint shape** rather than treating it as a verification
failure. The dev environment is the only live deployment, so rolling a new
blueprint shape forward is the expected workflow.

Edit `/config/automations.yaml` (or the relevant include file), save, reload
automations, and re-run the relevant checks. Report what changed and why. This
is the one carve-out from the "no edits beyond `tmp/` on the host" rule below.

### What I do NOT do without explicit ask

`./scripts/dev-deploy.py --restore` (reverses the deploy), restart HA again
after verification, push commits, edit anything beyond `tmp/` on the host
(with the carve-out for blueprint-compatibility breakage above). Even if a
verification step fails, surface the specific failure (which check + the exact
log line / state-entity attribute / notification body) and let the user
decide.
