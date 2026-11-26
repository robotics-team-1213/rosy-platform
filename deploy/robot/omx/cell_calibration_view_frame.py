"""Calibration profile frame resolution, exact-image binding and reference-space registration."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

import cell_attempts
import cell_params as prm

try:
    from cell_auto_evidence import bound_map_error
except ImportError:
    bound_map_error = None

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _read_json(path: Path | None) -> tuple[dict | None, str | None]:
    if path is None or not str(path) or not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data if isinstance(data, dict) else None), (None if isinstance(data, dict) else "not-object")
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def is_allowed_frame_url(url: str | None) -> bool:
    """Only allow HTTP(S) loopback URLs unless explicitly opted in as trusted local camera endpoints."""
    if not isinstance(url, str) or not url.strip():
        return False
    parts = urlsplit(url.strip())
    return parts.scheme in {"http", "https"} and (parts.hostname or "").lower() in LOOPBACK_HOSTS


def resolve_frame_target(entry: dict[str, Any], source: str) -> dict[str, Any]:
    """Resolve a server-side reference file path or live frame source for `profile_id`."""
    cfg_path = Path(entry["config_path"])
    config, _ = _read_json(cfg_path)
    config = config or {}
    if source == "reference":
        ref_str = entry.get("reference_top_path") or (config.get("preflight") or {}).get("reference_top") or ""
        return {"kind": "file", "path": Path(ref_str) if ref_str else None}
    if source == "live":
        if entry.get("live_top_path"):
            return {"kind": "file", "path": Path(entry["live_top_path"])}
        url = entry.get("live_frame_url") or ((config.get("cameras") or {}).get("top") or {}).get("url")
        return {"kind": "url", "url": url}
    return {"kind": "none"}


_FRAME_MATCH_LOCK = Lock()


def _generation(calibration):
    return cell_attempts.digest([calibration[k] for k in
                                 ("reference_top_sha256", "reference_map_sha", "reference_geometry_sha")])


def bind_frame(entry, source, frame_bytes):
    """Register these exact image bytes; unmatched frames retain their original pixels."""
    import cv2
    import numpy as np
    import cell_preflight

    report = {"status": "unverified"}
    try:
        config, _ = _read_json(Path(entry["config_path"]))
        calibration, _ = _read_json(Path(entry.get("calibration_path") or config["calibration_path"]).expanduser())
        if source == "reference":
            reference = frame_bytes
        elif source == "live":
            ref = entry.get("reference_top_path") or config["preflight"]["reference_top"]
            reference = Path(ref).expanduser().read_bytes()
        else:
            return frame_bytes, report
        if not reference or bound_map_error is None or bound_map_error(calibration, config, reference):
            return frame_bytes, report
        report.update(reference_sha256=calibration["reference_top_sha256"], generation=_generation(calibration))
        if source == "reference":
            return frame_bytes, {**report, "status": "reference"}
        ref_image = cv2.imdecode(np.frombuffer(reference, np.uint8), cv2.IMREAD_GRAYSCALE)
        image = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        if ref_image is None or image is None or image.shape[:2] != ref_image.shape:
            return frame_bytes, report
        with _FRAME_MATCH_LOCK:
            shift = cell_preflight.camera_shift_px(ref_image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                                                   include_transform=True)
        if not shift.get("ok"):
            return frame_bytes, report
        report.update(max_px=shift["max_px"], inliers=shift["inliers"])
        param_file = config.get("params_path")
        params_path = Path(entry["config_path"]).parent / Path(param_file).expanduser() if param_file else None
        params = prm.load(params_path)["values"]
        if shift["inliers"] < 30 or not 0 <= shift["max_px"] <= prm.get(params, "calibrate.max_shift_px"):
            return frame_bytes, report
        matrix = np.asarray(shift["reference_to_current"], dtype=float)
        if np.linalg.matrix_rank(matrix) != 3:
            return frame_bytes, report
        registered = cv2.warpPerspective(image, matrix, ref_image.shape[::-1],
                                         flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        ok, jpeg = cv2.imencode(".jpg", registered)
        if ok:
            return jpeg.tobytes(), {**report, "status": "aligned"}
    except (KeyError, OSError, ValueError, TypeError, AttributeError, cv2.error, np.linalg.LinAlgError):
        pass
    return frame_bytes, report


def _image_size(path: Path | None) -> list[int] | None:
    if path is None or not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as img:
            return [int(img.width), int(img.height)]
    except Exception:
        return None


def _camera_shift(ref_path: Path | None, live_path: Path | None) -> dict | None:
    if not (ref_path and ref_path.is_file() and live_path and live_path.is_file()):
        return None
    try:
        import cv2
        import cell_preflight
        ref = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
        cur = cv2.imread(str(live_path), cv2.IMREAD_GRAYSCALE)
        if ref is None or cur is None:
            return None
        with _FRAME_MATCH_LOCK:
            return cell_preflight.camera_shift_px(ref, cur)
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
