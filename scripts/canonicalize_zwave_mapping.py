#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Canonicalize a ZPM mapping.json file.

Rewrites the JSON in deterministic canonical form so two runs of the
LLM mapping suggester against the same DB snapshot produce
byte-identical proposals -- the strict reproducibility invariant the
skill commits to.

Canonical ordering:

- Top-level keys: ``metadata``, ``locators``, ``quirks``,
  ``off_labels``, ``on_labels``, ``low_tokens``, ``high_tokens``.
- ``metadata`` keys: ``zwave_js_tag``, ``zwave_js_commit``,
  ``zwave_js_commit_date`` first; remaining keys in alphabetical
  order (forward-compat for new provenance fields).
- ``locators`` keyed by ``GenericParamNames`` declaration order. A
  ``LabelMatch``'s ``labels`` list sorts by extraction frequency
  (descending), alphabetical tiebreak. The frequency table comes
  from ``--extraction``; without it, labels sort alphabetically.
- ``quirks`` nested by concept (declaration order), manufacturer
  (alphabetical), model (alphabetical); quirk fields fixed order
  (``invert``, ``off_value``, ``on_value``).
- ``off_labels`` / ``on_labels`` / ``low_tokens`` / ``high_tokens``
  sorted alphabetically.
- JSON output: ``indent=2``, trailing newline.
- ``--reviewed`` (optional): canonicalize the reviewed-ascending
  companion list in the same run, sorted by concept (declaration order),
  manufacturer, then model.
- ``--emit-fixture`` (optional): write the canonical-extraction test
  fixture (the mapping's labels + their device counts from
  ``--extraction``) so ``test_mapping_json_is_canonical`` stays in
  lockstep with the mapping it guards.

``--check`` exits non-zero if ``--mapping`` (or ``--reviewed``) is not
already canonical (without writing).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.blueprint_toolkit.zwave_parameter_manager.catalog import (  # noqa: E402, E501
    GenericParamNames,
)

_TOP_LEVEL_ORDER: tuple[str, ...] = (
    "metadata",
    "locators",
    "quirks",
    "off_labels",
    "on_labels",
    "low_tokens",
    "high_tokens",
)
_METADATA_PREFERRED_ORDER: tuple[str, ...] = (
    "zwave_js_tag",
    "zwave_js_commit",
    "zwave_js_commit_date",
)
_QUIRK_FIELD_ORDER: tuple[str, ...] = ("invert", "off_value", "on_value")
_CONCEPT_ORDER: dict[str, int] = {
    name.value: i for i, name in enumerate(GenericParamNames)
}


def _ordered_dict(
    raw: dict[str, Any], preferred: tuple[str, ...]
) -> dict[str, Any]:
    """Return ``raw`` with ``preferred`` keys first, then alphabetical."""

    out: dict[str, Any] = {}
    for key in preferred:
        if key in raw:
            out[key] = raw[key]
    for key in sorted(set(raw) - set(preferred)):
        out[key] = raw[key]
    return out


def _label_frequency(
    extraction: dict[str, Any] | None,
) -> dict[tuple[int, str], int]:
    if extraction is None:
        return {}
    out: dict[tuple[int, str], int] = {}
    classes = extraction.get("command_classes", {})
    if not isinstance(classes, dict):
        return out
    for cc_str, block in classes.items():
        try:
            cc = int(cc_str)
        except (TypeError, ValueError):
            continue
        if not isinstance(block, dict):
            continue
        for entry in block.get("labels", []):
            if not isinstance(entry, dict):
                continue
            label = entry.get("label")
            count = entry.get("device_count")
            if isinstance(label, str) and isinstance(count, int):
                out[(cc, label)] = count
    return out


