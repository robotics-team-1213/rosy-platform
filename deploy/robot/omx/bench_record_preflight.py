#!/usr/bin/env python3
"""Top-camera corridor & occupancy preflight for blind IK replay trajectories."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def _resolve_cfg_path(prep: Path, raw) -> Path | None:
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    return p if p.is_absolute() else (Path(prep) / p)


def _resolve_pick_xy(prep: Path, arm: str, traj: dict) -> tuple[float, float] | None:
    src = traj.get("source") if isinstance(traj, dict) else None
    lib_name = src.get("library") if isinstance(src, dict) else None
    if not isinstance(lib_name, str) or not lib_name:
        return None
    letter = arm.split("_")[-1] if "_" in arm else arm
    lib_p = Path(prep) / f"cell-arm-{letter}" / lib_name
    if not lib_p.is_file():
        return None
    try:
        pick = (json.loads(lib_p.read_text(encoding="utf-8")).get("source") or {}).get("pick")
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if isinstance(pick, dict) and isinstance(pick.get("x"), (int, float)) and isinstance(pick.get("y"), (int, float)):
        return (float(pick["x"]), float(pick["y"]))
    return None


def check_replay_corridor(prep: Path, arm: str, traj: dict, *, opener=None) -> dict:
    """Verify live top-camera corridor clearance for segment A before accepting blind IK replay."""
    try:
        from cell_task_exec import _arm_run_spec
        _, stack_p, _, _, primary_site = _arm_run_spec(arm, Path(prep))
    except (ValueError, ImportError):
        return {"checked": False, "clear": True, "reason": "no_cell_stack"}
    if not stack_p.is_file():
        return {"checked": False, "clear": True, "reason": "no_cell_stack"}

    import cell_corridor
    import cell_observe
    import cell_params as prm
    import cell_pivot
    import cell_place_fit
    import cv2
    import numpy as np
    import omx_tcp

    cfg = cell_place_fit.with_tiers(json.loads(stack_p.read_text(encoding="utf-8")))[0]
    cal_p = _resolve_cfg_path(Path(prep), cfg.get("calibration_path"))
    if cal_p is None or not cal_p.is_file():
        return {"checked": False, "clear": True, "reason": "no_calibration"}
    top_url = ((cfg.get("cameras") or {}).get("top") or {}).get("url")
    if not top_url or urllib.parse.urlsplit(str(top_url)).scheme not in ("http", "https"):
        return {"checked": False, "clear": True, "reason": "no_top_camera"}

    fetch = opener or urllib.request.urlopen
    try:
        with fetch(top_url, timeout=2.5) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        return {
            "checked": True, "clear": False, "camera_error": f"HTTP {exc.code}",
            "reason": f"{arm} 상단 카메라 영상 확인 실패 (HTTP {exc.code}) — 블라인드 리플레이를 차단합니다",
        }
    except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError):
        return {"checked": False, "clear": True, "reason": "camera_viewer_offline"}

    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    if img is None or img.size == 0:
        return {
            "checked": True, "clear": False, "camera_error": "invalid_image",
            "reason": f"{arm} 상단 카메라 프레임이 비어 있어 블라인드 리플레이를 차단합니다",
        }

    frames = list(traj.get("frames") or [])
    seg_a = (traj.get("segments") or {}).get("A")
    if isinstance(seg_a, (list, tuple)) and len(seg_a) == 2:
        frames = frames[int(seg_a[0]):int(seg_a[1])]
    if not frames:
        return {"checked": True, "clear": True, "low": [], "reason": "empty_frames"}
    sample = frames[::15] + [frames[-1]]

    params_p = _resolve_cfg_path(Path(prep), cfg.get("params_path"))
    params = prm.load(str(params_p) if (params_p and params_p.is_file()) else None)["values"]
    cal = json.loads(cal_p.read_text(encoding="utf-8"))
    roi = (0, 0, int(img.shape[1]), int(img.shape[0]))
    sites = cfg.get("sites") or {}
    polys = cell_corridor.calibrated_surface_polygons(cfg, primary_site)
    if not polys:
        return {"checked": False, "clear": True, "reason": "no_surface_polygons"}

    mask, _ = cell_corridor.site_foreground_mask(img, sites, roi, params)
    tcp_x_m = omx_tcp.config_tcp(cfg)
    pts = [cell_pivot.joints_tcp(f, tcp_x_m=tcp_x_m)[:3] for f in sample]
    to_px = lambda p: cell_observe.predicted_pixel(cfg, cal, primary_site, p)  # noqa: E731
    try:
        ver = cell_corridor.check(
            pts, mask, roi, to_px, pick_xy=_resolve_pick_xy(Path(prep), arm, traj), params=params, surface_px=polys,
        )
    except (KeyError, ValueError, TypeError):
        return {"checked": False, "clear": True, "reason": "site_geometry_incomplete"}
    low_hits = list(ver.get("low") or [])
    if low_hits:
        pts_txt = ", ".join(str(h["centre_px"]) for h in low_hits[:3])
        return {
            "checked": True, "clear": False, "low": low_hits,
            "reason": f"{arm} 하강/적재 경로에 객체 또는 점유 슬롯 감지 ({len(low_hits)}건: {pts_txt}) — 장애물·슬롯 확인 후 다시 생성하세요",
        }
    return {"checked": True, "clear": True, "low": [], "reason": "clear"}


def _probe_video_luma(mp4_path: Path) -> tuple[int, list[float]]:
    try:  # PyAV (libdav1d) decodes LeRobot AV1 mp4s when pip opencv-python lacks AV1 support.
        import av

        with av.open(str(mp4_path)) as c:
            if c.streams.video:
                n = int(c.streams.video[0].frames or 0)
                targets = {0, min(n // 2, 150), min(max(0, n - 1), 300)} if n > 0 else {0, 15, 30}
                limit = max(targets)
                means, seen = [], 0
                for idx, fr in enumerate(c.decode(video=0)):
                    seen = idx + 1
                    if idx in targets:
                        means.append(float(fr.to_ndarray(format="rgb24").mean()))
                    if idx >= limit:
                        break
                if means:
                    return (n or seen), means
    except Exception:
        pass

    import cv2

    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        return 0, []
    try:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        means = []
        for idx in (0, max(0, n // 2), max(0, n - 1)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if ok and fr is not None:
                means.append(float(fr.mean()))
        return n, means
    finally:
        cap.release()


def check_dataset_cameras(dataset_dir: Path, *, require_top: bool = True, probe=None) -> dict:
    """Fail closed before transfer/intake/upload when top video is missing, undecodable, or black."""
    dataset_dir = Path(dataset_dir)
    info_p = dataset_dir / "meta" / "info.json"
    info = {}
    if info_p.is_file():
        try:
            loaded = json.loads(info_p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                info = loaded
        except (OSError, ValueError):
            info = {}
    features = info.get("features") if isinstance(info.get("features"), dict) else {}
    declared = [
        k for k, v in features.items()
        if isinstance(v, dict) and (v.get("dtype") == "video" or k.startswith("observation.images."))
    ]
    videos_dir = dataset_dir / "videos"
    if not declared and not videos_dir.is_dir():
        return {"checked": False, "cameras": {}}
    if not declared:
        declared = sorted(p.name for p in videos_dir.iterdir() if p.is_dir())
    if require_top and "observation.images.top" not in declared:
        raise ValueError("top 카메라 영상(observation.images.top)이 없는 데이터셋은 전송·업로드할 수 없습니다")
    probe_fn = probe or _probe_video_luma
    summary = {}
    for key in declared:
        mp4s = sorted((videos_dir / key).rglob("*.mp4")) if (videos_dir / key).is_dir() else []
        if not mp4s:
            raise ValueError(f"{key} 영상 파일(.mp4)이 없어 전송·업로드할 수 없습니다")
        max_luma = 0.0
        for mp4 in mp4s:
            if mp4.stat().st_size <= 0:
                raise ValueError(f"{key} 영상 파일이 비어 있습니다 ({mp4.name})")
            n_frames, means = probe_fn(mp4)
            if n_frames <= 0 or not means:
                raise ValueError(f"{key} 영상을 디코딩할 수 없습니다 ({mp4.name})")
            luma = max(float(m) for m in means)
            if luma < 2.0:
                raise ValueError(f"{key} 영상이 검은 화면(카메라 미수신, max_luma={luma:.1f})이라 전송·업로드할 수 없습니다")
            max_luma = max(max_luma, luma)
        summary[key] = {"files": len(mp4s), "max_luma": round(max_luma, 1)}
    return {"checked": True, "cameras": summary}
