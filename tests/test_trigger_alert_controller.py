#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "PyYAML",
# ]
# ///
# This is AI generated code
"""Structure checks for the standalone ``trigger_alert_controller`` blueprint.

``trigger_alert_controller`` is a standalone blueprint: its action chain is
plain Home Assistant YAML with no ``blueprint_toolkit.<service>`` dispatch, so
it has no handler, no ``_SCHEMA``, and no ``BlueprintSchemaDriftBase``
subclass. This file is the standalone-blueprint equivalent of the per-handler
schema-drift test -- it pins the marker, the input surface, the ``mode``, and
the no-service-dispatch contract so a future edit can't quietly turn it into
a handler-backed blueprint or break the marker the category convention keys
off. See ``AUTOMATIONS.md`` ("Standalone blueprints").
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
BLUEPRINT_PATH = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "bundled"
    / "blueprints"
    / "automation"
    / "blueprint_toolkit"
    / "trigger_alert_controller.yaml"
)
STANDALONE_MARKER = "# blueprint-kind: standalone"
EXPECTED_INPUT_KEYS = {
    "alert_name",
    "trigger_sensors",
    "detection_delay",
    "initial_notification_action",
    "repeat_interval",
    "siren_entity",
    "siren_tone",
    "presence_entities",
    "repeated_notification_action",
}


class _BlueprintLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader that returns None for HA-specific tags like ``!input``."""


def _ignore_unknown_tag(
    loader: yaml.Loader,  # noqa: ARG001
    tag_suffix: str,  # noqa: ARG001
    node: yaml.Node,  # noqa: ARG001
) -> Any:
    return None


_BlueprintLoader.add_multi_constructor("!", _ignore_unknown_tag)


def _raw_text() -> str:
    return BLUEPRINT_PATH.read_text()


def _load() -> dict[str, Any]:
    data = yaml.load(_raw_text(), Loader=_BlueprintLoader)
    assert isinstance(data, dict)
    return data


def _leaf_input_keys(inputs: dict[str, Any]) -> set[str]:
    """Flatten a blueprint ``input:`` block, descending into sections.

    A section is an input-block entry that itself carries a nested
    ``input:`` mapping; its children are the real inputs. Every other
    entry is a leaf input.
    """
    keys: set[str] = set()
    for name, body in inputs.items():
        if isinstance(body, dict) and isinstance(body.get("input"), dict):
            keys |= _leaf_input_keys(body["input"])
        else:
            keys.add(name)
    return keys


def _iter_service_refs(node: Any) -> Iterator[str]:
    """Yield every ``action:`` / ``service:`` string value under ``node``."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("action", "service") and isinstance(value, str):
                yield value
            yield from _iter_service_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_service_refs(item)


class TestStandaloneMarker:
    def test_marker_is_first_line(self) -> None:
        first = _raw_text().splitlines()[0]
        assert first == STANDALONE_MARKER, (
            "trigger_alert_controller.yaml must start with the standalone "
            f"marker {STANDALONE_MARKER!r}; got {first!r}. The marker "
            "identifies the standalone-blueprint category -- see "
            "AUTOMATIONS.md."
        )


class TestBlueprintStructure:
    def test_domain_is_automation(self) -> None:
        assert _load()["blueprint"]["domain"] == "automation"

    def test_mode_is_single(self) -> None:
        assert _load()["mode"] == "single"

    def test_input_surface(self) -> None:
        inputs = _load()["blueprint"]["input"]
        assert _leaf_input_keys(inputs) == EXPECTED_INPUT_KEYS

    def test_no_service_handler_dispatch(self) -> None:
        """A standalone blueprint's actions are plain HA YAML -- they never
        dispatch to a ``blueprint_toolkit.<service>`` handler.
        """
        refs = _iter_service_refs(_load().get("actions"))
        offenders = [r for r in refs if r.startswith("blueprint_toolkit.")]
        assert not offenders, (
            "trigger_alert_controller.yaml is a standalone blueprint but its "
            f"actions dispatch to a service handler: {offenders}"
        )

    def test_top_level_blocks_present(self) -> None:
        """The blueprint must carry non-empty ``triggers:``, ``actions:``,
        and ``variables:`` blocks. AUTOMATIONS.md ("Blueprint YAML") notes
        that a missing ``triggers:`` key renders automations from the
        blueprint as ``unavailable``; the action chain also depends on
        automation-level ``variables:`` being populated for the templates
        that reference ``trigger_sensors`` / ``siren_entity`` / etc.
        """
        bp = _load()
        for key in ("triggers", "actions", "variables"):
            assert bp.get(key), (
                f"trigger_alert_controller.yaml is missing or has empty "
                f"{key!r}; the blueprint will not function without it."
            )

    def test_ha_start_path_debounces_on_detection_delay(self) -> None:
        """The ``ha_start`` re-entry branch must wait ``detection_delay``
        before continuing, mirroring the ``for:`` debounce on the state
        trigger. Without it, a transient on reading at HA startup would
        fire the full siren / notification response immediately.
        """
        actions = _load().get("actions")
        assert isinstance(actions, list)
        debounce_branches = [
            step
            for step in actions
            if isinstance(step, dict)
            and "if" in step
            and any(
                isinstance(cond, dict)
                and "ha_start" in str(cond.get("value_template", ""))
                for cond in step["if"]
            )
        ]
        assert debounce_branches, (
            "trigger_alert_controller.yaml actions must contain a top-level "
            "branch gated on `trigger.id == 'ha_start'`."
        )
        for branch in debounce_branches:
            then_steps = branch.get("then") or []
            assert any(
                isinstance(s, dict) and "delay" in s for s in then_steps
            ), (
                "ha_start re-entry branch must wait detection_delay before "
                "continuing -- see trigger_alert_controller.md "
                "'Restart recovery'."
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
