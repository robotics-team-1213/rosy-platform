"""Catalog-only detected object ingestion and query routes for Fleet R cell cockpit (D-136 safe)."""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from fastapi import HTTPException, Request, Response

from fleet.server.pipeline_recovery_policy import cell_quality_key_allowed

SCHEMA = "rosy.cell-detected-objects.v1"
MAX_BODY_BYTES = 65536
MAX_OBJECTS_PER_CELL = 64
MIN_TTL_S = 1.0
MAX_TTL_S = 30.0
DEFAULT_TTL_S = 15.0
VALID_CELLS = frozenset({"cell_s", "cell_ab"})
CELL_ARMS = {"cell_s": frozenset({"arm_s"}), "cell_ab": frozenset({"arm_a", "arm_b"})}
_CATALOG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _reject_media_bytes(val: Any) -> None:
    if isinstance(val, str):
        if len(val) >= 2048 or val.strip().lower().startswith("data:image/"):
            raise ValueError("media or oversized string rejected by D-136")
        return
    if isinstance(val, float):
        if not math.isfinite(val):
            raise ValueError("non-finite number")
        return
    if isinstance(val, list):
        for item in val:
            _reject_media_bytes(item)
        return
    if isinstance(val, dict):
        for k, v in val.items():
            if not isinstance(k, str):
                raise ValueError("object keys must be strings")
            _reject_media_bytes(v)


