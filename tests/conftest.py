"""Pytest configuration - runs before test collection."""
# This is AI generated code

import atexit
import os
import shutil
import sys
import tempfile
from datetime import UTC
from pathlib import Path
from typing import Any, ClassVar

import pytest

# Repository root
_REPO_ROOT = Path(__file__).parent.parent

# Make ``custom_components.blueprint_toolkit.*`` importable
sys.path.insert(0, str(_REPO_ROOT))


# Create a temporary directory for __pycache__ and redirect
# all bytecode there
_pycache_tmpdir = tempfile.mkdtemp(prefix="pytest_pycache_")
sys.pycache_prefix = _pycache_tmpdir

# Also prevent bytecode writing for subsequent imports
# (belt and suspenders)
sys.dont_write_bytecode = True


def _cleanup_all_caches() -> None:
    """Remove the temp pycache dir and any ``__pycache__`` in the repo."""
    # Clean up the temp pycache directory
    shutil.rmtree(_pycache_tmpdir, ignore_errors=True)
    # Clean up any __pycache__ created before
    # sys.pycache_prefix was set (e.g., conftest.py's
    # own bytecode)
    for pycache in _REPO_ROOT.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)


# Register cleanup for when Python exits
atexit.register(_cleanup_all_caches)


def pytest_sessionfinish() -> None:
    """Clean up pycache directories after test session."""
    _cleanup_all_caches()


