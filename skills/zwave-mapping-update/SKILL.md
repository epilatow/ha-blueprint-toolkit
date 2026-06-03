---
name: zwave-mapping-update
description: Classify node-zwave-js parameter labels into ZPM catalog concepts and propose updates to custom_components/blueprint_toolkit/zwave_parameter_manager/mapping.json. Walks the deterministic extraction, applies conservative per-concept classification criteria, emits a proposed mapping.json, validates it against the existing mapping and (when available) against the fleet snapshot. Run weekly to surface new device labels as zwave-js ships them.
---

# zwave-mapping-update

This skill is the LLM-classification half of the ZPM mapping pipeline. The
deterministic half (download + extract + per-(CC, label) aggregation) is
`scripts/zwave_db_extract.py`; this skill consumes its output. Verification
(offline against a fleet snapshot) is `scripts/verify_zwave_mapping.py`.

The operational invariants are non-negotiable:

- **Never query a live HA host during classification.** Use only the
  extraction output + the in-repo `mapping.json` + (optionally) the
  pre-captured `tmp/fleet.yaml`. The fleet snapshot is captured once, ahead of
  time, by the operator -- not by this skill. This bars the operator's HA host
  and their device states, *not* the public web. Consulting a device manual,
  the OEM's config, or the zwave-js / z-wave.info databases to settle an
  uncertain scale direction (step 4) is allowed and encouraged -- research
  only **stable** device facts (a sensor's sensitivity convention does not
  change over time), never volatile ones, and record the source in the commit
  message so the call is auditable. Reproducibility here depends on **source
  authority**, not just stability: public sources disagree, so two runs
  converge only when they weigh an unambiguous authoritative source the same
  way -- which is why step 4 ranks sources and flags conflicts rather than
  trusting whatever turns up first. The two are different universes: the live
  fleet is off-limits; public device documentation is fair game.
- **Conservative classification bar.** False positives are worse than false
  negatives. A wrong locator routes the resolver to the wrong device param; a
  missed locator just produces NOT_APPLICABLE, which the operator can resolve
  later by adding a label.
- **No label hallucination.** Every label emitted in the proposed mapping must
  exist verbatim in `tmp/zwave_db_labels.json`. The validate step checks this;
  a hallucination is a skill bug.
- **Reproducibility (byte-strict).** After the canonicalize step, two runs of
  this skill against the same extraction snapshot must produce byte-identical
  proposed mappings. Non-deterministic LLM ordering is squashed by
  `scripts/canonicalize_zwave_mapping.py`. Drift in the criteria is a
  deliberate edit to this file, not a per-run improvisation.

## Inputs

- `tmp/zwave_db_labels.json` -- output of `zwave_db_extract.py`. If missing or
  older than 7 days, refresh it (step 1).
- `custom_components/blueprint_toolkit/zwave_parameter_manager/mapping.json`
  -- the current checked-in mapping. New runs propose a diff against this.
- `custom_components/blueprint_toolkit/zwave_parameter_manager/catalog.py` --
  the GenericParamNames + CATALOG entries (including each concept's
  description). Read this every run; the catalog may have gained concepts
  since the last run.
- `tmp/fleet.yaml` (optional, when present) -- offline fleet snapshot. Used by
  the verification step only; the classification itself ignores it.

## Procedure

### 1. Refresh the extraction (if stale)

```bash
./scripts/zwave_db_extract.py
```

Outputs `tmp/zwave_db_labels.json`. The script records the `node-zwave-js` tag
it pulled; the tag goes into the proposed `mapping.json`'s commit message
later.

### 2. Read the current state

Load:

- `tmp/zwave_db_labels.json` -- the full label catalog, grouped by command
  class then label. Each label entry has `command_class`, `label`,
  `device_count`, and `instances` -- one per device that carries the label,
  each with `manufacturer`, `model`, `value_size`, `min`, `max`, `unit`,
  `options` (value + label), and `description`. The per-device `description`
  is the only *prose* source of a device's scale *direction* (step 4 also
  reads option ordering and `min`/`max`, and may consult the device manual --
  but prose, when present, lives only here).
- `custom_components/blueprint_toolkit/zwave_parameter_manager/mapping.json`
  -- the current locators (the **canonical accepted set** of labels per
  concept, to be preserved verbatim in the proposal), quirks, and label /
  token vocab.
- `custom_components/blueprint_toolkit/zwave_parameter_manager/catalog.py` --
  the `GenericParamNames` enum members and their `CATALOG` entries
  (`param_type`, `units`, `range`, `description`).

If the catalog has gained a concept not currently in `mapping.json` or in the
criteria below, stop. New concepts need explicit criteria added to this file
before classification can extend to them.

