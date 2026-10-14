#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for scripts/dev-deploy.py.

Covers the shipping archive's contents rather than the ssh
transport: the stream is built on the development machine and
extracted by the host's ``tar``, so a member the local ``tar``
hides on read still lands on the host as a file.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DEV_DEPLOY = REPO_ROOT / "scripts" / "dev-deploy.py"


def _load_dev_deploy() -> object:
    """Import dev-deploy.py under a module name Python accepts.

    The hyphen in the filename is not a legal identifier, so the
    file cannot be imported by name; everything it does at import
    time sits behind a ``__main__`` guard.
    """
    spec = importlib.util.spec_from_file_location(
        "dev_deploy_under_test", DEV_DEPLOY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tar_members(src: Path, env: dict[str, str]) -> list[str]:
    """Member names in a ``tar`` stream built the way shipping builds it."""
    archive = src.parent / "out.tar"
    subprocess.run(
        ["tar", "-cf", str(archive), "-C", str(src), "payload.yaml"],
        env=env,
        check=True,
    )
    with tarfile.open(archive) as handle:
        return handle.getnames()


def _set_xattr(target: Path) -> None:
    """Give ``target`` one extended attribute, best effort.

    An attribute is what makes Apple's ``tar`` emit a companion, so
    the control case needs one. The call is best effort because the
    interface is platform-specific and the namespace a filesystem
    accepts varies; macOS also sets ``com.apple.provenance`` itself,
    which is sufficient on its own.
    """
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(target, "user.test", b"x")
            return
        except OSError:
            return
    subprocess.run(
        ["xattr", "-w", "com.example.test", "x", str(target)],
        check=False,
        capture_output=True,
    )


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    """A source directory whose file carries an extended attribute."""
    src = tmp_path / "src"
    src.mkdir()
    target = src / "payload.yaml"
    target.write_text("blueprint: {}\n")
    _set_xattr(target)
    return src


class TestShippingArchive:
    def test_no_apple_double_members(self, payload: Path) -> None:
        """The stream carries no ``._`` companion.

        ``tarfile`` is the right reader for this: Apple's ``tar``
        reassembles a companion into the real member's attributes
        on read, so ``tar -t`` reports a clean archive either way,
        while the host's ``tar`` writes the companion out as a file.
        """
        module = _load_dev_deploy()
        env = module.tar_env()  # type: ignore[attr-defined]

        names = _tar_members(payload, env)

        assert "payload.yaml" in names
        assert not [n for n in names if Path(n).name.startswith("._")], (
            f"shipping archive carries AppleDouble member(s): {names}. "
            "Those extract as real files on the host, keep the "
            "original's extension, and reach Home Assistant's "
            "blueprint scan."
        )

    def test_env_sets_the_documented_opt_out(self) -> None:
        module = _load_dev_deploy()
        assert module.tar_env()["COPYFILE_DISABLE"] == "1"  # type: ignore[attr-defined]

    @pytest.mark.skipif(
        sys.platform != "darwin",
        reason="only Apple's tar emits AppleDouble members",
    )
    def test_guard_is_load_bearing_here(self, payload: Path) -> None:
        """Without the opt-out this platform does emit a companion.

        Without this, the check above would pass on a machine whose
        ``tar`` never had the behaviour and prove nothing.
        """
        bare = {k: v for k, v in os.environ.items() if k != "COPYFILE_DISABLE"}

        names = _tar_members(payload, bare)

        assert [n for n in names if Path(n).name.startswith("._")], (
            "expected Apple's tar to emit an AppleDouble member "
            f"without COPYFILE_DISABLE, got: {names}"
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import run_tests

    run_tests(
        test_file=__file__,
        script_path=DEV_DEPLOY,
    )
