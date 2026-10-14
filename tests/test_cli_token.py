#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.372",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for the CLI-token provisioning module.

Drives ``cli_token.async_apply`` against a typed fake auth manager + owner, so
the mint / re-mint / revoke / file lifecycle is exercised without standing up
a full HA instance. The fake mirrors the slice of ``hass.auth`` the module
calls; the real long-lived-token constant is imported so a token-type rename
in HA fails the test rather than passing silently.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from homeassistant.auth.models import (
    TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
)

from custom_components.blueprint_toolkit import cli_token

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant


class _FakeToken(NamedTuple):
    id: str
    client_name: str
    token_type: str


class _FakeOwner:
    def __init__(self) -> None:
        self.refresh_tokens: dict[str, _FakeToken] = {}


class _FakeAuth:
    def __init__(self, owner: _FakeOwner | None) -> None:
        self._owner = owner
        self.removed: list[_FakeToken] = []
        self.mints = 0
        self.last_expiration: timedelta | None = None

    async def async_get_owner(self) -> _FakeOwner | None:
        return self._owner

    async def async_create_refresh_token(
        self,
        user: _FakeOwner,
        *,
        client_name: str,
        token_type: str,
        access_token_expiration: timedelta,
    ) -> _FakeToken:
        self.last_expiration = access_token_expiration
        token = _FakeToken(
            id=f"rt{len(user.refresh_tokens)}",
            client_name=client_name,
            token_type=token_type,
        )
        user.refresh_tokens[token.id] = token
        return token

    def async_create_access_token(self, refresh_token: _FakeToken) -> str:
        self.mints += 1
        return f"JWT-{refresh_token.id}-{self.mints}"

    def async_remove_refresh_token(self, refresh_token: _FakeToken) -> None:
        self.removed.append(refresh_token)
        self._owner.refresh_tokens.pop(refresh_token.id, None)  # type: ignore[union-attr]


class _FakeHass:
    def __init__(self, auth: _FakeAuth) -> None:
        self.auth = auth

    async def async_add_executor_job(
        self, target: Callable[..., object], *args: object
    ) -> object:
        return target(*args)


def _apply(hass: _FakeHass, *, enabled: bool, token_path: Path) -> None:
    asyncio.run(
        cli_token.async_apply(
            cast("HomeAssistant", hass),
            enabled=enabled,
            token_path=token_path,
        )
    )


def _llats(owner: _FakeOwner) -> list[_FakeToken]:
    return [
        t
        for t in owner.refresh_tokens.values()
        if t.token_type == TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
    ]


def test_enable_mints_writes_and_locks_down(tmp_path: Path) -> None:
    owner = _FakeOwner()
    auth = _FakeAuth(owner)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=True, token_path=path)

    assert path.read_text().strip().startswith("JWT-")
    assert oct(path.stat().st_mode)[-3:] == "600"
    tokens = _llats(owner)
    assert len(tokens) == 1
    assert tokens[0].client_name == "Blueprint Toolkit CLI"
    # Minted long-lived, not a default-short-lived expiry.
    assert auth.last_expiration is not None
    assert auth.last_expiration.days >= 365


def test_enable_is_idempotent_when_token_and_file_present(
    tmp_path: Path,
) -> None:
    owner = _FakeOwner()
    auth = _FakeAuth(owner)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=True, token_path=path)
    mints = auth.mints
    _apply(_FakeHass(auth), enabled=True, token_path=path)

    assert auth.mints == mints  # no re-mint
    assert len(_llats(owner)) == 1  # no second token


def test_enable_rewrites_a_missing_file_without_a_new_token(
    tmp_path: Path,
) -> None:
    owner = _FakeOwner()
    auth = _FakeAuth(owner)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=True, token_path=path)
    path.unlink()
    _apply(_FakeHass(auth), enabled=True, token_path=path)

    assert path.exists()
    assert len(_llats(owner)) == 1  # reused the existing refresh token


def test_disable_revokes_and_deletes(tmp_path: Path) -> None:
    owner = _FakeOwner()
    auth = _FakeAuth(owner)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=True, token_path=path)
    _apply(_FakeHass(auth), enabled=False, token_path=path)

    assert not path.exists()
    assert len(auth.removed) == 1
    assert not owner.refresh_tokens


def test_disable_is_a_noop_without_a_token(tmp_path: Path) -> None:
    owner = _FakeOwner()
    auth = _FakeAuth(owner)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=False, token_path=path)

    assert not path.exists()
    assert not auth.removed


def test_no_owner_is_a_safe_noop(tmp_path: Path) -> None:
    auth = _FakeAuth(None)
    path = tmp_path / "blueprint_toolkit" / "cli_token"

    _apply(_FakeHass(auth), enabled=True, token_path=path)

    assert not path.exists()
    assert auth.mints == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