### 3. Classify per concept

For each concept in the catalog, walk the extraction's labels and apply the
criteria below. Emit two outputs per concept: an ACCEPTED list (becomes the
locator's `labels`) and a REJECTED list with reasons (kept in the run log;
used for human review).

Format each decision: keep the label exact (preserve case, spacing, and
punctuation). Reject everything you're not certain about.

The semantic meaning of each concept (what it is, what its value shape and
units are, how the resolver applies it) lives in `catalog.py`'s `description`
field on each `GenericParam` -- the authoritative source. Read it there; the
criteria below are skill-specific (when to ACCEPT or REJECT a candidate label)
and don't repeat the catalog's semantic documentation.

**The skill is additive only.** The proposal must preserve every label already
under `mapping.json`'s `locators.<concept>.labels` verbatim and only add new
matches from the extraction. Removals are a deliberate operator edit, not
something the skill performs. The `ACCEPT` bullets below therefore describe
only the *pattern* for finding new candidates; the canonical accepted set for
each concept is `mapping.json` itself and is not re-listed per concept here.

Additive applies to **quirks too**, not just labels. Every entry in
`mapping.json`'s `quirks` (and every entry in the reviewed-ascending
companion, step 4) must reappear verbatim in the proposal -- carry the current
direction decisions forward and only add to them. A quirk you re-derive this
run must match the committed one; a quirk you don't re-derive must still be
preserved. Step 8 enforces this: dropping a current quirk fails validation,
because a dropped `invert` on a flagger-blind device (prose-only inversion the
heuristic can't parse) would otherwise be a silent wrong-direction write.

**Criteria backfill -- keep classification reproducible.** The byte-strict
reproducibility guarantee comes from canonicalize (step 7); it pins
*ordering*, not classification *judgment*. If you ACCEPT a label that no
enumerated ACCEPT pattern below already captures -- i.e. you accepted it under
a general clause -- a future run could legitimately reject it, breaking
reproducibility. Whenever you make such an accept, also edit that concept's
ACCEPT criteria in this file to name the form you accepted, and stage the
SKILL.md edit in the review worktree alongside the mapping change (step 9).
The operator then reviews the new label and the rule that makes it
deterministic together, and accepting the branch leaves the next run
reproducible by construction. If every accept this run is already covered by
an enumerated pattern, no SKILL.md edit is owed.

#### motion_sensitivity

- **ACCEPT** patterns: head noun from the motion family (`Motion`,
  `Motion Sensor`, `Motion Detector`, `Motion Detection`, or `PIR`), paired
  with `Sensitivity` or `Sensitivity Level`. An interposed qualifier is fine
  when the head is a motion term (`Motion Detection Sensitivity`). Mild
  punctuation variants (`Motion Sensor: Sensitivity`) match the same pattern.
- **REJECT** when the label belongs to a different sensor type or a different
  setting:
  - Tilt / vibration / contact sensors -- these may need their own concept
    later, not motion_sensitivity.
  - Motion timeout / clear-delay / re-trigger time -- these are timing
    controls, not sensitivity.
  - Motion reporting toggles (e.g. `Motion Sensor Report Indicator`) --
    ambiguous wording, conservative reject.
  - Anything mentioning Basic Set, Association Group, LED, or Brightness in
    the same string.

#### light_on_motion

- **ACCEPT** patterns:
  - `LED` (any spelling: `LED`, `LED Indicator`, `Status LED`) tied to motion
    -- either paired with `on Motion`, `(Motion)`, or `: Blink on Motion`, or
    a motion-prefixed toggle (`Motion LED`) whose options or description
    confirm it enables / disables a motion-triggered LED (e.g. Disable /
    Enable with a description like "LED flash when motion is sensed"). The tie
    to motion must be explicit in the label or its description, and the param
    must be an on / off toggle, not a brightness / color setting.
  - A report- / activity-triggered LED toggle whose label does not itself name
    motion but whose `description` ties the LED to the device's reports /
    activity (e.g. `LED Activity`, description "Enable/Disable LED activity
    when specific reports are sent"), with a clean Disable / Enable option
    pair. On a motion sensor the reports that drive the LED include motion, so
    this IS the device's motion LED -- but only there. Accept ONLY when
    **every** device carrying the label is a motion sensor: each instance's
    `(manufacturer, model)` must also appear, in the extraction, under a
    motion-family parameter (a `Motion` / `Motion Sensor` / `PIR` sensitivity
    or detection label -- the motion_sensitivity ACCEPT set). If any carrier
    is not a motion sensor the label is ambiguous across device types --
    REJECT it (a generic activity LED on a plug or contact sensor is not
    motion-driven). Today `LED Activity` is carried only by the Aeotec ZWA045,
    a motion sensor, so it qualifies.
- **REJECT** when:
  - The LED triggers on a specific NON-motion event
    (`LED Indicator: Tamper Alarm`, `LED Indicator: Open/Close Change`,
    `LED Indicator: Wake Up`). (A *generic* activity / reports LED differs: on
    a motion sensor its reports include motion -- see the second ACCEPT
    pattern -- whereas these name a single non-motion event.)
  - The label controls motion reporting rather than LED
    (`Motion Detection: Send Basic Set`, `Motion Sensor Report Indicator`).
  - The label is about LED brightness or color (a continuous setting, not an
    on / off toggle).
  - A report- / activity-triggered LED toggle carried by ANY device that is
    not a motion sensor (no motion-family parameter on that
    `(manufacturer, model)`) -- there the LED is not motion-driven.

#### humidity_report_threshold

- **ACCEPT** patterns: labels combining `Humidity` with `Report` or
  `Reporting`, optionally `Change`, and `Threshold` (in either order). Mild
  prefix / punctuation variants (`Humidity Sensor: ...`,
  `... D-Value (Report Threshold) Setting`, or a leading report-context prefix
  that supplies the `Report` / `Reporting` token, e.g.
  `Automatic Reporting: Humidity Change Threshold`) match the same pattern
  when the meaning is still "minimum humidity change before sending a report."
- **REJECT** when:
  - The label refers to a time-based reporting interval
    (`Humidity Reporting Interval`).
  - The label refers to an absolute alert threshold
    (`High Humidity Alert Threshold`, `Low Humidity Alert Threshold`).
  - The label refers to a Basic Set trigger threshold
    (`High Humidity Basic Set Threshold`,
    `High Humidity Trigger Basic Set Value`).
  - The label refers to a calibration offset (`Humidity Offset`).

#### threshold_check_interval

- **ACCEPT** patterns: the canonical `Threshold Check Interval`, plus
  reordered / prefixed forms that name the SAME single whole-device
  threshold-recheck cadence -- e.g.
  `Change Threshold Reporting: Check Interval` (the recheck cadence paired
  with a `Change Threshold Reporting: <sensor>` threshold on the same device).
  Accept such a form only when the device carries exactly one check-interval
  param (verify via the label's `instances` -- the device should not also
  carry per-sensor check intervals); a single match is what keeps it
  unambiguous.
- **REJECT** when:
  - The label is sensor-specific (`Brightness Check Interval`,
    `Temperature Check Interval`, `Humidity Check Interval`) -- these scope a
    check to one sensor, and a multisensor carries several at once, so
    matching them would make the concept AMBIGUOUS. (This is why the accept
    above is restricted to whole-device, single-interval forms.)
  - The label refers to sensing cadence (`Brightness Sensing Interval`).
  - The label refers to report cadence (`Brightness Reporting Interval`,
    `Sensor Report Interval`, `Automatic Reporting Interval`).
  - The label is unrelated to threshold checking (`Heartbeat Interval`,
    `Battery Check Interval`).

#### wake_up_interval

- This concept is locked to `FixedValueId(132, "wakeUpInterval")` via the
  `WAKE_UP_INTERVAL_VALUE` constant in `logic.py`. No label classification is
  required or accepted -- the locator is the protocol-level value-id, not a
  label match.

### 4. Quirks + scale-direction safety

A `ModelQuirk` overrides what the device metadata can't express:

- `invert: true` -- a RANGE param whose raw scale runs backwards (a higher raw
  value means LESS, not more).
- `off_value` / `on_value` -- pin a BOOL's raw values when the option states
  don't clearly name an off / on.

A quirk key is `(concept_name, manufacturer, model)`. The JSON nests
`concept -> manufacturer -> model -> quirk_fields`. The manufacturer / model
strings come from the instance (`instances[].manufacturer` /
`instances[].model`) under the label.

**Direction is the one error the rest of the pipeline cannot see.** The
resolver assumes a higher raw value means more; `verify` treats a
wrong-direction write as a valid RESOLVED, not an error. So for every RANGE
concept (`param_type == RANGE` in `catalog.py`), you MUST read each accepted
label's `instances` and judge direction per device:

- **Read every instance's `description`** (and `options`, and `min`/`max`).
  Direction lives in the prose -- "8 = highest, 255 = lowest", "Higher values
  = lower sensitivity", "1 = least, 10 = most". A device with a descending
  scale gets `invert: true` for its `(concept, manufacturer, model)`. Reversed
  option ordering (e.g. `1=High, 2=Medium, 3=Low`) is the same signal.
- **A conventional-looking range is not proof of ascending.** A min of 0 or 1
  does NOT settle direction. The real red flag is a device with **no in-DB
  direction signal at all** -- no direction-bearing description AND no named
  options -- whose same-OEM sibling IS descending. Vendors ship one
  sensitivity convention across a product line, so an undescribed `1-7` or
  `0-15` sensor from an OEM whose described sibling runs `1=Highest..7=Lowest`
  or `8=highest..255=lowest` is almost certainly descending too -- and the
  heuristic flagger, which reads `min in {0,1}` as ascending, is blind to it.
  Compare descriptions and ranges across `instances` to spot the family.
  **Resolve such a device; do not guess -- but weigh your sources.** The
  authoritative sources, in order, are: the node-zwave-js config DB itself,
  the manufacturer's official manual / datasheet, and curated Z-Wave device
  databases (the openHAB Z-Wave binding docs, z-wave.info). Community blogs,
  forum posts, and reseller listings are NOT authoritative -- use them only to
  corroborate, never as the sole basis for a direction call (a single blog can
  have the direction backwards). Cross-check against the parameter's **default
  value**: a sensitivity that defaults to its most-sensitive end tells you
  which raw end is "more". When an authoritative source settles it, add
  `invert: true` if descending or a reviewed-ascending entry if confirmed
  ascending, recording the source in the commit message. When sources
  **conflict** -- or only non-authoritative sources exist -- the direction is
  unresolved: do NOT classify it (no quirk, no reviewed-ascending entry); flag
  it in the operator report as direction-unresolved, naming the conflicting
  sources, so a human settles it. Never silently accept ascending, and never
  let one low-authority source override the config DB or the manual.
- **Record reviewed-ascending devices.** When an instance would trip the
  validate net (descending-looking or direction-uncertain) but you have read
  it and confirmed it IS ascending, append `{concept, manufacturer, model}` to
  the reviewed-ascending companion (a JSON list). This is how the net knows
  you reviewed it rather than missed it. Like quirks, this is **durable
  direction data**: the committed companion beside `mapping.json`
  (`mapping_direction_reviewed.json`) is part of the mapping artifact that a
  standalone re-validate reads. During a run you build the proposal's
  companion at `tmp/zwave_mapping_direction_reviewed.json`, starting from the
  current committed companion and carrying its entries forward additively;
  step 9 commits it alongside the mapping.

The validate step (8) runs a heuristic direction flagger as a backstop -- it
catches the machine-detectable descending / uncertain instances and fails if
any lack an `invert` quirk or a reviewed-ascending entry. The flagger CANNOT
parse prose-only inversions ("Higher values = lower sensitivity"), so it is a
safety net under your reading, not a substitute for it: you are the decider,
the net only ensures nothing machine-detectable slipped through.

Only propose `off_value` / `on_value` quirks when a BOOL device's `options`
demonstrate the need (reversed ordering, or no clean Disable / Enable pair).
Quirks default empty unless the per-device data forces one.

### 5. Vocab

The four label / token categories must remain pairwise disjoint
(MappingTable's `__post_init__` enforces this and raises ValueError on
overlap; the from_dict loader propagates the error).

- `off_labels`: lowercase device-option labels equivalent to "off" (`disable`,
  `disabled`, `off`, `no`, `none`).
- `on_labels`: lowercase device-option labels equivalent to "on" (`enable`,
  `enabled`, `on`, `yes`).
- `low_tokens`: substrings within option labels that indicate the
  scale-direction's low end (`lowest`, `low`).
- `high_tokens`: substrings within option labels that indicate the
  scale-direction's high end (`highest`, `high`).

Only edit these when the extraction surfaces new device option-label
vocabulary not yet covered. Edits to these are infrequent. `low_tokens` /
`high_tokens` are consumed by both the runtime resolver (`_detect_descending`)
and the validate flagger's option-label check, so extending them strengthens
both the runtime and the gate. (The flagger additionally parses *descriptions*
for `8=high`-style digit pairs with its own built-in word list; that prose
parser has no resolver counterpart -- see step 8.)

### 6. Emit the proposed mapping

Write the proposed mapping to `tmp/zwave_mapping_proposed.json` in the same
shape as the current `mapping.json` (the from_dict loader parses both). Don't
worry about sort order or key order -- the canonicalize step in step 7 fixes
both. The required top-level keys are: `metadata`, `locators`, `quirks`,
`off_labels`, `on_labels`, `low_tokens`, `high_tokens`.

Alongside the mapping, write the run's reviewed-ascending companion to
`tmp/zwave_mapping_direction_reviewed.json` (the step-4 list, built additively
from the current committed companion). Both files get committed together in
step 9.

Fill the `metadata` provenance block by branching on whether the snapshot
moved. Compare the extraction's top-level `tag` against the current
`mapping.json`'s `metadata.zwave_js_tag`:

- **Same tag (a *widen* of the existing snapshot).** Carry the current
  `mapping.json`'s `metadata` block forward verbatim. A tag points at one
  immutable commit, so the SHA + committer date are already correct -- and the
  extraction's `commit` / `commit_date` may be absent or `null` (an older
  extraction, or one taken while the GitHub API was unreachable) without
  mattering. Do not trust the extraction's provenance fields in this case; the
  current mapping is the source of truth.

- **Different tag (a *refresh* to a new snapshot).** Take `tag`, `commit`, and
  `commit_date` from the extraction, renamed onto the block:

  ```json
  "metadata": {
    "zwave_js_tag": "<tag>",
    "zwave_js_commit": "<commit sha>",
    "zwave_js_commit_date": "<committer ISO date>"
  }
  ```

  Here the extraction's `commit` / `commit_date` MUST be populated -- they are
  the only record of the new snapshot's SHA. If either is `null` or absent,
  the extraction is stale (written before the provenance feature, or while
  GitHub was unreachable); re-run `zwave_db_extract.py` to repopulate them
  before proceeding.

All three fields are deterministic given the snapshot, so the artifact stays
byte-stable across re-runs against the same DB. Do not add `extracted_at` or
any other non-deterministic field. (The *extraction* file
`tmp/zwave_db_labels.json` does carry a wall-clock `extracted_at` and so is
not itself byte-identical run-to-run; the mapping must not inherit that
non-determinism -- which is why the byte-stability guarantee is about the
mapping after canonicalize, not about the extraction file.)

### 7. Canonicalize

Rewrite the proposal into canonical form (squashes any LLM-introduced ordering
variance):

```bash
./scripts/canonicalize_zwave_mapping.py \
    --mapping tmp/zwave_mapping_proposed.json \
    --extraction tmp/zwave_db_labels.json \
    --reviewed tmp/zwave_mapping_direction_reviewed.json \
    --emit-fixture tmp/zwave_mapping_canonical_extraction.fixture.json
```

The script rewrites both in place: the mapping gets fixed top-level key order,
locator order by catalog declaration, label order by extraction frequency
descending (with alphabetical tiebreak), alphabetic label / token sets, and a
fixed-shape JSON encoding (`indent=2`, trailing newline); `--reviewed` sorts
the companion by concept / manufacturer / model. `--emit-fixture` writes the
canonical-extraction test fixture (the located labels + their device counts)
that `test_mapping_json_is_canonical` needs -- generate it here so it stays in
lockstep with the mapping rather than hand-maintaining it. After this step,
two runs of the skill against the same extraction snapshot produce
byte-identical output for both files.

### 8. Validate

One script wraps every check the proposal must pass:

```bash
./scripts/validate_zwave_mapping_proposal.py \
    --proposed tmp/zwave_mapping_proposed.json \
    --extraction tmp/zwave_db_labels.json \
    --reviewed tmp/zwave_mapping_direction_reviewed.json \
    --fleet tmp/fleet.yaml
```

The script's canonicalize-first short-circuit handles the weekly idle case:
when the canonicalized proposal byte-matches the current `mapping.json`, it
prints `no changes` and exits 0 -- skip to the end and report "no changes."
(The short-circuit compares the canonicalized proposal against the *raw*
current `mapping.json`, so it relies on the committed mapping already being
canonical for the current snapshot -- which holds because step 9 only ever
commits the canonicalized form. One caveat: label order is frequency-based, so
if device counts shift between snapshots without any label-set change, a
genuine no-op can surface as a diff.) When the proposal differs, the script
runs the remaining checks:

- **No hallucinations.** Every label in the proposed `locators.labels` appears
  verbatim in `tmp/zwave_db_labels.json` under CC 112 (Configuration) --
  LabelMatch is Configuration-only, so the check keys on CC 112.
- **Shape.** The proposal round-trips through `MappingTable.from_dict` without
  raising.
- **Quirk preservation.** Every quirk in the current `mapping.json` reappears
  verbatim in the proposal (quirks are additive, like labels -- step 3). A
  dropped or altered current quirk fails; this is what stops a prior `invert`
  on a flagger-blind device from being silently lost.
- **Direction.** For every accepted RANGE-concept label, the heuristic flagger
  checks each device instance; any descending or direction-uncertain instance
  must carry an `invert` quirk or appear in the reviewed-ascending companion
  (`--reviewed`, defaulting to the committed
  `mapping_direction_reviewed.json`; a run points it at
  `tmp/zwave_mapping_direction_reviewed.json`). The flagger parses each
  instance's `description` for `8=high`-style digit pairs (its own word list)
  and its `options` for low/high tokens (the built-in set *plus* the mapping's
  `low_tokens`/`high_tokens`); it is deliberately a different engine from the
  runtime resolver, and is blind to prose-only inversions and to no-signal
  devices (`min` in {0,1}, no prose, no options) -- step 4 is the decider,
  this is the gate for the machine-detectable subset.
- **Unit report (non-blocking).** For every accepted VALUE-concept label, any
  device instance whose `unit` the resolver can't convert from the concept's
  unit is printed as a `UNIT WARNINGS` note. It does not fail (the device just
  UNMAPPABLEs -- safe and loud), but surface it in the operator report: it is
  either a resolver unit-coverage gap or a mis-classified label.
- **Fleet** (when `--fleet` is supplied). `verify_zwave_mapping.py` exits 0 on
  the proposal (no AMBIGUOUS) **and** the proposal's RESOLVED count is not
  lower than the current mapping's (i.e. nothing that resolves today loses its
  match).

