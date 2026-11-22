"""Bounded loader bridging curated HF inventory/manifest and local watch receipts for /learning/canonical."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

_CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "contracts" / "learning" / "src"
if str(_CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_SRC))

from canonical_watch import read_bounded_json, scan_watch_dir, strip_paths  # noqa: E402
from rosy.contracts.learning.omx_recording_todo import (  # noqa: E402
    COLLECTION_INVENTORY_SCHEMA,
    CURATED_MANIFEST_SCHEMA,
    build_recording_todo,
    derive_inventory_from_manifest,
    validate_inventory,
)

MAX_INVENTORY_BYTES = 262144
WATCH_FILENAMES = ("recording-inventory.json", "inventory.json")


def _load_candidate(path: Path, root: Path | None) -> tuple[dict | None, str]:
    if root is not None:
        if path.is_symlink():
            return None, "invalid"
    else:
        if path.is_symlink() or path.parent.is_symlink():
            return None, "invalid"
    doc = read_bounded_json(path, max_bytes=MAX_INVENTORY_BYTES, root=root)
    if doc is None:
        return None, "invalid" if path.exists() or path.is_symlink() else "unavailable"
    schema = doc.get("schema")
    try:
        if schema == COLLECTION_INVENTORY_SCHEMA:
            return validate_inventory(doc), "configured"
        if schema == CURATED_MANIFEST_SCHEMA:
            payload_sha = hashlib.sha256(
                json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest()
            return derive_inventory_from_manifest(doc, manifest_sha256=payload_sha), "configured"
    except ValueError:
        return None, "invalid"
    return None, "invalid"


def load_recording_inventory(manifest_path: Path | None, watch_roots: dict) -> tuple[dict | None, str]:
    """Load bounded inventory/manifest JSON from explicit path or watch_roots (never follows symlinks)."""
    if manifest_path is not None:
        if not manifest_path.exists() and not manifest_path.is_symlink():
            return None, "unavailable"
        inv, state = _load_candidate(manifest_path, None)
        return inv, ("configured_manifest" if inv is not None else state)

    saw_invalid = False
    for meta in (watch_roots or {}).values():
        wroot = meta.get("path")
        if not isinstance(wroot, Path) or wroot.is_symlink() or not wroot.is_dir():
            continue
        for name in WATCH_FILENAMES:
            cand = wroot / name
            if not cand.exists() and not cand.is_symlink():
                continue
            inv, state = _load_candidate(cand, wroot)
            if inv is not None:
                return inv, "watch_root"
            if state == "invalid":
                saw_invalid = True
    return None, ("invalid" if saw_invalid else "unconfigured")


def _collect_local_receipts(watch_roots: dict) -> list[dict]:
    receipts: list[dict] = []
    for meta in (watch_roots or {}).values():
        wroot = meta.get("path")
        if not isinstance(wroot, Path):
            continue
        watched = scan_watch_dir(wroot, meta)
        for r in watched.get("gate_receipts") or []:
            goals_counts = {}
            rpath = wroot / r["name"] / "gate-receipt.json"
            full = read_bounded_json(rpath, root=wroot)
            if full and isinstance(full.get("episodes"), list):
                for ep in full["episodes"]:
                    if isinstance(ep, dict) and ep.get("verdict") == "pass" and isinstance(ep.get("goal"), str):
                        g = ep["goal"]
                        goals_counts[g] = goals_counts.get(g, 0) + 1
            if full:
                receipts.append({**r, "goal_scope": full.get("goal_scope", "h1"), "goals_passing_counts": goals_counts})
    return receipts


def build_service_todo(manifest_path: Path | None, watch_roots: dict) -> dict:
    inv, source_state = load_recording_inventory(manifest_path, watch_roots)
    receipts = _collect_local_receipts(watch_roots) if inv is not None else None
    todo = build_recording_todo(inv, local_receipts=receipts, source_state=source_state)
    return strip_paths(todo)
