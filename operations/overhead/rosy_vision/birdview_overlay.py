"""Annotated bird-view map-plane preview overlay (metric grid, lanes, places, robots, arms).

Display-only preview copy layered atop the D-560 calibrated top-down map plane.
All labels use crisp ASCII glyphs for OpenCV ``FONT_HERSHEY_SIMPLEX`` rendering.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping

import cv2
import numpy as np

from .rectify import MapPlane, _decode, _encode

_GRID_STEP_M = 0.5
_AXIS_COLOR = (180, 195, 110)
_GRID_COLOR = (95, 105, 95)
_LANE_COLOR = (235, 190, 80)
_PLACE_COLOR = (0, 210, 255)
_ARM_COLOR = (60, 155, 255)
_ROBOT_COLOR = (100, 235, 110)
_TEXT_BG = (18, 22, 26)
_TEXT_FG = (235, 240, 245)


def _finite_xy(item: Mapping, x_key: str = "x", y_key: str = "y") -> tuple[float, float] | None:
    x, y = item.get(x_key), item.get(y_key)
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    fx, fy = float(x), float(y)
    return (fx, fy) if math.isfinite(fx) and math.isfinite(fy) else None


def _ascii_label(value: object, fallback: str, max_len: int = 24) -> str:
    raw = value if isinstance(value, str) else ""
    clean = "".join(ch for ch in raw.strip() if 32 <= ord(ch) <= 126)[:max_len].strip()
    if clean:
        return clean
    fb = "".join(ch for ch in str(fallback).strip() if 32 <= ord(ch) <= 126)[:max_len].strip()
    return fb or "?"


def _to_px(x: float, y: float, min_x: float, max_y: float, ppm: float) -> tuple[int, int]:
    return int(round((x - min_x) * ppm)), int(round((max_y - y) * ppm))


def _in_frame(u: int, v: int, width: int, height: int, margin: int = 24) -> bool:
    return -margin <= u < width + margin and -margin <= v < height + margin


def _put_tag(img: np.ndarray, text: str, x: int, y: int, fg: tuple[int, int, int], scale: float = 0.42) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), bl = cv2.getTextSize(text, font, scale, 1)
    h, w = img.shape[:2]
    px = max(2, min(w - tw - 6, x))
    py = max(th + 4, min(h - bl - 4, y))
    cv2.rectangle(img, (px - 2, py - th - 3), (px + tw + 3, py + bl + 2), _TEXT_BG, -1)
    cv2.putText(img, text, (px, py), font, scale, fg, 1, cv2.LINE_AA)


def overlay_signature(
    places: Iterable[Mapping] = (),
    robots: Iterable[Mapping] = (),
    arms: Iterable[Mapping] = (),
) -> str:
    """Compact deterministic cache key (1 cm quantisation) for dynamic overlay entities."""
    parts: list[str] = []
    for p in list(places)[:64]:
        if not isinstance(p, Mapping):
            continue
        xy = _finite_xy(p)
        if xy:
            parts.append(f"p:{p.get('id') or p.get('name') or ''}:{round(xy[0], 2)},{round(xy[1], 2)}")
    for r in sorted((r for r in robots if isinstance(r, Mapping)), key=lambda item: str(item.get("robot_id") or ""))[:32]:
        xy = _finite_xy(r)
        if xy:
            yaw = r.get("yaw")
            yv = round(float(yaw), 2) if isinstance(yaw, (int, float)) and not isinstance(yaw, bool) and math.isfinite(yaw) else ""
            parts.append(f"r:{r.get('robot_id') or ''}:{round(xy[0], 2)},{round(xy[1], 2)},{yv}")
    for a in sorted((a for a in arms if isinstance(a, Mapping)), key=lambda item: str(item.get("target_id") or ""))[:16]:
        bxy = _finite_xy(a, "base_x", "base_y")
        if bxy:
            hxy = _finite_xy(a, "head_x", "head_y")
            hs = f">{round(hxy[0], 2)},{round(hxy[1], 2)}" if hxy else ""
            parts.append(f"a:{a.get('target_id') or ''}:{round(bxy[0], 2)},{round(bxy[1], 2)}{hs}")
    return "|".join(parts)


def render_map_overlay_jpeg(
    plane: MapPlane,
    *,
    map_paint=None,
    places: Iterable[Mapping] = (),
    robots: Iterable[Mapping] = (),
    arms: Iterable[Mapping] = (),
    observed_fraction: float | None = None,
) -> bytes:
    """Render an annotated bird-view JPEG on top of an already-warped D-560 ``MapPlane``."""
    img = _decode(plane.jpeg).copy()
    height, width = img.shape[:2]
    min_x, min_y, max_x, max_y = plane.bounds_m
    ppm = plane.px_per_m
    if not (all(math.isfinite(v) for v in (min_x, min_y, max_x, max_y, ppm)) and ppm > 0 and max_x > min_x and max_y > min_y):
        return _encode(img)

    # 1. Optional road/lane paint overlay from MapPaint STL
    if map_paint is not None and hasattr(map_paint, "render"):
        try:
            mat_2x3 = np.array([[ppm, 0.0, -min_x * ppm - 0.5],
                                [0.0, -ppm, max_y * ppm - 0.5]], dtype=float)
            mask = map_paint.render(mat_2x3, (width, height))
            lit = mask > 0
            if np.any(lit):
                lane = np.array(_LANE_COLOR, dtype=np.float32) * 0.25
                img[lit] = np.clip(0.75 * img[lit] + lane, 0, 255).astype(np.uint8)
        except Exception:
            pass

    # 2. 0.5 m metric grid and X/Y axis crosshairs + border tick labels
    if (max_x - min_x) / _GRID_STEP_M <= 200 and (max_y - min_y) / _GRID_STEP_M <= 200:
        gx = math.ceil(min_x / _GRID_STEP_M) * _GRID_STEP_M
        while gx <= max_x + 1e-6:
            u = int(round((gx - min_x) * ppm))
            if 0 <= u < width:
                is_axis = abs(gx) < 1e-6
                cv2.line(img, (u, 0), (u, height - 1), _AXIS_COLOR if is_axis else _GRID_COLOR, 2 if is_axis else 1)
                lbl = "0.0m" if is_axis else f"{gx:.1f}m"
                _put_tag(img, lbl, u - 14, height - 8, _AXIS_COLOR if is_axis else _TEXT_FG, 0.36)
            gx += _GRID_STEP_M

        gy = math.ceil(min_y / _GRID_STEP_M) * _GRID_STEP_M
        while gy <= max_y + 1e-6:
            v = int(round((max_y - gy) * ppm))
            if 0 <= v < height:
                is_axis = abs(gy) < 1e-6
                cv2.line(img, (0, v), (width - 1, v), _AXIS_COLOR if is_axis else _GRID_COLOR, 2 if is_axis else 1)
                lbl = "0.0m" if is_axis else f"{gy:.1f}m"
                _put_tag(img, lbl, 6, v + 4, _AXIS_COLOR if is_axis else _TEXT_FG, 0.36)
            gy += _GRID_STEP_M

    if min_x <= 0.0 <= max_x and min_y <= 0.0 <= max_y:
        ou, ov = _to_px(0.0, 0.0, min_x, max_y, ppm)
        cv2.drawMarker(img, (ou, ov), _AXIS_COLOR, cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)

    # 3. Map places (waypoints / charge bays / stands / stations)
    for item in list(places)[:64]:
        if not isinstance(item, Mapping):
            continue
        xy = _finite_xy(item)
        if xy is None:
            continue
        u, v = _to_px(xy[0], xy[1], min_x, max_y, ppm)
        if not _in_frame(u, v, width, height):
            continue
        name = _ascii_label(item.get("name") or item.get("id"), str(item.get("id") or "P"), 14)
        cv2.drawMarker(img, (u, v), _PLACE_COLOR, cv2.MARKER_DIAMOND, 10, 2, cv2.LINE_AA)
        _put_tag(img, f"{name} ({xy[0]:.2f},{xy[1]:.2f})", u + 7, v - 6, _PLACE_COLOR, 0.36)

    # 4. OMX-AI arm anchors & head vectors
    for item in list(arms)[:16]:
        if not isinstance(item, Mapping):
            continue
        bxy = _finite_xy(item, "base_x", "base_y")
        if bxy is None:
            continue
        bu, bv = _to_px(bxy[0], bxy[1], min_x, max_y, ppm)
        if not _in_frame(bu, bv, width, height):
            continue
        tid = _ascii_label(item.get("target_id") or item.get("label"), "arm", 16)
        cv2.circle(img, (bu, bv), 8, _ARM_COLOR, 2, cv2.LINE_AA)
        hxy = _finite_xy(item, "head_x", "head_y")
        if hxy is not None:
            hu, hv = _to_px(hxy[0], hxy[1], min_x, max_y, ppm)
            if _in_frame(hu, hv, width, height, margin=2000):
                cv2.line(img, (bu, bv), (hu, hv), _ARM_COLOR, 2, cv2.LINE_AA)
                cv2.circle(img, (hu, hv), 4, _ARM_COLOR, -1, cv2.LINE_AA)
        _put_tag(img, f"{tid} ({bxy[0]:.2f},{bxy[1]:.2f})", bu + 10, bv - 6, _ARM_COLOR, 0.38)

    # 5. Live tracked robots (position + heading arrow)
    for item in list(robots)[:32]:
        if not isinstance(item, Mapping):
            continue
        xy = _finite_xy(item)
        if xy is None:
            continue
        u, v = _to_px(xy[0], xy[1], min_x, max_y, ppm)
        if not _in_frame(u, v, width, height):
            continue
        rid = _ascii_label(item.get("robot_id"), "robot", 16)
        cv2.circle(img, (u, v), 11, _ROBOT_COLOR, 2, cv2.LINE_AA)
        yaw = item.get("yaw")
        if isinstance(yaw, (int, float)) and not isinstance(yaw, bool) and math.isfinite(yaw):
            hx = xy[0] + 0.16 * math.cos(float(yaw))
            hy = xy[1] + 0.16 * math.sin(float(yaw))
            hu, hv = _to_px(hx, hy, min_x, max_y, ppm)
            cv2.arrowedLine(img, (u, v), (hu, hv), _ROBOT_COLOR, 2, cv2.LINE_AA, tipLength=0.35)
        _put_tag(img, f"{rid} ({xy[0]:.2f},{xy[1]:.2f})", u + 12, v + 4, _ROBOT_COLOR, 0.40)

    # 6. Top-left HUD banner & bottom-right 0.5 m scale bar
    obs_text = f" | obs={round(observed_fraction * 100)}%" if observed_fraction is not None and math.isfinite(observed_fraction) else ""
    hud = f"BIRDVIEW MAP+COORD | +X-> +Y^ | rev={_ascii_label(plane.revision, 'cal', 28)}{obs_text}"
    _put_tag(img, hud, 8, 20, _TEXT_FG, 0.44)
    bar_px = int(round(_GRID_STEP_M * ppm))
    if 20 <= bar_px < width // 2:
        bx1, bx0, by = width - 16, width - 16 - bar_px, height - 24
        cv2.line(img, (bx0, by), (bx1, by), _TEXT_FG, 2)
        cv2.line(img, (bx0, by - 4), (bx0, by + 4), _TEXT_FG, 2)
        cv2.line(img, (bx1, by - 4), (bx1, by + 4), _TEXT_FG, 2)
        _put_tag(img, "0.5 m", bx0, by - 8, _TEXT_FG, 0.36)

    return _encode(img)
