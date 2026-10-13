# This is AI generated code
"""Atomic JSON writes + a best-effort cross-process lock.

Shared by the Z-Wave driver-session record and the ZPM pending store: both are
read-modify-written by the in-process handler AND the standalone CLI, so a
write must be atomic (temp file + rename) and a read-modify-write must be held
under an advisory lock. Pure -- no HA imports -- so the CLI venv imports it.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path
    from typing import Any


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Serialize ``data`` and replace ``path`` atomically (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Best-effort cross-process advisory lock on a sibling ``.lock`` file.

    Absent on non-POSIX hosts (no ``fcntl``), in which case the atomic rename
    still prevents torn writes and only a rare concurrent update is lost.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        yield
        return
    lock_path = path.with_name(f"{path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