Exit non-zero on any failure. The skill aborts and reports what failed -- no
commit happens. A `FAIL direction` means step 4 is incomplete: read the named
instances' descriptions and either add the `invert` quirk or record them as
reviewed-ascending, then re-run.

### 9. Commit to a review worktree

When step 8 reports `no changes`, skip this step and just report "no changes"
to the operator. When the proposal passes with a real diff, land it in a fresh
worktree branch the operator reviews using standard git tooling
(`npx difit <sha>`, `git diff`, etc.), not a `tmp/` file:

```bash
REPO=$(git rev-parse --show-toplevel)
TS=$(date +%Y%m%d-%H%M%S)
WT=$REPO/.wt/zwave-mapping-update-$TS
BRANCH=zwave-mapping-update/$TS
ZPM=custom_components/blueprint_toolkit/zwave_parameter_manager

git worktree add -b "$BRANCH" "$WT"

# Apply the canonical proposal, its reviewed-ascending companion, AND the
# regenerated canonical-extraction fixture (step 7). The fixture must move
# in the same commit -- test_mapping_json_is_canonical fails otherwise,
# because it drives its frequency sort from the committed fixture.
cp tmp/zwave_mapping_proposed.json "$WT/$ZPM/mapping.json"
cp tmp/zwave_mapping_direction_reviewed.json \
    "$WT/$ZPM/mapping_direction_reviewed.json"
cp tmp/zwave_mapping_canonical_extraction.fixture.json \
    "$WT/tests/fixtures/zwave_mapping_canonical_extraction.json"

# If this run owed any criteria backfill (step 3), copy the edited
# SKILL.md into the worktree too so the rule travels with the label.
# cp skills/zwave-mapping-update/SKILL.md "$WT/skills/zwave-mapping-update/SKILL.md"

cd "$WT"
scripts/bump-manifest-version.py
git add "$ZPM/mapping.json" "$ZPM/mapping_direction_reviewed.json" \
        tests/fixtures/zwave_mapping_canonical_extraction.json \
        custom_components/blueprint_toolkit/manifest.json
# git add skills/zwave-mapping-update/SKILL.md   # only if criteria backfilled
git commit -F -   # paste the message built from the template below
```