def _canonicalize_locators(
    raw: Any, freq: dict[tuple[int, str], int]
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for concept in sorted(
        raw, key=lambda c: (_CONCEPT_ORDER.get(c, len(_CONCEPT_ORDER)), c)
    ):
        spec = raw[concept]
        if not isinstance(spec, dict):
            out[concept] = spec
            continue
        if "labels" in spec:
            labels = list(spec["labels"])
            # LabelMatch is currently CC 112 only; the resolver only
            # populates LabelMatch over Configuration-class params.
            cc = 112
            sorted_labels = sorted(
                labels, key=lambda lbl: (-freq.get((cc, lbl), 0), lbl)
            )
            out[concept] = {"labels": sorted_labels}
        elif "command_class" in spec:
            out[concept] = {
                "command_class": spec["command_class"],
                "property": spec.get("property"),
            }
        else:
            out[concept] = spec
    return out


def _canonicalize_quirks(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for concept in sorted(
        raw, key=lambda c: (_CONCEPT_ORDER.get(c, len(_CONCEPT_ORDER)), c)
    ):
        by_mfg = raw[concept]
        if not isinstance(by_mfg, dict):
            out[concept] = by_mfg
            continue
        sorted_mfgs: dict[str, Any] = {}
        for mfg in sorted(by_mfg):
            by_model = by_mfg[mfg]
            if not isinstance(by_model, dict):
                sorted_mfgs[mfg] = by_model
                continue
            sorted_models: dict[str, Any] = {}
            for model in sorted(by_model):
                quirk = by_model[model]
                if isinstance(quirk, dict):
                    sorted_models[model] = _ordered_dict(
                        quirk, _QUIRK_FIELD_ORDER
                    )
                else:
                    sorted_models[model] = quirk
            sorted_mfgs[mfg] = sorted_models
        out[concept] = sorted_mfgs
    return out


def _sorted_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return sorted(x for x in raw if isinstance(x, str))


def canonicalize_reviewed(raw: Any) -> list[dict[str, str]]:
    """Canonicalize the reviewed-ascending companion list.

    Each entry is normalized to ``{concept, manufacturer, model}`` with a
    fixed key order; the list sorts by concept (declaration order), then
    manufacturer, then model -- so two runs produce byte-identical
    companions, the same reproducibility guarantee the mapping carries.
    """

    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        concept = r.get("concept")
        mfg = r.get("manufacturer")
        model = r.get("model")
        if (
            isinstance(concept, str)
            and isinstance(mfg, str)
            and isinstance(model, str)
        ):
            entries.append(
                {"concept": concept, "manufacturer": mfg, "model": model}
            )
    entries.sort(
        key=lambda e: (
            _CONCEPT_ORDER.get(e["concept"], len(_CONCEPT_ORDER)),
            e["concept"],
            e["manufacturer"],
            e["model"],
        )
    )
    return entries


def canonicalize(
    raw: dict[str, Any], extraction: dict[str, Any] | None
) -> dict[str, Any]:
    """Return ``raw`` in canonical form. Pure function -- no I/O."""

    freq = _label_frequency(extraction)
    canonical: dict[str, Any] = {}
    metadata = raw.get("metadata")
    if isinstance(metadata, dict) and metadata:
        canonical["metadata"] = _ordered_dict(
            metadata, _METADATA_PREFERRED_ORDER
        )
    canonical["locators"] = _canonicalize_locators(
        raw.get("locators", {}), freq
    )
    canonical["quirks"] = _canonicalize_quirks(raw.get("quirks", {}))
    canonical["off_labels"] = _sorted_str_list(raw.get("off_labels"))
    canonical["on_labels"] = _sorted_str_list(raw.get("on_labels"))
    canonical["low_tokens"] = _sorted_str_list(raw.get("low_tokens"))
    canonical["high_tokens"] = _sorted_str_list(raw.get("high_tokens"))
    # Drop any top-level keys we don't recognise from the canonical
    # output (from_dict would reject them at load anyway).
    extra = set(raw) - set(_TOP_LEVEL_ORDER)
    if extra:
        print(
            f"warning: dropping unknown top-level keys "
            f"{sorted(extra)} from canonical output",
            file=sys.stderr,
        )
    return canonical


def _render(canonical: dict[str, Any]) -> str:
    return json.dumps(canonical, indent=2) + "\n"


def canonical_fixture(
    mapping: dict[str, Any], extraction: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the canonical-extraction test fixture for ``mapping``.

    The fixture is the slice of the extraction the
    ``test_mapping_json_is_canonical`` check needs: the (label,
    device_count) pair for every label the mapping locates, so the test
    can reproduce the frequency-based label sort in CI without the full
    multi-MB extraction in ``tmp/``. Generating it mechanically here is
    what keeps it in lockstep with the mapping it guards. Labels sort by
    count (descending, alphabetical tiebreak) for a stable file.
    """

    freq = _label_frequency(extraction)
    raw_tag = (extraction or {}).get("tag", "fixture")
    tag = raw_tag if isinstance(raw_tag, str) else "fixture"
    labels: set[str] = set()
    for spec in mapping.get("locators", {}).values():
        if isinstance(spec, dict) and "labels" in spec:
            for lbl in spec["labels"]:
                if isinstance(lbl, str):
                    labels.add(lbl)
    entries: list[dict[str, Any]] = [
        {"label": lbl, "device_count": freq.get((112, lbl), 0)}
        for lbl in labels
    ]
    entries.sort(key=lambda e: (-int(e["device_count"]), str(e["label"])))
    return {
        "tag": f"{tag}-fixture",
        "command_classes": {
            "112": {"name": "Configuration", "labels": entries}
        },
    }


def main() -> int:
    summary = (__doc__ or "").strip().split("\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="Input mapping.json to canonicalize.",
    )
    parser.add_argument(
        "--extraction",
        type=Path,
        default=None,
        help=(
            "Optional zwave_db_labels.json for frequency-based label "
            "sort (without it, labels sort alphabetically)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (defaults to in-place rewrite of --mapping).",
    )
    parser.add_argument(
        "--reviewed",
        type=Path,
        default=None,
        help=(
            "Optional reviewed-ascending companion JSON list to "
            "canonicalize in place alongside --mapping."
        ),
    )
    parser.add_argument(
        "--emit-fixture",
        type=Path,
        default=None,
        help=(
            "Write the canonical-extraction test fixture (the mapping's "
            "labels + their device counts from --extraction) to this path, "
            "so test_mapping_json_is_canonical stays in lockstep. Requires "
            "--extraction."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if --mapping (or --reviewed) is not already "
        "canonical; do not write.",
    )
    args = parser.parse_args()

    raw = json.loads(args.mapping.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        print(
            f"FAIL: {args.mapping}: top-level must be a mapping",
            file=sys.stderr,
        )
        return 1
    extraction: dict[str, Any] | None = None
    if args.extraction is not None:
        ext_raw = json.loads(args.extraction.read_text(encoding="utf-8"))
        if isinstance(ext_raw, dict):
            extraction = ext_raw

    canonical = canonicalize(raw, extraction)
    text = _render(canonical)

    rev_text: str | None = None
    if args.reviewed is not None:
        rev_raw = json.loads(args.reviewed.read_text(encoding="utf-8"))
        rev_text = json.dumps(canonicalize_reviewed(rev_raw), indent=2) + "\n"

    if args.check:
        failed = False
        if args.mapping.read_text(encoding="utf-8") != text:
            print(
                f"FAIL: {args.mapping} is not in canonical form "
                f"(diff would be emitted by a write run)",
                file=sys.stderr,
            )
            failed = True
        if rev_text is not None and (
            args.reviewed.read_text(encoding="utf-8") != rev_text
        ):
            print(
                f"FAIL: {args.reviewed} is not in canonical form",
                file=sys.stderr,
            )
            failed = True
        return 1 if failed else 0

    out_path = args.output if args.output is not None else args.mapping
    out_path.write_text(text, encoding="utf-8")
    if rev_text is not None:
        args.reviewed.write_text(rev_text, encoding="utf-8")
    if args.emit_fixture is not None:
        fixture = canonical_fixture(canonical, extraction)
        args.emit_fixture.write_text(
            json.dumps(fixture, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
