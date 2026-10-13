#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.357",
#     "types-PyYAML",
#     "zwave-js-server-python==0.73.0",
# ]
# ///
# This is AI generated code
"""Tests for the standalone zwavectl script.

The script bootstraps its own venv for socketio / aiohttp. Most
tests exercise its pure logic (formatting, parsing, sorting, and
row assembly); focused mocks cover important fetcher error paths.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "bundled"
    / "bin"
    / "zwavectl.py"
)

sys.path.insert(0, str(_SCRIPT_PATH.parent))

import zwavectl as zc  # noqa: E402

# --- fetch_zwave_nodes ------------------------------------------


class _MalformedNodesClient:
    async def connect(self, url: str, *, socketio_path: str) -> None:
        pass

    async def call(
        self,
        event: str,
        data: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object]:
        _ = event, data, timeout
        return {"result": "not-a-list"}

    async def disconnect(self) -> None:
        pass


def test_fetch_zwave_nodes_rejects_malformed_result() -> None:
    client = _MalformedNodesClient()
    socketio = ModuleType("socketio")
    socketio.__dict__["AsyncClient"] = lambda: client
    with (
        patch.dict(sys.modules, {"socketio": socketio}),
        pytest.raises(TypeError, match="unexpected shape"),
    ):
        asyncio.run(zc.fetch_zwave_nodes())


# --- _parse_numeric ---------------------------------------------


class TestParseNumeric:
    def test_int(self) -> None:
        assert zc._parse_numeric("42") == 42

    def test_float_non_integer(self) -> None:
        assert zc._parse_numeric("3.5") == 3.5

    def test_float_integer_value_collapses_to_int(self) -> None:
        # "100.0" comes back as 100 (int), not 100.0 (float), so
        # renderers don't show ".0" for whole numbers.
        v = zc._parse_numeric("100.0")
        assert v == 100
        assert isinstance(v, int)

    def test_none_and_sentinels(self) -> None:
        for raw in (None, "unavailable", "unknown", ""):
            assert zc._parse_numeric(raw) is None

    def test_garbage(self) -> None:
        assert zc._parse_numeric("not a number") is None


# --- _drop_rate / _fmt_drop_rate --------------------------------


class TestDropRate:
    def test_both_none(self) -> None:
        assert zc._drop_rate(None, None) is None

    def test_no_activity_is_none(self) -> None:
        # 0 success + 0 drops is a meaningless rate, not 0%.
        assert zc._drop_rate(0, 0) is None

    def test_all_success(self) -> None:
        assert zc._drop_rate(100, 0) == 0.0

    def test_all_drops(self) -> None:
        assert zc._drop_rate(0, 100) == 1.0

    def test_mixed(self) -> None:
        assert zc._drop_rate(90, 10) == pytest.approx(0.1)

    def test_drops_only_counter_present(self) -> None:
        # When only the drops counter came back, treat the missing
        # success counter as 0 rather than None -- the rate is
        # still computable.
        assert zc._drop_rate(None, 5) == 1.0

    def test_success_only_counter_present(self) -> None:
        assert zc._drop_rate(5, None) == 0.0

    def test_non_numeric_rejected(self) -> None:
        # Strings shouldn't creep into the arithmetic; treated
        # like None.
        assert zc._drop_rate("5", "3") is None

    def test_explicit_zero_counter_not_confused_with_none(self) -> None:
        # This is the bug the refactor fixed: 0 must not get
        # coerced to None by a truthiness check. We verify by
        # driving a rate computation that requires distinguishing
        # between "success=0, drops=5" (1.0) and "no data" (None).
        assert zc._drop_rate(0, 5) == 1.0
        assert zc._drop_rate(5, 0) == 0.0


class TestFmtDropRate:
    def test_none(self) -> None:
        assert zc._fmt_drop_rate(None, use_color=False) == zc.DASH

    def test_zero(self) -> None:
        assert zc._fmt_drop_rate(0.0, use_color=False) == "0"

    def test_sub_one_percent(self) -> None:
        # Non-zero rate that would round to 0 shows as "<1".
        assert zc._fmt_drop_rate(0.001, use_color=False) == "<1"

    def test_rounded_int_percent(self) -> None:
        assert zc._fmt_drop_rate(0.03, use_color=False) == "3"
        assert zc._fmt_drop_rate(0.10, use_color=False) == "10"

    def test_color_thresholds(self) -> None:
        # green < 1%, yellow 1-5%, red > 5%.
        assert zc.ANSI_GREEN in zc._fmt_drop_rate(0.005, use_color=True)
        assert zc.ANSI_YELLOW in zc._fmt_drop_rate(0.03, use_color=True)
        assert zc.ANSI_RED in zc._fmt_drop_rate(0.20, use_color=True)


# --- _ss_quality / _ss_color ------------------------------------


class TestSsQuality:
    def test_mesh_buckets(self) -> None:
        assert zc._ss_quality(-60, "Mesh") == "good"
        assert zc._ss_quality(-75, "Mesh") == "fair"
        assert zc._ss_quality(-90, "Mesh") == "poor"

    def test_lr_buckets(self) -> None:
        # LR thresholds are ~15 dB weaker than Mesh. A value
        # that's "poor" on Mesh is often still "fair" on LR.
        assert zc._ss_quality(-90, "LR") == "fair"
        assert zc._ss_quality(-70, "LR") == "good"
        assert zc._ss_quality(-105, "LR") == "poor"

    def test_none_input(self) -> None:
        assert zc._ss_quality(None, "Mesh") is None

    def test_unknown_protocol_falls_back_to_mesh(self) -> None:
        assert zc._ss_quality(-60, None) == "good"
        assert zc._ss_quality(-90, "unknown") == "poor"

    def test_boundary_values(self) -> None:
        # Boundaries: "> good_above" is good; "> fair_above" is
        # fair; otherwise poor. Exactly at the boundary lands in
        # the weaker bucket.
        assert zc._ss_quality(-70, "Mesh") == "fair"
        assert zc._ss_quality(-85, "Mesh") == "poor"


class TestSsColor:
    def test_color_per_bucket(self) -> None:
        assert zc._ss_color(-60, "Mesh") == zc.ANSI_GREEN
        assert zc._ss_color(-75, "Mesh") == zc.ANSI_YELLOW
        assert zc._ss_color(-90, "Mesh") == zc.ANSI_RED

    def test_none_input(self) -> None:
        assert zc._ss_color(None, "Mesh") == ""


# --- _fmt_last_seen ---------------------------------------------


class TestFmtLastSeen:
    def test_none(self) -> None:
        assert zc._fmt_last_seen(None) == zc.DASH

    def test_unparseable(self) -> None:
        assert zc._fmt_last_seen("this is not a timestamp") == zc.DASH

    def test_naive_timestamp_assumed_utc(self) -> None:
        # Naive (no tz) input should be treated as UTC, not as
        # local time (which would give variable results per host).
        t = datetime.now(UTC) - timedelta(minutes=5)
        assert zc._fmt_last_seen(t.replace(tzinfo=None).isoformat()) == "5m"

    def test_zulu_suffix(self) -> None:
        # Python 3.11+ parses "Z" natively; the script's old
        # .replace("Z", "+00:00") hack was dead code, but we
        # want to make sure the native path still works.
        t = datetime.now(UTC) - timedelta(hours=2)
        stamp = t.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        assert zc._fmt_last_seen(stamp) == "2h"

    def test_tier_transitions(self) -> None:
        now = datetime.now(UTC)
        cases = [
            (timedelta(seconds=0), "now"),
            (timedelta(seconds=30), "30s"),
            (timedelta(minutes=5), "5m"),
            (timedelta(hours=3), "3h"),
            (timedelta(days=2), "2d"),
            (timedelta(days=120), "4mo"),
        ]
        for delta, expected in cases:
            stamp = (now - delta).isoformat()
            assert zc._fmt_last_seen(stamp) == expected, expected

    def test_future_clamped_to_now(self) -> None:
        # Clock skew / HA recording a state slightly in the
        # future shouldn't surface as a negative age.
        future = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        assert zc._fmt_last_seen(future) == "now"


# --- _fmt_update ------------------------------------------------


class TestFmtUpdate:
    def test_no_updates(self) -> None:
        assert zc._fmt_update(None) == "no"
        assert zc._fmt_update([]) == "no"

    def test_with_version(self) -> None:
        assert zc._fmt_update([{"version": "7.21.0"}]) == "yes (v7.21.0)"

    def test_without_version(self) -> None:
        assert zc._fmt_update([{}]) == "yes"

    def test_non_list(self) -> None:
        # The runtime guard defends against a non-list (the node cast could
        # be a lie); pass a deliberately wrong type to exercise it.
        assert zc._fmt_update("garbage") == "no"  # type: ignore[arg-type]


# --- _fmt_num / _fmt_battery / _fmt_version / _fmt_neighbors ---


class TestFmtNum:
    def test_none(self) -> None:
        assert zc._fmt_num(None) == zc.DASH

    def test_int(self) -> None:
        assert zc._fmt_num(42) == "42"

    def test_float_integer_value(self) -> None:
        assert zc._fmt_num(42.0) == "42"

    def test_float_fractional(self) -> None:
        assert zc._fmt_num(3.15) == "3.1"


class TestFmtBattery:
    def test_none(self) -> None:
        assert zc._fmt_battery(None) == zc.DASH

    def test_int(self) -> None:
        assert zc._fmt_battery(75) == "75"

    def test_float_truncates(self) -> None:
        assert zc._fmt_battery(75.9) == "75"


class TestFmtVersion:
    def test_none(self) -> None:
        assert zc._fmt_version(None) == zc.DASH

    def test_empty(self) -> None:
        assert zc._fmt_version("") == zc.DASH

    def test_value(self) -> None:
        assert zc._fmt_version("1.2.3") == "v1.2.3"


class TestFmtNeighbors:
    def test_none(self) -> None:
        assert zc._fmt_neighbors(None) == zc.DASH

    def test_empty(self) -> None:
        assert zc._fmt_neighbors([]) == "none"

    def test_list(self) -> None:
        assert zc._fmt_neighbors([1, 17, 50]) == "1 17 50"


class TestFmtRole:
    def test_none(self) -> None:
        assert zc._fmt_role(None) == zc.DASH

    def test_known(self) -> None:
        assert zc._fmt_role(5) == "AlwaysOn"

    def test_unknown(self) -> None:
        assert zc._fmt_role(99) == "?99"


class TestFmtRouteSpeed:
    def test_none(self) -> None:
        assert zc._fmt_route_speed(None) == zc.DASH

    def test_known(self) -> None:
        assert zc._fmt_route_speed(3) == "100k"
        assert zc._fmt_route_speed(4) == "LR"

    def test_unknown(self) -> None:
        assert zc._fmt_route_speed(99) == "?99"


class TestFmtMaxSpeed:
    def test_none(self) -> None:
        assert zc._fmt_max_speed(None) == zc.DASH

    def test_known(self) -> None:
        assert zc._fmt_max_speed(100000) == "100k"

    def test_unknown(self) -> None:
        assert zc._fmt_max_speed(42000) == "?42000"


# --- _visible_len / _pad ----------------------------------------


class TestVisibleLen:
    def test_plain(self) -> None:
        assert zc._visible_len("hello") == 5

    def test_with_ansi(self) -> None:
        s = f"{zc.ANSI_GREEN}hello{zc.ANSI_RESET}"
        assert zc._visible_len(s) == 5

    def test_truncated_ansi_terminates(self) -> None:
        # Malformed/truncated escape shouldn't scan past the end
        # of string or hang; the exact fallback count isn't
        # important (alignment code only cares that it returns).
        result = zc._visible_len("\033[3")
        assert isinstance(result, int)
        assert result >= 0


class TestPad:
    def test_left_align(self) -> None:
        assert zc._pad("hi", 5, right_align=False) == "hi   "

    def test_right_align(self) -> None:
        assert zc._pad("hi", 5, right_align=True) == "   hi"

    def test_overflow(self) -> None:
        assert zc._pad("abcdef", 3, right_align=False) == "abcdef"

    def test_visible_len_used_for_padding(self) -> None:
        # A colored 5-char string should pad to width 5, not
        # width-including-escape-codes.
        colored = f"{zc.ANSI_GREEN}hello{zc.ANSI_RESET}"
        padded = zc._pad(colored, 7, right_align=False)
        assert padded.endswith("  ")
        assert zc._visible_len(padded) == 7


# --- _parse_columns / _parse_sort -------------------------------


class TestParseColumns:
    def test_empty_returns_defaults(self) -> None:
        assert zc._parse_columns("") == zc._COLUMN_ALIASES["defaults"]

    def test_all(self) -> None:
        assert zc._parse_columns("all") == zc.ALL_COLUMNS

    def test_alias_expansion(self) -> None:
        assert zc._parse_columns("firmware") == zc._COLUMN_ALIASES["firmware"]

    def test_mixed_alias_and_columns(self) -> None:
        # Aliases expand in place; duplicates are dropped.
        out = zc._parse_columns("node,firmware,device")
        assert out == ["node", "firmware-dev", "firmware-sdk", "device"]

    def test_unknown_column_raises(self) -> None:
        with pytest.raises(SystemExit):
            zc._parse_columns("not-a-real-column")

    def test_whitespace_and_case(self) -> None:
        assert zc._parse_columns("  Node , Device ") == ["node", "device"]

    def test_singular_default_alias_works(self) -> None:
        # 'default' is a back-compat singular synonym of 'defaults'.
        assert zc._parse_columns("default") == zc._COLUMN_ALIASES["defaults"]


class TestParseSort:
    def test_default(self) -> None:
        assert zc._parse_sort("node") == ["node"]

    def test_multi(self) -> None:
        assert zc._parse_sort("location,device") == ["location", "device"]

    def test_dedup(self) -> None:
        assert zc._parse_sort("location,location") == ["location"]

    def test_unknown_raises(self) -> None:
        with pytest.raises(SystemExit):
            zc._parse_sort("not-a-real-column")

    def test_alias_rejected(self) -> None:
        # --sort accepts real column names only, not aliases.
        with pytest.raises(SystemExit):
            zc._parse_sort("firmware")

    def test_empty_falls_back_to_node(self) -> None:
        assert zc._parse_sort("") == ["node"]
        assert zc._parse_sort(" , ") == ["node"]


# --- _route_label -----------------------------------------------


class TestRouteLabel:
    def test_none(self) -> None:
        assert zc._route_label(None, {}) == zc.DASH

    def test_no_repeaters(self) -> None:
        assert zc._route_label({"repeaters": []}, {}) == zc.DASH

    def test_repeater_resolves_to_device_name(self) -> None:
        node_to_ha = {
            50: zc.NodeHaInfo(
                device_name="Hallway Switch", area_name="", stat_entities={}
            ),
        }
        assert (
            zc._route_label({"repeaters": [50]}, node_to_ha) == "Hallway Switch"
        )

    def test_repeater_falls_back_to_node_label(self) -> None:
        # Unknown node id -> "node N".
        assert zc._route_label({"repeaters": [99]}, {}) == "node 99"

    def test_multiple_hops_shows_count(self) -> None:
        node_to_ha = {
            50: zc.NodeHaInfo(
                device_name="Repeater A", area_name="", stat_entities={}
            ),
        }
        assert (
            zc._route_label({"repeaters": [50, 17, 13]}, node_to_ha)
            == "Repeater A (+2)"
        )


# --- _state_at_or_before ----------------------------------------


def _hist(times: list[tuple[str, str]]) -> list[zc.HaState]:
    """Build a minimal HA history payload.

    Each ``(timestamp, state)`` pair becomes a row. Sorted
    chronologically as HA returns them.
    """
    return [{"last_changed": t, "state": s} for t, s in times]


class TestStateAtOrBefore:
    def test_empty_history(self) -> None:
        assert zc._state_at_or_before([], datetime.now(UTC)) is None

    def test_returns_last_state_before_target(self) -> None:
        hist = _hist(
            [
                ("2026-04-01T00:00:00+00:00", "-70"),
                ("2026-04-05T00:00:00+00:00", "-80"),
                ("2026-04-10T00:00:00+00:00", "-90"),
            ],
        )
        target = datetime(2026, 4, 7, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) == "-80"

    def test_target_before_any_reading(self) -> None:
        hist = _hist([("2026-04-10T00:00:00+00:00", "-70")])
        target = datetime(2026, 4, 1, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) is None

    def test_skips_unavailable_states(self) -> None:
        hist = _hist(
            [
                ("2026-04-01T00:00:00+00:00", "-70"),
                ("2026-04-02T00:00:00+00:00", "unavailable"),
                ("2026-04-03T00:00:00+00:00", "unknown"),
            ],
        )
        target = datetime(2026, 4, 5, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) == "-70"

    def test_zulu_timestamp_parses(self) -> None:
        hist = _hist([("2026-04-01T00:00:00Z", "-70")])
        target = datetime(2026, 4, 5, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) == "-70"

    def test_malformed_timestamp_skipped(self) -> None:
        hist: list[zc.HaState] = [
            {"last_changed": "not-a-timestamp", "state": "-70"},
            {"last_changed": "2026-04-01T00:00:00+00:00", "state": "-75"},
        ]
        target = datetime(2026, 4, 5, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) == "-75"

    def test_last_updated_fallback(self) -> None:
        hist: list[zc.HaState] = [
            {"last_updated": "2026-04-01T00:00:00+00:00", "state": "-70"},
        ]
        target = datetime(2026, 4, 5, tzinfo=UTC)
        assert zc._state_at_or_before(hist, target) == "-70"


# --- _read_recorder_keep_days ----------------------------------


class TestReadRecorderKeepDays:
    def test_missing_file(self, tmp_path: Path) -> None:
        with patch.object(
            zc,
            "HA_CONFIG_YAML",
            tmp_path / "does-not-exist.yaml",
        ):
            assert zc._read_recorder_keep_days() == 10

    def test_inline_block(self, tmp_path: Path) -> None:
        cfg = tmp_path / "configuration.yaml"
        cfg.write_text(
            "default_config:\n"
            "\n"
            "recorder:\n"
            "  purge_keep_days: 30\n"
            "  commit_interval: 5\n",
        )
        with patch.object(zc, "HA_CONFIG_YAML", cfg):
            assert zc._read_recorder_keep_days() == 30

    def test_include_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "configuration.yaml"
        included = tmp_path / "recorder.yaml"
        cfg.write_text("recorder: !include recorder.yaml\n")
        included.write_text("purge_keep_days: 45\ncommit_interval: 5\n")
        with patch.object(zc, "HA_CONFIG_YAML", cfg):
            assert zc._read_recorder_keep_days() == 45

    def test_include_dir_merge_named_falls_back_to_default(
        self,
        tmp_path: Path,
    ) -> None:
        # Documented limitation: !include_dir_* isn't parsed, so
        # retention silently falls back to the built-in default.
        # That's the safe direction (under-estimates rather than
        # over-estimates retention).
        cfg = tmp_path / "configuration.yaml"
        cfg.write_text("recorder: !include_dir_merge_named recorder_d\n")
        with patch.object(zc, "HA_CONFIG_YAML", cfg):
            assert zc._read_recorder_keep_days() == 10

    def test_no_recorder_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "configuration.yaml"
        cfg.write_text("default_config:\n")
        with patch.object(zc, "HA_CONFIG_YAML", cfg):
            assert zc._read_recorder_keep_days() == 10

    def test_recorder_without_purge_keep_days(self, tmp_path: Path) -> None:
        cfg = tmp_path / "configuration.yaml"
        cfg.write_text("recorder:\n  commit_interval: 5\n")
        with patch.object(zc, "HA_CONFIG_YAML", cfg):
            assert zc._read_recorder_keep_days() == 10


# --- bootstrap_venv --------------------------------------------


def _fake_venv_creator(venv_dir: Path) -> Any:
    """Build a fake ``subprocess.run`` that simulates
    ``python -m venv`` by materialising ``bin/python``.
    """

    def fake_run(*popenargs: Any, **kwargs: Any) -> None:
        args = popenargs[0] if popenargs else kwargs.get("args")
        if isinstance(args, list) and "venv" in args:
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").touch()

    return fake_run


class TestBootstrapVenv:
    """Verify the stamp-file gate.

    The stamp distinguishes a complete install from a partial
    one (venv created but pip install failed mid-way). Without
    it, a partial venv is mistaken for a working one and the
    script later crashes importing ``socketio`` inside it.
    """

    def test_fresh_install_creates_venv_and_writes_stamp(
        self,
        tmp_path: Path,
    ) -> None:
        venv_dir = tmp_path / ".venv"
        stamp = venv_dir / ".installed"
        with (
            patch.object(zc, "VENV_DIR", venv_dir),
            patch.object(zc, "VENV_STAMP", stamp),
            patch.object(
                subprocess,
                "run",
                autospec=True,
                side_effect=_fake_venv_creator(venv_dir),
            ) as mock_run,
        ):
            zc.bootstrap_venv()
        # venv create + pip install.
        assert mock_run.call_count == 2
        assert stamp.exists()

    def test_partial_venv_reinstalls_and_stamps(
        self,
        tmp_path: Path,
    ) -> None:
        # vpy exists but no stamp -> pip install must re-run.
        # This is the bug the stamp was added to fix: without it,
        # a half-built venv gets treated as ready and the script
        # crashes on the first ``import socketio``.
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").touch()
        stamp = venv_dir / ".installed"
        with (
            patch.object(zc, "VENV_DIR", venv_dir),
            patch.object(zc, "VENV_STAMP", stamp),
            patch.object(subprocess, "run", autospec=True) as mock_run,
        ):
            zc.bootstrap_venv()
        # Only pip install (no venv re-create).
        assert mock_run.call_count == 1
        cmd = mock_run.call_args[0][0]
        assert cmd[0].endswith("/pip")
        assert stamp.exists()

    def test_matching_stamp_is_noop(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").touch()
        stamp = venv_dir / ".installed"
        stamp.write_text("\n".join(zc.VENV_DEPS))
        with (
            patch.object(zc, "VENV_DIR", venv_dir),
            patch.object(zc, "VENV_STAMP", stamp),
            patch.object(subprocess, "run", autospec=True) as mock_run,
        ):
            zc.bootstrap_venv()
        mock_run.assert_not_called()

    def test_stale_stamp_reinstalls(self, tmp_path: Path) -> None:
        # A venv from an older zwavectl (fewer deps) must reinstall when
        # VENV_DEPS gains a dependency -- otherwise the stamp is present and
        # the new dep is silently never installed (an ImportError later).
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").touch()
        stamp = venv_dir / ".installed"
        stamp.write_text("aiohttp")  # an older, smaller dep set
        with (
            patch.object(zc, "VENV_DIR", venv_dir),
            patch.object(zc, "VENV_STAMP", stamp),
            patch.object(subprocess, "run", autospec=True) as mock_run,
        ):
            zc.bootstrap_venv()
        assert mock_run.call_count == 1  # pip install re-ran
        cmd = mock_run.call_args[0][0]
        assert cmd[0].endswith("/pip")
        assert stamp.read_text() == "\n".join(zc.VENV_DEPS)

    def test_venv_deps_cover_the_pipeline_yaml_import(self) -> None:
        # the param-manager views import the integration pipeline, which loads
        # the policy file with PyYAML; without it in the bootstrapped host
        # venv the command crashes with ModuleNotFoundError at import time.
        names = {
            d.lower().split("==")[0].replace("-", "") for d in zc.VENV_DEPS
        }
        assert "pyyaml" in names


# --- API key file resolution ------------------------------------


class TestApiKeyFile:
    def test_override_wins(self, tmp_path: Path) -> None:
        f = tmp_path / "k"
        f.write_text("tok")
        assert zc._resolve_api_key_file(str(f)) == f

    def test_default_then_legacy_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        default = tmp_path / "default"
        legacy = tmp_path / "legacy"
        monkeypatch.setattr(zc, "API_KEY_FILE", default)
        monkeypatch.setattr(zc, "LEGACY_API_KEY_FILE", legacy)
        # Neither present -> the default path (so a not-found error names it).
        assert zc._resolve_api_key_file("") == default
        # Only the legacy path present -> it.
        legacy.write_text("tok")
        assert zc._resolve_api_key_file("") == legacy
        # The persistent default present -> it wins over the legacy path.
        default.write_text("tok")
        assert zc._resolve_api_key_file("") == default

    def test_load_reads_and_strips(self, tmp_path: Path) -> None:
        f = tmp_path / "k"
        f.write_text("  mytoken\n")
        assert zc._load_api_key(str(f)) == "mytoken"

    def test_load_missing_prints_actionable_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(zc, "API_KEY_FILE", tmp_path / "absent")
        monkeypatch.setattr(zc, "LEGACY_API_KEY_FILE", tmp_path / "absent2")
        assert zc._load_api_key("") is None
        err = capsys.readouterr().err
        assert "API key file not found" in err
        assert "--api-key-file" in err


# --- Row / ALL_COLUMNS consistency -----------------------------


class TestRowSchema:
    def test_row_fields_match_all_columns(self) -> None:
        # The import-time sanity check in zwavectl.py
        # already enforces this, but a test gives a clearer
        # failure message if someone adds a column without a
        # matching Row field.
        from dataclasses import fields

        row_fields = {f.name for f in fields(zc.Row)}
        expected = {zc._row_attr(c) for c in zc.ALL_COLUMNS}
        assert row_fields == expected

    def test_row_attr_maps_dashes(self) -> None:
        assert zc._row_attr("rx-drop-rate") == "rx_drop_rate"
        assert zc._row_attr("node") == "node"


# --- build_node_to_ha -------------------------------------------


class TestBuildNodeToHa:
    def test_maps_zwave_device_to_node_id(self) -> None:
        devices: dict[str, zc.DeviceRow] = {
            "dev_A": {
                "id": "dev_A",
                "name": "Hallway Lock",
                "name_by_user": None,
                "area_id": "area_hallway",
                "identifiers": [["zwave_js", "1234-18-0"]],
            },
        }
        areas: dict[str, zc.AreaRow] = {
            "area_hallway": {"area_id": "area_hallway", "name": "Hall"}
        }
        entities: list[zc.EntityRow] = [
            {
                "entity_id": "sensor.hallway_lock_signal_strength",
                "device_id": "dev_A",
                "platform": "zwave_js",
            },
            {
                "entity_id": "sensor.hallway_lock_battery_level",
                "device_id": "dev_A",
                "platform": "zwave_js",
            },
            # Non-zwave_js platform should be ignored.
            {
                "entity_id": "sensor.hallway_lock_humidity",
                "device_id": "dev_A",
                "platform": "other",
            },
        ]
        out = zc.build_node_to_ha(devices, areas, entities)
        assert 18 in out
        info = out[18]
        assert info.device_name == "Hallway Lock"
        assert info.area_name == "Hall"
        assert info.stat_entities["ss"] == (
            "sensor.hallway_lock_signal_strength"
        )
        assert info.stat_entities["battery"] == (
            "sensor.hallway_lock_battery_level"
        )

    def test_prefers_name_by_user(self) -> None:
        devices: dict[str, zc.DeviceRow] = {
            "dev_A": {
                "id": "dev_A",
                "name": "Raw Device Name",
                "name_by_user": "User Friendly",
                "identifiers": [["zwave_js", "1234-7-0"]],
            },
        }
        out = zc.build_node_to_ha(devices, {}, [])
        assert out[7].device_name == "User Friendly"

    def test_skips_non_zwave_identifiers(self) -> None:
        devices: dict[str, zc.DeviceRow] = {
            "dev_A": {
                "id": "dev_A",
                "name": "Something",
                "identifiers": [["matter", "foo"]],
            },
        }
        out = zc.build_node_to_ha(devices, {}, [])
        assert out == {}

    def test_handles_unparseable_identifier(self) -> None:
        devices: dict[str, zc.DeviceRow] = {
            "dev_A": {
                "id": "dev_A",
                "name": "Something",
                "identifiers": [["zwave_js", "malformed"]],
            },
        }
        out = zc.build_node_to_ha(devices, {}, [])
        assert out == {}


# --- build_rows -------------------------------------------------


def _make_stat_entities(
    node_name: str,
    cols: list[str],
) -> dict[str, str]:
    return {col: f"sensor.{node_name}_{zc.ENTITY_SUFFIX[col]}" for col in cols}


class TestBuildRows:
    def test_skips_controller(self) -> None:
        zwave_nodes: dict[int, zc.ZwaveNode] = {
            1: {"id": 1, "protocol": 0, "isListening": True},
            18: {
                "id": 18,
                "protocol": 0,
                "isListening": True,
                "statistics": {},
            },
        }
        rows = zc.build_rows(
            zwave_nodes,
            {},
            {},
            {},
            day_offsets=[],
        )
        assert [r.node for r in rows] == [18]

    def test_basic_row_population(self) -> None:
        zwave_nodes: dict[int, zc.ZwaveNode] = {
            18: {
                "id": 18,
                "protocol": 1,  # LR
                "isListening": True,
                "manufacturer": "Kwikset",
                "productDescription": "HC620",
                "productLabel": "HC620",
                "security": "S2_AccessControl",
                "supportsBeaming": True,
                "firmwareVersion": "7.20.0",
                "sdkVersion": "7.13.8",
                "zwavePlusVersion": 2,
                "interviewStage": "Complete",
                "zwavePlusRoleType": 5,
                "maxDataRate": 100000,
                "statistics": {"lwr": {"protocolDataRate": 3}},
                "availableFirmwareUpdates": [],
            },
        }
        node_to_ha = {
            18: zc.NodeHaInfo(
                device_name="Front Door Lock",
                area_name="Entry",
                stat_entities=_make_stat_entities(
                    "front_door_lock",
                    [
                        "ss",
                        "ss-quality",  # backs onto the ss sensor
                        "rtt",
                        "rx",
                        "tx",
                        "rx-drop",
                        "tx-drop",
                        "timeouts",
                        "battery",
                        "status",
                        "last-seen",
                    ],
                ),
            ),
        }
        current_states = {
            "sensor.front_door_lock_signal_strength": "-75",
            "sensor.front_door_lock_round_trip_time": "12.5",
            "sensor.front_door_lock_successful_commands_rx": "100",
            "sensor.front_door_lock_successful_commands_tx": "95",
            "sensor.front_door_lock_commands_dropped_rx": "0",
            "sensor.front_door_lock_commands_dropped_tx": "5",
            "sensor.front_door_lock_timed_out_responses": "2",
            "sensor.front_door_lock_battery_level": "88",
            "sensor.front_door_lock_node_status": "alive",
        }
        rows = zc.build_rows(
            zwave_nodes,
            node_to_ha,
            current_states,
            {},
            day_offsets=[],
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.node == 18
        assert row.device == "Front Door Lock"
        assert row.location == "Entry"
        assert row.protocol == "LR"
        assert row.power == "Mains"
        assert row.manufacturer == "Kwikset"
        assert row.ss == -75
        # -75 on LR is "good" (LR's good_above is -80).
        assert row.ss_quality == "good"
        assert row.rtt == 12.5
        assert row.rx == 100
        assert row.tx == 95
        assert row.rx_drop == 0
        assert row.tx_drop == 5
        # tx_drop_rate = 5 / (5 + 95) = 0.05 = 5%
        assert row.tx_drop_rate == pytest.approx(0.05)
        # rx_drop_rate = 0 / (0 + 100) = 0.0
        assert row.rx_drop_rate == 0.0
        assert row.timeouts == 2
        assert row.battery == 88
        assert row.status == "alive"
        assert row.plus == "v2"
        assert row.role == 5
        assert row.firmware_dev == "7.20.0"
        assert row.firmware_sdk == "7.13.8"
        assert row.max_speed == 100000
        assert row.route_speed == 3
        assert row.update == "no"

    def test_battery_node_shows_battery_power(self) -> None:
        zwave_nodes: dict[int, zc.ZwaveNode] = {
            18: {
                "id": 18,
                "protocol": 0,
                "isListening": False,
                "statistics": {},
            },
        }
        rows = zc.build_rows(
            zwave_nodes,
            {},
            {},
            {},
            day_offsets=[],
        )
        assert rows[0].power == "Battery"
        assert rows[0].protocol == "Mesh"

    def test_historical_list_shape(self) -> None:
        # --days 2 -> list of 3 values [latest, -1d, -2d].
        zwave_nodes: dict[int, zc.ZwaveNode] = {
            18: {
                "id": 18,
                "protocol": 0,
                "isListening": True,
                "statistics": {},
            },
        }
        node_to_ha = {
            18: zc.NodeHaInfo(
                device_name="Node 18",
                area_name="",
                stat_entities={
                    "ss": "sensor.n18_signal_strength",
                    "ss-quality": "sensor.n18_signal_strength",
                },
            ),
        }
        history = {
            # -68 is "good" on Mesh (> -70); -80 is "fair" (in
            # the -70..-85 band).
            "sensor.n18_signal_strength": {1: "-68", 2: "-80"},
        }
        current_states = {"sensor.n18_signal_strength": "-65"}
        rows = zc.build_rows(
            zwave_nodes,
            node_to_ha,
            current_states,
            history,
            day_offsets=[1, 2],
        )
        assert rows[0].ss == [-65, -68, -80]
        assert rows[0].ss_quality == ["good", "good", "fair"]

    def test_routes_rendered_via_node_to_ha(self) -> None:
        zwave_nodes: dict[int, zc.ZwaveNode] = {
            18: {
                "id": 18,
                "protocol": 0,
                "isListening": True,
                "statistics": {},
                "applicationRoute": {"repeaters": [50]},
                "prioritySUCReturnRoute": {"repeaters": [50, 13]},
            },
            50: {
                "id": 50,
                "protocol": 0,
                "isListening": True,
                "statistics": {},
            },
        }
        node_to_ha = {
            50: zc.NodeHaInfo(
                device_name="Hallway",
                area_name="",
                stat_entities={},
            ),
        }
        rows_by_node = {
            r.node: r
            for r in zc.build_rows(
                zwave_nodes,
                node_to_ha,
                {},
                {},
                day_offsets=[],
            )
        }
        assert rows_by_node[18].priority_route == "Hallway"
        assert rows_by_node[18].suc_route == "Hallway (+1)"


# --- _sort_rows -------------------------------------------------


def _mk_row(**overrides: Any) -> zc.Row:
    """Construct a Row with sane defaults, override any field."""
    defaults: dict[str, Any] = {
        "node": 0,
        "device": "",
        "location": "",
        "protocol": "Mesh",
        "priority_route": "-",
        "suc_route": "-",
        "power": "Mains",
        "manufacturer": "",
        "product": "",
        "product_code": "",
        "security": "",
        "beaming": "no",
        "firmware_dev": None,
        "firmware_sdk": None,
        "plus": "no",
        "interview": "",
        "route_speed": None,
        "max_speed": None,
        "role": None,
        "update": "no",
        "neighbors": None,
        "ss": None,
        "ss_quality": None,
        "rtt": None,
        "rx": None,
        "tx": None,
        "rx_drop": None,
        "tx_drop": None,
        "rx_drop_rate": None,
        "tx_drop_rate": None,
        "timeouts": None,
        "battery": None,
        "status": None,
        "last_seen": None,
    }
    defaults.update(overrides)
    return zc.Row(**defaults)


class TestSortRows:
    def test_sort_by_node_ascending(self) -> None:
        rows = [_mk_row(node=n) for n in [18, 2, 50]]
        sorted_rows = zc._sort_rows(rows, ["node"], reverse=False)
        assert [r.node for r in sorted_rows] == [2, 18, 50]

    def test_sort_by_device_case_insensitive(self) -> None:
        rows = [
            _mk_row(node=1, device="Zigbee"),
            _mk_row(node=2, device="apple"),
            _mk_row(node=3, device="Banana"),
        ]
        sorted_rows = zc._sort_rows(rows, ["device"], reverse=False)
        assert [r.device for r in sorted_rows] == ["apple", "Banana", "Zigbee"]

    def test_null_primary_always_last(self) -> None:
        rows = [
            _mk_row(node=1, ss=-70),
            _mk_row(node=2, ss=None),
            _mk_row(node=3, ss=-85),
        ]
        # Ascending: -85, -70, then null last.
        asc = zc._sort_rows(rows, ["ss"], reverse=False)
        assert [r.node for r in asc] == [3, 1, 2]
        # Reverse: -70, -85, null still last (documented
        # invariant).
        desc = zc._sort_rows(rows, ["ss"], reverse=True)
        assert [r.node for r in desc] == [1, 3, 2]

    def test_ss_quality_severity_sort(self) -> None:
        # "--sort ss-quality" should surface poor nodes first.
        rows = [
            _mk_row(node=1, ss_quality="good"),
            _mk_row(node=2, ss_quality="poor"),
            _mk_row(node=3, ss_quality="fair"),
        ]
        out = zc._sort_rows(rows, ["ss-quality"], reverse=False)
        assert [r.node for r in out] == [2, 3, 1]

    def test_historical_list_sort_on_latest(self) -> None:
        rows = [
            _mk_row(node=1, ss=[-70, -75]),
            _mk_row(node=2, ss=[-90, -85]),
            _mk_row(node=3, ss=[-60, -65]),
        ]
        out = zc._sort_rows(rows, ["ss"], reverse=False)
        # Latest values: -60, -70, -90. Ascending sort puts
        # -90 first.
        assert [r.node for r in out] == [2, 1, 3]

    def test_neighbors_sorts_by_count(self) -> None:
        rows = [
            _mk_row(node=1, neighbors=[10, 20]),
            _mk_row(node=2, neighbors=[]),
            _mk_row(node=3, neighbors=[10, 20, 30]),
        ]
        out = zc._sort_rows(rows, ["neighbors"], reverse=False)
        assert [r.node for r in out] == [2, 1, 3]

    def test_secondary_key_tiebreaks(self) -> None:
        rows = [
            _mk_row(node=1, location="Office", device="B"),
            _mk_row(node=2, location="Office", device="A"),
            _mk_row(node=3, location="Hall", device="C"),
        ]
        out = zc._sort_rows(
            rows,
            ["location", "device"],
            reverse=False,
        )
        assert [r.node for r in out] == [3, 2, 1]


# --- _fmt_history_cell -----------------------------------------


class TestFmtHistoryCell:
    def test_scalar_latest_only(self) -> None:
        assert (
            zc._fmt_history_cell(
                -75,
                "ss",
                use_color=False,
                protocol="Mesh",
            )
            == "-75"
        )

    def test_scalar_rate(self) -> None:
        # Scalar rate cell (days=0) shows as percent int.
        out = zc._fmt_history_cell(
            0.03,
            "rx-drop-rate",
            use_color=False,
            protocol="Mesh",
        )
        assert out == "3"

    def test_list_joins_with_spaces(self) -> None:
        out = zc._fmt_history_cell(
            [-70, -75, None],
            "ss",
            use_color=False,
            protocol="Mesh",
        )
        assert out == "-70 -75 -"

    def test_list_position_widths_align(self) -> None:
        # Widths cover each sub-position; the formatter should
        # right-pad each sub-value to match.
        widths = [3, 3, 3]
        out = zc._fmt_history_cell(
            [None, -80, -85],
            "ss",
            use_color=False,
            position_widths=widths,
            protocol="Mesh",
        )
        # Each sub-value becomes 3 chars wide.
        # "  -" "-80" "-85" joined by single spaces.
        assert out == "  - -80 -85"

    def test_ss_quality_list_strings(self) -> None:
        out = zc._fmt_history_cell(
            ["poor", "fair", "good"],
            "ss-quality",
            use_color=False,
            protocol="Mesh",
        )
        assert out == "poor fair good"


# --- render_table -----------------------------------------------


class TestRenderTable:
    def test_minimal_table_has_header_and_divider(self) -> None:
        rows = [_mk_row(node=18, device="Hall Lock")]
        out = zc.render_table(
            rows,
            ["node", "device"],
            use_color=False,
        )
        lines = out.split("\n")
        assert lines[0].startswith("Node")
        assert "Device" in lines[0]
        # Divider row is just dashes and separators.
        assert all(c in "- " for c in lines[1])
        assert "18" in lines[2]
        assert "Hall Lock" in lines[2]

    def test_no_header_option(self) -> None:
        rows = [_mk_row(node=18, device="X")]
        out = zc.render_table(
            rows,
            ["node", "device"],
            use_color=False,
            show_header=False,
        )
        assert "Node" not in out
        assert "Device" not in out

    def test_empty_table_still_prints_header(self) -> None:
        out = zc.render_table(
            [],
            ["node", "device"],
            use_color=False,
        )
        lines = out.split("\n")
        assert lines[0].strip().startswith("Node")


# --- Subcommand parsing ----------------------------------------


class TestArgParser:
    def test_list_subcommand_parses_flags(self) -> None:
        args = zc.build_parser().parse_args(["list", "--cols", "node,device"])
        assert args.cmd1 == "list"
        assert args.cols == "node,device"

    def test_param_manager_mode_path(self) -> None:
        # Generic numbered levels carry the full path: cmd1 / cmd2.
        args = zc.build_parser().parse_args(["param-manager", "pending"])
        assert (args.cmd1, args.cmd2) == ("param-manager", "pending")

    def test_param_manager_rejects_unknown_mode(self) -> None:
        with pytest.raises(SystemExit):
            zc.build_parser().parse_args(["param-manager", "bogus"])

    def test_dispatch_keys_match_callbacks(self) -> None:
        # Every leaf path the parser reaches has a callback, and vice
        # versa -- a drift here is a missing or dangling entry point.
        assert set(zc.COMMAND_CALLBACKS) == {
            "list",
            "param-manager desired",
            "param-manager pending",
            "param-manager unused",
            "param-manager apply",
        }


class TestCli:
    def _argv(self, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["zwavectl", *argv])

    def _missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
        needle: str,
    ) -> None:
        # A missing subcommand exits 2 with the deepest level's full help on
        # stdout (not a terse usage error).
        self._argv(monkeypatch, argv)
        with pytest.raises(SystemExit) as exc:
            zc.cli()
        assert exc.value.code == 2
        assert needle in capsys.readouterr().out

    def test_missing_command_prints_top_help(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._missing(monkeypatch, capsys, [], "param-manager")

    def test_missing_action_prints_subcommand_help(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # ``param-manager`` with no view prints its help, which lists the
        # views (desired / pending / unused).
        self._missing(monkeypatch, capsys, ["param-manager"], "desired")

    def test_invalid_mode_is_a_usage_error_not_help(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # An INVALID subcommand is argparse's usage error on stderr, distinct
        # from the full-help path a missing subcommand takes.
        self._argv(monkeypatch, ["param-manager", "bogus"])
        with pytest.raises(SystemExit) as exc:
            zc.cli()
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_mode_dispatches_to_its_entry_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Each mode action routes to its own callback, which calls
        # _param_manager_config with that mode.
        seen: list[str] = []

        def fake(mode: str, **_kw: object) -> int:
            seen.append(mode)
            return 0

        monkeypatch.setattr(zc, "_param_manager_config", fake)
        self._argv(monkeypatch, ["param-manager", "unused"])
        assert zc.cli() == 0
        assert seen == ["unused"]


# --- Parameter Manager fleet read ------------------------------


def _pm_node_dict(node_id: int, mfr: str, model: str) -> dict[str, Any]:
    """A start_listening-shape node dict: a motion sensor with a sensitivity
    config param plus a wakeUpInterval."""
    return {
        "nodeId": node_id,
        "index": 0,
        "status": 1,
        "ready": True,
        "isListening": False,
        "isRouting": True,
        "isSecure": False,
        "name": f"node {node_id}",
        "deviceConfig": {"manufacturer": mfr, "label": model},
        "deviceClass": {
            "basic": {"key": 3, "label": "x"},
            "generic": {"key": 7, "label": "y"},
            "specific": {"key": 0, "label": "z"},
        },
        "endpoints": [{"nodeId": node_id, "index": 0}],
        "values": [
            {
                "endpoint": 0,
                "commandClass": 112,
                "commandClassName": "Configuration",
                "property": 12,
                "propertyName": "Motion Sensor Sensitivity",
                "value": 8,
                "metadata": {
                    "type": "number",
                    "label": "Motion Sensor Sensitivity",
                    "min": 0,
                    "max": 8,
                    "writeable": True,
                },
            },
            {
                "endpoint": 0,
                "commandClass": 132,
                "commandClassName": "Wake Up",
                "property": "wakeUpInterval",
                "propertyName": "Wake-up interval",
                "value": 3600,
                "metadata": {
                    "type": "number",
                    "label": "Wake-up interval",
                    "min": 0,
                    "max": 86400,
                    "writeable": True,
                },
            },
        ],
    }


class TestParamManagerFleet:
    def _registries(
        self,
    ) -> tuple[
        dict[str, zc.DeviceRow],
        list[zc.EntityRow],
        dict[str, zc.AreaRow],
        dict[str, str | None],
    ]:
        devices_by_id: dict[str, zc.DeviceRow] = {
            "devA": {
                "id": "devA",
                "identifiers": [["zwave_js", "0xc0ffee-5"]],
                "name": "Guest Bath Motion",
                "area_id": "areaA",
            }
        }
        entities: list[zc.EntityRow] = [
            {
                "platform": "zwave_js",
                "device_id": "devA",
                "entity_id": "binary_sensor.guest_bath_motion",
                "device_class": None,
                "original_device_class": None,
            },
            {
                "platform": "zwave_js",
                "device_id": "devA",
                "entity_id": "sensor.guest_bath_motion_node_status",
                "device_class": None,
                "original_device_class": None,
            },
        ]
        areas_by_id: dict[str, zc.AreaRow] = {
            "areaA": {"area_id": "areaA", "name": "Guest Bath"}
        }
        # zwave_js leaves the registry device_class unset; the state carries it.
        device_classes: dict[str, str | None] = {
            "binary_sensor.guest_bath_motion": "motion"
        }
        return devices_by_id, entities, areas_by_id, device_classes

    def test_node_contexts_maps_device_name_location_and_class(self) -> None:
        ctx = zc._node_contexts(*self._registries())
        assert ctx[5].device_id == "devA"
        assert ctx[5].name == "Guest Bath Motion"
        assert ctx[5].location == "Guest Bath"
        assert ctx[5].entities == [
            ("binary_sensor", "motion"),
            ("sensor", None),
        ]

    def test_node_contexts_captures_the_node_status_entity(self) -> None:
        # wake-last / wake-next need each node's node-status entity so the
        # fleet read can look up its last "awake" transition.
        ctx = zc._node_contexts(*self._registries())
        assert ctx[5].status_entity_id == "sensor.guest_bath_motion_node_status"

    def test_assemble_fleet_uses_shared_build_node_read(self) -> None:
        # The CLI's access layer feeds the SAME shared assembly the handler
        # does, so the resulting read matches: identity off the node,
        # device_types off the HA state device_class, context off the
        # registries.
        ctx = zc._node_contexts(*self._registries())
        fleet = zc._assemble_fleet([_pm_node_dict(5, "Zooz", "ZSE11")], ctx)
        assert len(fleet) == 1
        read = fleet[0]
        assert (read.device.node_id, read.device.model) == (5, "ZSE11")
        assert {t.name for t in read.device.device_types} == {"MOTION"}
        assert read.convergence.name == "Guest Bath Motion"
        assert read.convergence.location == "Guest Bath"
        assert read.convergence.wake_interval_seconds == 3600

    def test_assemble_fleet_threads_last_awake(self) -> None:
        # The last-awake map (fetched off the node-status history) lands on the
        # convergence device so it can drive the wake columns.
        ctx = zc._node_contexts(*self._registries())
        when = datetime(2026, 6, 9, 14, 30, tzinfo=UTC)
        fleet = zc._assemble_fleet(
            [_pm_node_dict(5, "Zooz", "ZSE11")], ctx, {5: when}
        )
        assert fleet[0].convergence.last_awake_at == when

    def test_last_awake_at_picks_the_most_recent_awake(self) -> None:
        history: list[zc.HaState] = [
            {"state": "asleep", "last_changed": "2026-06-09T10:00:00+00:00"},
            {"state": "awake", "last_changed": "2026-06-09T12:00:00+00:00"},
            {"state": "asleep", "last_changed": "2026-06-09T12:05:00+00:00"},
            {"state": "awake", "last_changed": "2026-06-09T13:00:00+00:00"},
        ]
        assert zc._last_awake_at(history) == datetime(
            2026, 6, 9, 13, 0, tzinfo=UTC
        )

    def test_last_awake_at_none_when_never_awake(self) -> None:
        history: list[zc.HaState] = [
            {"state": "asleep", "last_changed": "2026-06-09T10:00:00+00:00"},
        ]
        assert zc._last_awake_at(history) is None

    def test_wake_lookback_mirrors_the_handler_window(self) -> None:
        # The CLI derives last-awake from the HA history API over its own
        # lookback constant; the handler reads the recorder over
        # source._WAKE_LOOKBACK. The two must stay equal or the CLI and the
        # automation would disagree on which wake is "last".
        zc._ensure_integration_importable()
        from blueprint_toolkit.zwave_parameter_manager import (
            source,
        )

        assert zc._WAKE_LOOKBACK == source._WAKE_LOOKBACK

    def test_wake_columns_render_via_shared_formatting(self) -> None:
        from types import SimpleNamespace

        # The extractors import the shared zwave.formatting helpers; the fleet
        # read normally puts the package on sys.path, so do it explicitly here.
        zc._ensure_integration_importable()
        device = SimpleNamespace(
            wake_interval_seconds=3600,
            last_awake_at=datetime(2026, 6, 9, 14, 30, tzinfo=UTC),
            expected_next_wake=datetime(2026, 6, 9, 15, 30, tzinfo=UTC),
        )
        row = zc._PmRow(
            device=device,
            param=SimpleNamespace(),
            write=None,
        )
        assert zc._PM_COLUMNS["wake-interval"].extract(row) == "1 hour"
        assert zc._PM_COLUMNS["wake-last"].extract(row) == "2026-06-09 14:30"
        assert zc._PM_COLUMNS["wake-next"].extract(row) == "2026-06-09 15:30"

    def test_wake_columns_blank_when_unknown(self) -> None:
        from types import SimpleNamespace

        zc._ensure_integration_importable()
        device = SimpleNamespace(
            wake_interval_seconds=None,
            last_awake_at=None,
            expected_next_wake=None,
        )
        row = zc._PmRow(
            device=device,
            param=SimpleNamespace(),
            write=None,
        )
        assert zc._PM_COLUMNS["wake-interval"].extract(row) == ""
        assert zc._PM_COLUMNS["wake-last"].extract(row) == ""
        assert zc._PM_COLUMNS["wake-next"].extract(row) == ""

    def _seed_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Point the CLI at a temp API key + a valid one-policy config so the
        config / mapping load succeed and the flow reaches the fleet read."""
        key = tmp_path / "api-key"
        key.write_text("tok")
        monkeypatch.setattr(zc, "API_KEY_FILE", key)
        cfg = tmp_path / "zpm.yaml"
        cfg.write_text(
            "policies:\n"
            "  - name: hourly\n"
            "    match:\n"
            "      power: battery\n"
            "    settings:\n"
            "      wake_up_interval: 3600\n"
        )
        monkeypatch.setattr(zc, "PM_CONFIG_DEFAULT", cfg)

    def test_config_reports_fleet_read_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # A transport failure (3000 socket / HA API) surfaces a clear,
        # exit-coded message rather than a traceback.
        self._seed_config(monkeypatch, tmp_path)

        def boom(_api_key: str) -> list[Any]:
            raise zc._FleetReadError("connection refused")

        monkeypatch.setattr(zc, "_read_param_manager_fleet_sync", boom)
        assert zc._param_manager_config("desired") == 4
        assert "could not read the Z-Wave fleet" in capsys.readouterr().err

    def test_config_missing_policy_file_is_a_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        key = tmp_path / "api-key"
        key.write_text("tok")
        monkeypatch.setattr(zc, "API_KEY_FILE", key)
        monkeypatch.setattr(zc, "PM_CONFIG_DEFAULT", tmp_path / "absent.yaml")
        assert zc._param_manager_config("desired") == 2
        assert "Policy file not found" in capsys.readouterr().err

    def test_desired_wires_pipeline_over_an_empty_fleet(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # End-to-end over the REAL shared pipeline (load policies + the shipped
        # mapping, plan, render); an empty fleet renders just the header.
        self._seed_config(monkeypatch, tmp_path)
        monkeypatch.setattr(
            zc, "_read_param_manager_fleet_sync", lambda _api_key: []
        )
        assert zc._param_manager_config("desired") == 0
        header = capsys.readouterr().out.splitlines()[0].split()
        assert header == [
            "node",
            "device",
            "location",
            "parameter",
            "desired",
            "dev-current",
            "dev-pending",
            "policy",
        ]

    def test_pm_desired_rows_render_default_columns(self) -> None:
        from types import SimpleNamespace

        report = SimpleNamespace(
            devices=[
                SimpleNamespace(
                    device=SimpleNamespace(
                        node_id=5,
                        name="Guest Bath Motion",
                        location="Guest Bath",
                    ),
                    params=[
                        SimpleNamespace(
                            concept="motion_sensitivity",
                            concept_desired="8",
                            concept_unit="",
                            actual="4",
                            actual_unit="",
                            desired="6",
                            desired_unit="",
                        )
                    ],
                )
            ]
        )
        plan = SimpleNamespace(
            writes=[
                SimpleNamespace(
                    device=SimpleNamespace(node_id=5),
                    concept="motion_sensitivity",
                    policy="q-motion",
                    id="pid",
                )
            ]
        )
        rows = zc._pm_write_rows(report, plan, pending=False)
        row = zc._pm_write_table(rows, zc._PM_DEFAULT_COLS).splitlines()[2]
        # desired (generic 8), dev-current (device live 4), dev-pending
        # (device target 6).
        assert row.split() == [
            "5",
            "Guest",
            "Bath",
            "Motion",
            "Guest",
            "Bath",
            "motion_sensitivity",
            "8",
            "4",
            "6",
            "q-motion",
        ]

    def test_pm_pending_rows_show_current(self) -> None:
        from types import SimpleNamespace

        param = SimpleNamespace(
            concept="motion_sensitivity",
            concept_desired="8",
            concept_unit="",
            actual="4",
            actual_unit="",
            desired="6",
            desired_unit="",
        )
        report = SimpleNamespace(
            pending_devices=[
                SimpleNamespace(
                    device=SimpleNamespace(
                        node_id=5, name="Bath", location="Hall"
                    ),
                    pending_params=[param],
                )
            ]
        )
        plan = SimpleNamespace(
            writes=[
                SimpleNamespace(
                    device=SimpleNamespace(node_id=5),
                    concept="motion_sensitivity",
                    policy="q",
                    id="pid",
                )
            ]
        )
        rows = zc._pm_write_rows(report, plan, pending=True)
        lines = zc._pm_write_table(rows, zc._PM_DEFAULT_COLS).splitlines()
        assert lines[0].split() == [
            "node",
            "device",
            "location",
            "parameter",
            "desired",
            "dev-current",
            "dev-pending",
            "policy",
        ]
        # desired (generic 8), dev-current (device live 4), dev-pending
        # (device target 6).
        assert lines[2].split() == [
            "5",
            "Bath",
            "Hall",
            "motion_sensitivity",
            "8",
            "4",
            "6",
            "q",
        ]

    def test_pm_optional_columns_render(self) -> None:
        from types import SimpleNamespace

        write = SimpleNamespace(
            device=SimpleNamespace(
                node_id=5,
                manufacturer="Zooz",
                model="ZSE11",
                is_listening=False,
                device_types=["motion"],
            ),
            concept="wake_up_interval",
            policy="q",
            id=SimpleNamespace(
                command_class=112, property_=12, property_key=255
            ),
            value=14400,
        )
        report = SimpleNamespace(
            devices=[
                SimpleNamespace(
                    device=SimpleNamespace(
                        node_id=5, name="Bath", location="Hall"
                    ),
                    params=[
                        SimpleNamespace(
                            concept="wake_up_interval",
                            concept_desired="14400",
                            concept_unit="seconds",
                            actual="3600",
                            actual_unit="seconds",
                            desired="14400",
                            desired_unit="seconds",
                        )
                    ],
                )
            ]
        )
        plan = SimpleNamespace(writes=[write])
        rows = zc._pm_write_rows(report, plan, pending=False)
        cols = [
            "node",
            "make",
            "model",
            "power",
            "device-type",
            "units",
            "dev-units",
            "dev-cc",
            "dev-property",
            "dev-key",
            "dev-current",
            "dev-pending",
        ]
        row = zc._pm_write_table(rows, cols).splitlines()[2]
        assert row.split() == [
            "5",
            "Zooz",
            "ZSE11",
            "Battery",
            "motion",
            "seconds",
            "seconds",
            "112",
            "12",
            "255",
            "3600",
            "14400",
        ]

    def test_cols_rejects_an_unknown_column(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        self._seed_config(monkeypatch, tmp_path)
        assert zc._param_manager_config("desired", cols="node,bogus") == 2
        assert "unknown column(s): bogus" in capsys.readouterr().err

    def test_cols_defaults_alias_expands_inline(self) -> None:
        # `defaults,<col>` expands the default set then appends the extra,
        # de-duplicating (a default column named again is not repeated).
        cols, err = zc._pm_parse_cols(
            "defaults,device-type,node", zc._PM_DEFAULT_COLS
        )
        assert err is None
        assert cols == [*zc._PM_DEFAULT_COLS, "device-type"]

    def test_cols_all_alias_expands_to_every_column(self) -> None:
        cols, err = zc._pm_parse_cols("all", zc._PM_DEFAULT_COLS)
        assert err is None
        assert cols == list(zc._PM_COLUMNS)

    def test_cols_with_no_real_names_falls_back_to_default(self) -> None:
        # A spec that is only separators / whitespace names no columns, so it
        # falls back to the mode default rather than rendering an empty table.
        cols, err = zc._pm_parse_cols(" , ", zc._PM_DEFAULT_COLS)
        assert err is None
        assert cols == zc._PM_DEFAULT_COLS

    def test_cols_help_enumerates_every_registry_column(self) -> None:
        # The --cols help is generated from the registry, so a column added to
        # _PM_COLUMNS can never silently drift out of the help text.
        for name in zc._PM_COLUMNS:
            assert name in zc._PM_COLS_HELP

    def test_config_override_and_no_header(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        key = tmp_path / "api-key"
        key.write_text("tok")
        monkeypatch.setattr(zc, "API_KEY_FILE", key)
        cfg = tmp_path / "custom.yaml"
        cfg.write_text("policies: []\n")
        monkeypatch.setattr(
            zc, "_read_param_manager_fleet_sync", lambda _api_key: []
        )
        # --config points at the custom (empty) policy file; --no-header omits
        # the header, so an empty fleet prints nothing at all.
        assert (
            zc._param_manager_config("desired", config=str(cfg), no_header=True)
            == 0
        )
        assert capsys.readouterr().out == "\n"

    def test_pending_wires_over_an_empty_fleet(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        self._seed_config(monkeypatch, tmp_path)
        monkeypatch.setattr(
            zc, "_read_param_manager_fleet_sync", lambda _api_key: []
        )
        assert zc._param_manager_config("pending") == 0
        assert capsys.readouterr().out.splitlines()[0].split() == [
            "node",
            "device",
            "location",
            "parameter",
            "desired",
            "dev-current",
            "dev-pending",
            "policy",
        ]

    def test_unused_lists_a_policy_that_matched_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # The seeded `hourly` policy matches no device in an empty fleet, so
        # the real planner surfaces it as unused.
        self._seed_config(monkeypatch, tmp_path)
        monkeypatch.setattr(
            zc, "_read_param_manager_fleet_sync", lambda _api_key: []
        )
        assert zc._param_manager_config("unused") == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0].split() == ["policy", "parameter", "reason"]
        assert "hourly" in out

    def test_pm_unused_table_renders_named_setting_and_whole_policy(
        self,
    ) -> None:
        from types import SimpleNamespace

        plan = SimpleNamespace(
            unused=[
                SimpleNamespace(
                    policy="q-motion",
                    concept="motion_sensitivity",
                    reason="no matching parameter",
                ),
                SimpleNamespace(
                    policy="dead-policy",
                    concept=None,
                    reason="matched no devices",
                ),
            ]
        )
        lines = zc._pm_unused_table(plan).splitlines()
        # A named inert setting shows its concept; a whole inert policy "-".
        assert lines[2].split()[:2] == ["q-motion", "motion_sensitivity"]
        assert lines[3].split()[:2] == ["dead-policy", "-"]


# --- param-manager apply ---------------------------------------


def _apply_write(
    cc: int,
    prop: int | str,
    pkey: int | None,
    *,
    value: int = 8,
    node_id: int = 5,
    device_id: str | None = "dev1",
) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=SimpleNamespace(command_class=cc, property_=prop, property_key=pkey),
        device=SimpleNamespace(
            device_id=device_id, node_id=node_id, name="Hall"
        ),
        value=value,
    )


class TestApplyPayload:
    def test_config_param_uses_set_config_parameter(self) -> None:
        zc._ensure_integration_importable()
        service, data = zc._write_service_payload(
            _apply_write(112, 12, None, value=8)
        )
        assert service == "set_config_parameter"
        assert data == {
            "device_id": "dev1",
            "endpoint": 0,
            "parameter": 12,
            "value": 8,
        }

    def test_wake_interval_uses_set_value(self) -> None:
        zc._ensure_integration_importable()
        service, data = zc._write_service_payload(
            _apply_write(132, "wakeUpInterval", None, value=3600)
        )
        assert service == "set_value"
        assert data == {
            "device_id": "dev1",
            "command_class": 132,
            "endpoint": 0,
            "property": "wakeUpInterval",
            "value": 3600,
        }

    def test_partial_config_param_uses_set_value(self) -> None:
        zc._ensure_integration_importable()
        service, data = zc._write_service_payload(
            _apply_write(112, 1, 4, value=2)
        )
        assert service == "set_value"
        assert data["command_class"] == 112
        assert data["property_key"] == 4

    def test_apply_write_line(self) -> None:
        line = zc._apply_write_line(_apply_write(112, 12, None, value=8))
        assert "node 5" in line
        assert "cc112/12 = 8" in line


class TestApplyParser:
    def test_apply_parses_flags(self) -> None:
        args = zc.build_parser().parse_command(
            [
                "param-manager",
                "apply",
                "--dry-run",
                "--force",
                "--config",
                "/x.yaml",
            ]
        )
        assert args.command == "param-manager apply"
        assert args.dry_run is True
        assert args.force is True
        assert args.config == "/x.yaml"

    def test_do_pm_apply_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake(**kw: object) -> int:
            seen.update(kw)
            return 0

        monkeypatch.setattr(zc, "_param_manager_apply", fake)
        assert (
            zc.do_pm_apply(
                config="c", dry_run=True, force=False, api_key_file="k"
            )
            == 0
        )
        assert seen == {
            "config": "c",
            "dry_run": True,
            "force": False,
            "api_key_file": "k",
        }


class TestApplyFlow:
    _POLICY = (
        "policies:\n"
        "  - name: hourly\n"
        "    match:\n"
        "      power: battery\n"
        "    settings:\n"
        "      wake_up_interval: 3600\n"
    )

    def _seed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        key = tmp_path / "api-key"
        key.write_text("tok")
        monkeypatch.setattr(zc, "API_KEY_FILE", key)
        cfg = tmp_path / "zpm.yaml"
        cfg.write_text(self._POLICY)
        monkeypatch.setattr(zc, "PM_CONFIG_DEFAULT", cfg)
        monkeypatch.setattr(zc, "CONFIG_DIR", tmp_path)

    def test_missing_config_is_a_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        key = tmp_path / "api-key"
        key.write_text("tok")
        monkeypatch.setattr(zc, "API_KEY_FILE", key)
        monkeypatch.setattr(zc, "PM_CONFIG_DEFAULT", tmp_path / "absent.yaml")
        assert zc._param_manager_apply() == 2
        assert "Policy file not found" in capsys.readouterr().err

    def test_fleet_read_error_is_exit_4(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        self._seed(monkeypatch, tmp_path)

        def boom(_api_key: str) -> Any:
            raise zc._FleetReadError("connection refused")

        monkeypatch.setattr(zc, "_read_apply_inputs_sync", boom)
        assert zc._param_manager_apply() == 4
        assert "could not read the Z-Wave fleet" in capsys.readouterr().err

    def test_dry_run_issues_nothing_but_refreshes_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        self._seed(monkeypatch, tmp_path)
        monkeypatch.setattr(
            zc, "_read_apply_inputs_sync", lambda _k: ([], 42, 100, 50)
        )
        called: list[object] = []
        monkeypatch.setattr(
            zc, "_issue_writes_sync", lambda *a: called.append(a)
        )
        assert zc._param_manager_apply(dry_run=True) == 0
        assert called == []
        # The driver-session record is refreshed under CONFIG_DIR even on a
        # dry run, so a later apply sees a current last_reset_at.
        assert (tmp_path / "blueprint_toolkit" / "zwave-js-info.json").exists()

    def test_issue_path_dispatches_and_records_pending(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from types import SimpleNamespace

        self._seed(monkeypatch, tmp_path)
        zc._ensure_integration_importable()
        import blueprint_toolkit.zwave_parameter_manager.apply as ap
        import blueprint_toolkit.zwave_parameter_manager.pipeline as pl
        from blueprint_toolkit.zwave_parameter_manager import (
            pending_store,
        )
        from blueprint_toolkit.zwave_parameter_manager.logic import (
            ParamId,
        )

        write = SimpleNamespace(
            id=ParamId(132, "wakeUpInterval"),
            device=SimpleNamespace(device_id="devA", node_id=7, name="Hall"),
            value=3600,
        )
        plan = SimpleNamespace(
            writes=[write], unused=[], errors=[], warnings=[]
        )
        monkeypatch.setattr(
            pl, "plan_and_report", lambda *_a: (plan, SimpleNamespace())
        )
        decision = ap.ApplyDecision(
            writes=(write,), pending={(7, write.id): 3600}
        )
        monkeypatch.setattr(ap, "select_writes", lambda *_a: decision)
        monkeypatch.setattr(
            zc, "_read_apply_inputs_sync", lambda _k: ([], 42, 100, 50)
        )
        issued: list[object] = []
        monkeypatch.setattr(
            zc,
            "_issue_writes_sync",
            lambda _key, writes: issued.extend(writes),
        )

        assert zc._param_manager_apply() == 0
        assert issued == [write]
        state = pending_store.load(
            tmp_path / "blueprint_toolkit" / "zpm_pending.json"
        )
        assert state is not None
        assert state.commands[0].value == 3600
        assert state.commands[0].node_id == 7


# --- Code quality ----------------------------------------------

if __name__ == "__main__":
    from conftest import run_tests

    run_tests(__file__, _SCRIPT_PATH)