The commit message is the durable record of *why* each change was made. The
diff shows *what* (labels added, `invert: true` set) but never the reasoning,
and direction reasoning in particular is safety-critical and unrecoverable
from the diff: `invert: true` appears with no hint of why the device is
descending. So the body carries the per-decision rationale the diff can't --
found later via `git log` / `git blame` on `mapping.json` when a reader asks
"why was this device inverted?". This is a deliberate exception to the repo's
"1-3 short paragraphs" norm: a data commit where the reasoning *is* the
artifact. It is NOT a per-label enumeration (the criteria are that record, the
diff shows the labels) -- it is the *why* the diff omits.

Subject by snapshot move (the `metadata` branch in step 6):
`Widen the classification of <tag>.` (same tag) or
`Refresh mapping.json from <old> -> <new>.` (tag moved). Body, in this order:

1. **Summary line** -- additive pass by the skill over zwave-js `<tag>`
   (`<commit>`); `<N>` new labels across `<M>` concepts; `<K>` direction
   quirks; every prior label preserved; metadata
   `<carried forward | taken from the new snapshot>`.
2. **Direction** -- the part the diff cannot show. Every `invert` device
   grouped by the *evidence* that makes it descending, with any flagger-blind
   device (prose-only inversion, no digits, e.g. "Higher values = lower
   sensitivity") called out first -- those are the ones a reviewer most needs
   to re-verify. Then the reviewed-ascending devices and why each is *not*
   inverted despite tripping the flagger.
3. **Notable rejections** -- the near-misses a future reader would wonder
   about, each with a one-line reason. Not the whole reject list.
4. **Criteria** -- any ACCEPT / REJECT criteria extended this run, which
   concept, and why (ties to the SKILL.md edit shipped alongside).
5. **Validation** -- canonical, round-trips, direction gate green, fleet
   verify 0 with no RESOLVED -> UNMAPPABLE regression; plus any non-blocking
   unit-coverage notes.

Worked skeleton of the shape (a Widen). The `<...>` are placeholders -- this
illustrates the section structure, NOT a specific run's data; each run fills
in its own devices, evidence, counts, and rejections:

```text
- zwave_parameter_manager: Widen the classification of <tag>.

Additive pass by the zwave-mapping-update skill over zwave-js <tag>
(<commit>): <N> new labels across <M> concepts, <K> scale-direction
quirks. Every prior label preserved; metadata carried forward (same tag).

Direction (invert:true = the device's raw scale runs backwards, which
verify cannot detect from a successful resolve) -- one device per line,
grouped by the evidence, flagger-blind ones first:
- Flagger-blind / prose-only (no digits to parse): <Mfg Model> ("higher
  value = lower sensitivity", min=0 -- the gate reads it ascending and
  cannot catch it).
- Stated low/high in digits: <Mfg Model> (8=high / 255=low).
- Reversed options: <Mfg Model> (1=High .. 3=Low).
- No in-DB direction signal, confirmed externally: <Mfg Model> (manual:
  1 = most sensitive; cite the source per the research invariant).
Reviewed-ascending (confirmed not inverted): <Mfg Model> (why it is
ascending despite tripping the flagger).

Notable rejections: <label> (<one-line reason>); <label> (<reason>).

Criteria: <concept> ACCEPT extended to <form>, and why -- omit if none.

Validation: canonical, round-trips through MappingTable.from_dict,
direction gate green, fleet verify exits 0 with no RESOLVED -> UNMAPPABLE
regression; <non-blocking unit notes, if any>.
```

A Refresh differs only in the subject and summary line (name `<old>` ->
`<new>` tag, take `<commit>` / committer date from the new snapshot).

If this run extended any criteria (step 3), uncomment the SKILL.md `cp` +
`git add` lines above so the edit ships in the same commit; the Criteria block
records it.

After committing, run the worktree's full test suite (`./tests/run_all.py`
from `$WT`) and confirm it is green -- in particular `test_manifest` (the
bump) and `test_mapping_json_is_canonical` (the committed mapping matches the
regenerated step-7 fixture). A red suite here means the commit is incomplete;
fix it and amend before the review.

