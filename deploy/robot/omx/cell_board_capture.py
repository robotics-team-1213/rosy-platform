"""Fresh, read only board views for OMX lens calibration."""

import json
import hashlib
import math
import time
from pathlib import Path

import numpy as np


def capture_hand_eye(cell, config, centre, z_list, yaw_list, step_m, out, camera="wrist", log=print):
    """Motion capture is held until a checked owner and pose-timed camera receipt exist."""
    raise RuntimeError("CALIBRATION_REQUIRED: supervised checked hand-eye capture unavailable")


def verify_hand_eye_views(folder: Path, binding: dict | None) -> None:
    """Reject legacy, mixed, stale, or modified views before solving hand-eye."""
    metas = sorted(folder.glob("view-*.json"),
                   key=lambda path: int(path.stem[5:]) if path.stem[5:].isdigit() else -1)
    if not binding or not metas:
        raise ValueError("CALIBRATION_REQUIRED: hand-eye view binding missing")
    previous_seq, previous_stamp = -1, -1.0
    for index, meta in enumerate(metas):
        if meta.name != f"view-{index}.json":
            raise ValueError("CALIBRATION_REQUIRED: hand-eye views are incomplete")
        row = json.loads(meta.read_text())
        image = meta.with_suffix(".jpg")
        gate = row.get("motion_evidence")
        pose = row.get("t")
        rotation = row.get("R")
        pose_ok = (isinstance(pose, list) and len(pose) == 3 and
                   isinstance(rotation, list) and len(rotation) == 3 and
                   all(isinstance(axis, list) and len(axis) == 3 for axis in rotation))
        try:
            pose_ok = pose_ok and bool(np.isfinite(np.asarray(pose + sum(rotation, []), dtype=float)).all())
        except (TypeError, ValueError):
            pose_ok = False
        states_ok = False
        if isinstance(gate, dict):
            try:
                before = np.asarray(gate["state_before"], dtype=float)
                after = np.asarray(gate["state_after"], dtype=float)
                states_ok = (before.shape == after.shape == (5,) and np.isfinite(before).all()
                             and np.isfinite(after).all() and np.max(np.abs(before - after)) < 0.08
                             and isinstance(gate["state_before_at"], (int, float))
                             and isinstance(gate["state_after_at"], (int, float))
                             and math.isfinite(gate["state_before_at"])
                             and math.isfinite(gate["state_after_at"])
                             and gate["goto_reported_at"] <= gate["state_before_at"]
                             < row["source_stamp"] <= gate["state_after_at"])
            except (KeyError, TypeError, ValueError):
                pass
        if (row.get("device_binding") != binding or row.get("camera") != binding.get("role")
                or not image.is_file() or not isinstance(row.get("source_seq"), int)
                or isinstance(row.get("source_seq"), bool) or not isinstance(row.get("source_stamp"), (int, float))
                or not math.isfinite(row["source_stamp"]) or not pose_ok
                or not isinstance(gate, dict) or gate.get("checked_owner") is not True
                or gate.get("settled") is not True
                or not isinstance(gate.get("goto_reported_at"), (int, float))
                or not math.isfinite(gate["goto_reported_at"]) or not states_ok
                or row["source_stamp"] <= gate["goto_reported_at"]
                or row["source_seq"] <= previous_seq or row["source_stamp"] <= previous_stamp
                or hashlib.sha256(image.read_bytes()).hexdigest() != row.get("sha256")):
            raise ValueError("CALIBRATION_REQUIRED: hand-eye view source receipt invalid")
        previous_seq, previous_stamp = row["source_seq"], row["source_stamp"]


def capture_intrinsics_frames(cell, camera: str, folder: Path, want: int = 60,
                              timeout_s: float = 180, every_s: float = 1.5, log=None) -> int:
    """Save distinct fresh JPEG views and source receipts while a person moves the board."""
    import cell_checkerboard as cb

    log = log or (lambda row: print(json.dumps(row), flush=True))
    if not 25 <= want <= 80 or not 0 < timeout_s <= 600 or every_s < 0:
        raise ValueError("capture requires 25-80 frames and a bounded positive timeout")
    spec = cell.cameras[camera]
    url = spec["url"] if isinstance(spec, dict) else spec
    label = cb.viewer_label_from_url(url)
    binding = cb.live_camera_binding(camera, viewer_label=label)
    session = cb.viewer_session()
    folder.mkdir(parents=True, exist_ok=False)
    board = cb.charuco_board(*cb.PRINTED)
    previous = None
    count = 0
    looks, pixel_sets, scales = [], [], []
    deadline = time.monotonic() + timeout_s
    while count < want and time.monotonic() < deadline:
        try:
            before_seq, before_stamp = cb.runtime_viewer_state(label, binding["topic"])
            receipt = cell.frame_receipt(camera, previous=previous, max_age_s=2.0)
            after_seq, after_stamp = cb.runtime_viewer_state(label, binding["topic"])
            if not (before_seq <= receipt["source_seq"] <= after_seq
                    and before_stamp <= receipt["source_stamp"] <= after_stamp):
                raise ValueError("camera JPEG does not match runtime viewer source")
        except (OSError, TimeoutError, ValueError):
            pass  # a stale or missing frame consumes time, never a calibration view
        else:
            previous = receipt
            found = cb.find_charuco(receipt["image"], board, min_corners=12)
            if found is not None:
                xy = np.asarray(found[1], float).reshape(-1, 2)
                view = cb.board_view(*found)
                scale = view[0] if view else None
                look = (*xy.mean(axis=0), scale, view[1] if view else None)
                if not any(cb._same_look(look, seen) for seen in looks):
                    path = folder / f"view-{count:03d}.jpg"
                    path.write_bytes(receipt["jpeg_bytes"])
                    path.with_suffix(".json").write_text(json.dumps({
                        "camera": camera, "source_seq": receipt["source_seq"],
                        "source_stamp": receipt["source_stamp"], "sha256": receipt["jpeg_sha256"],
                        "device_binding": binding}))
                    count += 1
                    looks.append(look)
                    pixel_sets.append(xy)
                    scales.append(scale)
                    image = receipt["image"]
                    coverage = cb.view_coverage(pixel_sets, scales, (image.shape[1], image.shape[0]))
                    missing = cb.coverage_reasons(coverage)
                    log({"saved": count, "missing": missing, "empty_cells": coverage["missing_cells"],
                         "centre_span": [coverage["center_span_x"], coverage["center_span_y"]],
                         "distance_ratio": coverage["distance_ratio"]})
        if count < want:
            time.sleep(every_s)
    if cb.viewer_session() != session or cb.live_camera_binding(camera, viewer_label=label) != binding:
        raise ValueError("camera identity or focus changed during calibration capture")
    return count
