#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.324",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""pytest-homeassistant-custom-component harness coverage.

Stands up a minimal HomeAssistant instance via the
pytest-HACC plugin and uses it to validate the parts of
this repo that need real HA at hand:

- HA's blueprint loader parses every blueprint under
  ``custom_components/blueprint_toolkit/bundled/blueprints/``
  without error.
- A hass fixture comes up cleanly and tears down without
  warnings, proving the harness itself works for the
  step-6 integration tests.

Pinned to a specific (HA, pytest-HACC) pair because
pytest-HACC versions are tied to homeassistant releases.
The pin updates only when we explicitly bump.

Runs in the default test session (not docker-marked).
First run installs the pinned HA and pytest-HACC into a
uv-script env (large download, one-time per cache).
Subsequent runs reuse the cache.

The reconciler / installer get full coverage in
``tests/test_reconciler.py`` and ``tests/test_dev_install.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# HA blueprint YAMLs reference inputs via the custom !input
# tag. PyYAML's safe loader rejects unknown tags by default;
# register a no-op constructor that returns the input name
# as a string so we can yaml.safe_load() blueprints in the
# sync tests that don't want to spin up HA.
def _input_constructor(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    return loader.construct_scalar(cast("yaml.ScalarNode", node))


yaml.SafeLoader.add_constructor("!input", _input_constructor)

REPO_ROOT = Path(__file__).parent.parent
BUNDLED_ROOT = REPO_ROOT / "custom_components" / "blueprint_toolkit" / "bundled"
BLUEPRINT_DIR = BUNDLED_ROOT / "blueprints" / "automation" / "blueprint_toolkit"


class TestHassFixtureSmoke:
    """The hass fixture starts and stops without exception.

    Single test that proves pytest-HACC is correctly wired
    in this repo. Catches dependency-pin regressions and
    pyproject-config drift early.
    """

    async def test_hass_starts_and_has_config_dir(
        self, hass: HomeAssistant
    ) -> None:
        assert hass is not None
        assert Path(hass.config.config_dir).is_dir()


class TestBlueprintParse:
    """HA's loaders accept every shipped blueprint YAML."""

    @pytest.fixture
    def all_blueprints(self) -> list[Path]:
        return sorted(BLUEPRINT_DIR.glob("*.yaml"))

    def test_at_least_one_blueprint_exists(
        self, all_blueprints: list[Path]
    ) -> None:
        # Sanity check so a future move that misplaces the
        # blueprints can't silently turn the rest of the
        # suite into a no-op.
        assert all_blueprints, f"expected blueprints under {BLUEPRINT_DIR}"

    def test_yaml_syntactically_valid(self, all_blueprints: list[Path]) -> None:
        for path in all_blueprints:
            try:
                yaml.safe_load(path.read_text())
            except yaml.YAMLError as e:
                pytest.fail(f"{path.name} is not valid YAML: {e}")

    def test_each_blueprint_has_required_keys(
        self, all_blueprints: list[Path]
    ) -> None:
        for path in all_blueprints:
            data = yaml.safe_load(path.read_text())
            assert "blueprint" in data, (
                f"{path.name} missing top-level 'blueprint' key"
            )
            bp = data["blueprint"]
            for key in ("name", "domain"):
                assert key in bp, (
                    f"{path.name} missing required blueprint.{key}"
                )
            assert bp["domain"] == "automation", (
                f"{path.name} domain must be 'automation', got {bp['domain']!r}"
            )

    async def test_each_parses_via_ha_yaml_loader(
        self,
        hass: HomeAssistant,
        all_blueprints: list[Path],
    ) -> None:
        # HA ships its own YAML loader that knows about the
        # blueprint-specific !input tag and other HA
        # extensions. Verify each blueprint loads cleanly
        # through that loader -- a stricter signal than
        # PyYAML safe_load with our shim constructor, since
        # HA's loader runs the same code path the
        # production blueprint loader does.
        from homeassistant.util.yaml import loader as ha_yaml

        for path in all_blueprints:
            try:
                ha_yaml.load_yaml(str(path))
            except Exception as e:  # noqa: BLE001
                pytest.fail(f"{path.name} failed HA yaml load: {e}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