### 10. Zero-context review

A real diff gets an independent review before the operator sees it. The
deterministic gate (step 8) is blind to the one error class that matters most
-- a prose-only inversion the flagger reads as ascending (a description like
"higher value = lower sensitivity" with a min of 0 or 1: no digits to parse,
so the heuristic cannot see it). Only a fresh re-read of the descriptions
catches that, so this step is the semantic complement to the gate, not a
duplicate of it.

Spawn a subagent (the Agent tool) with **zero context from this run** -- it
does not see the classification reasoning, the run log, or this conversation.
Hand it only the commit SHA, the extraction path, and this file (the
criteria). It re-derives independently and reports findings; address each by
amending the worktree commit or recording why you rejected it.

This assumes you are the top-level agent of a Claude Code session, where the
Agent tool is available. If you are yourself a subagent, the Agent tool is not
exposed -- subagents cannot spawn nested subagents and there is no way to
enable it -- so you cannot fork a reviewer. In that case do the review
**inline**: re-derive direction and classification yourself, working only from
the extraction and the criteria below (not your own prior reasoning or run
log), applying the exact checks in the review prompt. An orchestrator that
needs a truly independent reviewer should instead run this skill and a
separate review agent as sibling top-level agents.

An inline review is, however, **blind to the run's own external-research
errors**: re-deriving direction from the same public sources reaches the same
wrong answer (a low-authority source trusted once is trusted again). So any
direction call that rested on external research (the step-4 no-in-DB-signal
devices) must be surfaced in the operator report as needing independent
verification even when the inline review agreed -- on those, the inline review
is not the last word; a separate top-level agent or the operator is.

