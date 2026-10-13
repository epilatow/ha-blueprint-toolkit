#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
# This is AI generated code
"""Walk a node-zwave-js device-config DB, resolve template imports,
and group parameters by command class + label.

Output is the input to the LLM mapping suggester. Each (command
class, label) carries the full per-device ``instances`` that share
that label -- manufacturer / model / range / options / description --
so the consumer can reason per device, not just per label. That
per-device fidelity is what makes scale direction visible: the
resolver assumes a higher raw value means more, and a device whose
scale runs the other way records that only in its ``description``.

Pure Python; the emitted JSON is deterministic (sorted iteration,
fixed key order) so re-running against the same DB snapshot produces
a byte-identical file.

Network access happens only on first run for a given tag, when the
script downloads the matching release tarball from GitHub Releases.
Subsequent runs reuse the local cache. With ``--devices-root``, the
script reads from an already-extracted tree and skips the network
entirely (used by tests and offline reruns).

Tag resolution: with ``--tag`` omitted and no ``--devices-root``, the
script queries the GitHub Releases API for the latest published
release. The resolved tag is recorded in the output so a downstream
consumer can verify against the same DB snapshot the suggester saw.

The zwave-js config files are JSONC (JSON + // and /* */ comments)
and heavily use ``$import`` references into ``templates/...`` files,
optionally rooted at the devices directory via ``~/``. The script
resolves both forms recursively before aggregation; without resolution
roughly half the params would be missed entirely.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

_TARBALL_URL = (
    "https://github.com/zwave-js/node-zwave-js/archive/refs/tags/{tag}.tar.gz"
)
_LATEST_RELEASE_API = (
    "https://api.github.com/repos/zwave-js/node-zwave-js/releases/latest"
)
_COMMIT_API = (
    "https://api.github.com/repos/zwave-js/node-zwave-js/commits/{tag}"
)
# paramInformation in device files is the Configuration CC surface;
# the protocol-level Wake Up value-id lives outside the device DB
# and is hardcoded by the runtime as WAKE_UP_INTERVAL_VALUE.
_CONFIGURATION_CC = 112
_DEFAULT_CACHE = Path("tmp/zwave-js-config-cache")
_DEFAULT_OUTPUT = Path("tmp/zwave_db_labels.json")
_TARBALL_DEVICES_PREFIX = ("packages", "config", "config", "devices")


def _resolve_latest_tag() -> str:
    req = urllib.request.Request(
        _LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    tag = body.get("tag_name")
    if not isinstance(tag, str):
        raise RuntimeError(  # noqa: TRY004 - API payload shape
            f"unexpected GitHub Releases payload: tag_name={tag!r}"
        )
    return tag


def _resolve_tag_commit(tag: str) -> tuple[str, str]:
    """Return ``(commit_sha, committer_date)`` for ``tag``.

    The committer date is the canonical authoritative timestamp for
    the pinned commit -- deterministic given the SHA, so downstream
    artifacts that record it stay byte-stable across re-runs that
    pull the same snapshot. ``tag`` may be a tag name or a SHA; the
    commits API resolves either.
    """

    req = urllib.request.Request(
        _COMMIT_API.format(tag=tag),
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    sha = body.get("sha")
    commit = body.get("commit", {})
    committer = commit.get("committer", {}) if isinstance(commit, dict) else {}
    date = committer.get("date") if isinstance(committer, dict) else None
    if not isinstance(sha, str) or not isinstance(date, str):
        raise RuntimeError(  # noqa: TRY004 - API payload shape
            f"unexpected GitHub commits payload for {tag!r}: "
            f"sha={sha!r} date={date!r}"
        )
    return sha, date


def _download_devices(cache_dir: Path, tag: str) -> Path:
    """Download + extract just the device-config subtree. Returns the
    path to the devices root inside the cache.

    The whole ``<tag>/`` directory appears atomically: extraction
    runs into ``<tag>.partial/``, then renames into place only after
    every file is written. An interrupted run leaves the partial dir
    behind and a re-run discards it -- the visible cache is never a
    partial tree.
    """

    tag_dir = cache_dir / tag
    devices_root = tag_dir / "devices"
    if devices_root.exists():
        return devices_root
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial_dir = cache_dir / f"{tag}.partial"
    if partial_dir.exists():
        shutil.rmtree(partial_dir)
    partial_devices = partial_dir / "devices"
    url = _TARBALL_URL.format(tag=tag)
    print(f"downloading {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=180) as resp:
        tarball_bytes = resp.read()
    partial_devices.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            parts = Path(member.name).parts
            # Tarball top-level dir is node-zwave-js-<version>; skip it.
            if len(parts) < len(_TARBALL_DEVICES_PREFIX) + 2:
                continue
            if parts[1 : 1 + len(_TARBALL_DEVICES_PREFIX)] != (
                _TARBALL_DEVICES_PREFIX
            ):
                continue
            if not member.isfile():
                continue
            rel = Path(*parts[1 + len(_TARBALL_DEVICES_PREFIX) :])
            dest = partial_devices / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            handle = tf.extractfile(member)
            if handle is None:
                continue
            dest.write_bytes(handle.read())
    partial_dir.rename(tag_dir)
    return devices_root


def _strip_jsonc(text: str) -> str:
    """Strip // line comments and /* */ block comments outside strings.

    The zwave-js config files freely mix JSON and JS-style comments;
    Python's ``json`` rejects either, so we strip them first.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            out.append(text[i : j + 1])
            i = j + 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(_strip_jsonc(text))
    if not isinstance(data, dict):
        raise ValueError(  # noqa: TRY004 - callers catch ValueError
            f"{path}: top-level must be an object"
        )
    return data


