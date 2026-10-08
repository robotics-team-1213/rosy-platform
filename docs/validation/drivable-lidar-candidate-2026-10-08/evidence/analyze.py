"""Read-only LiDAR proximity versus shadow drivable-area candidate audit."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
SESSIONS = (
    ("1006", "26", "082612", 2487),
    ("1006", "26", "091340", 642),
    ("1007", "60", "143038", 124),
    ("1007", "60", "143211", 83),
)
ANCHORS = {
    "082612": (884, 2129),
    "091340": (448, 630),
    "143038": (20, 55, 80),
    "143211": (55, 63, 80),
}


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def rows(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def analyze(video_dir):
    report = {
        "scope": "candidate_proxy_not_ground_truth",
        "rule": {
            "forward_deg": [178, 180, 182],
            "half_angle_deg": 20,
            "scan_max_age_s": 0.15,
            "min_valid_beam_fraction": 0.70,
            "near_m": 0.30,
            "broad_mask_fraction_gt": 0.50,
        },
        "sessions": {},
    }
    model_rows = {}
    for day in ("1006", "1007"):
        suffix = "c" if day == "1006" else "b"
        path = ROOT / "docs" / "validation" / f"drivable-smoke-{day}-full-2026-10-08{suffix}" / "evidence" / "per_frame.jsonl"
        model_rows[day] = rows(path)
        report.setdefault("model_sources", {})[day] = {"file": path.name, "sha256": digest(path)}

    for day, robot, session, count in SESSIONS:
        stem = f"teleop_rosy_{robot}_202610{day[-2:]}T{session}Z"
        sidecar_path = video_dir / f"{stem}.jsonl"
        scan_path = video_dir / f"{stem}.scan.npz"
        sidecar = rows(sidecar_path)
        model = [r for r in model_rows[day] if r["session"] == session]
        if len(sidecar) != count or len(model) != count:
            raise ValueError(f"{session}: frame count mismatch")
        if any(row["index"] != i or candidate["frame"] != i for i, (row, candidate) in enumerate(zip(sidecar, model))):
            raise ValueError(f"{session}: frame order mismatch")
        if any((candidate.get("stamp_ns") != row["stamp_ns"] if day == "1006"
                else abs(candidate["t"] - row["stamp_ns"] / 1e9) > 1e-6)
               for row, candidate in zip(sidecar, model)):
            raise ValueError(f"{session}: image stamp mismatch")

        with np.load(scan_path, allow_pickle=False) as scan:
            ranges = scan["ranges"].astype(np.float32)
            scan_stamp = scan["scan_stamp_ns"]
            dt = scan["dt"]
            angle_min = float(scan["angle_min"])
            angle_max = float(scan["angle_max"])
            increment = float(scan["angle_increment"])
            range_min = float(scan["range_min"])
            range_max = float(scan["range_max"])
            if ranges.shape != (count, 720) or not math.isclose(
                    angle_min + (ranges.shape[1] - 1) * increment, angle_max, abs_tol=0.001):
                raise ValueError(f"{session}: scan geometry mismatch")
            for i, row in enumerate(sidecar):
                side_scan = row.get("side", {}).get("scan")
                side_dt = row.get("dt", {}).get("scan")
                if side_scan is None:
                    if side_dt is not None or scan_stamp[i] != 0 or math.isfinite(float(dt[i])):
                        raise ValueError(f"{session} frame {i}: absent scan mismatch")
                elif (side_scan.get("stamp_ns") != int(scan_stamp[i]) or side_dt is None
                      or abs(float(side_dt) - float(dt[i])) > 0.0001):
                    raise ValueError(f"{session} frame {i}: scan sidecar mismatch")
            angles = angle_min + np.arange(ranges.shape[1]) * increment
            broad = np.array([r["near_drivable_fraction"] > 0.50 for r in model], dtype=bool)
            if any(not math.isfinite(r["near_drivable_fraction"])
                   or not 0 <= r["near_drivable_fraction"] <= 1 for r in model):
                raise ValueError(f"{session}: invalid model fraction")
            age = -dt
            fresh = np.isfinite(age) & (age >= 0) & (age <= 0.15)
            by_heading = {}
            near_by_heading = []
            details = {}
            for heading in (178, 180, 182):
                offset = np.arctan2(np.sin(angles - np.deg2rad(heading)),
                                    np.cos(angles - np.deg2rad(heading)))
                sector = ranges[:, np.abs(offset) <= np.deg2rad(20)]
                valid = np.isfinite(sector) & (sector >= range_min) & (sector <= range_max)
                nearest = np.min(np.where(valid, sector, np.inf), axis=1)
                usable = fresh & (valid.sum(axis=1) >= math.ceil(0.70 * sector.shape[1]))
                near = usable & (nearest < 0.30)
                near_by_heading.append(near)
                by_heading[str(heading)] = {
                    "usable": int(usable.sum()),
                    "near": int(near.sum()),
                    "near_and_broad": int((near & broad).sum()),
                }
                if heading == 180:
                    details = {
                        str(i): {
                            "scan_age_s": None if not math.isfinite(float(age[i])) else round(float(age[i]), 4),
                            "valid_beams": int(valid[i].sum()),
                            "near_m": None if not math.isfinite(float(nearest[i])) else round(float(nearest[i]), 4),
                            "usable": bool(usable[i]),
                            "broad_mask_fraction": round(float(model[i]["near_drivable_fraction"]), 4),
                        }
                        for i in ANCHORS[session]
                    }
        robust = np.logical_and.reduce(near_by_heading)
        report["sessions"][session] = {
            "frames": count,
            "sources": {
                "sidecar_sha256": digest(sidecar_path),
                "scan_sha256": digest(scan_path),
            },
            "mask_gt_half_all": int(broad.sum()),
            "headings": by_heading,
            "near_all_three_headings": int(robust.sum()),
            "near_all_three_and_broad": int((robust & broad).sum()),
            "anchors": details,
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(analyze(args.video_dir), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