def run_tests(
    test_file: str,
    script_path: Path,
) -> None:
    """Entry point for running a test file directly.

    Handles ``--verbose`` and ``--coverage`` flags, then
    invokes ``pytest.main()``.  Called from each test
    file's ``__main__`` block.

    Args:
        test_file: The test file's ``__file__`` path.
        script_path: Path to the script under test
            (used to derive the coverage module name).
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test output",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage report",
    )
    args = parser.parse_args()

    if args.coverage:
        # Run as subprocess so coverage tracks from the
        # start, including import-time lines (class defs,
        # function signatures, etc.) that are missed when
        # using pytest.main() in-process.
        import subprocess

        module = script_path.stem.replace("-", "_")
        cov_dir = Path(tempfile.gettempdir())
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            test_file,
            "-p",
            "no:cacheprovider",
            f"--cov={module}",
            "--cov-report=term-missing",
            f"--cov-report=html:{cov_dir / (module + '_htmlcov')}",
        ]
        if args.verbose:
            cmd.append("-v")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(script_path.parent)
        env["COVERAGE_FILE"] = str(cov_dir / f"{module}.coverage")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(cmd, check=False)
        # Clean up .coverage file left by subprocess
        cov_file = Path.cwd() / ".coverage"
        if cov_file.exists():
            cov_file.unlink()
        raise SystemExit(result.returncode)

    pytest_args = [test_file, "-p", "no:cacheprovider"]
    if args.verbose:
        pytest_args.append("-v")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    raise SystemExit(pytest.main(pytest_args))


# --------------------------------------------------------
# BlueprintSchemaDriftBase: shared per-handler test base
# --------------------------------------------------------


_BUNDLED_BLUEPRINTS_DIR = (
    _REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "bundled"
    / "blueprints"
    / "automation"
    / "blueprint_toolkit"
)


class BlueprintSchemaDriftBase:
    """Base for per-handler blueprint-vs-schema drift checks.

    Subclass per handler test file:

        class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
            handler = my_handler_module
            blueprint_filename = "my_handler.yaml"

    Inherited tests verify:

    - The first action's ``data:`` keys match the handler's
      ``_SCHEMA`` ``probatio.Required`` keys.
    - The first action's ``action:`` targets the handler's
      registered service (``blueprint_toolkit.<service>``).

    Originally duplicated as a per-handler ``TestBlueprintSchemaDrift``
    class in each test file. Centralised here so the drift
    contract evolves in one place; per-handler files just
    declare the two class vars and inherit the two tests.
    """

    handler: Any = None  # subclass override
    blueprint_filename: str = ""  # subclass override

    def _load_blueprint(self) -> dict[str, Any]:
        import yaml

        class _PermissiveLoader(yaml.SafeLoader):
            """SafeLoader that ignores blueprint-only ``!`` tags.

            Blueprint YAML uses ``!input <name>`` to interpolate
            inputs at load time; SafeLoader otherwise raises on
            the unrecognised tag. This test only inspects keys
            and the ``action:`` string, so tag values just get
            passed through.
            """

        def _passthrough(_loader: Any, _suffix: str, node: Any) -> Any:
            if hasattr(node, "value") and isinstance(node.value, str):
                return node.value
            return None

        _PermissiveLoader.add_multi_constructor("!", _passthrough)

        path = _BUNDLED_BLUEPRINTS_DIR / self.blueprint_filename
        loaded: dict[str, Any] = yaml.load(
            path.read_text(),
            Loader=_PermissiveLoader,
        )
        assert isinstance(loaded, dict)
        return loaded

    @staticmethod
    def _required_keys(schema: Any) -> set[str]:
        import probatio

        return {
            str(k.schema)
            for k in schema.schema
            if isinstance(k, probatio.Required)
        }

    def _first_action(self, bp: dict[str, Any]) -> dict[str, Any]:
        # Blueprints accept either ``actions:`` (list, current
        # convention) or singular ``action:`` (mapping). Handle
        # both so the base doesn't trip on an older blueprint.
        actions = bp.get("actions") or bp.get("action") or []
        first: dict[str, Any] = (
            actions[0] if isinstance(actions, list) else actions
        )
        assert isinstance(first, dict)
        return first

    def test_yaml_data_keys_match_schema_required_keys(self) -> None:
        bp = self._load_blueprint()
        action = self._first_action(bp)
        yaml_keys = set((action.get("data") or {}).keys())
        schema_keys = self._required_keys(self.handler._SCHEMA)
        assert yaml_keys == schema_keys, (
            f"blueprint {self.blueprint_filename} 'data:' keys do "
            f"not match handler._SCHEMA's probatio.Required keys.\n"
            f"  only in YAML:   {sorted(yaml_keys - schema_keys)}\n"
            f"  only in schema: {sorted(schema_keys - yaml_keys)}"
        )

    def test_blueprint_action_targets_registered_service(self) -> None:
        bp = self._load_blueprint()
        action = self._first_action(bp)
        action_name = action.get("action", "")
        expected = f"blueprint_toolkit.{self.handler._SERVICE}"
        assert action_name == expected, (
            f"blueprint {self.blueprint_filename} action: "
            f"{action_name!r} does not match the registered "
            f"service {expected!r}"
        )


class BlueprintDefaultsRoundTripBase(BlueprintSchemaDriftBase):
    """Base for per-handler blueprint-defaults-vs-schema round-trip checks.

    Subclass per handler test file::

        class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
            handler = my_handler_module
            blueprint_filename = "my_handler.yaml"
            template_defaults: ClassVar = {
                "instance_id": "automation.test",
                "trigger_id": "manual",
            }

    Without this guard a blueprint edit that bumps an input
    default out of the schema's range silently lands every
    newly-created automation in ``unavailable`` until the user
    notices and edits the value.

    Reads the first action's ``data:`` block; for each schema-
    required key whose ``data:`` value is a ``!input <name>``
    reference (recorded by the permissive loader as just the
    bare input name), looks up the input's ``default:`` in
    the blueprint's ``input:`` block and feeds that into a
    payload. Templated values (``"{{ ... }}"`` strings, e.g.
    ``instance_id: "{{ this.entity_id }}"``) come from
    ``template_defaults`` -- subclasses must supply a
    test-time stand-in for each templated key. Anything else
    in ``data:`` is passed through verbatim.

    The constructed payload is then run through
    ``handler._SCHEMA``; any ``probatio.Invalid`` raised fails
    the test.
    """

    template_defaults: ClassVar[dict[str, Any]] = {}  # subclass override

    def test_blueprint_defaults_pass_schema(self) -> None:
        bp = self._load_blueprint()
        action = self._first_action(bp)
        data: dict[str, Any] = dict(action.get("data") or {})
        inputs: dict[str, Any] = (bp.get("blueprint") or {}).get("input") or {}
        schema_keys = self._required_keys(self.handler._SCHEMA)

        payload: dict[str, Any] = {}
        missing_overrides: list[str] = []
        for key in sorted(schema_keys):
            # ``template_defaults`` always wins -- subclasses
            # use it both for templated ``data:`` keys (e.g.
            # ``instance_id: "{{ this.entity_id }}"``) and for
            # blueprint inputs that intentionally lack a
            # ``default:`` (the user-must-supply case, e.g.
            # TEC's ``controlled_entities``).
            if key in self.template_defaults:
                payload[key] = self.template_defaults[key]
                continue
            value = data.get(key)
            if isinstance(value, str) and value in inputs:
                # ``!input <name>`` reference -- look up the
                # input's default.
                input_def = inputs[value]
                if isinstance(input_def, dict) and "default" in input_def:
                    payload[key] = input_def["default"]
                else:
                    missing_overrides.append(
                        f"{key} (input {value!r} has no default; supply via"
                        " ``template_defaults``)"
                    )
            elif isinstance(value, str) and "{{" in value:
                missing_overrides.append(
                    f"{key} (templated; supply via ``template_defaults``)"
                )
            else:
                payload[key] = value

        assert not missing_overrides, (
            "blueprint defaults are missing for these schema-required keys:\n"
            + "\n".join(f"  - {entry}" for entry in missing_overrides)
        )

        # Should not raise -- if the blueprint defaults are
        # outside the schema's accepted range, this is the
        # canary.
        self.handler._SCHEMA(payload)


class RecoveryEventsIntegrationBase:
    """Shared restart-recovery + reload-recovery integration tests.

    Subclass per handler integration test file::

        class TestRecoveryEvents(RecoveryEventsIntegrationBase):
            service_tag = "DW"
            setup_integration = staticmethod(_setup_integration)

    Inherited tests verify that ``register_blueprint_handler``'s
    discovery-and-kick wiring fires both at integration setup
    (the ``hass.is_running`` immediate-call branch -- pytest-HACC
    has HA up by the time the integration loads) and on every
    ``EVENT_AUTOMATION_RELOADED``. The deferred
    ``EVENT_HOMEASSISTANT_STARTED`` branch is covered at the unit
    level by ``test_helpers_lifecycle.py``, which can simulate
    ``CoreState.starting`` cleanly.
    """

    service_tag: str = ""  # subclass override (e.g. "DW")
    # Subclass override: ``staticmethod(_setup_integration)``
    # bound to the per-handler integration test file's
    # module-level ``_setup_integration`` async function.
    setup_integration: Any = None

    async def test_setup_emits_recovery_log(
        self,
        hass: Any,
        caplog: Any,
    ) -> None:
        import logging

        with caplog.at_level(
            logging.INFO,
            logger="custom_components.blueprint_toolkit.helpers",
        ):
            await self.setup_integration(hass)

        tag = f"[{self.service_tag}]"
        assert any(
            tag in r.getMessage() and "discovered at startup" in r.getMessage()
            for r in caplog.records
        ), (
            f"expected {tag} startup-recovery log line; "
            f"saw: {[r.getMessage() for r in caplog.records]}"
        )

    async def test_automation_reloaded_event_kicks_discovery(
        self,
        hass: Any,
        caplog: Any,
    ) -> None:
        import logging

        from homeassistant.components.automation import (
            EVENT_AUTOMATION_RELOADED,
        )

        await self.setup_integration(hass)
        caplog.clear()
        with caplog.at_level(
            logging.INFO,
            logger="custom_components.blueprint_toolkit.helpers",
        ):
            hass.bus.async_fire(EVENT_AUTOMATION_RELOADED, {})
            await hass.async_block_till_done()

        tag = f"[{self.service_tag}]"
        assert any(
            tag in r.getMessage() and "discovered" in r.getMessage()
            for r in caplog.records
        ), (
            f"expected {tag} recovery log line after"
            " EVENT_AUTOMATION_RELOADED; "
            f"saw: {[r.getMessage() for r in caplog.records]}"
        )


class WatchdogFindingLifecycleBase:
    """A watchdog finding stays surfaced until fixed or excluded.

    Subclass per watchdog integration test file::

        class TestFindingLifecycle(WatchdogFindingLifecycleBase):
            service = SERVICE
            setup_integration = staticmethod(_setup_integration)
            exclusions = {"device": {"exclude_device_name_regex": "x"}}

            def payload(self, **overrides): ...
            def seed_finding(self, hass, index=0): ...
            def fix_finding(self, hass, index=0): ...
            def finding_device_id(self, hass, index=0): ...

    Inherited tests drive the real service against HA's real
    issue registry and notification store, once per surface:
    fixing or excluding a finding clears it on the next scan, and
    ignoring its repair or dismissing its notification does not.
    """

    service: str = ""  # subclass override (e.g. "device_watchdog")
    # Subclass override: ``staticmethod(_setup_integration)``.
    setup_integration: Any = None
    # Scan-payload overrides that each exclude the seeded finding,
    # keyed by a label for the failure message. Every ``exclude_*``
    # input the watchdog offers belongs here.
    exclusions: ClassVar[dict[str, dict[str, Any]]] = {}

    _DOMAIN = "blueprint_toolkit"
    _INSTANCE_ID = "automation.finding_lifecycle"

    def payload(self, **overrides: Any) -> dict[str, Any]:
        """Return a service payload that checks the seeded finding."""
        raise NotImplementedError

    def seed_finding(self, hass: Any, index: int = 0) -> None:
        """Plant one repairable finding, distinct per ``index``."""
        raise NotImplementedError

    def fix_finding(self, hass: Any, index: int = 0) -> None:
        """Resolve the finding ``seed_finding`` planted."""
        raise NotImplementedError

    def finding_device_id(self, hass: Any, index: int = 0) -> str:
        """Return the device the planted finding sits on."""
        raise NotImplementedError

    async def _scan(self, hass: Any, **overrides: Any) -> None:
        await hass.services.async_call(
            self._DOMAIN,
            self.service,
            self.payload(
                instance_id=self._INSTANCE_ID,
                validate_includes_excludes=False,
                **overrides,
            ),
            blocking=True,
        )
        await hass.async_block_till_done()

    def _repairs(self, hass: Any) -> dict[str, Any]:
        from homeassistant.helpers import issue_registry as ir

        return {
            issue.issue_id: issue
            for issue in ir.async_get(hass).issues.values()
            if issue.domain == self._DOMAIN and "__repair_" in issue.issue_id
        }

    def _notifications(self, hass: Any) -> dict[str, Any]:
        from homeassistant.components.persistent_notification import (
            _async_get_or_create_notifications,
        )

        prefix = f"{self._DOMAIN}_{self.service}__{self._INSTANCE_ID}__"
        return {
            notification_id: notification
            for notification_id, notification in (
                _async_get_or_create_notifications(hass).items()
            )
            if notification_id.startswith(prefix)
        }

    async def test_ignored_repair_returns_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        from homeassistant.helpers import issue_registry as ir

        await self.setup_integration(hass)
        self.seed_finding(hass)
        await self._scan(hass, create_repairs=True)
        [issue_id] = self._repairs(hass)
        created = self._repairs(hass)[issue_id].created

        ir.async_ignore_issue(hass, self._DOMAIN, issue_id, True)
        await self._scan(hass, create_repairs=True)

        issue = self._repairs(hass)[issue_id]
        assert issue.dismissed_version is None
        assert issue.created == created

    async def test_ignored_repair_stays_visible_at_the_cap(
        self,
        hass: Any,
    ) -> None:
        from homeassistant.helpers import issue_registry as ir

        await self.setup_integration(hass)
        self.seed_finding(hass, 0)
        self.seed_finding(hass, 1)
        await self._scan(hass, create_repairs=True, max_repairs=1)
        [issue_id] = self._repairs(hass)

        ir.async_ignore_issue(hass, self._DOMAIN, issue_id, True)
        await self._scan(hass, create_repairs=True, max_repairs=1)

        visible = [
            issue.issue_id
            for issue in self._repairs(hass).values()
            if issue.dismissed_version is None
        ]
        assert visible == [issue_id]
        titles = [n["title"] for n in self._notifications(hass).values()]
        assert any("1 additional repairable" in title for title in titles)

    async def test_fixed_repair_clears_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        await self.setup_integration(hass)
        self.seed_finding(hass)
        await self._scan(hass, create_repairs=True)
        assert len(self._repairs(hass)) == 1

        self.fix_finding(hass)
        await self._scan(hass, create_repairs=True)

        assert self._repairs(hass) == {}

    async def test_excluded_repair_clears_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        from homeassistant.helpers import issue_registry as ir

        await self.setup_integration(hass)
        self.seed_finding(hass)
        for label, exclusion in self.exclusions.items():
            for ignored in (False, True):
                await self._scan(hass, create_repairs=True)
                [issue_id] = self._repairs(hass)
                if ignored:
                    ir.async_ignore_issue(hass, self._DOMAIN, issue_id, True)

                await self._scan(hass, create_repairs=True, **exclusion)

                assert self._repairs(hass) == {}, (label, ignored)

    async def test_excluding_another_integration_on_the_device_clears_it(
        self,
        hass: Any,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        await self.setup_integration(hass)
        self.seed_finding(hass)
        er.async_get(hass).async_get_or_create(
            domain="fan",
            platform="switch_as_x",
            unique_id="shared-device",
            device_id=self.finding_device_id(hass),
        )
        await self._scan(hass, create_repairs=True)
        assert len(self._repairs(hass)) == 1

        await self._scan(
            hass,
            create_repairs=True,
            exclude_integrations=["switch_as_x"],
        )

        assert self._repairs(hass) == {}

    async def test_dismissed_notification_returns_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        await self.setup_integration(hass)
        self.seed_finding(hass)
        await self._scan(hass)
        [notification_id] = self._notifications(hass)

        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": notification_id},
            blocking=True,
        )
        assert self._notifications(hass) == {}
        await self._scan(hass)

        assert list(self._notifications(hass)) == [notification_id]

    async def test_fixed_notification_clears_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        await self.setup_integration(hass)
        self.seed_finding(hass)
        await self._scan(hass)
        assert len(self._notifications(hass)) == 1

        self.fix_finding(hass)
        await self._scan(hass)

        assert self._notifications(hass) == {}

    async def test_excluded_notification_clears_on_next_scan(
        self,
        hass: Any,
    ) -> None:
        await self.setup_integration(hass)
        self.seed_finding(hass)
        for label, exclusion in self.exclusions.items():
            await self._scan(hass)
            assert len(self._notifications(hass)) == 1, label

            await self._scan(hass, **exclusion)

            assert self._notifications(hass) == {}, label


class HandlerArgparseGuardsBase:
    """Generic argparse guard tests for every handler.

    Subclass per handler test file::

        class TestArgparseGuards(HandlerArgparseGuardsBase):
            handler = my_handler_module

    The inherited tests assert that the handler's argparse
    layer short-circuits before reaching ``_async_service_layer``
    in two scenarios:

    1. **Schema rejection** -- an empty (or
       ``schema_invalid_payload``-overridden) call fails
       ``_SCHEMA`` and ``validate_payload_or_emit_config_error``
       fires the config-error notification. Service-layer
       must not run.
    2. **Unregistered notify service** -- for handlers that
       have a ``notification_service`` schema field, a
       payload referencing a service that doesn't exist
       hits the cross-field guard. Service-layer must not
       run.

    Subclasses provide:
        ``handler``: the handler module under test.
        ``valid_payload``: a fully-populated, schema-valid
            service-call payload (used as the basis for the
            unregistered-notify test). Subclasses with no
            ``notification_service`` field may leave this
            unset; the unregistered-notify test is then
            skipped.
        ``schema_invalid_payload``: an explicitly-invalid
            payload. Defaults to ``{}`` (every handler has
            ``probatio.Required`` keys, so empty fails).
    """

    handler: Any = None  # subclass override
    valid_payload: dict[str, Any] | None = None
    schema_invalid_payload: dict[str, Any] | None = None  # default: {}

    @staticmethod
    def _make_hass() -> Any:
        """Build a mock hass with the surface argparse touches.

        Argparse reads ``hass.states.get`` (cross-field
        existence checks), ``hass.services.has_service``
        (notify-service existence), and the
        ``config_entries.async_entries(DOMAIN)`` accessor
        (for ``entry_for_domain``). All return empty /
        missing values; argparse paths exercised here
        bottom-out at the schema rejection or the cross-
        field error before any of those matter.
        """
        from dataclasses import dataclass, field

        @dataclass
        class _Services:
            calls: list[tuple[str, str, dict[str, Any]]] = field(
                default_factory=list,
            )

            async def async_call(
                self,
                domain: str,
                name: str,
                data: dict[str, Any] | None = None,
                **_kwargs: Any,
            ) -> None:
                self.calls.append((domain, name, dict(data or {})))

            def has_service(self, _domain: str, _name: str) -> bool:
                return False

        @dataclass
        class _States:
            def get(self, _eid: str) -> Any:
                return None

        @dataclass
        class _RuntimeData:
            handlers: dict[str, dict[str, Any]] = field(default_factory=dict)

        @dataclass
        class _Entry:
            runtime_data: _RuntimeData = field(default_factory=_RuntimeData)

            def async_create_background_task(
                self,
                _hass: Any,
                _coro: Any,
                _name: str,
            ) -> Any:
                return None

        @dataclass
        class _ConfigEntries:
            entries: list[_Entry] = field(default_factory=lambda: [_Entry()])

            def async_entries(self, _domain: str) -> list[_Entry]:
                return list(self.entries)

        @dataclass
        class _Hass:
            services: _Services = field(default_factory=_Services)
            states: _States = field(default_factory=_States)
            config_entries: _ConfigEntries = field(
                default_factory=_ConfigEntries,
            )
            data: dict[str, Any] = field(default_factory=dict)

        return _Hass()

    @staticmethod
    def _make_call(data: dict[str, Any]) -> Any:
        class _Call:
            def __init__(self, data: dict[str, Any]) -> None:
                self.data = data
                self.context = None

        return _Call(data)

    def _run_argparse_with_capture(
        self,
        payload: dict[str, Any],
    ) -> list[tuple[Any, ...]]:
        import asyncio
        from datetime import datetime

        captured: list[tuple[Any, ...]] = []

        async def _capture_service_layer(
            *args: Any,
            **kwargs: Any,
        ) -> None:
            captured.append((args, kwargs))

        async def _swallow_emit(
            _hass: Any,
            _instance_id: str,
            _errors: list[str],
        ) -> None:
            return None

        original_layer = self.handler._async_service_layer
        original_emit = self.handler._emit_config_error
        self.handler._async_service_layer = _capture_service_layer
        self.handler._emit_config_error = _swallow_emit
        try:
            asyncio.run(
                self.handler._async_argparse(
                    self._make_hass(),
                    self._make_call(payload),
                    now=datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC),
                ),
            )
        finally:
            self.handler._async_service_layer = original_layer
            self.handler._emit_config_error = original_emit
        return captured

    def test_schema_rejection_blocks_service_layer(self) -> None:
        """A schema-invalid payload must short-circuit before
        ``_async_service_layer`` runs -- the layer is what
        actually dispatches actions / writes state, so any
        regression that skips the schema gate would silently
        operate on garbage input. ``validate_payload_or_emit_config_error``
        emits the config-error notification and argparse
        early-returns; the layer must not be reached.
        """
        invalid = (
            {}
            if self.schema_invalid_payload is None
            else self.schema_invalid_payload
        )
        captured = self._run_argparse_with_capture(invalid)
        assert captured == [], (
            "schema rejection should short-circuit before "
            "_async_service_layer; saw service-layer "
            f"calls: {captured}"
        )

    def test_unregistered_notify_service_blocks_service_layer(self) -> None:
        """A payload with a ``notification_service`` referencing
        an unregistered service must hit the cross-field
        guard and short-circuit before
        ``_async_service_layer``. The mock hass's
        ``has_service`` returns ``False`` for everything, so
        any non-empty ``notification_service`` triggers the
        guard.
        """
        if self.valid_payload is None:
            import pytest

            pytest.skip("subclass did not supply ``valid_payload``")
        if "notification_service" not in self.valid_payload:
            import pytest

            pytest.skip("handler schema has no ``notification_service`` field")
        payload = dict(self.valid_payload)
        payload["notification_service"] = "notify.does_not_exist"
        captured = self._run_argparse_with_capture(payload)
        assert captured == [], (
            "unregistered notify-service should short-circuit "
            "before _async_service_layer; saw service-layer "
            f"calls: {captured}"
        )
