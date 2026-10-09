"""Exploratory first-ring-arc fit probe for the 260919 map_v2_fleet SIM.

Usage: python first_arc_fit_probe.py <run-dir>

Requires rec/frames.npz, rec/keep.jsonl, and log.jsonl; also accepts the two
recorder files flattened beside the log after copying them.
The predicted circle is reconstructed from the first turning ODOM pose and sent
turn_deg; each camera point is gated in the matching frame's ODOM pose. The CORE
private circle is not logged. The 45 mm local PCA direction filter and
fixed-radius least squares are an offline D-520 proxy, not the admission or
driving implementation. GT is used only for the separate oracle diagnostic and
evaluation; the 'predicted gate' rows do not use it to select or fit points.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run_dir", type=Path)
ROOT = parser.parse_args().run_dir
C = np.array([-0.3357, 0.0011])
R = 0.2514
RO = R + 0.095


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def span(points, centre):
    angle = np.sort(np.mod(np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0]), 2 * math.pi))
    if len(angle) < 2:
        return 0.0
    gap = np.diff(np.r_[angle, angle[0] + 2 * math.pi])
    return math.degrees(2 * math.pi - max(gap))


def fit_fixed_radius(points, centre):
    centre = centre.copy()
    for _ in range(5):
        delta = points - centre
        distance = np.linalg.norm(delta, axis=1)
        residual = distance - RO
        jac = -delta / distance[:, None]
        centre -= np.linalg.lstsq(jac, residual, rcond=None)[0]
    delta = points - centre
    distance = np.linalg.norm(delta, axis=1)
    jac = -delta / distance[:, None]
    singular = np.linalg.svd(jac, compute_uv=False)
    sigma_weak = 0.010 / singular[-1]
    return centre, float(np.sqrt(np.mean((distance - RO) ** 2))), sigma_weak


def oriented(points, centre):
    accepted = []
    for point in points:
        nearby = points[np.linalg.norm(points - point, axis=1) <= .045]
        if len(nearby) < 4:
            continue
        covariance = np.cov(nearby.T)
        eigenvalue, eigenvector = np.linalg.eigh(covariance)
        direction = eigenvector[:, -1]
        radial = (point - centre) / np.linalg.norm(point - centre)
        tangent = np.array([-radial[1], radial[0]])
        if abs(direction @ tangent) >= math.cos(math.radians(30)):
            accepted.append(point)
    return np.asarray(accepted).reshape(-1, 2)


test_angles = np.linspace(0, 2 * math.pi, 16, endpoint=False)
test_points = np.column_stack((RO * np.cos(test_angles), RO * np.sin(test_angles)))
test_centre, test_rms, _ = fit_fixed_radius(test_points, np.array([.01, -.02]))
assert np.linalg.norm(test_centre) < 1e-8 and test_rms < 1e-8


REC = ROOT / "rec" if (ROOT / "rec" / "frames.npz").exists() else ROOT
record = np.load(REC / "frames.npz")
stamps = record["stamp"]
gt = record["gt"]
odom = record["odom"]
keep = [json.loads(line) for line in (REC / "keep.jsonl").open()]
log = [json.loads(line) for line in (ROOT / "log.jsonl").open()]
arc = next(row for row in log if str(row.get("reason") or "").startswith("lane_arc") and row.get("gt"))
turn = next(row for row in log if row.get("reason") == "junction_turning" and row.get("gt"))
start_stamp = arc["sim_t"]
start_gt = np.array(arc["gt"])
yaw0 = wrap(turn["odom"][2] + math.radians(turn["junction"]["turn_deg"]))
centre_pred_global = np.array(arc["odom"][:2]) + R * np.array([-math.sin(yaw0), math.cos(yaw0)])
phi0 = math.atan2(start_gt[1] - C[1], start_gt[0] - C[0])
print("arc_start", round(start_stamp, 3), "gt", np.round(start_gt, 4).tolist())
print("centre_pred_odom", np.round(centre_pred_global, 4).tolist(),
      "vs_gt_map_m", round(float(np.linalg.norm(centre_pred_global-C)), 4))
print("stamp dist_m n_all n_gate span_deg rms_mm e_oracle_deg e_fit_deg weak_se10_mm n_dir span_dir rms_dir e_dir")
for frame in keep:
    stamp = frame.get("stamp")
    if not isinstance(stamp, (int, float)) or not start_stamp <= stamp <= start_stamp + 2:
        continue
    idx = int(np.argmin(np.abs(stamps - stamp)))
    if (abs(stamps[idx] - stamp) > .07 or not np.isfinite(gt[idx]).all()
            or not np.isfinite(odom[idx]).all() or abs(odom[idx, 5] - stamp) > .03):
        continue
    x, y, yaw = gt[idx]
    phi = math.atan2(y - C[1], x - C[0])
    along = R * wrap(phi - phi0)
    if along > .10:
        break
    rot = np.array([[math.cos(yaw), math.sin(yaw)], [-math.sin(yaw), math.cos(yaw)]])
    centre_true = rot @ (C - np.array([x, y]))
    points = np.asarray(frame.get("paint_points_m", []), dtype=float).reshape(-1, 2)
    if len(points) == 0:
        print(round(stamp, 3), round(along, 3), 0)
        continue
    mask = np.abs(np.linalg.norm(points - centre_true, axis=1) - RO) <= .06
    selected = points[mask]
    oracle = math.degrees(wrap(yaw - (phi + math.pi / 2)))
    if len(selected) < 3:
        print(round(stamp, 3), round(along, 3), len(points), len(selected), "--", "--", round(oracle, 1))
    else:
        centre_fit, rms, se = fit_fixed_radius(selected, centre_true)
        tangent_fit = math.atan2(-centre_fit[1], -centre_fit[0]) + math.pi / 2
        efit = math.degrees(wrap(-tangent_fit))
        direction_points = oriented(selected, centre_true)
        if len(direction_points) >= 3:
            direction_centre, direction_rms, _ = fit_fixed_radius(direction_points, centre_true)
            direction_tangent = math.atan2(-direction_centre[1], -direction_centre[0]) + math.pi / 2
            direction_error = math.degrees(wrap(-direction_tangent))
            direction_report = f"{len(direction_points)} {span(direction_points, centre_true):.1f} {direction_rms*1000:.1f} {direction_error:.1f}"
        else:
            direction_report = f"{len(direction_points)} -- -- --"
        print(f"{stamp:.3f} {along:.3f} {len(points)} {len(selected)} {span(selected, centre_true):.1f} "
              f"{rms*1000:.1f} {oracle:.1f} {efit:.1f} {se*1000:.1f} {direction_report}")
    ox, oy, oyaw = odom[idx, :3]
    rot_odom = np.array([[math.cos(oyaw), math.sin(oyaw)],
                         [-math.sin(oyaw), math.cos(oyaw)]])
    centre_pred = rot_odom @ (centre_pred_global - np.array([ox, oy]))
    pred_mask = np.abs(np.linalg.norm(points - centre_pred, axis=1) - RO) <= .06
    pred_points = oriented(points[pred_mask], centre_pred)
    if len(pred_points) >= 3:
        pred_fit, pred_rms, pred_se = fit_fixed_radius(pred_points, centre_pred)
        pred_tangent = math.atan2(-pred_fit[1], -pred_fit[0]) + math.pi / 2
        pred_error = math.degrees(wrap(-pred_tangent))
        print(f"  predicted gate: n={len(pred_points)} span={span(pred_points, centre_pred):.1f} "
              f"rms={pred_rms*1000:.1f}mm e={pred_error:.1f}deg "
              f"dr={np.linalg.norm(pred_fit)-R:+.3f}m se10={pred_se*1000:.1f}mm")
    else:
        print(f"  predicted gate: n={len(pred_points)}")
