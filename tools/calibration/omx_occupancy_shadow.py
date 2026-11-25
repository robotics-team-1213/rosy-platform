"""Offline D435 occupancy evaluation. All paths in the manifest resolve relative to it.

Manifest keys: factory (JSON path), rois (colour-pixel rectangles), samples.
Each sample has split (fit/holdout), labels (one empty/occupied label per ROI),
depth (640x480 little-endian Z16 burst), receipt (JSON path), and optional
capture_keys (successive keys locating the paired capture in a receipt). A D435
capture contains depth and sibling rgb records; flat top captures carry top_stamp
and top_sha256. camera_id and reference_rgb identify the setup. Each sample pins
setup_sha256, rgb, and rgb_sha256.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy/robot/omx"))
from cell_depth_pose import calibration
from cell_depth_slots import median_depth
from cell_preflight import camera_shift_px
from cell_shared_markers import depth_in_colour


def check_rois(rois):
    if not isinstance(rois, list) or not rois:
        raise ValueError("at least one colour ROI required")
    for i, roi in enumerate(rois):
        if not isinstance(roi, list) or len(roi) != 4 or any(type(x) is not int for x in roi):
            raise ValueError("ROI must contain four integer pixel coordinates")
        x, y, r, b = roi
        if not (0 <= x < r <= 640 and 0 <= y < b <= 480):
            raise ValueError("ROI outside 640x480 frame")
        for left, top, right, bottom in rois[:i]:
            if max(x, left) < min(r, right) and max(y, top) < min(b, bottom):
                raise ValueError("overlapping footprints")


def lookup(rec, keys):
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise ValueError("capture_keys must be a list of keys")
    for key in keys:
        rec = rec[key]
    return rec


def read_burst(root, sample, rgb_hash, hashes, intervals, rgb_stamps):
    receipt = json.loads((root / sample["receipt"]).read_text(encoding="utf-8-sig"))
    if "rgb_stamp_keys" in sample or "receipt_keys" in sample:
        raise ValueError("select the paired capture with capture_keys")
    capture = lookup(receipt, sample.get("capture_keys", []))
    if not isinstance(capture, dict):
        raise ValueError("invalid paired capture record")
    rec = capture.get("depth", capture)
    count = rec["frames"]
    path = root / sample["depth"]
    if type(count) is not int or not 1 <= count <= 9 or path.stat().st_size != count*480*640*2:
        raise ValueError("burst does not match receipt frame count and Z16 dimensions")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != rec["raw_sha256"]:
        raise ValueError("burst digest differs from capture receipt")
    start, end = rec["first_exposure_wall_estimate_s"], rec["exposure_wall_estimate_s"]
    if not all(type(t) in (float, int) and math.isfinite(t) and t > 0 for t in (start,end)) or end < start:
        raise ValueError("invalid exposure interval")
    if any(max(start,a) <= min(end,b) for a,b in intervals):
        raise ValueError("overlapping capture intervals")
    frames = np.frombuffer(raw, "<u2").reshape(count,480,640)
    fingerprints = {hashlib.sha256(f).digest() for f in frames}
    if fingerprints & hashes:
        raise ValueError("capture shares frames with another sample")
    hashes.update(fingerprints)
    intervals.append((start,end))
    if "depth" in capture:
        rgb = capture.get("rgb", {})
        if not isinstance(rgb, dict) or rgb.get("view", "top") != "top":
            raise ValueError("invalid paired top RGB record")
        stamp, recorded_hash = rgb.get("source_stamp"), rgb.get("sha256")
    else:
        stamp, recorded_hash = capture.get("top_stamp"), capture.get("top_sha256")
    if stamp is None or recorded_hash is None:
        return None, digest, "capture receipt lacks top RGB digest or source timestamp"
    if recorded_hash != rgb_hash:
        raise ValueError("top RGB digest differs from paired capture receipt")
    if type(stamp) not in (float,int) or not math.isfinite(stamp) or not start-.1 <= stamp <= end+.1:
        raise ValueError("top RGB timestamp outside depth capture window")
    if stamp in rgb_stamps:
        raise ValueError("top RGB exposure reused in multiple samples")
    rgb_stamps.add(stamp)
    return median_depth(frames)[0], digest, None


def measure(depth, factory, rois):
    image = depth_in_colour(depth, factory, (640,480))
    patches = []
    for x, y, r, b in rois:
        dx, dy = (r-x)//4, (b-y)//4
        part = image[y+dy:b-dy, x+dx:r-dx]
        valid = part[np.isfinite(part)]
        fraction = len(valid)/part.size
        # Forward projection of a D435 depth frame covers only part of the colour grid.
        usable = len(valid) >= 50 and fraction >= 0.2
        patches.append({"points": len(valid), "coverage": fraction,
                        "median_mm": float(np.median(valid)) if usable else None})
    return patches


def predict(empty, occupied, measurement):
    if measurement is None or not empty or not occupied or None in empty or None in occupied:
        return "UNKNOWN"
    # Disjoint witnessed depths, separated by at least half a nominal 30 mm container.
    if min(empty)-max(occupied) < 15:
        return "UNKNOWN"
    e, o = float(np.median(empty)), float(np.median(occupied))
    score = (e-measurement)/(e-o)
    if abs(score) < 0.25:
        return "empty"
    if abs(score-1) < 0.25:
        return "occupied"
    return "UNKNOWN"


def evaluate(path):
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    rois = doc["rois"]
    check_rois(rois)
    raw_factory = (path.parent / doc["factory"]).read_bytes()
    reference_bytes = (path.parent / doc["reference_rgb"]).read_bytes()
    reference = cv2.imdecode(np.frombuffer(reference_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if reference is None or reference.shape != (480,640) or not isinstance(doc["camera_id"],str) or not doc["camera_id"].strip():
        raise ValueError("invalid reference or camera identifier")
    binding = dict(camera_id=doc["camera_id"], rois=rois,
                   factory_sha256=hashlib.sha256(raw_factory).hexdigest(),
                   reference_sha256=hashlib.sha256(reference_bytes).hexdigest())
    setup = hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    factory = json.loads(raw_factory)
    if "stream.depth" in factory and "stream.color" in factory:
        factory["stream"] = {s: factory["stream."+s] for s in ("depth","color")}
    kd, kc, _, _ = calibration(factory)
    if any(k[0,0] <= 0 or k[1,1] <= 0 for k in (kd,kc)):
        raise ValueError("invalid focal lengths")
    if not math.isclose(factory.get("depth_scale", .001), .001, rel_tol=.0001):
        raise ValueError("expected Z16 in millimetres")
    samples, hashes, rgb_hashes, intervals, rgb_stamps = [], set(), set(), [], set()
    for sample in doc["samples"]:
        split, labels = sample["split"], sample["labels"]
        if (split not in ("fit","holdout") or not isinstance(labels,list) or len(labels)!=len(rois)
                or any(label not in ("empty","occupied") for label in labels)):
            raise ValueError("invalid split or per-footprint labels")
        rgb = (path.parent / sample["rgb"]).read_bytes()
        rgb_hash = hashlib.sha256(rgb).hexdigest()
        if sample["setup_sha256"] != setup or sample["rgb_sha256"] != rgb_hash:
            raise ValueError("sample setup or RGB digest mismatch")
        if rgb_hash in rgb_hashes:
            raise ValueError("top RGB capture reused in multiple samples")
        rgb_hashes.add(rgb_hash)
        image = cv2.imdecode(np.frombuffer(rgb,np.uint8),cv2.IMREAD_GRAYSCALE)
        if image is None or image.shape != reference.shape:
            raise ValueError("invalid RGB geometry")
        registration = camera_shift_px(reference,image)
        if (not registration["ok"] or registration["inliers"] < 30
                or not 0 <= registration["max_px"] <= 2):
            raise ValueError("unregistered RGB scene or camera shift above 2 px")
        depth, digest, reason = read_burst(path.parent, sample, rgb_hash, hashes, intervals, rgb_stamps)
        patches = measure(depth,factory,rois) if reason is None else [{"median_mm": None} for _ in rois]
        samples.append(dict(split=split, labels=labels, burst_sha256=digest, rgb_sha256=rgb_hash,
                            capture_verified=reason is None, unverified_reason=reason,
                            registration=registration, patches=patches))
    if {s["split"] for s in samples} != {"fit","holdout"}:
        raise ValueError("need independent fit and holdout bursts")
    train = [s for s in samples if s["split"] == "fit" and s["capture_verified"]]
    for s in samples:
        if s["split"] == "holdout":
            for i, patch in enumerate(s["patches"]):
                empty, full = ([t["patches"][i]["median_mm"] for t in train if t["labels"][i]==label]
                               for label in ("empty","occupied"))
                patch["prediction"] = predict(empty, full, patch["median_mm"])
    return dict(scope="offline_shadow_only", motion_authority=False, acceptance_authority=False,
                manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                setup_sha256=setup, setup=binding, samples=samples)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args.manifest)
    except (KeyError, ValueError, TypeError, OSError, cv2.error) as exc:
        parser.exit(2, f"invalid occupancy evidence: {exc}\n")
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
