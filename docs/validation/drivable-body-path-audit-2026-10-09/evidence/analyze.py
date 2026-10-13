"""Read-only straight-body-path check of the earlier LiDAR proximity candidates."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "contracts/foundation"), str(ROOT / "middleware/core/services")]

from core_common.robot_body import stop_gap_m  # noqa: E402
from core_features.line_follow.clearance import body_path_gap, front_sector, scan_points  # noqa: E402

PRIOR = ROOT / "docs/validation/drivable-lidar-candidate-2026-10-08/evidence/summary.json"
SESSIONS = (("1006", "26", "082612"), ("1006", "26", "091340"),
            ("1007", "60", "143038"), ("1007", "60", "143211"))
ANCHORS = {"082612": (884, 2129), "091340": (448, 630),
           "143038": (55, 80), "143211": (55, 63, 80)}
STOP_GAP_M = stop_gap_m(0.08, margin_m=0.02, latency_s=0.15, decel_mps2=0.5)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def analyze(video_dir):
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    result = {
        "scope": "hypothetical_straight_path_proxy_not_driving_or_ground_truth",
        "prior_summary_sha256": digest(PRIOR),
        "rule": {"linear_mps": 0.08, "angular_rps": 0, "stop_gap_m": STOP_GAP_M,
                 "path_horizon_m": 0.4, "lidar_forward_deg": 180, "lidar_x_m": -0.017,
                 "body_front_x_m": 0.04205, "body_rear_x_m": -0.076,
                 "body_half_width_m": 0.05655, "body_rotation_radius_m": 0.08257,
                 "max_scan_age_s": 0.15, "min_valid_front_beam_fraction": 0.7},
        "sessions": {},
    }
    models = {}
    for day in ("1006", "1007"):
        suffix = "c" if day == "1006" else "b"
        path = ROOT / "docs/validation" / f"drivable-smoke-{day}-full-2026-10-08{suffix}" / "evidence/per_frame.jsonl"
        if digest(path) != prior["model_sources"][day]["sha256"]:
            raise ValueError(f"{day}: model rows changed since prior audit")
        models[day] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    for day, robot, session in SESSIONS:
        stem = f"teleop_rosy_{robot}_202610{day[-2:]}T{session}Z"
        scan_path = video_dir / f"{stem}.scan.npz"
        if digest(scan_path) != prior["sessions"][session]["sources"]["scan_sha256"]:
            raise ValueError(f"{session}: scan changed since prior audit")
        rows = [row for row in models[day] if row["session"] == session]
        if len(rows) != prior["sessions"][session]["frames"] or any(
                row["frame"] != i for i, row in enumerate(rows)):
            raise ValueError(f"{session}: frame mismatch")
        counts = {"usable": 0, "sector_near_030m": 0, "path_near_030m": 0,
                  "sector_near_broad_mask": 0, "path_near_broad_mask": 0,
                  "hypothetical_stop": 0}
        anchors = {}
        min_path_gap = None
        with np.load(scan_path, allow_pickle=False) as z:
            if z["ranges"].shape[0] != len(rows):
                raise ValueError(f"{session}: scan frame mismatch")
            meta = {key: float(z[key]) for key in ("angle_min", "angle_max", "range_min", "range_max")}
            for i, row in enumerate(rows):
                age = -float(z["dt"][i])
                if not math.isfinite(age) or not 0 <= age <= 0.15:
                    continue
                sample = {**meta, "ranges": z["ranges"][i].tolist()}
                sector, valid, beams = front_sector(sample, forward_deg=180)
                if not beams or valid / beams < 0.7:
                    continue
                points = scan_points(sample, forward_deg=180, max_range=0.5)
                gap = body_path_gap([(x - 0.017, y) for x, y in points],
                                    linear=0.08, angular=0, front_x_m=0.04205,
                                    rear_x_m=-0.076, half_width_m=0.05655,
                                    rotation_radius_m=0.08257, horizon_m=0.4)
                broad = row["near_drivable_fraction"] > 0.5
                sector_near = sector is not None and sector < 0.3
                path_near = gap is not None and gap < 0.3
                stop = gap is not None and gap <= STOP_GAP_M
                counts["usable"] += 1
                counts["sector_near_030m"] += sector_near
                counts["path_near_030m"] += path_near
                counts["sector_near_broad_mask"] += sector_near and broad
                counts["path_near_broad_mask"] += path_near and broad
                counts["hypothetical_stop"] += stop
                if gap is not None:
                    min_path_gap = gap if min_path_gap is None else min(min_path_gap, gap)
                if i in ANCHORS[session]:
                    anchors[str(i)] = {"sector_m": None if sector is None else round(sector, 5),
                                       "path_gap_m": None if gap is None else round(gap, 5),
                                       "valid_beams": valid, "beams": beams}
        if counts["usable"] != prior["sessions"][session]["headings"]["180"]["usable"] or counts[
                "sector_near_030m"] != prior["sessions"][session]["headings"]["180"]["near"]:
            raise ValueError(f"{session}: product sector disagrees with prior audit")
        result["sessions"][session] = {"frames": len(rows), "counts": counts,
                                       "min_observed_path_gap_m": min_path_gap, "anchors": anchors}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(analyze(args.video_dir), indent=2, sort_keys=True) + "\n", encoding="utf-8")
