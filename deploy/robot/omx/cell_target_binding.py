"""Bound single-object targeting contract shared by :8781, cell_job_spec, cell_auto_pick, and cell_task_exec."""
from __future__ import annotations

import math
import time
from typing import Any

from cell_job_validators import _bool, _catalog_id, _centroid_mm, _int_range, _num, _object_ref

DEFAULT_TTL_S = 15.0
MIN_TTL_S = 1.0
MAX_TTL_S = 30.0
MIN_TOL_MM = 1.0
MAX_TOL_MM = 20.0

TARGET_OPTIONAL_PARAMS = {
    "target_object_ref": _object_ref,
    "target_catalog_id": _catalog_id,
    "target_centroid_mm": _centroid_mm,
    "target_source_seq": _int_range(0, 2_147_483_647),
    "target_observed_at": _num(0.0, 1e12),
    "target_ttl_s": _num(MIN_TTL_S, MAX_TTL_S),
    "target_tolerance_mm": _num(MIN_TOL_MM, MAX_TOL_MM),
    "expected_cell_state_gen": _int_range(0, 2_147_483_647),
    "one_shot": _bool,
}
TARGET_BINDING_KEYS = frozenset(k for k in TARGET_OPTIONAL_PARAMS if k.startswith("target_"))


def check_admission(params: dict[str, Any], current_state_gen: int, *, now_fn=time.time) -> dict[str, Any] | None:
    """Reject stale cell state or expired/incomplete target bindings before starting a cell job."""
    if "expected_cell_state_gen" in params:
        try:
            exp_gen = int(params["expected_cell_state_gen"])
        except (TypeError, ValueError):
            return {"code": 400, "error_code": "TARGET_BINDING_INCOMPLETE", "error": "invalid expected_cell_state_gen"}
        if exp_gen != int(current_state_gen):
            return {
                "code": 409,
                "error_code": "STALE_CELL_STATE",
                "error": f"expected cell_state_gen {exp_gen}, current {current_state_gen}",
            }
    if not any(k in params for k in TARGET_BINDING_KEYS):
        return None
    missing = [k for k in ("target_catalog_id", "target_centroid_mm", "target_observed_at") if params.get(k) in (None, "")]
    if missing:
        return {"code": 400, "error_code": "TARGET_BINDING_INCOMPLETE", "error": f"missing target params: {', '.join(missing)}"}
    ttl = float(params.get("target_ttl_s") if params.get("target_ttl_s") is not None else DEFAULT_TTL_S)
    obs = float(params["target_observed_at"])
    age = float(now_fn()) - obs
    if not math.isfinite(ttl) or not math.isfinite(age) or age > ttl or age < -5.0:
        return {
            "code": 409,
            "error_code": "TARGET_OBSERVATION_EXPIRED",
            "error": f"target observation age {age:.2f}s outside [-5.0, {ttl:.2f}]s",
        }
    return None


def bind_tol_mm(entry: dict[str, Any], requested_tol_mm: float | None = None) -> float:
    """Width-clamped click-to-execution tolerance: 0.45 * min(dim) capped at 20 mm (13.5 mm for 30 mm containers)."""
    min_dim = min(float(entry["width_mm"]), float(entry["length_mm"]))
    cap = min(MAX_TOL_MM, max(MIN_TOL_MM, 0.45 * min_dim))
    if requested_tol_mm is not None:
        return round(max(MIN_TOL_MM, min(float(requested_tol_mm), cap)), 2)
    return round(cap, 2)


