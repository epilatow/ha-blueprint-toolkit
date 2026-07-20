#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "voluptuous",
#     "PyYAML",
#     "pytest-homeassistant-custom-component==0.13.346",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for ``entity_defaults_watchdog.handler``.

Covers the parts that don't require booting HA: mutator
callbacks, ``_ensure_timer`` re-arm sequencing,
``_async_kick_for_recovery`` payload shape, periodic-
callback context-propagation regression tests, argparse
field validation (``drift_checks`` cross-validation,
multi-line regex helper delegation, schema-level int
rejection), and the blueprint <-> schema drift check. The
service layer's full build-and-apply loop is exercised
in ``test_entity_defaults_watchdog_integration.py``
against the pytest-HACC harness.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from _handler_stubs import install_homeassistant_stubs  # noqa: E402
from _handler_test_base import (  # noqa: E402
    ArgparseCapture,
    FakeServiceCall,
    FrozenNow,
    MockEntry,
    MockHass,
)
from conftest import (  # noqa: E402
    BlueprintDefaultsRoundTripBase,
    BlueprintSchemaDriftBase,
    HandlerArgparseGuardsBase,
)

_stubs = install_homeassistant_stubs(frozen_now=FrozenNow.value)

from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E402, E501
    handler,
)


def _make_state(
    instance_id: str = "automation.edw_test",
    *,
    armed_interval_minutes: int = 0,
    cancel_timer: Callable[[], None] | None = None,
) -> handler.EdwInstanceState:
    return handler.EdwInstanceState(
        instance_id=instance_id,
        armed_interval_minutes=armed_interval_minutes,
        cancel_timer=cancel_timer,
    )


def _hass_with_instances(
    instances: dict[str, handler.EdwInstanceState],
) -> MockHass:
    h = MockHass()
    entry = MockEntry()
    entry.runtime_data.handlers["entity_defaults_watchdog"] = {
        "instances": instances,
        "unsubs": [],
    }
    h.config_entries.entries.append(entry)
    return h


# --------------------------------------------------------
# Mutator callbacks
# --------------------------------------------------------


class TestOnReload:
    def test_cancels_pending_timers(self) -> None:
        canceled: list[int] = []

        s1 = _make_state(
            "automation.a",
            armed_interval_minutes=5,
            cancel_timer=lambda: canceled.append(1),
        )
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_reload(h)

        assert canceled == [1]
        assert s1.cancel_timer is None
        assert s1.armed_interval_minutes == 0
        assert s2.cancel_timer is None
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "entity_defaults_watchdog"
        ]
        assert set(bucket["instances"]) == {"automation.a", "automation.b"}


class TestOnEntityRemove:
    def test_drops_state_and_cancels_timer(self) -> None:
        canceled: list[int] = []
        s = _make_state(
            "automation.a",
            armed_interval_minutes=5,
            cancel_timer=lambda: canceled.append(1),
        )
        h = _hass_with_instances(
            {"automation.a": s, "automation.b": _make_state("automation.b")}
        )

        handler._on_entity_remove(h, "automation.a")

        assert canceled == [1]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "entity_defaults_watchdog"
        ]
        assert set(bucket["instances"]) == {"automation.b"}

    def test_unknown_id_is_noop(self) -> None:
        h = _hass_with_instances({"automation.a": _make_state("automation.a")})
        # Should not raise.
        handler._on_entity_remove(h, "automation.unknown")


class TestOnEntityRename:
    def test_moves_state_to_new_id(self) -> None:
        s = _make_state("automation.old")
        h = _hass_with_instances({"automation.old": s})

        handler._on_entity_rename(h, "automation.old", "automation.new")

        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "entity_defaults_watchdog"
        ]
        assert "automation.old" not in bucket["instances"]
        assert bucket["instances"]["automation.new"] is s
        assert s.instance_id == "automation.new"

    def test_unknown_old_id_is_noop(self) -> None:
        h = _hass_with_instances({})
        # Should not raise.
        handler._on_entity_rename(h, "automation.x", "automation.y")


class TestOnTeardown:
    def test_cancels_all_and_clears(self) -> None:
        canceled: list[int] = []
        s1 = _make_state(
            "automation.a", cancel_timer=lambda: canceled.append(1)
        )
        s2 = _make_state(
            "automation.b", cancel_timer=lambda: canceled.append(2)
        )
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_teardown(h)

        assert sorted(canceled) == [1, 2]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "entity_defaults_watchdog"
        ]
        assert bucket["instances"] == {}


