# Z-Wave Controller Wedge

Developer record of the Z-Wave controller wedge behind Z-Wave Route Manager's
circuit breaker, and a design for automating recovery. This file is not
shipped. The user-facing recovery steps are in
[zwave_route_manager.md](docs/zwave_route_manager.md).

## The incident

Observed once so far, 2026-04-23, after inclusion of two Zooz ZSE11 Q Sensors
as Z-Wave Long Range nodes (IDs 273 and 274). ZRM and the `zwavectl.py` probe
were both issuing `getPriorityRoute` for every node including LR ones;
upstream zwave-js-ui already skips LR for its own startup interview, so our
code was the last remaining LR-priority-route caller in this install. At some
point during that window the controller (HA Z-Wave JS addon 1.2.0) stopped
ACKing the driver's serial commands entirely -- every call timed out,
priority-route queries on mesh nodes and LR alike. zwave-js cycled
unresponsive -> soft-reset-failed -> reopen-serial -> next command hangs, and
the reconcile's own burst of queries re-triggered the wedge on each recovery,
so the automation itself became part of what kept the stick wedged.

What exactly triggered the wedge isn't conclusively known. Plausible
candidates: an LR-node `getPriorityRoute` call hitting a firmware bug, the
volume of concurrent priority-route commands saturating the controller queue,
or an interaction with the LR nodes' first post-inclusion check-ins. We never
reproduced a clean trigger.

The two-part fix (shipped):

1. **Skip LR nodes in the per-node route refresh**
   (`ZwaveJsUiClient.get_nodes_with_fresh_routes` and the mirror in the
   bundled `zwavectl.py`). LR is a direct-star topology with no mesh, no
   priority routes, and no SUC return routes, so the queries are meaningless
   regardless of any firmware issue. If LR priority-route calls were part of
   the trigger, this removes our contribution; if not, the calls were still
   wasted round-trips worth eliminating.
2. **Circuit breaker** (see `docs/zwave_route_manager.md`) so a wedge from any
   future trigger doesn't get amplified by subsequent reconciles.

### Recovery findings from the 2026-04-23 incident

Tried, in order:

1. **Addon restart** (`ha addons restart core_zwave_js`) -- made things worse.
   Pre-restart the driver was initialised and only `getPriorityRoute` calls
   hung. Post-restart the driver couldn't complete its own capability-query
   handshake; every attempt timed out on the ACK for
   `ZWaveController.queryCapabilities`. A driver-level reconnect is not enough
   to recover the stick.
2. **USB port "re-authorize" via sysfs, 1-second off-window**
   (`echo 0 > /sys/bus/usb/devices/<port>/authorized` then `echo 1 > ...`, ~1
   s between) -- unreliable. Worked once early in the incident and gave ~10 s
   of healthy operation before the wedge re-triggered, but a second attempt ~8
   h later with the same short window did nothing -- the driver couldn't even
   complete `queryCapabilities`.
3. **USB port re-authorize with a 10-second off-window** -- this is the one
   that worked. After idling the stick (addon stopped, nothing touching
   `/dev/ttyACM0` for ~30 s), toggling authorize 0 -> 1 with a 10 s gap let
   the driver come up cleanly and stay up. At the time of writing the
   controller has been healthy and processing traffic (including LR) for
   several minutes with no wedge recurrence.

The off-window length is the most obvious difference between the unreliable
and successful attempts, but with only three data points (two 1 s attempts,
one 10 s attempt) we can't conclusively say it's the causal factor. One
conjecture: the stick's MCU firmware has internal state that needs time to
drain; an instant re-authorize preserves that state, a longer off-window lets
it reset. Same sysfs path, same kernel API, different outcomes.

Unknowns that remain:

- **What actually triggered the self-sustaining wedge.** Our best guess is the
  probe script's burst of `getPriorityRoute` calls against the LR nodes we'd
  just included, but the wedge persisted and re-triggered for hours after all
  our code stopped issuing any commands. Something ambient (a sleepy mesh
  node's periodic check-in, or an LR node's wake-up frame) kept re-triggering
  the firmware bug on its own, on a ~30 s cadence. We couldn't isolate which
  specific frame from the silly-level driver log because the controller was
  too hung to produce useful traffic records.
