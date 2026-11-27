#!/usr/bin/env python3
"""Live catalog-only object metadata publisher and post-pick CellStateGen bumper (`cell_objects_sync.py`).

D-136: Publishes compact catalog-matched JSON geometry only (no image bytes or uncatalogued entries)
from local `:8767` frames via `cell_object_view.detect_objects` to Fleet `/api/fleet/pipeline/cell-objects`.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import ssl
import time
from typing import Any
from urllib.request import Request, urlopen

SCHEMA = "rosy.cell-detected-objects.v1"
CELL_OBJECTS_ENDPOINT = "/api/fleet/pipeline/cell-objects"
DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
DEFAULT_VIEWER_URL = "http://127.0.0.1:8767"
MAX_BODY_BYTES = 65536
MAX_OBJECTS = 64
DEFAULT_CELL_ARMS: tuple[tuple[str, str, str], ...] = (
    ("cell_s", "arm_s", "arm_s_top"),
    ("cell_ab", "arm_a", "top"),
    ("cell_ab", "arm_b", "top"),
)
_CATALOG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_FLOAT_PAIR_KEYS = ("centre_mm", "centre_px")


def parse_extra_targets(raw: str | None) -> list[tuple[str, str, str | None]]:
    """Parse semicolon-separated `url|token_file|ca_file` entries without failing on missing files."""
    if not raw or not isinstance(raw, str):
        return []
    targets: list[tuple[str, str, str | None]] = []
    for chunk in raw.split(";"):
        parts = [p.strip() for p in chunk.strip().split("|")]
        url = parts[0].rstrip("/") if parts else ""
        if not url.startswith(("http://", "https://")):
            continue
        tok = ""
        if len(parts) > 1 and parts[1]:
            try:
                tok = Path(parts[1]).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                continue
        ca = parts[2] if len(parts) > 2 and parts[2] else None
        targets.append((url, tok, ca))
    return targets


def _safe_str(val: Any, max_len: int) -> str | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s or len(s) > max_len or s.lower().startswith("data:image/"):
        return None
    return s


def _safe_xy(val: Any) -> list[float] | None:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        return None
    out: list[float] = []
    for item in val:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            return None
        out.append(round(float(item), 2))
    return out


def _sanitize_object(raw: Any) -> dict[str, Any] | None:
    """Keep only schema-allowed metadata for strictly catalog-matched objects."""
    if not isinstance(raw, dict):
        return None
    cat = raw.get("catalog_id")
    if not isinstance(cat, str) or not _CATALOG_RE.fullmatch(cat) or cat.lower() == "unmatched":
        return None
    ref = raw.get("object_ref")
    site = _safe_str(raw.get("site"), 64)
    centre_mm = _safe_xy(raw.get("centre_mm"))
    if not isinstance(ref, str) or not _REF_RE.fullmatch(ref) or not site or centre_mm is None:
        return None
    if not isinstance(raw.get("pickable"), bool):
        return None
    out: dict[str, Any] = {
        "catalog_id": cat, "object_ref": ref, "site": site,
        "centre_mm": centre_mm, "pickable": raw["pickable"],
    }
    if isinstance(raw.get("bind_tol_mm"), (int, float)) and not isinstance(raw["bind_tol_mm"], bool):
        tol = float(raw["bind_tol_mm"])
        if 1.0 <= tol <= 20.0 and math.isfinite(tol):
            out["bind_tol_mm"] = round(tol, 2)
    for key, lim in (("label", 80), ("colour", 32), ("veto_reason", 160)):
        if (s := _safe_str(raw.get(key), lim)) is not None:
            out[key] = s
    for dim in ("length_mm", "width_mm"):
        val = raw.get(dim)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and 1.0 <= float(val) <= 1000.0:
            out[dim] = round(float(val), 2)
    if (cpx := _safe_xy(raw.get("centre_px"))) is not None:
        out["centre_px"] = cpx
    corners = raw.get("corners_px")
    if isinstance(corners, list) and len(corners) == 4:
        pts = [_safe_xy(pt) for pt in corners]
        if all(pt is not None for pt in pts):
            out["corners_px"] = pts
    return out


def _build_payload(det: dict[str, Any], cell_id: str, arm_id: str, default_cam: str, state_gen: int) -> dict[str, Any]:
    raw_obs = det.get("observed_at")
    observed_at = (round(float(raw_obs), 3)
                   if isinstance(raw_obs, (int, float)) and not isinstance(raw_obs, bool) and math.isfinite(float(raw_obs)) and float(raw_obs) >= 0.0
                   else round(time.time(), 3))
    raw_ttl = det.get("ttl_s")
    ttl_s = (max(1.0, min(30.0, float(raw_ttl)))
             if isinstance(raw_ttl, (int, float)) and not isinstance(raw_ttl, bool) and math.isfinite(float(raw_ttl))
             else 15.0)
    fwh = det.get("frame_wh")
    frame_wh = ([int(fwh[0]), int(fwh[1])]
                if isinstance(fwh, (list, tuple)) and len(fwh) == 2 and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in fwh)
                else [640, 480])
    seq = det.get("source_seq")
    objs = [clean for item in (det.get("objects") or []) if (clean := _sanitize_object(item)) is not None][:MAX_OBJECTS]
    return {
        "schema": SCHEMA,
        "cell_id": cell_id,
        "arm_id": arm_id,
        "camera_role": _safe_str(det.get("camera_role"), 32) or default_cam,
        "frame_wh": frame_wh,
        **({"source_seq": seq} if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0 else {}),
        "observed_at": observed_at,
        "ttl_s": round(ttl_s, 2),
        "cell_state_gen": max(0, int(state_gen)),
        "status": _safe_str(det.get("status"), 32) or "ok",
        "objects": objs,
    }


def _ssl_ctx_for(url: str, ca_file: str | None) -> ssl.SSLContext | None:
    if not url.startswith("https://"):
        return None
    if not ca_file:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))


def _post_json(base_url: str, token: str, ctx: Any, payload: dict[str, Any], urlopen_fn: Any) -> bool:
    raw = json.dumps(payload, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("cell objects payload exceeds 65536 bytes")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{base_url.rstrip('/')}{CELL_OBJECTS_ENDPOINT}", data=raw, method="POST", headers=headers)
    kw: dict[str, Any] = {"timeout": 3.0}
    if req.full_url.startswith("https://") and ctx is not None:
        kw["context"] = ctx
    with urlopen_fn(req, **kw):
        return True


def sync_cell_objects(
    base: str, token: str, ctx: Any, urlopen_fn: Any = urlopen,
    *, prep_dir: Path = DEFAULT_PREP_DIR, viewer_url: str | None = None,
    cell_arms: tuple[tuple[str, str, str], ...] | None = None,
    extra_targets: list[tuple[str, str, str | None]] | None = None,
) -> dict[str, Any]:
    """Detect catalog-only objects per configured arm and push JSON metadata to Fleet target(s)."""
    from cell_job_readiness import CellStateGen
    import cell_object_view

    prep = Path(prep_dir)
    state_gen = CellStateGen(prep / "cell-job-api" / "cell-state-gen.json").current()
    viewer = (viewer_url or os.environ.get("ROSY_CELL_VIEWER_URL") or DEFAULT_VIEWER_URL).rstrip("/")
    parsed_extras = parse_extra_targets(os.environ.get("ROSY_CELL_OBJECTS_TARGETS")) if extra_targets is None else extra_targets
    summary: dict[str, Any] = {"cell_state_gen": state_gen, "posted": 0, "arms": {}, "errors": {}}
    extra_opener = getattr(urlopen_fn, "raw_urlopen", urlopen_fn)
    targets: list[tuple[str, str, Any, Any]] = [(base.rstrip("/"), token, ctx, urlopen_fn)]
    for e_url, e_tok, e_ca in parsed_extras:
        try:
            targets.append((e_url.rstrip("/"), e_tok, _ssl_ctx_for(e_url, e_ca), extra_opener))
        except (OSError, ssl.SSLError, ValueError) as exc:
            summary["errors"][f"target@{e_url}"] = type(exc).__name__

    for cell_id, arm_id, default_cam in (cell_arms or DEFAULT_CELL_ARMS):
        try:
            det = cell_object_view.detect_objects(prep, arm_id, viewer_url=viewer, cell_state_gen=state_gen, urlopen_fn=urlopen_fn)
            if isinstance(det, dict) and det.get("status") == "config_unavailable":
                summary["arms"][arm_id] = {"status": "config_unavailable", "objects": 0}
                continue
            if not isinstance(det, dict):
                raise TypeError("detect_objects must return a dict")
            payload = _build_payload(det, cell_id, arm_id, default_cam, state_gen)
        except Exception as exc:
            summary["errors"][arm_id] = type(exc).__name__
            continue
        arm_posted = 0
        for t_url, t_tok, t_ctx, t_opener in targets:
            try:
                _post_json(t_url, t_tok, t_ctx, payload, t_opener)
                arm_posted += 1
                summary["posted"] += 1
            except Exception as exc:
                summary["errors"][f"{arm_id}@{t_url}"] = type(exc).__name__
        summary["arms"][arm_id] = {"objects": len(payload["objects"]), "posted": arm_posted}
    return summary


def bump_state_gen_after_pick(prep_dir: Path, *, arm_id: str, placed: bool, task_id: str = "") -> int | None:
    """Advance shared CellStateGen after a verified pick placement so prior object bindings expire."""
    if not placed:
        return None
    from cell_job_readiness import CellStateGen
    return CellStateGen(Path(prep_dir) / "cell-job-api" / "cell-state-gen.json").bump()
