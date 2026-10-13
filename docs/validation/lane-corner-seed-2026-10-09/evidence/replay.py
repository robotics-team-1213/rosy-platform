"""Replay proved 10/6 or 10/7 camera inputs through keep_corner; no robot commands."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import yaml

REPO = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(REPO / p) for p in (
    "learning/training/perception", "learning/training/perception/dataset", "tools",
    "middleware/perception", "contracts/foundation")]
from road_replay_inputs import session_frames  # noqa: E402
from control.sensing.perception.camera_ground import nominal_ground_plane  # noqa: E402
from control.sensing.perception.lane_keep import LaneKeeper  # noqa: E402

CATALOG_SHA256 = "036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0"
SOURCE_SHA256 = "ab5378c963d8a04277b155086c4655456ebb6e0e9b34154caf07b843f397c57d"
GROUPS_1006 = {"20261006T082612Z_rosy_26": 2487, "20261006T091340Z_rosy_26": 642}
GROUPS_1007 = {"20261007T143038Z_rosy_60": 124, "20261007T143211Z_rosy_60": 83}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frames(source):
    if source.is_file():
        content = source.read_bytes()
        assert digest(content) == CATALOG_SHA256
        for item in map(json.loads, content.splitlines()):
            image = Path(item["image"])
            assert digest(image.read_bytes()) == item["image_sha256"]
            bgr = cv2.imread(str(image))
            assert bgr is not None and bgr.shape == (240, 320, 3)
            yield item["capture_group"], int(image.stem), item["mcap"]["frame"]["header_stamp_ns"] * 1e-9, bgr
        return
    source_record = (source / "source-readback-1006.json").read_bytes()
    assert digest(source_record) == SOURCE_SHA256
    source_sessions = {row["id"]: row for row in json.loads(source_record)["sessions"]}
    for group in GROUPS_1006:
        session = source / group
        manifest_bytes = (session / "manifest.json").read_bytes()
        expected = next(row["sha256"] for row in source_sessions[group]["files"] if row["path"] == "manifest.json")
        assert digest(manifest_bytes) == expected
        manifest = json.loads(manifest_bytes)
        assert manifest["id"] == group
        assert {p.relative_to(session).as_posix() for p in (session / "bag").glob("*.mcap")} == {
            item["path"] for item in manifest["files"] if item["path"].startswith("bag/") and item["path"].endswith(".mcap")}
        for item in manifest["files"]:
            content = (session / item["path"]).read_bytes()
            assert len(content) == item["bytes"] and digest(content) == item["sha256"]
        for index, frame in enumerate(session_frames(session)):
            assert frame.bgr.shape == (240, 320, 3)
            yield group, index, frame.t, frame.bgr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="10/6 recordings root or 10/7 proved catalog")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    if output == REPO or REPO in output.parents:
        parser.error("frame decisions belong outside the public repo")
    assert not output.exists() and output.parent.exists()
    profile_path = REPO / "middleware/apps/device/pinky/profile/config/camera_nominal.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    models = {}
    for pitch in (8.0, 11.8):
        candidate = dict(profile, pitch_rad=math.radians(pitch))
        plane = nominal_ground_plane(source="NOMINAL", allowed=True, width_px=320, height_px=240, profile=candidate)
        assert plane is not None
        models[str(pitch)] = (plane, LaneKeeper(camera_x_offset_m=float(candidate["x_offset_m"]), corner_turning=True))
    result = {"keeper_sha256": digest((REPO / "middleware/perception/control/sensing/perception/lane_keep.py").read_bytes()),
              "source_sha256": CATALOG_SHA256 if args.source.is_file() else SOURCE_SHA256,
              "rows": {pitch: [] for pitch in models}}
    counts = Counter()
    last_group = last_stamp = None
    for group, index, stamp, image in frames(args.source):
        assert group in (GROUPS_1007 if args.source.is_file() else GROUPS_1006)
        counts[group] += 1
        for pitch, (plane, keeper) in models.items():
            if group != last_group or last_stamp is None or not 0 <= stamp - last_stamp <= .5:
                keeper.reset()
            obs = keeper.update(image, plane, lane_half_width_m=.0925)
            result["rows"][pitch].append({"group": group, "frame": index,
                                          "strategy": keeper.last["strategy"], "reason": keeper.last.get("reason"),
                                          "error": None if obs is None else obs.error,
                                          "confidence": None if obs is None else obs.confidence,
                                          "boundaries": len(keeper.last["boundaries"])})
        last_group, last_stamp = group, stamp
    assert counts == (GROUPS_1007 if args.source.is_file() else GROUPS_1006)
    result["counts"] = {pitch: dict(Counter(row["strategy"] for row in rows))
                        for pitch, rows in result["rows"].items()}
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("keeper_sha256", "source_sha256", "counts")}))


if __name__ == "__main__":
    main()
