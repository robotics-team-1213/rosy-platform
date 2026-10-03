"""D-431: finite raw-head and decoded detection parity on the same camera frames."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def compare_outputs(reference, candidate, *, atol, rtol):
    ref, got = np.asarray(reference), np.asarray(candidate)
    if ref.shape != got.shape or not np.isfinite(ref).all() or not np.isfinite(got).all():
        return {"ok": False, "max_abs_diff": None, "reason": "non-finite output or shape mismatch"}
    diff = np.abs(ref.astype(np.float64) - got.astype(np.float64))
    ok = bool(np.all(diff <= atol + rtol * np.abs(ref)))
    return {"ok": ok, "max_abs_diff": float(diff.max()), "reason": None if ok else "raw output mismatch"}


def detection_parity(reference, candidate, *, min_iou, confidence_tolerance):
    """Same labels/counts and one-to-one boxes; no unmatched detections hidden by averages."""
    from control.sensing.perception.learned.detector import _iou
    if len(reference) != len(candidate):
        return False
    remaining = list(candidate)
    for ref in reference:
        matches = [(i, float(_iou(np.asarray(ref["bbox_xyxy"]),
                                  np.asarray([got["bbox_xyxy"]]))[0]))
                   for i, got in enumerate(remaining) if got["label"] == ref["label"]]
        if not matches:
            return False
        i, overlap = max(matches, key=lambda pair: pair[1])
        got = remaining.pop(i)
        if overlap < min_iou or abs(ref["confidence"] - got["confidence"]) > confidence_tolerance:
            return False
    return True


def compare_frames(reference, candidate, manifest, frames, *, atol, rtol, min_iou, confidence_tolerance):
    import cv2
    from control.sensing.perception.learned.detector import decode, letterbox
    from control.sensing.perception.learned.lane_mask import preprocess
    spec = manifest.input
    rows = []
    names = tuple(c.name for c in manifest.classes)
    for path in frames:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"unreadable frame: {Path(path).name}")
        boxed, scale, px, py = letterbox(image, spec.width, spec.height)
        x = preprocess(boxed, spec)
        ref, got = reference(x), candidate(x)
        result = compare_outputs(ref, got, atol=atol, rtol=rtol)
        if result["ok"]:
            options = dict(scale=scale, pad=(px, py), frame_size=(image.shape[1], image.shape[0]))
            result["ok"] = detection_parity(decode(ref, names, **options), decode(got, names, **options),
                                            min_iou=min_iou, confidence_tolerance=confidence_tolerance)
            if not result["ok"]:
                result["reason"] = "decoded detections mismatch"
        rows.append({"frame_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), **result})
    return {"ok": bool(rows) and all(r["ok"] for r in rows), "frames": len(rows), "results": rows,
            "atol": atol, "rtol": rtol, "min_box_iou": min_iou,
            "confidence_tolerance": confidence_tolerance}


def compare_lane_frames(reference, candidate, manifest, frames, *, atol, rtol, min_pixel_agreement):
    import cv2
    from control.sensing.perception.learned.lane_mask import preprocess
    rows = []
    for path in frames:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"unreadable frame: {Path(path).name}")
        x = preprocess(image, manifest.input)
        ref, got = reference(x), candidate(x)
        result = compare_outputs(ref, got, atol=atol, rtol=rtol)
        if result["ok"]:
            agreement = float(np.mean(np.argmax(ref, axis=1) == np.argmax(got, axis=1)))
            result["pixel_agreement"] = agreement
            result["ok"] = agreement >= min_pixel_agreement
            if not result["ok"]:
                result["reason"] = "lane pixel classification mismatch"
        rows.append({"frame_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), **result})
    return {"ok": bool(rows) and all(r["ok"] for r in rows), "frames": len(rows), "results": rows,
            "atol": atol, "rtol": rtol, "min_pixel_agreement": min_pixel_agreement}


def check_ncnn_evidence(manifest):
    """Validate the hashed export proof before an NCNN model enters intake."""
    import json
    import re
    from control.sensing.perception.learned.manifest import ManifestError
    if "export_parity.json" not in {f.name for f in manifest.files}:
        raise ManifestError("ncnn parity: missing hashed export_parity.json")
    try:
        proof = json.loads((manifest.folder / "export_parity.json").read_text(encoding="utf-8"))
        rows = proof["results"]
        minimum = proof.get("min_eval_frames")

        def bounded(value, low, high):
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and np.isfinite(value) and low <= value <= high)
        thresholds = bounded(proof.get("atol"), 0, float("inf")) and bounded(proof.get("rtol"), 0, float("inf"))
        if manifest.task == "lane_seg":
            thresholds = (thresholds and bounded(proof.get("min_pixel_agreement"), 0.999, 1)
                          and all(isinstance(r, dict) and bounded(r.get("pixel_agreement"),
                                  proof["min_pixel_agreement"], 1) for r in rows))
        else:
            thresholds = (thresholds and bounded(proof.get("min_box_iou"), 0.95, 1)
                          and bounded(proof.get("confidence_tolerance"), 0, 0.01))
        valid = (proof.get("ok") is True and isinstance(rows, list) and len(rows) > 0
                 and thresholds
                 and isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0
                 and len(rows) >= minimum
                 and proof.get("frames") == len(rows)
                 and all(isinstance(r, dict) and r.get("ok") is True
                         and isinstance(r.get("frame_sha256"), str)
                         and re.fullmatch(r"[0-9a-f]{64}", r["frame_sha256"])
                         and isinstance(r.get("max_abs_diff"), (int, float))
                         and np.isfinite(r["max_abs_diff"]) and r["max_abs_diff"] >= 0 for r in rows))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"ncnn parity: unreadable evidence: {exc}") from exc
    if not valid:
        raise ManifestError("ncnn parity: real-frame export comparison did not pass")