Skip this step on a `no changes` run (nothing to review).

The review prompt (verbatim; do not soften it or pre-frame any decision as
intentional):

```text
You are reviewing a single commit that updates the Z-Wave
parameter-manager mapping.json, produced by the
zwave-mapping-update skill. You have zero context from any
prior conversation -- evaluate it on its own merits.

Inputs:
- Commit SHA: <SHA>.
- Extraction: tmp/zwave_db_labels.json -- the per-(CC, label)
  device instances the mapping is derived from.
- Criteria: skills/zwave-mapping-update/SKILL.md -- the ACCEPT
  / REJECT rules and the step-4 direction rules.

The commit message states the author's reasoning. Treat it as
authored intent written after the fact: it may rationalize a
wrong call. Verify every claim against the extraction
independently; do not trust it.

Do these, in order:

1. DIRECTION (the critical one). For every accepted
   RANGE-concept label (param_type == RANGE in catalog.py),
   read each device instance's description, options, and
   min/max in the extraction and judge its scale direction
   yourself -- before looking at what the commit did. Then
   compare:
   - A descending device (higher raw = less) MUST have
     invert: true. Flag any that don't -- look especially for
     prose-only inversions with no digits ("Higher values =
     lower sensitivity"), which the validate flagger cannot
     see.
   - A device marked invert: true that is actually ascending
     is a double-inversion bug. Flag it.
   - A reviewed-ascending sidecar entry that is actually
     descending is a silent wrong write. Flag it.
   - A device with NO in-DB direction signal (no description,
     no options) accepted as ascending (no quirk, not in the
     sidecar) is a red flag when a same-OEM sibling is
     descending -- the flagger reads min in {0,1} as ascending
     and cannot catch it. You may consult the device manual /
     OEM config / zwave-js / z-wave.info to settle direction
     (a stable fact, not the live fleet); flag a silent
     ascending accept you cannot positively confirm.
2. CLASSIFICATION. For each accepted label, does it match its
   concept's criteria? Could it match more than one param on a
   real device (AMBIGUOUS)? Flag wrong accepts.
3. MISSES. Scan the extraction for labels that match the
   criteria but are NOT in the mapping. Flag plausible false
   negatives.
4. COMMIT MESSAGE. Does the stated reasoning match the diff?
   Any device in the direction list whose evidence you could
   not confirm? Any claim that overstates?

Tag findings P1 (silent wrong write -- a direction error) /
P2 (wrong or ambiguous accept, unsupported claim) / P3
(missed label, wording).
```

