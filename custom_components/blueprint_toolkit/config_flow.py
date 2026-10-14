# This is AI generated code
"""Config and options flows for blueprint_toolkit.

The user-facing flow is intentionally minimal:

- The setup flow asks for nothing. Confirming the form
  creates the single config entry; HA's
  ``async_setup_entry`` then runs the reconciler.
- The options flow exposes ``cli_symlink_dir`` (whether
  the bundled CLI scripts are symlinked into a
  user-visible directory; empty -- the default -- means
  not installed) and ``provision_cli_token`` (whether to
  mint + write an HA access token for the CLI; off by
  default). ``async_setup_entry`` acts on both when the
  options change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    OPTION_CLI_SYMLINK_DIR,
    OPTION_PROVISION_CLI_TOKEN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult


class BlueprintToolkitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Single-step config flow with no required inputs."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # The integration is single-instance: a second
        # entry would re-reconcile the same destinations
        # and confuse manifest tracking.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title="Blueprint Toolkit",
                data={},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> BlueprintToolkitOptionsFlow:
        return BlueprintToolkitOptionsFlow()


class BlueprintToolkitOptionsFlow(config_entries.OptionsFlow):
    """Options flow for the optional CLI dir + token provisioning.

    HA 2026 made ``config_entry`` a read-only property on
    ``OptionsFlow``; the framework supplies the binding via
    ``_config_entry_id``. We just inherit and don't try to
    set the attribute ourselves.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_dir = self.config_entry.options.get(OPTION_CLI_SYMLINK_DIR, "")
        provision = self.config_entry.options.get(
            OPTION_PROVISION_CLI_TOKEN, False
        )
        schema = probatio.Schema(
            {
                probatio.Optional(
                    OPTION_CLI_SYMLINK_DIR, default=current_dir
                ): str,
                probatio.Optional(
                    OPTION_PROVISION_CLI_TOKEN, default=provision
                ): bool,
            },
        )
        return self.async_show_form(step_id="init", data_schema=schema)