def _finite_float(val: Any, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError("number required")
    f = float(val)
    if not math.isfinite(f):
        raise ValueError("number must be finite")
    if (lo is not None and f < lo) or (hi is not None and f > hi):
        raise ValueError("number out of range")
    return f


def _nonneg_int(val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise ValueError("non-negative integer required")
    return val


def _xy_pair(val: Any, *, lo: float | None = None, hi: float | None = None) -> list[float]:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        raise ValueError("2-element coordinate pair required")
    return [round(_finite_float(val[0], lo=lo, hi=hi), 2), round(_finite_float(val[1], lo=lo, hi=hi), 2)]


def _validate_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("object entry must be a dict")
    cat = raw.get("catalog_id")
    if not isinstance(cat, str) or not _CATALOG_RE.fullmatch(cat) or cat.lower() == "unmatched":
        raise ValueError("catalog_id must be a matched catalog identifier")
    ref = raw.get("object_ref")
    if not isinstance(ref, str) or not _REF_RE.fullmatch(ref):
        raise ValueError("invalid object_ref")
    site = raw.get("site")
    if not isinstance(site, str) or not site.strip() or len(site) > 64:
        raise ValueError("site required")
    if not isinstance(raw.get("pickable"), bool):
        raise ValueError("pickable boolean required")
    centre_mm = _xy_pair(raw.get("centre_mm"), lo=-1000.0, hi=1000.0)
    out: dict[str, Any] = {
        "catalog_id": cat,
        "object_ref": ref,
        "site": site.strip(),
        "centre_mm": centre_mm,
        "pickable": raw["pickable"],
        "bind_tol_mm": round(_finite_float(raw["bind_tol_mm"], lo=1.0, hi=20.0), 2)
        if raw.get("bind_tol_mm") is not None else 13.5,
    }
    if raw.get("label") is not None:
        if not isinstance(raw["label"], str) or len(raw["label"]) > 80:
            raise ValueError("invalid label")
        out["label"] = raw["label"]
    if raw.get("colour") is not None:
        if not isinstance(raw["colour"], str) or len(raw["colour"]) > 32:
            raise ValueError("invalid colour")
        out["colour"] = raw["colour"]
    for dim in ("length_mm", "width_mm"):
        if raw.get(dim) is not None:
            out[dim] = round(_finite_float(raw[dim], lo=1.0, hi=1000.0), 2)
    if raw.get("centre_px") is not None:
        out["centre_px"] = _xy_pair(raw["centre_px"], lo=-2000.0, hi=4096.0)
    if raw.get("corners_px") is not None:
        cpx = raw["corners_px"]
        if not isinstance(cpx, list) or len(cpx) != 4:
            raise ValueError("corners_px must contain 4 points")
        out["corners_px"] = [_xy_pair(pt, lo=-2000.0, hi=4096.0) for pt in cpx]
    if raw.get("veto_reason") is not None:
        if not isinstance(raw["veto_reason"], str) or len(raw["veto_reason"]) > 160:
            raise ValueError("invalid veto_reason")
        out["veto_reason"] = raw["veto_reason"]
    return out


def latest_cell_state_gen(app: Any, cell_id: str) -> int | None:
    """Return latest integer cell_state_gen recorded for `cell_id`, or None if never reported."""
    store = getattr(app.state, "cell_detected_objects", None) or {}
    rec = store.get(cell_id)
    if not isinstance(rec, dict):
        return None
    gen = rec.get("cell_state_gen")
    return gen if isinstance(gen, int) and not isinstance(gen, bool) else None


def install_cell_objects_routes(app, ctx) -> None:
    """Mount JSON-only catalog detected objects routes (no image bytes, D-136)."""
    read_guard = ctx.read_guard
    proposer_guard = getattr(ctx, "proposer_guard", ctx.operator_guard)
    app.state.cell_detected_objects = getattr(app.state, "cell_detected_objects", None) or {}

    @app.post("/api/fleet/pipeline/cell-objects", dependencies=proposer_guard)
    async def ingest_cell_objects(request: Request):
        raw_bytes = await request.body()
        if len(raw_bytes) > MAX_BODY_BYTES:
            raise HTTPException(413, detail={"code": "CELL_OBJECTS_PAYLOAD_TOO_LARGE"})
        try:
            body = json.loads(raw_bytes.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            _reject_media_bytes(body)
            json.dumps(body, allow_nan=False)
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_CELL_OBJECTS", "error": str(exc)[:120]}) from None

        cell_id = str(body.get("cell_id") or "").strip()
        arm_id = str(body.get("arm_id") or "").strip()
        if cell_id not in VALID_CELLS or arm_id not in CELL_ARMS[cell_id]:
            raise HTTPException(422, detail={"code": "INVALID_CELL_OBJECTS", "error": "invalid cell_id or arm_id"})
        if not cell_quality_key_allowed(app, request, cell_id):
            raise HTTPException(403, detail={"code": "CELL_OBJECTS_FORBIDDEN"})
        try:
            observed_at = _finite_float(body.get("observed_at"), lo=0.0, hi=1e12)
            ttl_s = _finite_float(body["ttl_s"], lo=MIN_TTL_S, hi=MAX_TTL_S) if body.get("ttl_s") is not None else DEFAULT_TTL_S
            source_seq = _nonneg_int(body["source_seq"]) if body.get("source_seq") is not None else None
            cell_state_gen = _nonneg_int(body["cell_state_gen"]) if body.get("cell_state_gen") is not None else 0
            fwh = body.get("frame_wh")
            frame_wh = ([_nonneg_int(fwh[0]), _nonneg_int(fwh[1])] if isinstance(fwh, list) and len(fwh) == 2 and fwh[0] > 0 and fwh[1] > 0
                        else [640, 480])
            if fwh is not None and not (isinstance(fwh, list) and len(fwh) == 2 and frame_wh[0] > 0 and frame_wh[1] > 0):
                raise ValueError("frame_wh must be 2 positive ints")
            cam_role = body.get("camera_role")
            if cam_role is not None and (not isinstance(cam_role, str) or len(cam_role) > 32):
                raise ValueError("invalid camera_role")
            raw_objs = body.get("objects")
            if not isinstance(raw_objs, list) or len(raw_objs) > MAX_OBJECTS_PER_CELL:
                raise ValueError(f"objects must be a list of at most {MAX_OBJECTS_PER_CELL} entries")
            objects = [_validate_object(item) for item in raw_objs]
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_CELL_OBJECTS", "error": str(exc)[:120]}) from None

        now_s = round(time.time(), 3)
        snap = {
            "schema": SCHEMA,
            "cell_id": cell_id,
            "arm_id": arm_id,
            "camera_role": cam_role or ("arm_s_top" if arm_id == "arm_s" else "top"),
            "frame_wh": frame_wh,
            "source_seq": source_seq,
            "observed_at": round(observed_at, 3),
            "received_at": now_s,
            "ttl_s": round(ttl_s, 2),
            "cell_state_gen": cell_state_gen,
            "status": str(body.get("status") or "ok")[:32],
            "objects": objects,
        }
        cell_entry = app.state.cell_detected_objects.setdefault(cell_id, {"by_arm": {}, "cell_state_gen": 0, "updated_at": now_s})
        cell_entry["by_arm"][arm_id] = snap
        cell_entry["cell_state_gen"] = cell_state_gen
        cell_entry["updated_at"] = now_s
        return {"ok": True, "schema": SCHEMA, "cell_id": cell_id, "arm_id": arm_id, "count": len(objects), "cell_state_gen": cell_state_gen}

    @app.get("/api/fleet/pipeline/cell-objects", dependencies=read_guard)
    async def list_cell_objects(response: Response, cell_id: str | None = None, arm_id: str | None = None):
        response.headers["Cache-Control"] = "no-store"
        now_s = time.time()
        cells_out: dict[str, Any] = {}
        by_arm_out: dict[str, Any] = {}
        for cid, entry in (app.state.cell_detected_objects or {}).items():
            if cell_id is not None and cid != cell_id:
                continue
            arms_filtered = {}
            for aid, snap in (entry.get("by_arm") or {}).items():
                if arm_id is not None and aid != arm_id:
                    continue
                age_s = round(max(0.0, now_s - float(snap.get("received_at", 0.0))), 2)
                obs_age_s = now_s - float(snap.get("observed_at", 0.0))
                ttl_s = float(snap.get("ttl_s", DEFAULT_TTL_S))
                stale = (age_s > ttl_s) or (obs_age_s > ttl_s) or (obs_age_s < -5.0)
                enriched = {**snap, "age_s": age_s, "stale": stale}
                arms_filtered[aid] = enriched
                by_arm_out[aid] = enriched
            cells_out[cid] = {
                "cell_id": cid,
                "cell_state_gen": entry.get("cell_state_gen", 0),
                "updated_at": entry.get("updated_at"),
                "arms": arms_filtered,
            }
        return {"schema": SCHEMA, "observed_at": round(now_s, 3), "cells": cells_out, "by_arm": by_arm_out}
