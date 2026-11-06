#!/usr/bin/env -S uv run --script --exact
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for the per-file test entry point that tests/run_all.py drives.

run_all.py runs each discovered test file as a subprocess, passing
``--verbose`` / ``--coverage``; the file hands those to
``conftest.run_tests``, which turns them into the pytest run.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import run_all as ra
from conftest import coverage_source, run_tests

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = REPO_ROOT / "tests" / "conftest.py"

_TEST_FILE = "/repo/tests/test_example.py"


def _make_repo(root: Path) -> Path:
    """Build a repo with a package module and a bare script."""
    package = root / "custom_components" / "example"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "logic.py").write_text("")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "dev-thing.py").write_text("")
    return root


class TestCoverageSource:
    def test_package_module_is_its_dotted_name(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        module = repo / "custom_components" / "example" / "logic.py"
        assert (
            coverage_source(module, repo) == "custom_components.example.logic"
        )

    def test_package_init_is_the_package_name(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        init = repo / "custom_components" / "example" / "__init__.py"
        assert coverage_source(init, repo) == "custom_components.example"

    def test_directory_is_its_path(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        package = repo / "custom_components" / "example"
        assert coverage_source(package, repo) == str(package)

    def test_bare_script_is_its_importable_stem(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        script = repo / "scripts" / "dev-thing.py"
        assert coverage_source(script, repo) == "dev_thing"


class TestRunTests:
    """The pytest invocation ``run_tests`` builds from its argv.

    ``patch.dict(os.environ)`` undoes the environment write
    ``run_tests`` makes for the run it starts.
    """

    @staticmethod
    def _pytest_argv(
        argv: list[str], pytest_args: tuple[str, ...] = ()
    ) -> list[str]:
        with (
            patch.dict(os.environ),
            patch.object(sys, "argv", [_TEST_FILE, *argv]),
            patch.object(pytest, "main", autospec=True, return_value=3) as main,
            pytest.raises(SystemExit) as exited,
        ):
            run_tests(
                _TEST_FILE, _SCRIPT_PATH, REPO_ROOT, pytest_args=pytest_args
            )
        assert exited.value.code == 3
        main.assert_called_once()
        args: list[str] = main.call_args.args[0]
        return args

    def test_default_run(self) -> None:
        assert self._pytest_argv([]) == [
            _TEST_FILE,
            "-p",
            "no:cacheprovider",
        ]

    def test_verbose(self) -> None:
        assert self._pytest_argv(["--verbose"])[-1] == "-v"

    def test_file_arguments_precede_passed_through_ones(self) -> None:
        argv = self._pytest_argv(
            ["-k", "name", "-x"], pytest_args=("-p", "no:plugin")
        )
        assert argv == [
            _TEST_FILE,
            "-p",
            "no:cacheprovider",
            "-p",
            "no:plugin",
            "-k",
            "name",
            "-x",
        ]

    def test_missing_code_under_test_fails_without_running(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "missing.py"
        with (
            patch.dict(os.environ),
            patch.object(sys, "argv", [_TEST_FILE]),
            patch.object(pytest, "main", autospec=True) as main,
            pytest.raises(SystemExit) as exited,
        ):
            run_tests(_TEST_FILE, missing, REPO_ROOT)
        assert exited.value.code == 2
        main.assert_not_called()
        assert str(missing) in capsys.readouterr().err

    def test_cov_option_is_passed_through_not_abbreviated(self) -> None:
        # ``--cov`` would abbreviate ``--coverage`` if argparse allowed
        # it, which would swallow the option rather than hand it on.
        assert self._pytest_argv(["--cov=pkg"])[-1] == "--cov=pkg"

    def test_coverage_runs_pytest_in_a_subprocess(self) -> None:
        completed: subprocess.CompletedProcess[bytes] = (
            subprocess.CompletedProcess(args=[], returncode=5)
        )
        with (
            patch.dict(os.environ),
            patch.object(sys, "argv", [_TEST_FILE, "--coverage", "-x"]),
            patch.object(
                subprocess, "run", autospec=True, return_value=completed
            ) as run,
            pytest.raises(SystemExit) as exited,
        ):
            run_tests(
                _TEST_FILE,
                _SCRIPT_PATH,
                REPO_ROOT,
                pytest_args=("-p", "no:plugin"),
            )
        assert exited.value.code == 5
        cmd = run.call_args.args[0]
        assert cmd[:3] == [sys.executable, "-m", "pytest"]
        assert cmd[3:9] == [
            _TEST_FILE,
            "-p",
            "no:cacheprovider",
            "-p",
            "no:plugin",
            "-x",
        ]
        assert "--cov=conftest" in cmd
        env = run.call_args.kwargs["env"]
        assert env["COVERAGE_FILE"].endswith("test_example.coverage")


class TestEveryFileEndsByCallingRunTests:
    """Each file run_all.py discovers hands its run to ``run_tests``.

    run_all.py passes ``--verbose`` / ``--coverage`` to every file it
    runs, so a file that calls pytest itself rejects or ignores them.
    The call also ends the file: a class added below it still runs,
    since pytest imports the module to collect it, but the end of the
    source then no longer reads as the end of the tests.
    """

    @staticmethod
    def _ends_with_run_tests(path: Path) -> bool:
        body = ast.parse(path.read_text(encoding="utf-8")).body
        if not body or not isinstance(body[-1], ast.If):
            return False
        block = body[-1]
        if ast.unparse(block.test) != "__name__ == '__main__'":
            return False
        last = block.body[-1]
        if not (
            isinstance(last, ast.Expr) and isinstance(last.value, ast.Call)
        ):
            return False
        call = last.value
        return (
            ast.unparse(call.func) == "run_tests"
            and bool(call.args)
            and ast.unparse(call.args[0]) == "__file__"
        )

    def test_discovers_test_files(self) -> None:
        # The gate below passes vacuously on an empty discovery.
        discovered = ra.discover_test_files(ra.TESTS_DIR)
        assert Path(__file__).resolve() in discovered

    def test_every_discovered_file_ends_by_calling_run_tests(self) -> None:
        wrong = [
            path.name
            for path in ra.discover_test_files(ra.TESTS_DIR)
            if not self._ends_with_run_tests(path)
        ]
        assert wrong == [], (
            f"test files not ending in a __main__ block whose last "
            f"statement is run_tests(__file__, ...): {wrong}"
        )


if __name__ == "__main__":
    run_tests(__file__, _SCRIPT_PATH, REPO_ROOT)
