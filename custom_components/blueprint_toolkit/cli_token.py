# This is AI generated code
"""Provision the standalone CLI's Home Assistant access token.

``zwavectl`` runs on the HA host and needs a bearer token for HA's websocket
registries + recorder history (node names, areas, device types, wake times).
When the integration's CLI-token option is on, this mints a long-lived access
token on the owner user -- named so it appears in (and can be revoked from) the
owner's Profile -> Long-lived access tokens -- and writes it to the file
``zwavectl`` reads. When the option is off (or the entry is removed) it revokes
that token and deletes the file.

The token is full-access and stored plaintext under ``/config`` (and so in HA
backups); the option is opt-in for exactly that reason.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.auth.models import RefreshToken, User
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Labels the token in the owner's Profile -> Long-lived access tokens list and
# is the key this module finds its own token by (each client_name holds one).
_CLIENT_NAME = "Blueprint Toolkit CLI"
_EXPIRATION = timedelta(days=3650)


async def async_apply(
    hass: HomeAssistant, *, enabled: bool, token_path: Path
) -> None:
    """Reconcile the CLI token to ``enabled``: provision + write when on,
    revoke + delete when off. Idempotent -- safe to call on every setup."""

    owner = await hass.auth.async_get_owner()
    if owner is None:
        if enabled:
            _LOGGER.warning(
                "Cannot provision the CLI token: no owner user found"
            )
        return

    existing = _find_token(owner)

    if not enabled:
        if existing is not None:
            hass.auth.async_remove_refresh_token(existing)
        await hass.async_add_executor_job(_delete_file, token_path)
        return

    file_present = await hass.async_add_executor_job(token_path.exists)
    if existing is not None and file_present:
        return  # token + file both in place; nothing to do.
    refresh = existing or await hass.auth.async_create_refresh_token(
        owner,
        client_name=_CLIENT_NAME,
        token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
        access_token_expiration=_EXPIRATION,
    )
    token = hass.auth.async_create_access_token(refresh)
    await hass.async_add_executor_job(_write_file, token_path, token)


def _find_token(owner: User) -> RefreshToken | None:
    """The owner's long-lived token this module manages, or ``None``."""

    return next(
        (
            t
            for t in owner.refresh_tokens.values()
            if t.token_type == TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
            and t.client_name == _CLIENT_NAME
        ),
        None,
    )


def _write_file(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Recreate at owner-only mode so the full-access token is never even
    # briefly world-readable (a plain write + chmod leaves a umask-default
    # window); unlink first so a stale, looser-mode file can't survive.
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{token}\n")


def _delete_file(path: Path) -> None:
    path.unlink(missing_ok=True)
