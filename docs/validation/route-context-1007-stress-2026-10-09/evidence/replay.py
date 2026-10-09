"""Candidate-only D-531 B9 stress replay over source-proved 10/7 images.

The synthetic bend hint on every frame is deliberately stronger than a real
Fleet instruction. Counts are changed decisions, never accepted ground truth.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "contracts/foundation"), str(ROOT / "middleware/perception"),
                str(ROOT / "learning/training/perception")]

from control.sensing.perception.lane_keep import LaneKeeper  # noqa: E402
from road_replay import ground_for  # noqa: E402

SESSIONS = {"20261007T143038Z_rosy_60": 124, "20261007T143211Z_rosy_60": 83}


def replay(catalog: Path) -> dict:
    raw = catalog.read_bytes()
    entries = [json.loads(line) for line in raw.splitlines()]
    counts = Counter(entry["source_session"] for entry in entries)
    if counts != SESSIONS or any(entry.get("source_kind") != "mcap" for entry in entries):
        raise ValueError("expected the two source-proved 10/7 MCAP sessions")
    for session, count in SESSIONS.items():
        rows = [entry for entry in entries if entry["source_session"] == session]
        if [Path(entry["image"]).stem for entry in rows] != [f"{i:06d}" for i in range(count)]:
            raise ValueError("source frames must be continuous and ordered")
        for entry in rows:
            if hashlib.sha256(Path(entry["image"]).read_bytes()).hexdigest() != entry["image_sha256"]:
                raise ValueError("source image digest mismatch")
    result = {"validated": False, "catalog_sha256": hashlib.sha256(raw).hexdigest(),
              "context": "synthetic bend on every frame; not a Fleet instruction", "cases": {}}
    for pitch in (None, 11.8):
        profile, ground = ground_for(pitch)
        for session in SESSIONS:
            plain = LaneKeeper(camera_x_offset_m=float(profile["x_offset_m"]), corner_turning=True)
            guided = LaneKeeper(camera_x_offset_m=float(profile["x_offset_m"]), corner_turning=True)
            changed = Counter()
            newly_driving = []
            for entry in (row for row in entries if row["source_session"] == session):
                frame = cv2.imread(entry["image"])
                if frame is None:
                    raise ValueError("unreadable source image")
                plain.update(frame, ground, lane_half_width_m=0.0925)
                guided.update(frame, ground, lane_half_width_m=0.0925, bend_expected=True)
                before, after = plain.last, guided.last
                before_go, after_go = before.get("target_m") is not None, after.get("target_m") is not None
                changed["frames"] += 1
                if not before_go and after_go:
                    changed["hold_to_drive"] += 1
                    newly_driving.append(Path(entry["image"]).name)
                elif before_go and not after_go:
                    changed["drive_to_hold"] += 1
                elif before_go and after_go:
                    distance = sum((a - b) ** 2 for a, b in zip(before["target_m"], after["target_m"])) ** 0.5
                    if distance > 0.01:
                        changed["drive_target_shift_gt_1cm"] += 1
                if (before["strategy"], before.get("reason")) != (after["strategy"], after.get("reason")):
                    changed["strategy_or_reason_change"] += 1
            result["cases"][f"{session}:{pitch}"] = dict(changed, hold_to_drive_frames=newly_driving)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(replay(args.catalog), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
