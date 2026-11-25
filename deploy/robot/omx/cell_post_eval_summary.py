"""Monitor-backed lateral XY summary of the post-eval visits (`cell_post_eval.lateral_summary`, moved out at the
400-line module cap; `cell_cal_eval` and `cell_calibrate` read it through `cell_post_eval`)."""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import cell_pivot_bias as cpb

import cell_attempts, cell_cal_monitor, cell_params as prm, cell_pivot  # noqa: E401


def lateral_summary(config: dict, calibration: dict | None, *, rows: list[dict[str, Any]] | None = None,
                    now_ts: float | None = None) -> dict[str, Any]:
    """Pure monitor-backed summary for `cell_cal_eval`: true only when fresh opposing-yaw visits pass."""
    params = (config or {}).get("params")
    now, max_age, tol_mm = (float(now_ts) if now_ts is not None else time.time()), float(prm.get(params, "post.max_age_s")), float(prm.get(params, "post.tol_mm"))
    if rows is None:
        rows = cell_cal_monitor.load_observations(cell_cal_monitor.monitor_path(config), arm_id=(config or {}).get("arm_id"))
    visits = [r for r in rows if r.get("source") == "visit" and (now - float(r.get("ts") or 0.0)) <= max_age]
    sites_out, cal = {}, calibration or {"sites": {}}
    for name, spec in ((config or {}).get("sites") or {}).items():
        if (spec or {}).get("tier_of"):
            continue
        rec = cell_pivot.map_record(cal, name)
        sha = cell_attempts.digest(rec) if rec else None
        matched = [r for r in visits if sha is not None and r.get("site") == name and r.get("map_sha") == sha]
        if not matched:
            continue
        latest = matched[-1]
        res = latest.get("residual_mm") or [0.0, 0.0]
        mag, lim = round(math.hypot(float(res[0]), float(res[1])), 2), max(tol_mm, 2.0 * float(latest.get("sigma_mm") or 3.0))
        if not latest.get("accepted") or not latest.get("scene_ok", True) or not latest.get("finger_ok", True):
            st = "fail"
        elif latest.get("geometry_dependent") or not latest.get("yaw_pair", True):
            st = "advisory"
        else:
            st = "pass" if mag <= lim else "fail"
        sites_out[name] = {"status": st, "residual_mm": res, "residual_mag_mm": mag, "sigma_mm": latest.get("sigma_mm"),
                           "geometry_dependent": bool(latest.get("geometry_dependent")), "n": len(matched), "map_sha": sha}
    if not sites_out:
        return {"lateral_xy_verified": False, "verdict": "unmeasured", "sites": {}, "visit_count": 0}
    statuses = [v["status"] for v in sites_out.values()]
    verdict = "fail" if "fail" in statuses else ("advisory" if "advisory" in statuses else "pass")
    return {"lateral_xy_verified": verdict == "pass", "verdict": verdict, "sites": sites_out, "visit_count": sum(v["n"] for v in sites_out.values())}


def _visit_common_shift(rows: list[dict[str, Any]], config: dict) -> tuple[bool, dict[str, Any]]:
    """Detect common-mode translation or 2D rigid/scale drift across distinct real sites in one post-eval run."""
    cfg_sites, vecs, pts_r, res_r, used_biases = (config.get("sites") or {}), {}, [], [], []
    for r in rows:
        spec = cfg_sites.get(r.get("site") or "") or {}
        if r.get("accepted") and not spec.get("tier_of") and not spec.get("map_from") and isinstance(r.get("residual_mm"), list):
            if "used_bias_mm" in r:
                used_biases.append(r["used_bias_mm"])
            v, pt = r["residual_mm"], r.get("point_m")
            if isinstance(pt, list) and len(pt) >= 2 and len(v) >= 2:
                pts_r.append(pt[:2])
                res_r.append(v[:2])
            if r.get("status") == "drift" and len(v) >= 2 and math.hypot(*v) > 0:
                vecs[f"{r.get('map_sha')}:{r['site']}"] = np.asarray(v, float)
    rigid = cpb.decompose_rigid_drift(pts_r, res_r, trans_tol_mm=float(prm.get((config or {}).get("params"), "post.tol_mm")))
    if used_biases and all(list(b) == [0.0, 0.0] for b in used_biases):
        return False, {**rigid, "global_drift": False}
    vals = list(vecs.values())
    pair_common = len(vals) >= 2 and all(
        float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) > math.cos(math.radians(45.0))
        and max(np.linalg.norm(a), np.linalg.norm(b)) <= 2.0 * min(np.linalg.norm(a), np.linalg.norm(b))
        for i, a in enumerate(vals) for b in vals[i + 1:]
    )
    return bool(pair_common or rigid.get("global_drift")), rigid
