"""Continuous post-calibration innovation log and NIS / CUSUM drift detector (`cell_cal_monitor.py`).

Single Responsibility:
  - Append raw pre-bias innovations from runtime measurements (`learn_bias`, `cell_look`).
  - Evaluate per-(map_sha, site, arm_id) chi-square NIS and Phase-I frozen two-sided CUSUM (MAD sigma).
  - Surface advisory recalibration suggestions (`remap` vs `pivot-near`) without triggering motion (D-911).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

SCHEMA = "rosy.omx-cal-monitor.v1"
LOG_NAME = "cal-monitor.jsonl"


def monitor_path(config_or_work: dict | Path | None) -> Path | None:
    if config_or_work is None:
        return None
    if isinstance(config_or_work, dict):
        wd = config_or_work.get("work_dir")
        return Path(wd).expanduser() / LOG_NAME if wd else None
    return Path(config_or_work).expanduser() / LOG_NAME


def _finite2(vals) -> list[float] | None:
    if not isinstance(vals, (list, tuple)) or len(vals) < 2:
        return None
    x, y = float(vals[0]), float(vals[1])
    return [x, y] if (math.isfinite(x) and math.isfinite(y)) else None


def record_observation(
    config: dict | None,
    *,
    site: str,
    map_sha: str | None,
    source: str,
    raw_mm,
    residual_mm,
    sigma_mm: float = 3.0,
    accepted: bool = True,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append one compact raw innovation row (skips silently when work_dir missing or non-finite)."""
    path = monitor_path(config)
    raw = _finite2(raw_mm)
    res = _finite2(residual_mm)
    if path is None or raw is None or res is None or not math.isfinite(float(sigma_mm)):
        return None
    entry = {
        "schema": SCHEMA,
        "ts": time.time(),
        "arm_id": (config or {}).get("arm_id"),
        "site": site,
        "map_sha": map_sha,
        "source": source,
        "raw_mm": [round(raw[0], 2), round(raw[1], 2)],
        "residual_mm": [round(res[0], 2), round(res[1], 2)],
        "sigma_mm": round(max(1.0, float(sigma_mm)), 2),
        "accepted": bool(accepted),
        **({"reason": reason} if reason else {}),
        **({k: v for k, v in extra.items() if k not in ("schema", "ts", "arm_id", "site", "map_sha", "source", "raw_mm", "residual_mm", "sigma_mm", "accepted", "reason")} if extra else {}),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        return None
    return entry


def load_observations(path: Path | None, *, arm_id: str | None = None, tail: int = 2000) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and (arm_id is None or row.get("arm_id") == arm_id):
            rows.append(row)
    return rows


def _robust_axis_sigma(e: np.ndarray, floor_mm: float) -> float:
    """Pooled 1.4826*MAD per axis after 3.5*MAD Phase-I trimming, clamped to [1.0*floor, 2.0*floor]."""
    med = np.median(e, axis=0)
    mad = np.maximum(1e-6, np.median(np.abs(e - med), axis=0) * 1.4826)
    inliers = e[np.all(np.abs(e - med) <= 3.5 * mad, axis=1)] if len(e) >= 5 else e
    if len(inliers) >= 4:
        med2 = np.median(inliers, axis=0)
        mad = np.median(np.abs(inliers - med2), axis=0) * 1.4826
    pooled = float(np.sqrt(np.mean(mad ** 2))) if mad.size else floor_mm
    return min(2.0 * floor_mm, max(floor_mm, pooled))


def _ar1_inflate(x: np.ndarray) -> float:
    """AR(1) lag-1 positive autocorrelation inflation sqrt((1+rho)/(1-rho)), clipped to rho in [0, 0.9]."""
    if len(x) < 6:
        return 1.0
    xc = x - np.median(x, axis=0)
    num, den = float(np.sum(xc[:-1] * xc[1:])), float(np.sum(xc * xc))
    rho = max(0.0, min(0.9, num / den)) if den > 1e-9 else 0.0
    return math.sqrt((1.0 + rho) / max(1e-6, 1.0 - rho))


def _cusum2(e: np.ndarray, mu: np.ndarray, sigma_1d: float, k_sig: float, h_sig: float) -> dict[str, Any]:
    k, h = k_sig * sigma_1d, h_sig * sigma_1d
    sp, sn = np.zeros(2), np.zeros(2)
    peak = 0.0
    alarm = None
    for idx, row in enumerate(e):
        d = row - mu
        sp = np.maximum(0.0, sp + d - k)
        sn = np.maximum(0.0, sn - d - k)
        peak = max(peak, float(sp.max()), float(sn.max()))
        if alarm is None and (sp.max() > h or sn.max() > h):
            ax = int(np.argmax(np.maximum(sp, sn)))
            alarm = {"index": idx, "axis": "xy"[ax], "sign": "+" if sp[ax] >= sn[ax] else "-"}
    return {"peak_mm": round(peak, 2), "limit_mm": round(h, 2), "alarm": alarm is not None, "first": alarm}


def evaluate_site_series(rows: list[dict[str, Any]], params=None) -> dict[str, Any]:
    """Evaluate per-axis NIS and Phase-I frozen two-sided CUSUM on matching-map_sha rows for one site."""
    valid_res = [r for r in rows if _finite2(r.get("residual_mm")) is not None]
    n = len(rows)
    if n == 0:
        return {"n": 0, "status": "unknown", "latest_nis": None, "cusum_alarm": False, "pivot_disagrees": False, "rejected": 0}
    nis_limit = float(prm.get(params, "verify.nis_alarm"))
    k_sig = float(prm.get(params, "verify.cusum_k_sigma"))
    h_sig = float(prm.get(params, "verify.cusum_h_sigma"))
    min_n = int(prm.get(params, "verify.cusum_min_n"))

    # Stored sigma_mm is per-axis 1-sigma (mm) so NIS follows chi2(2)
    nis_vals = []
    for r in valid_res:
        res = r["residual_mm"]
        sig_1d = max(1.0, float(r.get("sigma_mm") or 3.0))
        nis_vals.append((float(res[0]) ** 2 + float(res[1]) ** 2) / (sig_1d * sig_1d))
    latest_nis = round(nis_vals[-1], 2) if nis_vals else None
    nis_alarm = (len(nis_vals) >= 3 and (sum(nis_vals[-3:]) / 3.0) > nis_limit) or (
        latest_nis is not None and latest_nis > 2.0 * nis_limit
    )

    raw_pts = [_finite2(r.get("raw_mm")) for r in rows]
    e = np.array([p for p in raw_pts if p is not None], float).reshape(-1, 2)
    cusum = shift_mm = None
    cusum_alarm = pivot_disagrees = False
    tail_mean = [round(float(v), 2) for v in np.mean(e[-min(len(e), 5):], axis=0)] if len(e) else None
    if len(e) >= min_n:
        base = e[:min_n]
        sig_1d_prior = max(1.0, float(rows[-1].get("sigma_mm") or 3.0))
        sig_1d = _robust_axis_sigma(base, sig_1d_prior) * _ar1_inflate(base)
        mu = np.median(base, axis=0)
        if len(e) > min_n:
            cusum = _cusum2(e[min_n:], mu, sig_1d, k_sig, h_sig)
            tail = np.mean(e[max(min_n, len(e) - 5):], axis=0) - mu
            shift_mm = [round(float(v), 2) for v in tail]
        else:
            cusum = {"peak_mm": 0.0, "limit_mm": round(h_sig * sig_1d, 2), "alarm": False, "first": None}
        cusum_alarm = bool(cusum["alarm"])
        res_pts = np.array([_finite2(r.get("residual_mm")) for r in valid_res[:min_n]], float).reshape(-1, 2)
        if len(res_pts) >= min_n:
            res_med = np.median(res_pts, axis=0)
            pivot_disagrees = float(np.hypot(*res_med)) / (sig_1d / math.sqrt(min_n)) > 3.0

    rejected = sum(1 for r in rows[-10:] if not r.get("accepted", True))
    alarm = nis_alarm or cusum_alarm or rejected >= 2
    status = "advisory" if (alarm or pivot_disagrees) else ("pass" if len(e) >= min_n else "unknown")
    return {
        "n": n, "rejected": rejected, "latest_nis": latest_nis, "nis_limit": nis_limit,
        "nis_alarm": nis_alarm, "cusum": cusum, "cusum_alarm": cusum_alarm,
        "pivot_disagrees": pivot_disagrees, "tail_mean_mm": tail_mean, "shift_mm": shift_mm, "status": status,
    }


def summarize(config: dict, calibration: dict | None, *, rows: list[dict] | None = None) -> dict[str, Any]:
    """Summarize active map-generation drift per site and distinguish common-mode drift from local pivot mismatch."""
    params = (config or {}).get("params")
    arm_id = (config or {}).get("arm_id")
    if rows is None:
        rows = load_observations(monitor_path(config), arm_id=arm_id)
    import cell_attempts
    import cell_pivot

    sites_out: dict[str, dict[str, Any]] = {}
    alarmed_sites: list[str] = []
    group_vecs: dict[str, np.ndarray] = {}
    cfg_sites = (config or {}).get("sites") or {}
    for name, spec in cfg_sites.items():
        rec = cell_pivot.map_record(calibration or {}, name)
        sha = cell_attempts.digest(rec) if rec else None
        matched = [r for r in rows if r.get("site") == name and sha is not None and r.get("map_sha") == sha]
        res = evaluate_site_series(matched, params)
        res["map_sha"] = sha
        sites_out[name] = res
        if res["status"] == "advisory":
            alarmed_sites.append(name)
            vec = res.get("shift_mm") if res.get("cusum_alarm") else None
            if vec is not None and not (spec or {}).get("tier_of") and not (spec or {}).get("map_from"):
                key = f"{sha}:{name}"
                group_vecs[key] = np.asarray(vec, float)

    vecs = list(group_vecs.values())
    common_dir = len(vecs) >= 2 and all(
        np.linalg.norm(a) > 0 and np.linalg.norm(b) > 0
        and float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) > math.cos(math.radians(45))
        and max(np.linalg.norm(a), np.linalg.norm(b)) <= 2.0 * min(np.linalg.norm(a), np.linalg.norm(b))
        for i, a in enumerate(vecs) for b in vecs[i + 1:]
    )
    pattern = "common" if common_dir else ("local" if alarmed_sites else "none")
    suggested = (["remap"] if pattern == "common" else []) + [
        f"pivot-near {s}" for s in alarmed_sites if pattern != "common" or sites_out[s].get("pivot_disagrees")
    ]
    return {"sites": sites_out, "alarmed_sites": alarmed_sites, "pattern": pattern, "suggested_advisory": suggested}
