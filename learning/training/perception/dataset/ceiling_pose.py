"""D-563 3: ceiling marker poses (poses.jsonl from tools/capture/ceiling_poses.py, which owns the
Rosy Cam / rosy_vision side) fused with robot odometry. Learning code reads the poses only
(D-427 §2: learning does not import operations/vision).

``fuse`` (used by map_projected_drivable.py) gives each robot camera stamp a map pose: the
nearest detection within max_gap_s, carried to the stamp by the odometry's relative motion;
the stamp is unusable without a detection, without odometry, or when the detections before and
after it disagree once carried (pose/clock error). robot time = site time + clock_offset_s;
``estimate_clock_offset`` takes it from the yaw-rate cross-correlation of both series.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
for _p in (HERE,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from geometry import world_to_base, wrap  # noqa: E402

FUSE = {"max_gap_s": 1.0, "max_disagree_m": 0.05, "max_disagree_yaw": math.radians(10.0),
        "sigma_aruco_m": 0.02, "sigma_aruco_yaw": math.radians(3.0), "drift_per_m": 0.05,
        "max_reproj_m": 0.008}


def read_calibration(rec_dir, source_id="ceiling_north"):
    """(raw bytes, {"record", "frame_lens"}) from calibration.json (ceiling_record.py) or
    calibrations.json (a saved GET /api/fleet/calibrations response)."""
    rec_dir = Path(rec_dir)
    if (rec_dir / "calibration.json").is_file():
        raw = (rec_dir / "calibration.json").read_bytes()
        return raw, json.loads(raw)
    raw = (rec_dir / "calibrations.json").read_bytes()
    records = [r for r in json.loads(raw).get("calibrations", []) if r.get("source_id") == source_id]
    return raw, {"source_id": source_id, "record": records[0] if records else None, "frame_lens": None}


def _carry(det, odom_a, odom_t):
    """Detection pose moved by the odometry's relative motion from odom_a to odom_t."""
    dx, dy = world_to_base(odom_a, np.array([[odom_t[0], odom_t[1]]]))[0]
    c, s = math.cos(det[2]), math.sin(det[2])
    return det[0] + c * dx - s * dy, det[1] + s * dx + c * dy, float(wrap(det[2] + odom_t[2] - odom_a[2]))


def fuse(detections, odom, stamps, *, clock_offset_s=0.0, params=FUSE):
    """Per robot stamp: {t, x, y, yaw, usable, reason, anchor_dt, sigma_m, sigma_yaw}."""
    p = {**FUSE, **params}
    dets = sorted((d["t"] + clock_offset_s, d["x"], d["y"], d["yaw"]) for d in detections
                  if d["reproj_err"] <= p["max_reproj_m"])
    times = [d[0] for d in dets]
    out = []
    for t in stamps:
        i = int(np.searchsorted(times, t))
        near = [dets[j] for j in (i - 1, i) if 0 <= j < len(dets) and abs(dets[j][0] - t) <= p["max_gap_s"]]
        row = {"t": t, "usable": False, "reason": "no_detection"}
        odom_t = odom.at(t)
        carried = []
        for det in near:
            odom_a = odom.at(det[0])
            if odom_a is not None and odom_t is not None:
                carried.append((abs(det[0] - t), _carry(det[1:], odom_a, odom_t),
                                math.hypot(odom_t[0] - odom_a[0], odom_t[1] - odom_a[1]),
                                abs(odom_t[2] - odom_a[2])))
        if near and not carried:
            row["reason"] = "no_odom"
        elif len(carried) == 2 and (
                math.dist(carried[0][1][:2], carried[1][1][:2]) > p["max_disagree_m"]
                or abs(float(wrap(carried[0][1][2] - carried[1][1][2]))) > p["max_disagree_yaw"]):
            row["reason"] = "disagree"
        elif carried:
            dt, (x, y, yaw), moved, turned = min(carried)
            row.update(x=x, y=y, yaw=yaw, usable=True, reason=None, anchor_dt=dt,
                       sigma_m=p["sigma_aruco_m"] + p["drift_per_m"] * moved,
                       sigma_yaw=p["sigma_aruco_yaw"] + p["drift_per_m"] * turned)
        out.append(row)
    return out


def estimate_clock_offset(detections, odom, *, max_lag_s=5.0, step_s=0.05, max_reproj_m=FUSE["max_reproj_m"]):
    """robot - site clock (s): the lag that best correlates the odometry and ceiling yaw rates, or None.

    Yaw rate, not motion onset: on 2026-10-09 real drives the onset was off by 1.5 s (a nudge before
    the drive), the yaw-rate correlation agreed within 0.1 s on both sessions."""
    d = sorted((r for r in detections if r["reproj_err"] <= max_reproj_m), key=lambda r: r["t"])
    if len(d) < 10 or len(odom) < 10:
        return None
    t, yaw = np.array([r["t"] for r in d]), np.unwrap([r["yaw"] for r in d])
    grid = np.arange(max(t[0], odom.t[0]) + max_lag_s, min(t[-1], odom.t[-1]) - max_lag_s, 0.25)
    if grid.size < 20:
        return None
    a = np.abs(np.gradient(np.interp(grid, odom.t, odom.yaw), grid))
    if a.std() == 0:
        return None
    best = max((np.corrcoef(a, np.abs(np.gradient(np.interp(grid, t + lag, yaw), grid)))[0, 1], lag)
               for lag in np.arange(-max_lag_s, max_lag_s + step_s / 2, step_s))
    return None if not np.isfinite(best[0]) else round(float(best[1]), 3)