- **Whether the 10 s off-window is deterministic or just lucky.** We have one
  data point where it worked. Needs more evidence across different wedge
  depths before we trust it as a reliable remediation.
- **Whether controller firmware version matters.** This incident was on a Nabu
  Casa ZWA-2 (800-series Silicon Labs). Older 500/700-series sticks may behave
  differently.
- **Whether `ha host reboot`** (which cycles the USB subsystem at the OS
  level) would also clear the state when authorize-toggle doesn't. Not
  evaluated since the 10 s authorize window worked first.

Until we have more data, treat recovery as an escalation ladder: (a) addon
restart -- cheap but insufficient in the one instance we tried; (b) USB
authorize toggle with a 10-second-or-greater off-window -- this is new and
promising; (c) `ha host reboot` -- untested for this failure mode; (d)
physical unplug/replug -- untested in this incident but the canonical fallback
for any USB device in an unknown state; requires hardware access.

## Auto-reset design

When the circuit breaker trips repeatedly (e.g. N opens within M hours), we
would like a software-only self-heal action. We have one empirically-confirmed
recovery recipe from the 2026-04-23 incident (see "Recovery findings" above):

1. Stop the addon (`hassio.addon_stop`).
2. Idle for ~30 s with nothing touching `/dev/ttyACM0`.
3. Toggle the stick's USB port authorize:
   `echo 0 > /sys/bus/usb/devices/<port>/authorized`, wait **at least 10 s**,
   then `echo 1 > .../authorized`. See "Recovery findings" above for why the
   off-window length appears to matter.
4. Wait ~3 s for the bus to settle.
5. Start the addon (`hassio.addon_start`).
6. Poll the driver-ready signal; give up after ~60 s.

All of this is automatable from the integration's handler (or a small
companion automation). The HA core container has write access to
`/sys/bus/usb/devices/<port>/authorized` (confirmed during debugging -- it's
root-owned 0644 and the integration runs in-process), and `hassio.addon_stop`
/ `hassio.addon_start` are first-class services. **Do not use
`hassio.addon_restart`** -- that's what we tried first and it made things
worse.

Design sketch for the implementation:

- Blueprint input `reset_wedged_controllers` (default `false`) so this is
  opt-in and the user has explicitly acknowledged what the automation is
  allowed to do.
- Blueprint input for the stick's USB sysfs port path (e.g. `1-1.1`) -- the
  path is hardware/topology specific and can't be auto-detected reliably
  across systems. Default empty means "disabled regardless of the
  reset_wedged_controllers toggle."
- State fields `last_auto_reset_at` (datetime) and `auto_reset_count_today` to
  cap attempts.
- Cooldown (e.g. 6 hours between resets, max 3 per 24 hours) to prevent a
  reset loop if the action stops working.
- Separate persistent notification (distinct id outside the sweep's
  `keep_pattern`) that describes what was attempted and when, and is **not**
  auto-cleared -- the user should see the history.
- Detection signal is the breaker's `open` transition; auto-reset fires when
  the transition count within the last X minutes exceeds a threshold.
- Post-action validation: after the addon starts, poll for a successful
  `getNodes` response within ~60 s. If still wedged, **do not** escalate
  automatically -- surface a notification describing the failed recovery and
  stop.
- Skipped from v1 for two reasons: (a) the shipped LR-filter fix removes our
  code's possible contribution to the trigger (we don't know for sure LR
  priority-route calls were the trigger, but if they were, our code no longer
  issues them); (b) the recovery recipe has exactly one successful data point
  so far, which isn't enough to trust it for unattended operation. Revisit
  once either the wedge recurs despite the LR filter (so we know the recipe is
  worth automating) or we gather more data points confirming the recipe is
  reliable.
