#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Validate a proposed mapping.json against the canonical pipeline.

Wraps every check the SKILL.md ``Validate`` step needs into one
script with deterministic exit semantics. Canonicalize-first: if the
proposal canonicalizes to the current checked-in mapping, exit
zero ("no changes") -- the weekly idle case where zwave-js shipped
nothing new since the last classification. Only run the rest of the
checks (no-hallucinations, ``MappingTable.from_dict`` round-trip,
existing-quirk preservation, the scale-direction safety net, fleet
verify) when there's a real diff.

The direction net is the only gate on silent mis-maps: a
wrong-direction RESOLVED is a valid RESOLVED, so verify can't see it.
A cheap heuristic flags every descending / direction-uncertain device
instance under an accepted RANGE-concept label; each must be addressed
with an ``invert`` quirk or an explicit reviewed-ascending entry, or
validation fails. Those acknowledgements live in a committed companion
to mapping.json, part of the durable mapping artifact; and existing
quirks must be preserved verbatim -- a dropped invert on a flagger-blind
device would otherwise pass the net silently.

The unit report is non-blocking by contrast: a VALUE-concept label
match whose device unit the resolver can't convert surfaces as
UNMAPPABLE at runtime (safe and loud), so it is reported -- a resolver
unit-coverage gap or a possible mis-classification to review -- without
failing.

Exit codes:

- 0: proposal canonicalizes to the current mapping (no work), OR is
  canonical and every check passed.
- 1: a check failed (hallucinated label, malformed shape, fleet
  AMBIGUOUS, RESOLVED -> UNMAPPABLE regression vs current, etc.).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit.zwave_parameter_manager.catalog import (  # noqa: E402, E501
    CATALOG,
    GenericParamNames,
    ParamType,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402
    MappingTable,
    _convert_quantity,
)

_ZPM_DIR = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "zwave_parameter_manager"
)
_DEFAULT_MAPPING = _ZPM_DIR / "mapping.json"
# The reviewed-ascending companion records the devices a human confirmed
# ascending despite the direction flagger. It sits beside mapping.json as
# part of the committed mapping artifact, so a standalone re-validate reads
# its direction acknowledgements from here; absent file = empty.
_DEFAULT_REVIEWED = _ZPM_DIR / "mapping_direction_reviewed.json"
_CANONICALIZE = REPO_ROOT / "scripts" / "canonicalize_zwave_mapping.py"
_VERIFY = REPO_ROOT / "scripts" / "verify_zwave_mapping.py"