def _resolve_import_target(
    import_str: str, relative_to: Path, devices_root: Path
) -> tuple[Path, str]:
    if "#" in import_str:
        path_part, key = import_str.split("#", 1)
    else:
        path_part, key = import_str, ""
    if not path_part:
        return relative_to, key
    if path_part.startswith("~/"):
        return devices_root / path_part[2:], key
    return relative_to.parent / path_part, key


def _resolve_param(
    raw: dict[str, Any],
    relative_to: Path,
    devices_root: Path,
    template_cache: dict[Path, dict[str, Any]],
    seen: frozenset[tuple[Path, str]] | None = None,
) -> dict[str, Any]:
    """Recursively resolve ``$import`` references and merge.

    The imported entry provides the base; the calling entry's keys
    override on top (shallow merge), matching zwave-js's resolution.

    ``seen`` tracks (file, key) pairs already in the active resolution
    chain so a self-referential or mutually-recursive template breaks
    out cleanly instead of recursing until the stack runs out.
    """

    if "$import" not in raw:
        return raw
    import_str = raw["$import"]
    if not isinstance(import_str, str):
        return {k: v for k, v in raw.items() if k != "$import"}
    target_path, key = _resolve_import_target(
        import_str, relative_to, devices_root
    )
    chain_key = (target_path, key)
    if seen is not None and chain_key in seen:
        print(
            f"warning: import cycle at {target_path}#{key}, breaking",
            file=sys.stderr,
        )
        return {k: v for k, v in raw.items() if k != "$import"}
    if target_path not in template_cache:
        try:
            template_cache[target_path] = _load_jsonc(target_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(
                f"warning: failed to load template {target_path}: {exc}",
                file=sys.stderr,
            )
            template_cache[target_path] = {}
    imported_raw = template_cache[target_path].get(key)
    imported: dict[str, Any] = (
        imported_raw if isinstance(imported_raw, dict) else {}
    )
    next_seen = (seen or frozenset()) | {chain_key}
    resolved_imported = _resolve_param(
        dict(imported), target_path, devices_root, template_cache, next_seen
    )
    merged = dict(resolved_imported)
    for k, v in raw.items():
        if k == "$import":
            continue
        merged[k] = v
    return merged


def _is_device_file(path: Path) -> bool:
    return path.suffix == ".json" and "templates" not in path.parts


def _walk(
    devices_root: Path,
) -> tuple[dict[tuple[int, str], dict[str, Any]], int]:
    agg: dict[tuple[int, str], dict[str, Any]] = {}
    template_cache: dict[Path, dict[str, Any]] = {}
    devices_processed = 0
    for path in sorted(devices_root.rglob("*.json")):
        if not _is_device_file(path):
            continue
        try:
            doc = _load_jsonc(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"warning: skipping {path}: {exc}", file=sys.stderr)
            continue
        manufacturer = doc.get("manufacturer")
        model = doc.get("label")
        params = doc.get("paramInformation")
        if not isinstance(manufacturer, str) or not isinstance(model, str):
            continue
        if not isinstance(params, list):
            continue
        devices_processed += 1
        for raw in params:
            if not isinstance(raw, dict):
                continue
            resolved = _resolve_param(raw, path, devices_root, template_cache)
            label = resolved.get("label")
            if not isinstance(label, str) or not label.strip():
                continue
            _record(agg, manufacturer, model, label, resolved)
    return agg, devices_processed


def _record(
    agg: dict[tuple[int, str], dict[str, Any]],
    manufacturer: str,
    model: str,
    label: str,
    resolved: dict[str, Any],
) -> None:
    """Record one device's param under its label as a full instance.

    Each (manufacturer, model) contributes at most one instance per
    label -- a device's same-labeled params share direction, so the
    first occurrence wins. The per-instance ``min`` / ``max`` /
    ``options`` / ``description`` carry the per-device scale and the
    prose that states its direction; the resolver assumes ascending,
    so a descending device's ``description`` is the only place the
    inversion is recorded.
    """

    key = (_CONFIGURATION_CC, label)
    entry = agg.get(key)
    if entry is None:
        entry = {
            "command_class": _CONFIGURATION_CC,
            "label": label,
            "instances": {},
        }
        agg[key] = entry
    inst_key = (manufacturer, model)
    if inst_key in entry["instances"]:
        return
    options: list[dict[str, Any]] = []
    raw_opts = resolved.get("options")
    if isinstance(raw_opts, list):
        for opt in raw_opts:
            if not isinstance(opt, dict):
                continue
            val = opt.get("value")
            olabel = opt.get("label")
            if val is None or not isinstance(olabel, str):
                continue
            options.append({"value": val, "label": olabel})
    desc = resolved.get("description")
    entry["instances"][inst_key] = {
        "manufacturer": manufacturer,
        "model": model,
        "value_size": resolved.get("valueSize"),
        "min": resolved.get("minValue"),
        "max": resolved.get("maxValue"),
        "unit": resolved.get("unit"),
        "options": options,
        "description": desc if isinstance(desc, str) else None,
    }


def _cc_name(cc: int) -> str:
    return {112: "Configuration", 132: "Wake Up"}.get(cc, f"CC{cc}")


def _emit(
    agg: dict[tuple[int, str], dict[str, Any]],
    devices_processed: int,
    tag: str,
    commit_sha: str | None,
    commit_date: str | None,
) -> dict[str, Any]:
    by_cc: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (cc, _label), entry in agg.items():
        instances = sorted(
            entry["instances"].values(),
            key=lambda i: (i["manufacturer"], i["model"]),
        )
        by_cc[cc].append(
            {
                "command_class": entry["command_class"],
                "label": entry["label"],
                "device_count": len(instances),
                "instances": instances,
            }
        )
    command_classes: dict[str, dict[str, Any]] = {}
    for cc, labels in sorted(by_cc.items()):
        labels.sort(key=lambda e: (-int(e["device_count"]), str(e["label"])))
        command_classes[str(cc)] = {
            "name": _cc_name(cc),
            "label_count": len(labels),
            "labels": labels,
        }
    out: dict[str, Any] = {
        "tag": tag,
        "commit": commit_sha,
        "commit_date": commit_date,
        "extracted_at": dt.datetime.now(dt.UTC).isoformat(),
        "devices_processed": devices_processed,
        "command_classes": command_classes,
    }
    return out


def main() -> int:
    summary = (__doc__ or "").strip().split("\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument(
        "--tag",
        default=None,
        help="node-zwave-js release tag (defaults to latest).",
    )
    parser.add_argument(
        "--devices-root",
        type=Path,
        default=None,
        help=(
            "Skip download and read from this already-extracted devices/ tree."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE,
        help="Local tarball cache (default: tmp/zwave-js-config-cache).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Output JSON path (default: tmp/zwave_db_labels.json).",
    )
    args = parser.parse_args()

    commit_sha: str | None = None
    commit_date: str | None = None
    if args.devices_root is not None:
        tag = args.tag or "(local)"
        devices_root = args.devices_root
    else:
        tag = args.tag or _resolve_latest_tag()
        commit_sha, commit_date = _resolve_tag_commit(tag)
        devices_root = _download_devices(args.cache_dir, tag)
    print(f"tag: {tag}", file=sys.stderr)
    if commit_sha is not None:
        print(f"commit: {commit_sha} ({commit_date})", file=sys.stderr)
    print(f"devices_root: {devices_root}", file=sys.stderr)

    agg, devices_processed = _walk(devices_root)
    out = _emit(agg, devices_processed, tag, commit_sha, commit_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    total_labels = sum(
        cc["label_count"] for cc in out["command_classes"].values()
    )
    print(
        f"wrote {args.output}: {devices_processed} devices, "
        f"{total_labels} unique labels",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
