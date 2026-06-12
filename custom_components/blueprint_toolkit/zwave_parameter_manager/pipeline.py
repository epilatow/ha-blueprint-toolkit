# This is AI generated code
"""Shared Z-Wave Parameter Manager pipeline.

The policy-file load, the shipped mapping load, and the plan + report
composition that both the in-process handler and the standalone ``zwavectl``
CLI run. Only the fleet ACQUISITION (the in-process driver vs the CLI's own
access layer, both behind ``source.build_node_read`` -> ``NodeRead``) and the
RENDERER (persistent notification vs table) differ between the two consumers;
the planning pipeline itself lives here so there is one of it, not two.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from . import config
from .logic import MappingTable, Plan, Policy, evaluate_policies
from .report import build_report

if TYPE_CHECKING:
    from ..zwave.convergence import ConvergenceReport
    from .source import NodeRead

# The shipped, generated concept->param mapping the resolver consumes; it
# lives in the package next to this module.
_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "mapping.json")


def load_policies(
    path: str | os.PathLike[str],
) -> tuple[tuple[Policy, ...], list[str]]:
    """Read + parse the policy YAML at ``path``.

    Returns ``(policies, error-strings)``. A missing file is NOT an error --
    it means no policies are configured yet.
    """

    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as err:
        return (), [f"could not read config file: {err}"]
    try:
        loaded = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as err:
        return (), [f"config YAML parse error: {err}"]
    parsed = config.parse_policies(loaded)
    return parsed.policies, list(parsed.errors)


def load_mapping(
    path: str | os.PathLike[str] = _MAPPING_PATH,
) -> tuple[MappingTable | None, str | None]:
    """Load + parse the shipped ``mapping.json``. Returns ``(table, error)``."""

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return None, f"could not read mapping.json: {err}"
    try:
        return MappingTable.from_dict(raw), None
    except (ValueError, KeyError, TypeError) as err:
        return None, f"invalid mapping.json: {err}"


def plan_and_report(
    reads: Sequence[NodeRead],
    policies: Sequence[Policy],
    mapping: MappingTable,
) -> tuple[Plan, ConvergenceReport]:
    """Plan ``policies`` against the fleet ``reads`` and build its convergence
    report.

    The ``Plan`` carries the writes / warnings / errors / unused; the report
    carries the per-device desired-vs-actual rows (both the device-specific
    and generic-concept views).
    """

    devices = [r.device for r in reads]
    convergence = {r.device.node_id: r.convergence for r in reads}
    actuals = {r.device.node_id: r.actuals for r in reads}
    plan = evaluate_policies(devices, list(policies), mapping)
    report = build_report(plan, convergence, actuals)
    return plan, report
