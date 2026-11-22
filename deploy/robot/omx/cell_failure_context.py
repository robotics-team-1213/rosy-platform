#!/usr/bin/env python3
"""Stdlib-only failure context emitter, atomic store, and fence checks (D-1072)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_failure_vetoes import (  # noqa: E402,F401
    FALLBACK_VERBS,
    HOME_POSE_TOL_UNITS,
    MAX_CHAIN_DEPTH,
    MEASURED_VETO_CODES,
    build_allowed_fallback_menu,
    compute_measured_vetoes,
    redact_context,
)

SCHEMA = "rosy.omx-failure-context.v1"
MAX_BYTES = 49_152
MAX_DEPTH = 6
DEFAULT_TTL_S = 30.0
MAX_FAILURE_BUNDLES = 200
MAX_CONTROL_BUNDLES = 50
MAX_TOTAL_BYTES = 512 * 1024 * 1024

_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4", ".jsonl": "application/x-ndjson"}
_LONG_B64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]{2048,}$")


def default_bundle_root(state_dir: Path | None = None) -> Path:
    base = Path(state_dir) if state_dir is not None else Path(os.environ.get("ROSY_OMX_STATE_DIR") or (Path.home() / "rosy-omx"))
    return base / "failure-bundles"


def canonical_sha256(payload: dict[str, Any], *, omit_keys: tuple[str, ...] = ("context_sha256", "freshness")) -> str:
    filtered = {k: v for k, v in payload.items() if k not in omit_keys} if omit_keys else payload
    raw = json.dumps(filtered, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _check_depth_and_no_b64(value: Any, level: int = 0) -> None:
    if level > MAX_DEPTH:
        raise ValueError(f"JSON nested deeper than {MAX_DEPTH}")
    if isinstance(value, str):
        if "data:image/" in value.lower() or _LONG_B64_RE.fullmatch(value):
            raise ValueError("inline base64 image payloads are forbidden")
    elif isinstance(value, dict):
        for v in value.values():
            _check_depth_and_no_b64(v, level + 1)
    elif isinstance(value, list):
        for v in value:
            _check_depth_and_no_b64(v, level + 1)


def build_bundle(
    *,
    kind: str,
    arm_id: str,
    cell_id: str,
    executor_mode: str,
    correlation: dict[str, Any],
    generation: dict[str, Any],
    measurement: dict[str, Any],
    spatial: dict[str, Any],
    visual: dict[str, Any],
    history: dict[str, Any] | None = None,
    bundle_id: str | None = None,
    ttl_s: float = DEFAULT_TTL_S,
    created_at_s: float | None = None,
    monotonic_s: float | None = None,
    fallback_chain_depth: int = 0,
    has_declared_alternates: bool = False,
    dest_full_pre_motion: bool = False,
    auto_fold_armed: bool = False,
    pending_intent_present: bool = False,
) -> dict[str, Any]:
    """Assemble, redact, compute vetoes/menu, size-check, and digest-sign a bundle."""
    now = time.time() if created_at_s is None else float(created_at_s)
    mono = time.monotonic() if monotonic_s is None else float(monotonic_s)
    bid = bundle_id or f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}-{arm_id}-{kind}"
    if not _BUNDLE_ID_RE.fullmatch(bid):
        raise ValueError(f"invalid bundle_id {bid!r}")
    meas_r, spat_r = redact_context(measurement), redact_context(spatial)
    vis_in = redact_context(visual)
    vis_norm = {
        "camera_manifest": vis_in.get("camera_manifest") or {},
        "frames": list(vis_in.get("frames") or []),
        "gaps": list(vis_in.get("gaps") or []),
        "control_ref": vis_in.get("control_ref"),
        "depth_summary": vis_in.get("depth_summary"),
    }
    hist_in = redact_context(history or {})
    repeat_tripped = bool(hist_in.get("repeat_unknown_tripped"))
    vetoes = compute_measured_vetoes(meas_r, spat_r, vis_norm, pending_intent_present=pending_intent_present, repeat_unknown_tripped=repeat_tripped)
    cause = str((meas_r.get("outcome") or {}).get("attempt_cause") or "unknown")
    menu = build_allowed_fallback_menu(
        executor_mode, cause, vetoes, fallback_chain_depth=fallback_chain_depth,
        has_declared_alternates=has_declared_alternates, dest_full_pre_motion=dest_full_pre_motion, auto_fold_armed=auto_fold_armed,
    )
    bundle = {
        "schema": SCHEMA,
        "bundle_id": bid,
        "kind": kind,
        "created_at_s": now,
        "monotonic_s": mono,
        "ttl_s": float(ttl_s),
        "arm_id": arm_id,
        "cell_id": cell_id,
        "executor_mode": executor_mode,
        "correlation": redact_context(correlation),
        "generation": dict(generation),
        "measurement": meas_r,
        "spatial": spat_r,
        "visual": vis_norm,
        "history_and_constraints": {
            "recent_attempts": list(hist_in.get("recent_attempts") or []),
            "recent_decisions": list(hist_in.get("recent_decisions") or []),
            "decisions_digest": str(hist_in.get("decisions_digest") or "")[:600],
            "recent_why": list(hist_in.get("recent_why") or []),
            "repeat_unknown_count": int(hist_in.get("repeat_unknown_count") or 0),
            "repeat_unknown_tripped": repeat_tripped,
            "knowledge_sha": hist_in.get("knowledge_sha"),
            "knowledge": list(hist_in.get("knowledge") or []),
            "choices_record": dict(hist_in.get("choices_record") or {}),
            "compensation": dict(hist_in.get("compensation") or {}),
            "measured_vetoes": vetoes,
            "allowed_fallback_menu": menu,
        },
        "freshness": None,
    }
    _check_depth_and_no_b64(bundle)
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError(f"bundle exceeds {MAX_BYTES} bytes ({len(encoded)})")
    bundle["context_sha256"] = canonical_sha256(bundle)
    return bundle


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _prune(root: Path, *, pinned: set[str], max_failure: int, max_control: int, max_bytes: int) -> None:
    rows: list[tuple[float, str, str, int]] = []
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith(".") or sub.is_symlink():
            continue
        bf = sub / "bundle.json"
        if not bf.is_file():
            continue
        try:
            meta = json.loads(bf.read_text(encoding="utf-8"))
            rows.append((float(meta.get("created_at_s", 0.0)), sub.name, str(meta.get("kind", "stop")), _dir_size(sub)))
        except (OSError, ValueError):
            continue
    rows.sort()
    fail_rows = [r for r in rows if r[2] != "control"]
    ctrl_rows = [r for r in rows if r[2] == "control"]
    drop: set[str] = set()
    for r in fail_rows[: max(0, len(fail_rows) - max_failure)]:
        if r[1] not in pinned:
            drop.add(r[1])
    for r in ctrl_rows[: max(0, len(ctrl_rows) - max_control)]:
        if r[1] not in pinned:
            drop.add(r[1])
    total = sum(r[3] for r in rows if r[1] not in drop)
    for r in rows:
        if total <= max_bytes:
            break
        if r[1] not in drop and r[1] not in pinned:
            drop.add(r[1])
            total -= r[3]
    for bid in drop:
        shutil.rmtree(root / bid, ignore_errors=True)


def write_bundle(
    root: Path,
    bundle: dict[str, Any],
    assets: dict[str, bytes] | None = None,
    *,
    pinned_bundle_ids: set[str] | tuple[str, ...] = (),
    max_failure_bundles: int = MAX_FAILURE_BUNDLES,
    max_control_bundles: int = MAX_CONTROL_BUNDLES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> Path:
    """Atomically write bundle.json + SHA-verified assets, append index.jsonl, and enforce retention."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    bid = str(bundle["bundle_id"])
    if not _BUNDLE_ID_RE.fullmatch(bid):
        raise ValueError(f"invalid bundle_id {bid!r}")
    tmp = root / f".tmp-{bid}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    to_write = json.loads(json.dumps(bundle, allow_nan=False))
    try:
        asset_meta: dict[str, tuple[int, str]] = {}
        for name, data in (assets or {}).items():
            if not _SAFE_FILE_RE.fullmatch(name) or Path(name).suffix.lower() not in _MIME_TYPES:
                raise ValueError(f"unsupported asset filename {name!r}")
            (tmp / name).write_bytes(data)
            asset_meta[name] = (len(data), hashlib.sha256(data).hexdigest())
        for frame in to_write["visual"]["frames"]:
            if frame.get("file") in asset_meta:
                frame["bytes"], frame["sha256"] = asset_meta[frame["file"]]
        trace_ref = to_write["measurement"].get("trace_ref")
        if isinstance(trace_ref, dict) and trace_ref.get("file") in asset_meta:
            trace_ref["bytes"], trace_ref["sha256"] = asset_meta[trace_ref["file"]]
        _check_depth_and_no_b64(to_write)
        to_write["context_sha256"] = canonical_sha256(to_write)
        encoded = json.dumps(to_write, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError(f"bundle exceeds {MAX_BYTES} bytes")
        (tmp / "bundle.json").write_bytes(encoded)
        dest = root / bid
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tmp, dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    row = {
        "bundle_id": bid,
        "created_at_s": to_write["created_at_s"],
        "arm_id": to_write["arm_id"],
        "kind": to_write["kind"],
        "executor_mode": to_write["executor_mode"],
        "attempt_cause": (to_write["measurement"].get("outcome") or {}).get("attempt_cause"),
        "context_sha256": to_write["context_sha256"],
        "cell_state_gen": (to_write["generation"] or {}).get("cell_state_gen"),
    }
    with (root / "index.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    _prune(root, pinned=set(pinned_bundle_ids), max_failure=max_failure_bundles, max_control=max_control_bundles, max_bytes=max_total_bytes)
    return root / bid


def _bundle_dir(root: Path, bundle_id: str) -> Path:
    if not _BUNDLE_ID_RE.fullmatch(bundle_id):
        raise ValueError("invalid bundle_id")
    base = Path(root).resolve()
    target = Path(root) / bundle_id
    if target.is_symlink() or not target.is_dir() or not target.resolve().is_relative_to(base):
        raise FileNotFoundError(bundle_id)
    return target


def list_bundles(root: Path, *, arm: str | None = None, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    idx = Path(root) / "index.jsonl"
    if not idx.is_file():
        return []
    cap = max(1, min(int(limit), 100))
    items: list[dict[str, Any]] = []
    for line in reversed(idx.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if arm and row.get("arm_id") != arm:
            continue
        if kind and row.get("kind") != kind:
            continue
        if (Path(root) / str(row.get("bundle_id", "")) / "bundle.json").is_file():
            items.append(row)
        if len(items) >= cap:
            break
    return items


def load_bundle(
    root: Path,
    bundle_id: str,
    *,
    current_cell_state_gen: int | None = None,
    now_s: float | None = None,
    active_holds: tuple[str, ...] = (),
) -> dict[str, Any]:
    bdir = _bundle_dir(root, bundle_id)
    bfile = bdir / "bundle.json"
    if bfile.is_symlink() or not bfile.is_file():
        raise FileNotFoundError(bundle_id)
    data = json.loads(bfile.read_text(encoding="utf-8"))
    if data.get("context_sha256") != canonical_sha256(data):
        raise ValueError("bundle context_sha256 integrity mismatch")
    now = time.time() if now_s is None else float(now_s)
    age_s = max(0.0, now - float(data["created_at_s"]))
    bgen = int((data.get("generation") or {}).get("cell_state_gen", 0))
    cgen = bgen if current_cell_state_gen is None else int(current_cell_state_gen)
    reasons: list[str] = []
    if cgen != bgen:
        reasons.append(f"cell_state_gen advanced {bgen}->{cgen}")
    if age_s > float(data.get("ttl_s", DEFAULT_TTL_S)):
        reasons.append(f"bundle expired ({age_s:.1f}s > {data.get('ttl_s', DEFAULT_TTL_S)}s)")
    if data.get("arm_id") in active_holds:
        reasons.append(f"active hold on {data.get('arm_id')}")
    data["freshness"] = {
        "age_s": round(age_s, 3),
        "current_cell_state_gen": cgen,
        "gen_matches": cgen == bgen,
        "still_valid_for_action": len(reasons) == 0,
        "invalidated_reasons": reasons,
    }
    return data


def resolve_asset(root: Path, bundle_id: str, filename: str) -> tuple[Path, str, str]:
    """Return verified (path, mime_type, sha256) for a bundle sidecar asset; fail on traversal/symlink/tamper."""
    if not _SAFE_FILE_RE.fullmatch(filename):
        raise ValueError("invalid asset filename")
    mime = _MIME_TYPES.get(Path(filename).suffix.lower())
    if mime is None:
        raise ValueError("unsupported asset extension")
    bdir = _bundle_dir(root, bundle_id)
    bundle = load_bundle(root, bundle_id)
    declared = {f["file"]: f["sha256"] for f in bundle["visual"]["frames"] if isinstance(f, dict) and "file" in f}
    trace_ref = bundle["measurement"].get("trace_ref")
    if isinstance(trace_ref, dict) and "file" in trace_ref and "sha256" in trace_ref:
        declared[trace_ref["file"]] = trace_ref["sha256"]
    expected_sha = declared.get(filename)
    if expected_sha is None:
        raise FileNotFoundError(filename)
    asset = bdir / filename
    if asset.is_symlink() or not asset.is_file() or not asset.resolve().is_relative_to(bdir.resolve()):
        raise ValueError("unsafe asset path")
    actual_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError("asset sha256 mismatch")
    return asset, mime, actual_sha


def check_fence(
    bundle: dict[str, Any],
    *,
    expected_context_sha256: str,
    expected_cell_state_gen: int,
    current_cell_state_gen: int,
    now_s: float | None = None,
    active_holds: tuple[str, ...] = (),
    max_age_s: float | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Enforce TOCTOU freshness & digest checks; return (True, None, []) or (False, 'STALE_FAILURE_CONTEXT', reasons)."""
    reasons: list[str] = []
    if bundle.get("context_sha256") != expected_context_sha256:
        reasons.append("context_sha256 mismatch")
    bgen = int((bundle.get("generation") or {}).get("cell_state_gen", 0))
    if bgen != int(expected_cell_state_gen) or int(current_cell_state_gen) != bgen:
        reasons.append(f"cell_state_gen drift (bundle={bgen}, expected={expected_cell_state_gen}, current={current_cell_state_gen})")
    now = time.time() if now_s is None else float(now_s)
    age_s = max(0.0, now - float(bundle["created_at_s"]))
    limit = float(bundle.get("ttl_s", DEFAULT_TTL_S)) if max_age_s is None else min(float(max_age_s), float(bundle.get("ttl_s", DEFAULT_TTL_S)))
    if age_s > limit:
        reasons.append(f"stale age {age_s:.1f}s > {limit:.1f}s")
    if bundle.get("arm_id") in active_holds:
        reasons.append(f"active hold on {bundle.get('arm_id')}")
    return (True, None, []) if not reasons else (False, "STALE_FAILURE_CONTEXT", reasons)
