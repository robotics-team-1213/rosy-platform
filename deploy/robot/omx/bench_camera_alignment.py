"""Operator-confirmed side framing reference, independent of the lighting baseline."""

import base64
import binascii
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

from camera_roles import registry_path
from cell_camera_input_preflight import binding_status, collect, policy_roles, viewer_cell
from omx_cameras import load
from omx_devices import role_env, video_facts

REFERENCE = "camera-side-reference.json"
SETTINGS = "camera-side-markers.json"


def fresh_side():
    return viewer_cell(("side",)).frame_receipt("side", timeout_s=2.0, max_age_s=0.6)


def preparation(bench, arm):
    roles = policy_roles(arm)
    lighting = bench.check_camera_drift(arm)
    try:
        path = registry_path()
        bindings = binding_status(roles, load(path), role_env(path.parent), video_facts(), lighting.get("topics", {}))
    except (OSError, ValueError, TypeError, AttributeError, SystemExit):
        bindings = dict.fromkeys(roles, "registry_unavailable")
    evidence = collect(arm, viewer_cell(roles).frame_receipt)
    for role, row in evidence["cameras"].items():
        row.update(binding=bindings[role], lighting=lighting["cameras"].get(role, {}).get("status", "missing"))
    try:
        frame = fresh_side()
    except (OSError, ValueError):
        frame = None
    if frame is not None and evidence["cameras"]["side"]["ok"] and bindings["side"] == "matched":
        with bench.lock:
            bench.__dict__.setdefault("_side_references", deque(maxlen=8)).append(
                {key: value for key, value in frame.items() if key != "image"})
    return {**evidence, "side_alignment": check(bench.prep, frame)}


def save_confirmed(bench, body):
    digest = body.get("sha256")
    if body.get("confirmed") is not True or not isinstance(digest, str):
        raise ValueError("측면 구도를 확인한 뒤 기준을 저장하세요.")
    with bench.lock:
        frame = next((row for row in reversed(getattr(bench, "_side_references", ()))
                      if row["jpeg_sha256"] == digest), None)
        if frame is None or time.time() - frame["source_stamp"] > 5 or bench.state["status"] == "recording":
            raise ValueError("측면 화면을 다시 확인한 뒤 기준을 저장하세요.")
        return save_reference(bench.prep, frame)


def save_reference(prep: Path, frame: dict) -> dict:
    data = {key: frame[key] for key in ("camera", "jpeg_sha256", "source_seq", "source_stamp")}
    data["jpeg"] = base64.b64encode(frame["jpeg_bytes"]).decode("ascii")
    tmp = NamedTemporaryFile(mode="w", dir=prep, encoding="utf-8", delete=False)
    try:
        name = Path(tmp.name)
        with tmp:
            json.dump(data, tmp)
        os.replace(name, prep / REFERENCE)
    finally:
        name.unlink(missing_ok=True)
    return {"source_stamp": data["source_stamp"]}


def reference_image(prep: Path) -> bytes:
    data = json.loads((prep / REFERENCE).read_text(encoding="utf-8"))
    try:
        raw = base64.b64decode(data["jpeg"], validate=True)
        valid = data["camera"] == "side" and hashlib.sha256(raw).hexdigest() == data["jpeg_sha256"]
    except (KeyError, TypeError, binascii.Error):
        valid = False
    if not valid:
        raise ValueError("invalid side reference")
    return raw


def _marker_settings(prep: Path):
    data = json.loads((prep / SETTINGS).read_text(encoding="utf-8"))
    ids = data.get("ids") if isinstance(data, dict) else None
    tolerance = data.get("max_shift_px") if isinstance(data, dict) else None
    if (not isinstance(ids, list) or len(ids) != 2
            or any(type(key) is not int or not 0 <= key < 50 for key in ids)
            or ids[0] == ids[1] or type(tolerance) not in (int, float)
            or not 0 < tolerance <= 640):
        raise ValueError("expected two fixed DICT_4X4_50 IDs and a measured pixel tolerance")
    return ids, tolerance


def compare_markers(reference, current, ids, tolerance):
    if any(key not in reference or key not in current for key in ids):
        return {"status": "markers_missing"}
    shifts = [(float(x - rx), float(y - ry)) for key in ids
              for (rx, ry), (x, y) in zip(reference[key], current[key], strict=True)]
    maximum = max(math.hypot(dx, dy) for dx, dy in shifts)
    return {"status": "moved" if maximum > tolerance else "aligned", "max_px": round(maximum, 1),
            "dx_px": round(sum(dx for dx, _ in shifts) / len(shifts), 1),
            "dy_px": round(sum(dy for _, dy in shifts) / len(shifts), 1)}


def check(prep: Path, frame=None) -> dict:
    result = {"has_reference": False}
    if frame is not None:
        result.update(current_jpeg=base64.b64encode(frame["jpeg_bytes"]).decode("ascii"),
                      current_sha256=frame["jpeg_sha256"])
    try:
        reference = reference_image(prep)
    except FileNotFoundError:
        return {**result, "status": "no_reference"}
    except (OSError, ValueError):
        return {**result, "status": "reference_invalid"}
    result["has_reference"] = True
    try:
        ids, tolerance = _marker_settings(prep)
    except FileNotFoundError:
        return {**result, "status": "manual_comparison"}
    except (OSError, ValueError):
        return {**result, "status": "settings_invalid"}
    if frame is None:
        return {**result, "status": "side_unavailable"}
    current = frame["image"]

    import cv2
    import numpy as np

    from cell_shared_markers import detect_markers

    saved = cv2.imdecode(np.frombuffer(reference, dtype=np.uint8), cv2.IMREAD_COLOR)
    if saved is None or saved.shape != current.shape:
        return {**result, "status": "reference_invalid"}
    try:
        reference_markers, current_markers = detect_markers(saved), detect_markers(current)
    except (AttributeError, cv2.error):
        return {**result, "status": "detector_unavailable"}
    comparison = compare_markers(reference_markers, current_markers, ids, tolerance)
    if comparison["status"] != "markers_missing":
        h, w = saved.shape[:2]
        comparison["points"] = {
            name: [(np.mean(markers[key], axis=0) / (w, h)).tolist() for key in ids]
            for name, markers in (("reference", reference_markers), ("current", current_markers))
        }
    return {**result, **comparison}