def _run_canonicalize(
    mapping: Path, extraction: Path, out: Path
) -> tuple[bool, str]:
    proc = subprocess.run(
        [
            str(_CANONICALIZE),
            "--mapping",
            str(mapping),
            "--extraction",
            str(extraction),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, proc.stderr or proc.stdout
    return True, ""


def _no_hallucinations(
    proposed: dict[str, Any], extraction: dict[str, Any]
) -> list[tuple[str, str]]:
    """Return ``[(concept, label), ...]`` for hallucinated entries."""

    by_cc: dict[int, set[str]] = {}
    classes = extraction.get("command_classes", {})
    if isinstance(classes, dict):
        for cc_str, block in classes.items():
            try:
                cc = int(cc_str)
            except (TypeError, ValueError):
                continue
            if not isinstance(block, dict):
                continue
            by_cc[cc] = {
                e["label"]
                for e in block.get("labels", [])
                if isinstance(e, dict) and isinstance(e.get("label"), str)
            }
    bad: list[tuple[str, str]] = []
    locators = proposed.get("locators", {})
    if not isinstance(locators, dict):
        return bad
    for concept, spec in locators.items():
        if not isinstance(spec, dict) or "labels" not in spec:
            continue
        for label in spec["labels"]:
            # LabelMatch is CC 112 only at present (Configuration).
            if label not in by_cc.get(112, set()):
                bad.append((concept, label))
    return bad


def _round_trip(proposed: dict[str, Any]) -> str | None:
    try:
        MappingTable.from_dict(proposed)
    except ValueError as exc:
        return str(exc)
    return None


def _verify_fleet(mapping: Path, fleet: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [
            str(_VERIFY),
            "--mapping",
            str(mapping),
            "--fleet",
            str(fleet),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _resolved_locator_count(mapping: Path, fleet: Path) -> int:
    """RESOLVED-row count in verify_zwave_mapping.py's report.

    Used to detect a regression where a proposal causes something
    that resolves today to stop resolving (RESOLVED -> UNMAPPABLE).
    """

    _, output = _verify_fleet(mapping, fleet)
    return sum(
        1 for line in output.splitlines() if re.search(r"\bRESOLVED\b", line)
    )


# -- Scale-direction safety net --------------------------------------
#
# verify can't see direction: a wrong-direction RESOLVED is still a
# valid RESOLVED, not AMBIGUOUS. So this is the only gate on the one
# error class that silently mis-maps. The heuristic below is a FLAGGER,
# not a decider -- it cheaply marks every instance that is descending
# or direction-uncertain. The skill (LLM) is the decider; the gate
# only asserts the skill ADDRESSED each flagged instance, with an
# `invert` quirk or an explicit reviewed-ascending acknowledgement.

_HI = ("highest", "high", "most", "maximum", "max")
_LO = ("lowest", "low", "least", "minimum", "min")


def _classify_direction(
    inst: dict[str, Any],
    low_tokens: tuple[str, ...] = (),
    high_tokens: tuple[str, ...] = (),
) -> str:
    """ascending / descending / unknown for one device instance.

    ascending = a higher raw value means more (the resolver's
    assumption). descending = inverted. unknown = no direction evidence
    and an unusual scale, so it cannot be assumed ascending.

    The description digit-pair parser is the flagger's own prose
    heuristic (the resolver never reads descriptions). The option-label
    check, by contrast, matches the flagger's own low/high word set OR
    ``low_tokens`` / ``high_tokens`` from the mapping -- the same vocab
    the resolver's ``_detect_descending`` consumes, so the gate and the
    runtime share one direction vocabulary.
    """

    desc = (inst.get("description") or "").lower()
    pairs = re.findall(
        r"(\d+)\s*[=:\-. ]{0,6}\s*"
        r"(highest|lowest|high|low|most|least|maximum|minimum|max|min)",
        desc,
    )
    hi = [int(n) for n, w in pairs if w in _HI]
    lo = [int(n) for n, w in pairs if w in _LO]
    if hi and lo:
        if max(hi) < min(lo):
            return "descending"
        if min(hi) > max(lo):
            return "ascending"

    opts = inst.get("options")
    opts = opts if isinstance(opts, list) else []
    low_vals: list[int] = []
    high_vals: list[int] = []
    for o in opts:
        if not isinstance(o, dict):
            continue
        lab = o.get("label")
        val = o.get("value")
        if not isinstance(lab, str) or not isinstance(val, int):
            continue
        token = lab.lower()
        if re.search(r"low|least", token) or any(
            t in token for t in low_tokens
        ):
            low_vals.append(val)
        if re.search(r"high|most", token) or any(
            t in token for t in high_tokens
        ):
            high_vals.append(val)
    if low_vals and high_vals:
        if max(high_vals) < min(low_vals):
            return "descending"
        if min(high_vals) > max(low_vals):
            return "ascending"

    mn = inst.get("min")
    if not opts and isinstance(mn, int) and mn not in (0, 1):
        return "unknown"
    return "ascending"


def _has_invert(
    quirks: dict[str, Any], concept: str, mfg: str, model: str
) -> bool:
    entry = quirks.get(concept, {}).get(mfg, {}).get(model, {})
    return isinstance(entry, dict) and bool(entry.get("invert"))


def _quirk_preservation_findings(
    proposed: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Current quirks dropped or altered by the proposal.

    Quirks are safety-critical per-device direction data, so the additive
    rule that preserves locator labels holds for them too: a quirk in the
    current mapping must reappear verbatim in the proposal. A dropped
    ``invert`` on a flagger-blind device (prose-only inversion) would pass
    the direction net and produce a silent wrong-direction write. Removing
    a quirk is a deliberate edit to the current mapping, not something a
    run performs.
    """

    cur = current.get("quirks", {})
    prop = proposed.get("quirks", {})
    findings: list[str] = []
    if not isinstance(cur, dict):
        return findings
    if not isinstance(prop, dict):
        prop = {}
    for concept, by_mfg in cur.items():
        if not isinstance(by_mfg, dict):
            continue
        for mfg, by_model in by_mfg.items():
            if not isinstance(by_model, dict):
                continue
            for model, fields in by_model.items():
                got = prop.get(concept, {}).get(mfg, {}).get(model)
                if got != fields:
                    findings.append(
                        f"{concept}: {mfg} {model} quirk {fields!r} in the "
                        f"current mapping is missing or altered in the "
                        f"proposal (got {got!r})"
                    )
    return findings


def _instances_by_label(
    extraction: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    classes = extraction.get("command_classes", {})
    if isinstance(classes, dict):
        for block in classes.values():
            if not isinstance(block, dict):
                continue
            for entry in block.get("labels", []):
                if isinstance(entry, dict) and isinstance(
                    entry.get("label"), str
                ):
                    out[entry["label"]] = entry.get("instances", [])
    return out


def _direction_findings(
    proposed: dict[str, Any],
    extraction: dict[str, Any],
    reviewed: set[tuple[str, str, str]],
) -> list[str]:
    """Flagged instances under accepted RANGE-concept labels that
    carry no invert quirk and no reviewed-ascending acknowledgement."""

    insts_by_label = _instances_by_label(extraction)
    quirks = proposed.get("quirks", {})
    if not isinstance(quirks, dict):
        quirks = {}
    low_tokens = tuple(
        t for t in proposed.get("low_tokens", []) if isinstance(t, str)
    )
    high_tokens = tuple(
        t for t in proposed.get("high_tokens", []) if isinstance(t, str)
    )
    locators = proposed.get("locators", {})
    findings: list[str] = []
    for concept, loc in locators.items():
        try:
            gp = CATALOG[GenericParamNames(concept)]
        except (ValueError, KeyError):
            continue  # a concept the catalog doesn't define
        if gp.param_type is not ParamType.RANGE:
            continue
        if not isinstance(loc, dict) or "labels" not in loc:
            continue
        for label in loc["labels"]:
            for inst in insts_by_label.get(label, []):
                if not isinstance(inst, dict):
                    continue
                direction = _classify_direction(inst, low_tokens, high_tokens)
                if direction == "ascending":
                    continue
                mfg = str(inst.get("manufacturer"))
                model = str(inst.get("model"))
                if _has_invert(quirks, concept, mfg, model):
                    continue
                if (concept, mfg, model) in reviewed:
                    continue
                findings.append(
                    f"{concept}: {mfg} {model} (label {label!r}) is "
                    f"{direction} but has no invert quirk and is not "
                    f"reviewed-ascending"
                )
    return findings


def _unit_findings(
    proposed: dict[str, Any], extraction: dict[str, Any]
) -> list[str]:
    """Accepted VALUE-concept label instances whose device unit the
    resolver cannot convert from the concept's unit.

    A mismatch is non-blocking: it surfaces as UNMAPPABLE at runtime
    (safe and loud, unlike a wrong-direction write), so this is a
    report, not a gate. It flags both resolver unit-coverage gaps
    (an unrecognized spelling like ``2%``) and possible
    mis-classifications (a time concept matched on a percent param).
    """

    insts_by_label = _instances_by_label(extraction)
    locators = proposed.get("locators", {})
    findings: list[str] = []
    for concept, loc in locators.items():
        try:
            gp = CATALOG[GenericParamNames(concept)]
        except (ValueError, KeyError):
            continue  # a concept the catalog doesn't define
        if gp.param_type is not ParamType.VALUE:
            continue
        if gp.units is None:
            continue
        if not isinstance(loc, dict) or "labels" not in loc:
            continue
        for label in loc["labels"]:
            for inst in insts_by_label.get(label, []):
                if not isinstance(inst, dict):
                    continue
                du = inst.get("unit")
                du = du if isinstance(du, str) else None
                raw, _ = _convert_quantity(1.0, gp.units, du)
                if raw is None:
                    findings.append(
                        f"{concept}: {inst.get('manufacturer')} "
                        f"{inst.get('model')} (label {label!r}) device "
                        f"unit {du!r} is not convertible from "
                        f"{gp.units!r} -> UNMAPPABLE on that device"
                    )
    return findings


def _load_reviewed(path: Path | None) -> set[tuple[str, str, str]]:
    if path is None or not path.exists():
        return set()
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: set[tuple[str, str, str]] = set()
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, dict):
            out.add(
                (
                    str(r.get("concept")),
                    str(r.get("manufacturer")),
                    str(r.get("model")),
                )
            )
    return out


def main() -> int:
    summary = (__doc__ or "").strip().split("\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument(
        "--proposed",
        type=Path,
        required=True,
        help="Path to the proposed mapping.json (LLM output).",
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=_DEFAULT_MAPPING,
        help="Path to the current checked-in mapping.json.",
    )
    parser.add_argument(
        "--extraction",
        type=Path,
        required=True,
        help="Path to the zwave_db_labels.json extraction output.",
    )
    parser.add_argument(
        "--fleet",
        type=Path,
        default=None,
        help=(
            "Optional fleet.yaml -- when present, runs fleet verify "
            "and checks for RESOLVED -> UNMAPPABLE regressions."
        ),
    )
    parser.add_argument(
        "--reviewed",
        type=Path,
        default=_DEFAULT_REVIEWED,
        help=(
            "Path to the reviewed-ascending companion (a JSON list of "
            "{concept, manufacturer, model} a human confirmed ascending "
            "despite the direction flagger). Defaults to the committed "
            "companion beside mapping.json; a skill run points it at the "
            "run's proposed companion. Absent file = empty."
        ),
    )
    args = parser.parse_args()

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False
    ) as tmp_handle:
        tmp_path = Path(tmp_handle.name)
    try:
        ok, err = _run_canonicalize(args.proposed, args.extraction, tmp_path)
        if not ok:
            print(f"FAIL canonicalize: {err}", file=sys.stderr)
            return 1
        canonical_text = tmp_path.read_text(encoding="utf-8")

        current_text = (
            args.current.read_text(encoding="utf-8")
            if args.current.exists()
            else ""
        )
        if canonical_text == current_text:
            print("no changes (proposal canonicalizes to the current mapping)")
            return 0

        proposed = json.loads(canonical_text)
        extraction = json.loads(args.extraction.read_text(encoding="utf-8"))

        hallucinated = _no_hallucinations(proposed, extraction)
        if hallucinated:
            print(
                f"FAIL no-hallucinations: {len(hallucinated)} label(s) "
                f"absent from extraction:"
            )
            for concept, label in hallucinated:
                print(f"  {concept}: {label!r}")
            return 1

        round_trip_err = _round_trip(proposed)
        if round_trip_err is not None:
            print(f"FAIL round-trip: {round_trip_err}")
            return 1

        current_obj = json.loads(current_text) if current_text else {}
        dropped = _quirk_preservation_findings(proposed, current_obj)
        if dropped:
            print(
                f"FAIL quirk-preservation: {len(dropped)} current quirk(s) "
                f"dropped or altered (quirks are additive, like labels):"
            )
            for f in dropped:
                print(f"  {f}")
            return 1

        reviewed = _load_reviewed(args.reviewed)
        direction = _direction_findings(proposed, extraction, reviewed)
        if direction:
            print(
                f"FAIL direction: {len(direction)} descending / "
                f"direction-uncertain instance(s) under accepted "
                f"RANGE-concept labels are unhandled (need an invert "
                f"quirk or a reviewed-ascending entry):"
            )
            for f in direction:
                print(f"  {f}")
            return 1

        units = _unit_findings(proposed, extraction)
        if units:
            print(
                f"UNIT WARNINGS (non-blocking): {len(units)} VALUE-concept "
                f"instance(s) carry a unit the resolver can't convert; they "
                f"will UNMAPPABLE on those devices. Review whether the "
                f"resolver should learn the unit, or the device just "
                f"doesn't apply:"
            )
            for f in units:
                print(f"  {f}")

        if args.fleet is not None:
            current_resolved = _resolved_locator_count(args.current, args.fleet)
            proposed_resolved = _resolved_locator_count(tmp_path, args.fleet)
            if proposed_resolved < current_resolved:
                print(
                    f"FAIL fleet regression: RESOLVED dropped from "
                    f"{current_resolved} to {proposed_resolved}"
                )
                return 1
            code, output = _verify_fleet(tmp_path, args.fleet)
            if code != 0:
                print(f"FAIL fleet verify (exit {code}):")
                print(output)
                return 1

        print(
            "all checks passed (proposal differs from current; "
            "ready for worktree commit)"
        )
        return 0
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