def bind_observed(
    objects: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    binding: dict[str, Any],
    source_frame: dict[str, Any] | None = None,
    *,
    now_fn=time.time,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Resolve one unique catalog-matched object matching the operator's bound target, or return a refusal code."""
    catalog_id = str(binding.get("catalog_id") or "").strip()
    if not catalog_id or catalog_id.lower() == "unmatched":
        return [], "TARGET_CATALOG_UNKNOWN", "target catalog_id is missing or unmatched"
    entry = next((e for e in catalog if isinstance(e, dict) and e.get("id") == catalog_id), None)
    if entry is None:
        return [], "TARGET_CATALOG_UNKNOWN", f"unknown catalog_id {catalog_id!r}"

    ttl = float(binding.get("ttl_s") if binding.get("ttl_s") is not None else DEFAULT_TTL_S)
    age = float(now_fn()) - float(binding["observed_at"])
    if not math.isfinite(ttl) or not math.isfinite(age) or age > ttl or age < -5.0:
        return [], "TARGET_OBSERVATION_EXPIRED", f"bound observation expired (age={age:.2f}s, ttl={ttl:.2f}s)"

    bind_seq = binding.get("source_seq")
    cur_seq = source_frame.get("source_seq") if isinstance(source_frame, dict) else None
    if bind_seq is not None and cur_seq is not None and int(cur_seq) < int(bind_seq):
        return [], "TARGET_FRAME_SEQ_REGRESSED", f"frame seq {cur_seq} precedes bound seq {bind_seq}"

    tx, ty = float(binding["centroid_mm"][0]), float(binding["centroid_mm"][1])
    tol = bind_tol_mm(entry, binding.get("tolerance_mm"))
    near = [
        o for o in objects
        if isinstance(o, dict) and o.get("matched") is True and isinstance(o.get("centre_mm"), (list, tuple)) and len(o["centre_mm"]) >= 2
        and math.hypot(float(o["centre_mm"][0]) - tx, float(o["centre_mm"][1]) - ty) <= tol
    ]
    same_cat = [o for o in near if o.get("object") == catalog_id]
    if not same_cat:
        if near:
            found_ids = ", ".join(sorted({str(o.get("object")) for o in near}))
            return [], "TARGET_CATALOG_MISMATCH", f"object near ({tx:.1f}, {ty:.1f}) mm is {found_ids}, expected {catalog_id}"
        return [], "TARGET_NOT_FOUND_OR_MOVED", f"no {catalog_id} within {tol:.1f} mm of ({tx:.1f}, {ty:.1f}) mm"
    if len(same_cat) > 1:
        return [], "TARGET_AMBIGUOUS", f"{len(same_cat)} {catalog_id} objects within {tol:.1f} mm of ({tx:.1f}, {ty:.1f}) mm"
    return [same_cat[0]], None, None


def prepare_candidates(
    objects: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    config: dict[str, Any],
    source_frame: dict[str, Any] | None,
    error: str | None,
    *,
    now_fn=time.time,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Filter `objects` down to the single bound object when `_target_binding` is active."""
    binding = config.get("_target_binding")
    if not binding or error:
        return objects, None
    matched, code, msg = bind_observed(objects, catalog, binding, source_frame, now_fn=now_fn)
    if code is not None:
        return [], {"result": f"refused: {msg}", "refusal_code": code}
    return matched, None


def append_cli_args(args: list[str], opt_checked: dict[str, Any]) -> None:
    """Append `--target-*` and `--one-shot` flags for validated `cell_job_spec` optional params."""
    if opt_checked.get("one_shot"):
        args.append("--one-shot")
    for opt, flag in (
        ("target_object_ref", "--target-object-ref"),
        ("target_catalog_id", "--target-catalog-id"),
        ("target_source_seq", "--target-source-seq"),
        ("target_observed_at", "--target-observed-at"),
        ("target_ttl_s", "--target-ttl-s"),
        ("target_tolerance_mm", "--target-tolerance-mm"),
    ):
        if opt in opt_checked:
            args += [flag, str(opt_checked[opt])]
    if "target_centroid_mm" in opt_checked:
        c = opt_checked["target_centroid_mm"]
        val = f"{c[0]},{c[1]}" if isinstance(c, (list, tuple)) else str(c)
        args += ["--target-centroid-mm", val]


def handoff_cli_args(handoff: dict[str, Any]) -> list[str]:
    """Convert `handoff['target_object']` from Fleet-R claim payload into `cell_auto_pick.py` CLI flags."""
    tgt = handoff.get("target_object") if isinstance(handoff, dict) else None
    if not isinstance(tgt, dict):
        return []
    cat_id, centroid, obs = tgt.get("catalog_id"), tgt.get("centroid_mm"), tgt.get("observed_at")
    if not cat_id or not isinstance(centroid, (list, tuple)) or len(centroid) != 2 or obs is None:
        return []
    args = [
        "--one-shot",
        "--target-catalog-id", str(cat_id),
        "--target-centroid-mm", f"{float(centroid[0])},{float(centroid[1])}",
        "--target-observed-at", str(float(obs)),
    ]
    for key, flag in (
        ("object_ref", "--target-object-ref"),
        ("source_seq", "--target-source-seq"),
        ("ttl_s", "--target-ttl-s"),
        ("tolerance_mm", "--target-tolerance-mm"),
    ):
        if tgt.get(key) is not None:
            args += [flag, str(tgt[key])]
    return args