Address each finding by amending the worktree commit (re-run steps 6-8 after
any change so the gate stays green and canonical), or record it as rejected
with reasoning. A P1 direction finding is never "nice to have" -- fix it or
prove it wrong.

### 11. Report to the operator

The commit message (step 9) already carries the *what and why* -- per-concept
additions, direction evidence, notable rejections, criteria extended, and the
validation result including any non-blocking unit notes. Don't restate it;
point at it. The report adds only what the commit can't:

- Where to read it: the worktree path and the commit SHA, so the operator can
  `npx difit <sha>` / `git show <sha>` for the full reasoning.
- The step-10 review outcome: each finding and how it was resolved (fixed in
  the commit, or rejected with reasoning). This is process state, not part of
  the mapping diff, so it lives only here.

The operator reviews via standard git tooling (e.g. `npx difit <sha>`,
`git diff main -- mapping.json`). On accept, they cherry-pick or merge. On
reject, they delete the worktree (`git worktree remove "$WT"`) and the branch.

## Failure modes to call out, not paper over

- A new catalog concept exists in `catalog.py` but has no criteria in this
  file. Stop and ask -- adding criteria is a deliberate edit.
- The extraction is older than 7 days. Refresh it.
- The fleet snapshot is older than 30 days. Note it in the output; the
  operator may want to refresh.
- A label clearly belongs to a concept that doesn't exist yet (recurring
  uncovered pattern across many devices). Surface as a
  candidate-for-new-concept in the rejected list, with reasoning. Don't invent
  a concept inline.

## Operational notes

- The skill lands its proposal as a commit on a fresh review worktree branch
  (step 9), reviewed by an independent agent (step 10) before the operator
  sees it -- not as a `tmp/` file. The operator reviews that commit
  (`npx difit <sha>`, `git diff main -- mapping.json`) and cherry-picks or
  merges on accept, or deletes the worktree on reject.
- The first run after the catalog gains a concept will be the largest (a fresh
  classification pass over the whole DB for that concept). Subsequent weekly
  runs should be near-idle.
- If a label was deliberately rejected in a previous run and the DB hasn't
  changed, the rejection should reproduce. Drift here is a signal to recheck
  the criteria.
