"""Target-object validation & CAS freshness checks for one-shot Fleet cell tasks (D-996 / D-430)."""
from __future__ import annotations

import math
import re
import time
from typing import Any

from fastapi import HTTPException

from fleet.server.pipeline.pipeline_cell_objects import MAX_TTL_S, MIN_TTL_S, DEFAULT_TTL_S, latest_cell_state_gen

ALLOWED_TARGET_KEYS = frozenset({
    "object_ref", "catalog_id", "centroid_mm", "source_seq", "observed_at",
    "ttl_s", "tolerance_mm", "expected_cell_state_gen", "site",
})
_CATALOG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _parse_finite(val: Any, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError("finite number required")
    f = float(val)
    if not math.isfinite(f):
        raise ValueError("non-finite number")
    if (lo is not None and f < lo) or (hi is not None and f > hi):
        raise ValueError("number out of range")
    return f


def validate_target_object_for_create(app: Any, cell_id: str, spec: dict[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
    """Validate nested `spec['target_object']` (closed keys, catalog-only, TTL, and `expected_cell_state_gen`)."""
    raw = spec.get("target_object")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(422, detail={"code": "INVALID_TARGET_OBJECT", "error": "target_object must be an object"})
    extra_keys = set(raw) - ALLOWED_TARGET_KEYS
    if extra_keys:
        raise HTTPException(422, detail={"code": "INVALID_TARGET_OBJECT", "error": f"unknown target_object keys: {sorted(extra_keys)}"})

    try:
        cat_id = raw.get("catalog_id")
        if not isinstance(cat_id, str) or not _CATALOG_RE.fullmatch(cat_id) or cat_id.lower() == "unmatched":
            raise ValueError("catalog_id must name a matched catalog object")
        c_raw = raw.get("centroid_mm")
        if not isinstance(c_raw, (list, tuple)) or len(c_raw) != 2:
            raise ValueError("centroid_mm requires [x_mm, y_mm]")
        centroid_mm = [round(_parse_finite(c_raw[0], lo=-1000.0, hi=1000.0), 3),
                       round(_parse_finite(c_raw[1], lo=-1000.0, hi=1000.0), 3)]
        observed_at = _parse_finite(raw.get("observed_at"), lo=0.0, hi=1e12)
        ttl_s = _parse_finite(raw["ttl_s"], lo=MIN_TTL_S, hi=MAX_TTL_S) if raw.get("ttl_s") is not None else DEFAULT_TTL_S
        out: dict[str, Any] = {
            "catalog_id": cat_id,
            "centroid_mm": centroid_mm,
            "observed_at": round(observed_at, 3),
            "ttl_s": round(ttl_s, 2),
        }
        if raw.get("object_ref") is not None:
            ref = raw["object_ref"]
            if not isinstance(ref, str) or not _REF_RE.fullmatch(ref):
                raise ValueError("invalid object_ref")
            out["object_ref"] = ref
        if raw.get("source_seq") is not None:
            seq = raw["source_seq"]
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
                raise ValueError("source_seq must be a non-negative integer")
            out["source_seq"] = seq
        if raw.get("tolerance_mm") is not None:
            out["tolerance_mm"] = round(_parse_finite(raw["tolerance_mm"], lo=1.0, hi=20.0), 2)
        if raw.get("expected_cell_state_gen") is not None:
            gen = raw["expected_cell_state_gen"]
            if isinstance(gen, bool) or not isinstance(gen, int) or gen < 0:
                raise ValueError("expected_cell_state_gen must be a non-negative integer")
            out["expected_cell_state_gen"] = gen
        if raw.get("site") is not None:
            site = raw["site"]
            if not isinstance(site, str) or not site.strip() or len(site) > 64:
                raise ValueError("invalid site")
            out["site"] = site.strip()
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": "INVALID_TARGET_OBJECT", "error": str(exc)[:120]}) from None

    now_s = time.time() if now is None else float(now)
    age = now_s - out["observed_at"]
    if age > out["ttl_s"] or age < -5.0:
        raise HTTPException(409, detail={"code": "TARGET_OBJECT_EXPIRED", "age_s": round(age, 2), "ttl_s": out["ttl_s"]})
    cur_gen = latest_cell_state_gen(app, cell_id)
    exp_gen = out.get("expected_cell_state_gen")
    if cur_gen is not None and (exp_gen is None or cur_gen != exp_gen):
        raise HTTPException(409, detail={"code": "STALE_CELL_STATE", "expected": exp_gen, "current": cur_gen})
    return out


def check_target_object_fresh(app: Any, task: dict[str, Any], *, now: float | None = None) -> tuple[bool, str | None]:
    """Re-verify TTL and latest `cell_state_gen` for a bound task at admission or claim time."""
    tgt = task.get("target_object")
    if not isinstance(tgt, dict):
        return True, None
    now_s = time.time() if now is None else float(now)
    try:
        obs = float(tgt["observed_at"])
        ttl = float(tgt.get("ttl_s") if tgt.get("ttl_s") is not None else DEFAULT_TTL_S)
    except (KeyError, TypeError, ValueError):
        return False, "TARGET_OBJECT_EXPIRED"
    age = now_s - obs
    if not math.isfinite(obs) or not math.isfinite(ttl) or age > ttl or age < -5.0:
        return False, "TARGET_OBJECT_EXPIRED"
    cur_gen = latest_cell_state_gen(app, str(task.get("cell_id") or ""))
    exp_gen = tgt.get("expected_cell_state_gen")
    if cur_gen is not None and (exp_gen is None or int(cur_gen) != int(exp_gen)):
        return False, "STALE_CELL_STATE"
    return True, None