# --------------------------------------------------------
# _ensure_timer
# --------------------------------------------------------


class TestEnsureTimer:
    def setup_method(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.unsub_called: list[int] = []

        def _fake_schedule(
            _hass: Any,
            entry: Any,
            *,
            interval: timedelta,
            instance_id: str,
            action: Any,
        ) -> Callable[[], None]:
            handle_index = len(self.calls)
            self.calls.append(
                {
                    "entry": entry,
                    "interval": interval,
                    "instance_id": instance_id,
                    "action": action,
                }
            )

            def _unsub() -> None:
                self.unsub_called.append(handle_index)

            return _unsub

        self._real_schedule = handler.schedule_periodic_with_jitter
        handler.schedule_periodic_with_jitter = _fake_schedule  # type: ignore[assignment]

    def teardown_method(self) -> None:
        handler.schedule_periodic_with_jitter = self._real_schedule

    def test_first_call_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.edw")
        e = object()

        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.calls[0]["entry"] is e
        assert self.calls[0]["interval"] == timedelta(minutes=5)
        assert self.calls[0]["instance_id"] == "automation.edw"
        assert s.armed_interval_minutes == 5
        assert s.cancel_timer is not None

    def test_same_interval_does_not_re_arm(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.edw")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.unsub_called == []

    def test_changed_interval_re_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.edw")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 10)  # type: ignore[arg-type]

        assert self.unsub_called == [0]
        assert len(self.calls) == 2
        assert self.calls[1]["interval"] == timedelta(minutes=10)
        assert s.armed_interval_minutes == 10


# --------------------------------------------------------
# Argparse harness
# --------------------------------------------------------


def _valid_argparse_payload(**overrides: Any) -> dict[str, Any]:
    """Return a schema-valid raw payload with optional overrides."""
    payload = {
        "instance_id": "automation.edw_test",
        "trigger_id": "manual",
        "drift_checks_raw": [],
        "include_integrations_raw": [],
        "exclude_integrations_raw": [],
        "exclude_device_name_regex_raw": "",
        "exclude_entities_raw": [],
        "exclude_entity_id_regex_raw": "",
        "exclude_entity_name_regex_raw": "",
        "check_interval_minutes_raw": 5,
        "max_device_notifications_raw": 0,
        "create_repairs_raw": False,
        "max_repairs_raw": 5,
        "validate_includes_excludes_raw": True,
        "debug_logging_raw": False,
    }
    payload.update(overrides)
    return payload


class _ArgparseHarness:
    """Shared setup/teardown for argparse-only tests.

    Subclasses inherit ``setup_method`` / ``teardown_method``
    so each test gets a fresh ``ArgparseCapture`` and a
    fresh ``config_errors`` capture list. The handler-side
    ``_async_service_layer`` and ``_emit_config_error``
    references are restored on teardown so cross-test
    pollution is impossible.
    """

    def setup_method(self) -> None:
        self.capture = ArgparseCapture()
        self._real_service_layer = handler._async_service_layer
        handler._async_service_layer = self.capture  # type: ignore[assignment]
        self.config_errors: list[list[str]] = []

        async def _capture_errors(
            _hass: Any,
            _instance_id: str,
            errors: list[str],
        ) -> None:
            self.config_errors.append(errors)

        self._real_emit = handler._emit_config_error
        handler._emit_config_error = _capture_errors

    def teardown_method(self) -> None:
        handler._async_service_layer = self._real_service_layer
        handler._emit_config_error = self._real_emit


# --------------------------------------------------------
# Argparse: drift_checks cross-validation
# --------------------------------------------------------


class TestArgparseDriftChecks(_ArgparseHarness):
    def test_empty_defaults_to_all_checks(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(_valid_argparse_payload(drift_checks_raw=[]))
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.config_errors == [[]]
        assert len(self.capture.calls) == 1
        # Empty input -> CHECK_ALL forwarded to the service
        # layer (mirrors the blueprint description that
        # documents empty-means-all).
        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E402, E501, PLC0415
            logic,
        )

        assert self.capture.calls[0]["drift_checks"] == logic.CHECK_ALL

    def test_unknown_value_emits_error(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                drift_checks_raw=["device-entity-id", "bogus-check"],
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == [], (
            "service layer must NOT run when drift_checks has unknowns"
        )
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "drift_checks" in joined
        assert "bogus-check" in joined

    def test_valid_subset_passes_through(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                drift_checks_raw=["device-entity-id"],
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.config_errors == [[]]
        assert self.capture.calls[0]["drift_checks"] == frozenset(
            {"device-entity-id"}
        )


# --------------------------------------------------------
# Argparse: multi-line regex fields
# --------------------------------------------------------
#
# EDW has THREE multi-line regex inputs
# (exclude_device_name_regex, exclude_entity_id_regex,
# exclude_entity_name_regex). Each is split on newlines and
# joined with ``|`` so two patterns on separate lines reach
# the service layer as a single alternation regex. The
# split/join + per-line validation lives in the shared
# ``helpers.validate_and_join_regex_patterns``;
# parser-semantic tests for the helper itself live in
# ``test_helpers_lifecycle.py``
# (``TestValidateAndJoinRegexPatterns``). This class only
# verifies the handler-side wiring: that argparse delegates
# to the helper for every regex field and that helper-level
# errors surface as a config-error notification.


class TestArgparseMultilineRegex(_ArgparseHarness):
    def test_all_three_regex_fields_join_with_pipe(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                exclude_device_name_regex_raw="^Stale-Hub\nold-hub$",
                exclude_entity_id_regex_raw="sensor\\.foo\nsensor\\.bar",
                exclude_entity_name_regex_raw="^Custom .*\nKeep this",
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.config_errors == [[]]
        assert len(self.capture.calls) == 1
        kw = self.capture.calls[0]
        assert kw["exclude_device_name_regex"] == "^Stale-Hub|old-hub$"
        assert kw["exclude_entity_id_regex"] == "sensor\\.foo|sensor\\.bar"
        assert kw["exclude_entity_name_regex"] == "^Custom .*|Keep this"

    def test_helper_errors_emit_config_error_notification(self) -> None:
        # Wiring check: when the shared helper returns
        # errors, argparse short-circuits dispatch and
        # surfaces them as a config-error notification.
        # The exact errors (which lines fail, why) are
        # parser semantics covered by
        # ``TestValidateAndJoinRegexPatterns``.
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                exclude_entity_id_regex_raw="foo\n[invalid",
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == [], (
            "service layer must NOT run when argparse has errors"
        )
        assert len(self.config_errors) == 1
        assert self.config_errors[0], "expected a non-empty error list"

    def test_all_empty_fields_pass_through_clean(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(_valid_argparse_payload())
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.config_errors == [[]]
        assert len(self.capture.calls) == 1
        kw = self.capture.calls[0]
        assert kw["exclude_device_name_regex"] == ""
        assert kw["exclude_entity_id_regex"] == ""
        assert kw["exclude_entity_name_regex"] == ""

    def test_argparse_delegates_to_shared_regex_helper(self) -> None:
        """Lock in that argparse delegates regex parsing to
        ``helpers.validate_and_join_regex_patterns``.

        Why this matters: re-implementing multi-line regex
        parsing inline would silently lose the helper's
        guarantees (per-line ``re.compile`` validation,
        ``.*``-rejection, alternation join, empty-line
        drop). If a future refactor moves off the helper,
        this test fires and forces the maintainer to
        choose: (a) restore the call-through, or (b)
        re-implement equivalent guarantees inline -- see
        ``TestValidateAndJoinRegexPatterns`` in
        ``test_helpers_lifecycle.py`` for the full
        contract.

        EDW has three regex fields, so argparse should call
        the helper at least once per non-empty field; we
        only assert the spy was called (and let
        TestArgparseMultilineRegex above cover the
        per-field output shape).
        """
        import asyncio

        spy_calls: list[tuple[Any, ...]] = []
        real = handler.validate_and_join_regex_patterns

        def _spy(*args: Any, **kwargs: Any) -> Any:
            spy_calls.append(args)
            return real(*args, **kwargs)

        handler.validate_and_join_regex_patterns = _spy
        try:
            h = MockHass()
            call = FakeServiceCall(
                _valid_argparse_payload(
                    exclude_device_name_regex_raw="foo\nbar",
                    exclude_entity_id_regex_raw="baz",
                    exclude_entity_name_regex_raw="qux",
                ),
            )
            asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]
        finally:
            handler.validate_and_join_regex_patterns = real

        assert spy_calls, (
            "argparse must call helpers.validate_and_join_regex_patterns "
            "-- see this test's docstring for the contract"
        )


# --------------------------------------------------------
# Argparse: int-input rejection (schema-level)
# --------------------------------------------------------
#
# Schema-level validation:
# ``vol.All(vol.Coerce(int), vol.Range(min=..., max=...))``
# rejects non-numeric and out-of-range integers; rejections
# flow through ``vol.MultipleInvalid`` and surface as a
# config-error notification carrying the offending field
# name (the ``schema:`` prefix the helper prepends).


class TestArgparseSlugListValidation(_ArgparseHarness):
    def test_bad_shape_integration_rejected(self) -> None:
        # Defense-in-depth: slug-shape validation rejects
        # mis-cased / hyphenated values that HA's
        # integration-id charset would never produce.
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                include_integrations_raw=["zwave-js"],
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == []
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "include_integrations_raw" in joined


class TestArgparseIntValidation(_ArgparseHarness):
    def test_non_numeric_check_interval_minutes_rejected(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                check_interval_minutes_raw="not-a-number",
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == [], (
            "service layer must NOT run when schema rejects an input"
        )
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "check_interval_minutes_raw" in joined
        # ``vol.Coerce(int)`` produces this phrasing on
        # bad-int input; if voluptuous changes the message
        # in the future this assertion may need a softer
        # match.
        assert "expected int" in joined

    def test_out_of_range_max_device_notifications_rejected(self) -> None:
        import asyncio

        h = MockHass()
        call = FakeServiceCall(
            _valid_argparse_payload(
                max_device_notifications_raw=9999,
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == []
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "max_device_notifications_raw" in joined
        # ``vol.Range(min=0, max=1000)`` -> "value must be
        # at most 1000".
        assert "at most 1000" in joined


# --------------------------------------------------------
# _build_visible_aliased_inputs defensive-skip cases
# --------------------------------------------------------
#
# The visible-aliased drift check sources its candidate set
# from ``hass.config_entries.async_entries("switch_as_x")``;
# every defensive-skip branch lives in
# ``_build_visible_aliased_inputs`` (the logic layer never
# sees skipped entries). Each test below plants exactly one
# fake switch_as_x entry plus a hand-rolled entity registry
# and asserts the builder returns ``(infos=[],
# defensive_skipped=1)`` -- the per-cause counter shape the
# diagnostic-state ``visible_aliased_excluded`` arithmetic
# depends on.


class _FakeRegistryEntry:
    def __init__(
        self,
        *,
        entity_id: str,
        config_entry_id: str | None = None,
        domain: str = "",
        hidden_by: object = None,
        disabled_by: object = None,
        name: str | None = None,
        original_name: str | None = None,
        device_id: str | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.config_entry_id = config_entry_id
        self.domain = domain or entity_id.split(".", 1)[0]
        self.hidden_by = hidden_by
        self.disabled_by = disabled_by
        self.name = name
        self.original_name = original_name
        self.device_id = device_id


class _FakeEntityRegistry:
    def __init__(self) -> None:
        self.entities: dict[str, _FakeRegistryEntry] = {}

    def add(self, e: _FakeRegistryEntry) -> None:
        self.entities[e.entity_id] = e

    def async_get(self, entity_id: str) -> _FakeRegistryEntry | None:
        return self.entities.get(entity_id)


class _FakeConfigEntry:
    def __init__(
        self,
        *,
        entry_id: str,
        domain: str,
        title: str = "",
        options: dict[str, Any] | None = None,
        disabled_by: object = None,
    ) -> None:
        self.entry_id = entry_id
        self.domain = domain
        self.title = title
        self.options = options if options is not None else {}
        self.disabled_by = disabled_by


class _FakeConfigEntries:
    def __init__(self, entries: list[_FakeConfigEntry]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[_FakeConfigEntry]:
        return [e for e in self._entries if e.domain == domain]


class _FakeHassForBuilder:
    def __init__(self, entries: list[_FakeConfigEntry]) -> None:
        self.config_entries = _FakeConfigEntries(entries)


class TestExtractVisibleAliasedCandidates:
    """Extractor coverage for ``_extract_visible_aliased_candidates``.

    The extractor is a thin reader: one raw candidate per
    switch_as_x config entry, no skip decisions. Each test
    plants registry / config-entry state and asserts the
    extracted candidate carries the right raw facts; the
    finding-vs-skip classification of those facts is covered by
    the logic-layer tests.
    """

    def setup_method(self) -> None:
        self._real_async_get = handler.er.async_get
        self._registry = _FakeEntityRegistry()

        def _fake_async_get(_hass: Any) -> _FakeEntityRegistry:
            return self._registry

        handler.er.async_get = _fake_async_get  # type: ignore[assignment]

    def teardown_method(self) -> None:
        handler.er.async_get = self._real_async_get

    def test_clean_entry_extracted(self) -> None:
        # Visible source + exactly one wrapper: the candidate
        # carries the source facts and the single wrapper
        # object_id (the logic turns this into a finding).
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="switch.foo",
                domain="switch",
                hidden_by=None,
                disabled_by=None,
                original_name="Foo",
            ),
        )
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="fan.foo",
                domain="fan",
                config_entry_id="entry-id-foo",
                original_name="Foo",
            ),
        )
        entry = _FakeConfigEntry(
            entry_id="entry-id-foo",
            domain="switch_as_x",
            options={"entity_id": "switch.foo", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        c = candidates[0]
        assert c.entry_disabled is False
        assert c.source_entity_id == "switch.foo"
        assert c.target_domain == "fan"
        assert c.source_registered is True
        assert c.wrapper_obj_ids == ("foo",)
        assert c.source_hidden_by is None
        assert c.source_disabled_by is None
        assert c.source_friendly_name == "Foo"

    def test_wrapper_missing_yields_no_wrapper_ids(self) -> None:
        # Source registered, well-formed options, but no
        # registry entry whose config_entry_id matches -> the
        # candidate carries an empty wrapper_obj_ids tuple.
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="switch.foo",
                domain="switch",
                original_name="Foo",
            ),
        )
        entry = _FakeConfigEntry(
            entry_id="orphan-entry-id",
            domain="switch_as_x",
            options={"entity_id": "switch.foo", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        assert candidates[0].wrapper_obj_ids == ()

    def test_multiple_wrappers_carried_through(self) -> None:
        # Two registry entries match the same switch_as_x entry
        # on config_entry_id + target_domain. The extractor
        # carries both object_ids; the logic flags the !=1 count.
        self._registry.add(
            _FakeRegistryEntry(entity_id="switch.dup", domain="switch"),
        )
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="fan.dup_a",
                domain="fan",
                config_entry_id="entry-id-dup",
            ),
        )
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="fan.dup_b",
                domain="fan",
                config_entry_id="entry-id-dup",
            ),
        )
        entry = _FakeConfigEntry(
            entry_id="entry-id-dup",
            domain="switch_as_x",
            options={"entity_id": "switch.dup", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        assert set(candidates[0].wrapper_obj_ids) == {"dup_a", "dup_b"}

    def test_source_disabled_carried_through(self) -> None:
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="switch.bar",
                domain="switch",
                disabled_by="user",
                original_name="Bar",
            ),
        )
        self._registry.add(
            _FakeRegistryEntry(
                entity_id="fan.bar",
                domain="fan",
                config_entry_id="entry-id-bar",
            ),
        )
        entry = _FakeConfigEntry(
            entry_id="entry-id-bar",
            domain="switch_as_x",
            options={"entity_id": "switch.bar", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        assert candidates[0].source_disabled_by == "user"

    def test_disabled_entry_carried_through(self) -> None:
        entry = _FakeConfigEntry(
            entry_id="entry-id-disabled",
            domain="switch_as_x",
            options={"entity_id": "switch.x", "target_domain": "fan"},
            disabled_by="user",
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        assert candidates[0].entry_disabled is True

    def test_malformed_options_yield_none_fields(self) -> None:
        entry = _FakeConfigEntry(
            entry_id="entry-id-malformed",
            domain="switch_as_x",
            options={},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        c = candidates[0]
        assert c.source_entity_id is None
        assert c.target_domain is None
        assert c.source_registered is False

    def test_unregistered_source_marked_unregistered(self) -> None:
        # entity_id present in the options but not in the
        # registry: the candidate keeps the id but flags the
        # source as unregistered.
        entry = _FakeConfigEntry(
            entry_id="entry-id-ghost",
            domain="switch_as_x",
            options={"entity_id": "switch.ghost", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert len(candidates) == 1
        c = candidates[0]
        assert c.source_entity_id == "switch.ghost"
        assert c.source_registered is False

    def test_non_switch_as_x_integration_ignored(self) -> None:
        # ``async_entries("switch_as_x")`` filters by domain,
        # so an entry from another integration never reaches the
        # extractor loop.
        entry = _FakeConfigEntry(
            entry_id="other-entry-id",
            domain="some_other_integration",
            options={"entity_id": "switch.unrelated", "target_domain": "fan"},
        )
        h = _FakeHassForBuilder([entry])

        candidates = handler._extract_visible_aliased_candidates(h)  # type: ignore[arg-type]

        assert candidates == []


# --------------------------------------------------------
# Restart-recovery kick payload
# --------------------------------------------------------


class TestKickWiring:
    def test_spec_kick_variables_match(self) -> None:
        assert handler._SPEC.kick_variables == {"trigger_id": "manual"}


# --------------------------------------------------------
# Schema vs blueprint drift
# --------------------------------------------------------


class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
    """The blueprint's ``data:`` keys must match the schema."""

    handler = handler
    blueprint_filename = "entity_defaults_watchdog.yaml"


class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
    """Blueprint input defaults must satisfy the schema."""

    handler = handler
    blueprint_filename = "entity_defaults_watchdog.yaml"
    template_defaults = {
        "instance_id": "automation.edw_default_check",
        "trigger_id": "manual",
    }


class TestBlueprintDriftChecksOptionsMatchCheckAll:
    """The blueprint's ``drift_checks`` selector options must
    map 1:1 to ``logic.CHECK_ALL``.

    Without this guard a refactor that adds a new
    ``DRIFT_CHECK_*`` constant + wires it into
    ``CHECK_ALL`` (or vice versa) can leave the blueprint
    UI unable to surface the new value, or accept a value
    the constant set rejects. Both directions silently
    break the user-visible drift-check selector.
    """

    def test_options_match_check_all(self) -> None:
        import yaml  # noqa: PLC0415

        from custom_components.blueprint_toolkit.entity_defaults_watchdog import (  # noqa: E501, PLC0415
            logic,
        )

        bp_path = (
            REPO_ROOT
            / "custom_components"
            / "blueprint_toolkit"
            / "bundled"
            / "blueprints"
            / "automation"
            / "blueprint_toolkit"
            / "entity_defaults_watchdog.yaml"
        )

        class _Loader(yaml.SafeLoader):
            pass

        def _passthrough(
            _loader: object,
            _suffix: str,
            node: object,
        ) -> object:
            value = getattr(node, "value", None)
            if isinstance(value, str):
                return value
            return None

        # types-PyYAML ships no annotations for add_multi_constructor.
        _Loader.add_multi_constructor("!", _passthrough)  # type: ignore[no-untyped-call]
        loaded: dict[str, object] = yaml.load(  # noqa: S506
            bp_path.read_text(),
            Loader=_Loader,
        )
        bp = loaded.get("blueprint")
        assert isinstance(bp, dict)
        inputs = bp.get("input")
        assert isinstance(inputs, dict)
        drift_checks = inputs.get("drift_checks")
        assert isinstance(drift_checks, dict)
        selector = drift_checks.get("selector")
        assert isinstance(selector, dict)
        select = selector.get("select")
        assert isinstance(select, dict)
        options = select.get("options")
        assert isinstance(options, list)
        offered: set[Any] = {
            o.get("value") for o in options if isinstance(o, dict)
        }
        assert offered == set(logic.CHECK_ALL), (
            "blueprint drift_checks options do not match CHECK_ALL.\n"
            f"  only in blueprint: "
            f"{sorted(offered - set(logic.CHECK_ALL))}\n"
            f"  only in CHECK_ALL: "
            f"{sorted(set(logic.CHECK_ALL) - offered)}"
        )


class TestArgparseGuards(HandlerArgparseGuardsBase):
    """Schema rejection / unregistered notify must short-circuit argparse."""

    handler = handler
    valid_payload = _valid_argparse_payload()


if __name__ == "__main__":
    # ``-p no:homeassistant`` disables pytest-HACC's plugin,
    # which fails to import against this file's stubbed
    # ``homeassistant`` modules; HACC is a mypy-only dep here.
    sys.exit(
        pytest.main([__file__, "-v", "-p", "no:homeassistant", *sys.argv[1:]])
    )
