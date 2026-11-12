"""Vision-based anchored pose + head estimation for Pinky robots and 4x zoomed ROI continuous tracking for OMX-AI arms."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
import math
import threading
import time

import cv2
import numpy as np

from core_common.protocol.sightings import SiteSightingPayload
from rosy_vision.track import geometry
from rosy_vision.track.model import Calibration, Detection, DetectorResult, ROBOT_TOP_HEIGHT_M

OMX_HEAD_HEIGHT_M = 0.11
PINKY_HEAD_OFFSET_M = 0.055
SIGHTING_MIN_INTERVAL_S = 0.22


@dataclass
class TargetAnchor:
    target_id: str
    kind: str  # "pinky" | "omx_ai"
    label: str
    base_x: float
    base_y: float
    base_yaw: float
    reach_m: float = 0.28
    zoom: int = 4
    marker_id: int | None = None
    updated_at: float = 0.0


@dataclass
class TrackedHeadState:
    target_id: str
    kind: str
    label: str
    base_x: float
    base_y: float
    base_yaw: float
    head_x: float
    head_y: float
    head_yaw: float
    extension_m: float
    vx: float = 0.0
    vy: float = 0.0
    speed_mps: float = 0.0
    moving: bool = False
    confidence: float = 0.0
    zoom: int = 4
    reach_m: float = 0.28
    captured_at: float = 0.0
    roi_jpeg: bytes | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {"target_id": self.target_id, "kind": self.kind, "label": self.label, "base_x": round(self.base_x, 4),
                "base_y": round(self.base_y, 4), "base_yaw": round(self.base_yaw, 4), "head_x": round(self.head_x, 4),
                "head_y": round(self.head_y, 4), "head_yaw": round(self.head_yaw, 4), "extension_m": round(self.extension_m, 4),
                "speed_mps": round(self.speed_mps, 4), "moving": bool(self.moving), "confidence": round(self.confidence, 3),
                "zoom": int(self.zoom), "reach_m": round(self.reach_m, 3), "captured_at": round(self.captured_at, 3)}


def default_anchors() -> dict[str, TargetAnchor]:
    now = time.time()
    return {
        "rosy_46": TargetAnchor("rosy_46", "pinky", "rosy-pinky-b8xy (rosy_46)", -0.4184, 0.380, -1.5708, 0.18, 3, 46, now),
        "rosy_45": TargetAnchor("rosy_45", "pinky", "rosy-pinky-y8xs (rosy_45)", -0.1896, 0.380, -1.5708, 0.18, 3, 45, now),
        "rosy_42": TargetAnchor("rosy_42", "pinky", "rosy-pinky-geg6 (rosy_42)", 0.6987, -0.2512, 3.1416, 0.18, 3, 42, now),
        "arm_a": TargetAnchor("arm_a", "omx_ai", "OMX-AI #1 (북동 상차 · Arm A)", 0.551, 0.365, -1.5708, 0.28, 4, None, now),
        "arm_b": TargetAnchor("arm_b", "omx_ai", "OMX-AI #2 (동북 상차 · Arm B)", 0.956, 0.370, -1.5708, 0.28, 4, None, now),
        "arm_s": TargetAnchor("arm_s", "omx_ai", "OMX-AI #3 (동남 분류 · Arm S)", 0.960, -0.035, 3.1416, 0.28, 4, None, now),
    }


def _wrap_angle(angle: float) -> float: return math.atan2(math.sin(angle), math.cos(angle))
def _blend_angle(a: float, b: float, weight_b: float) -> float: return _wrap_angle(a + weight_b * _wrap_angle(b - a))


class AnchorHeadTracker:
    """Tracks Pinky pose+head and 4x zoomed OMX-AI arm head/gripper continuously from anchored map positions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._anchors: dict[str, TargetAnchor] = default_anchors()
        self._states: dict[str, TrackedHeadState] = {}
        self._last_sighting_at: dict[str, float] = {}

    def update_from_config(self, config: Mapping | None) -> None:
        if not isinstance(config, Mapping):
            return
        robot_markers = config.get("robot_markers") if isinstance(config.get("robot_markers"), Mapping) else {}
        anchors_cfg = config.get("anchors") if isinstance(config.get("anchors"), Sequence) else ()
        occupied_cfg = config.get("occupied") if isinstance(config.get("occupied"), Sequence) else ()
        with self._lock:
            for rid, mid in robot_markers.items():
                if rid in self._anchors and isinstance(mid, int):
                    self._anchors[rid].marker_id = mid
            for item in anchors_cfg:
                if not isinstance(item, Mapping):
                    continue
                tid = str(item.get("target_id") or "")
                if not tid:
                    continue
                try:
                    bx, by = float(item["base_x"]), float(item["base_y"])
                    byaw = float(item.get("base_yaw", -1.5708))
                    reach = float(item.get("reach_m", 0.28 if tid.startswith("arm_") else 0.38))
                    zoom = int(item.get("zoom", 4 if tid.startswith("arm_") else 3))
                    updated_at = float(item.get("updated_at") or 0.0)
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(math.isfinite(v) for v in (bx, by, byaw, reach)):
                    continue
                kind = str(item.get("kind") or ("omx_ai" if tid.startswith("arm_") else "pinky"))
                label = str(item.get("label") or tid)
                existing = self._anchors.get(tid)
                if existing is None or updated_at >= existing.updated_at:
                    self._anchors[tid] = TargetAnchor(
                        target_id=tid, kind=kind, label=label, base_x=bx, base_y=by, base_yaw=byaw,
                        reach_m=max(0.12, min(0.80, reach)), zoom=max(2, min(6, zoom)),
                        marker_id=robot_markers.get(tid, existing.marker_id if existing else None),
                        updated_at=updated_at,
                    )
                    if (existing is None or math.hypot(bx - existing.base_x, by - existing.base_y) > 0.03
                            or abs(_wrap_angle(byaw - existing.base_yaw)) > 0.08):
                        self._states.pop(tid, None)
            for occ in occupied_cfg:
                if not isinstance(occ, Mapping):
                    continue
                rid, basis = occ.get("robot_id"), occ.get("basis")
                if isinstance(rid, str) and rid in self._anchors and basis == "operator_pin":
                    try:
                        ox, oy = float(occ["x"]), float(occ["y"])
                        if math.isfinite(ox) and math.isfinite(oy):
                            anc = self._anchors[rid]
                            if math.hypot(ox - anc.base_x, oy - anc.base_y) > 0.04:
                                anc.base_x, anc.base_y = ox, oy
                    except (KeyError, TypeError, ValueError):
                        pass

    def step(
        self, image: np.ndarray, captured_at: float, calibration: Calibration, result: DetectorResult, *,
        source_id: str, map_id: str, processor_revision: str, seq: int, already_sighted: Collection[str] = (),
    ) -> tuple[DetectorResult, tuple[SiteSightingPayload, ...], list[dict]]:
        if image is None or calibration is None:
            return result, (), self.snapshot_list()
        img_to_map = geometry.as_matrix(calibration.image_to_map)
        try:
            map_to_img = np.linalg.inv(img_to_map)
        except np.linalg.LinAlgError:
            return result, (), self.snapshot_list()

        camera_pose = geometry.camera_from_homography(img_to_map, calibration.image_size, calibration.hfov_deg)
        scale_x = image.shape[1] / calibration.image_size[0]
        scale_y = image.shape[0] / calibration.image_size[1]

        with self._lock:
            anchors = list(self._anchors.values())
        omx_anchors = [a for a in anchors if a.kind == "omx_ai"]
        pinky_anchors = [a for a in anchors if a.kind == "pinky"]

        for anchor in omx_anchors:
            st = self._track_omx_target(image, captured_at, anchor, img_to_map, map_to_img, camera_pose, scale_x, scale_y)
            if st is not None:
                with self._lock:
                    self._states[anchor.target_id] = st

        raw_detections = list(result.detections) if result.status == "OK" else []
        filtered_detections: list[Detection] = [
            det for det in raw_detections
            if det.marker_id is not None or not any(
                math.hypot(det.x - omx.base_x, det.y - omx.base_y) <= omx.reach_m + 0.06 for omx in omx_anchors
            )
        ]

        new_sightings: list[SiteSightingPayload] = []
        for anchor in pinky_anchors:
            st, matched_det = self._track_pinky_target(
                image, captured_at, anchor, filtered_detections, img_to_map, map_to_img,
                camera_pose, scale_x, scale_y, calibration.track_bounds_m,
            )
            if st is not None:
                with self._lock:
                    self._states[anchor.target_id] = st
                    self._anchors[anchor.target_id].base_x = st.base_x
                    self._anchors[anchor.target_id].base_y = st.base_y
                    self._anchors[anchor.target_id].base_yaw = st.head_yaw
                if matched_det is not None:
                    filtered_detections = [
                        d for d in filtered_detections
                        if d.marker_id is not None or math.hypot(d.x - st.base_x, d.y - st.base_y) > 0.14
                    ]
                    if not any(d.marker_id == matched_det.marker_id for d in filtered_detections if matched_det.marker_id is not None):
                        filtered_detections.insert(0, matched_det)
                last_sent = self._last_sighting_at.get(anchor.target_id, 0.0)
                if (anchor.target_id not in already_sighted and st.confidence >= 0.45
                        and captured_at - last_sent >= SIGHTING_MIN_INTERVAL_S):
                    self._last_sighting_at[anchor.target_id] = captured_at
                    new_sightings.append(SiteSightingPayload(
                        robot_id=anchor.target_id, x=round(st.base_x, 4), y=round(st.base_y, 4), yaw=round(st.head_yaw, 4),
                        captured_at=captured_at, seq=seq, map_id=map_id, calibration_revision=calibration.revision,
                        processor_revision=processor_revision, quality=round(st.confidence, 3),
                        corner_marker_ids=None, calibration_source="approved_record",
                    ))

        updated_result = DetectorResult(tuple(filtered_detections), "OK") if result.status == "OK" or filtered_detections else result
        return updated_result, tuple(new_sightings), self.snapshot_list()

    def _track_omx_target(
        self, image: np.ndarray, captured_at: float, anchor: TargetAnchor, img_to_map: np.ndarray,
        map_to_img: np.ndarray, camera_pose: tuple[float, float, float] | None, scale_x: float, scale_y: float,
    ) -> TrackedHeadState | None:
        h, w = image.shape[:2]
        pts = geometry.apply(map_to_img, [
            (anchor.base_x, anchor.base_y),
            (anchor.base_x + anchor.reach_m, anchor.base_y),
            (anchor.base_x, anchor.base_y + anchor.reach_m),
        ])
        if not np.all(np.isfinite(pts)):
            return None
        u_base, v_base = float(pts[0][0] * scale_x), float(pts[0][1] * scale_y)
        r_px = int(max(48, min(120, max(
            math.hypot((pts[1][0] - pts[0][0]) * scale_x, (pts[1][1] - pts[0][1]) * scale_y),
            math.hypot((pts[2][0] - pts[0][0]) * scale_x, (pts[2][1] - pts[0][1]) * scale_y),
        ) * 1.15)))
        x0, y0 = max(0, int(round(u_base)) - r_px), max(0, int(round(v_base)) - r_px)
        x1, y1 = min(w, int(round(u_base)) + r_px), min(h, int(round(v_base)) + r_px)
        if x1 - x0 < 20 or y1 - y0 < 20:
            return None

        patch = image[y0:y1, x0:x1]
        zoom = max(2, int(anchor.zoom or 4))
        zoomed = cv2.resize(patch, (0, 0), fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        zh, zw = zoomed.shape[:2]
        ub_z, vb_z = (u_base - x0) * zoom, (v_base - y0) * zoom

        gray = cv2.cvtColor(zoomed, cv2.COLOR_BGR2GRAY)
        thresh_val = max(42.0, min(82.0, float(np.median(gray)) * 0.52))
        mask = (gray < thresh_val).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_cnts = [c for c in cnts if cv2.contourArea(c) >= 180 * (zoom / 4.0) ** 2]
        chosen_cnt = (
            max(valid_cnts, key=lambda c: cv2.contourArea(c) - abs(cv2.pointPolygonTest(c, (float(ub_z), float(vb_z)), True)) * 18.0)
            if valid_cnts else None
        )

        head_uz, head_vz, confidence = ub_z, vb_z, 0.35
        if chosen_cnt is not None:
            pts_z = chosen_cnt.reshape(-1, 2).astype(np.float64)
            dists = np.hypot(pts_z[:, 0] - ub_z, pts_z[:, 1] - vb_z)
            max_dist = float(np.max(dists)) if len(dists) else 0.0
            if max_dist > 8.0:
                tip_pts_z = pts_z[dists >= max(6.0, np.percentile(dists, 86))]
                head_uz, head_vz = float(np.mean(tip_pts_z[:, 0])), float(np.mean(tip_pts_z[:, 1]))
                confidence = min(0.98, 0.55 + min(0.43, max_dist / (r_px * zoom * 0.85)))

        u_head_cal, v_head_cal = (x0 + head_uz / zoom) / scale_x, (y0 + head_vz / zoom) / scale_y
        mapped_head = geometry.apply(img_to_map, [(u_head_cal, v_head_cal)])[0]
        raw_hx, raw_hy = float(mapped_head[0]), float(mapped_head[1])
        if camera_pose is not None and math.isfinite(raw_hx) and math.isfinite(raw_hy):
            try:
                raw_hx, raw_hy = geometry.parallax_correct((raw_hx, raw_hy), camera_pose, OMX_HEAD_HEIGHT_M)
            except ValueError:
                pass

        dx_m, dy_m = raw_hx - anchor.base_x, raw_hy - anchor.base_y
        ext_m = math.hypot(dx_m, dy_m)
        if ext_m > anchor.reach_m * 1.25 and ext_m > 1e-4:
            scale_ext = (anchor.reach_m * 1.25) / ext_m
            raw_hx, raw_hy = anchor.base_x + dx_m * scale_ext, anchor.base_y + dy_m * scale_ext
            ext_m = math.hypot(raw_hx - anchor.base_x, raw_hy - anchor.base_y)

        raw_yaw = math.atan2(raw_hy - anchor.base_y, raw_hx - anchor.base_x) if ext_m > 0.02 else anchor.base_yaw
        with self._lock:
            prev = self._states.get(anchor.target_id)

        if prev is not None and 0.0 < captured_at - prev.captured_at < 3.0:
            dt = max(0.05, captured_at - prev.captured_at)
            alpha, beta = 0.55, 0.18
            pred_x, pred_y = prev.head_x + prev.vx * dt, prev.head_y + prev.vy * dt
            rx, ry = raw_hx - pred_x, raw_hy - pred_y
            hx, hy = pred_x + alpha * rx, pred_y + alpha * ry
            vx, vy = (1.0 - beta) * prev.vx + (beta / dt) * rx, (1.0 - beta) * prev.vy + (beta / dt) * ry
            hyaw = _blend_angle(prev.head_yaw, raw_yaw, 0.55)
        else:
            hx, hy, vx, vy, hyaw = raw_hx, raw_hy, 0.0, 0.0, raw_yaw

        speed = math.hypot(vx, vy)
        ext_m = math.hypot(hx - anchor.base_x, hy - anchor.base_y)

        vis = zoomed.copy()
        if chosen_cnt is not None:
            cv2.drawContours(vis, [chosen_cnt], -1, (0, 215, 255), 2)
        bx_i, by_i, hx_i, hy_i = int(round(ub_z)), int(round(vb_z)), int(round(head_uz)), int(round(head_vz))
        cv2.circle(vis, (bx_i, by_i), 10, (80, 230, 100), 2)
        cv2.drawMarker(vis, (bx_i, by_i), (80, 230, 100), cv2.MARKER_CROSS, 16, 2)
        cv2.arrowedLine(vis, (bx_i, by_i), (hx_i, hy_i), (255, 220, 0), 3, tipLength=0.18)
        cv2.rectangle(vis, (hx_i - 18, hy_i - 18), (hx_i + 18, hy_i + 18), (255, 255, 0), 2)
        cv2.circle(vis, (hx_i, hy_i), 5, (0, 80, 255), -1)
        cv2.rectangle(vis, (0, 0), (zw, 52), (18, 22, 28), -1)
        cv2.putText(vis, f"{anchor.target_id.upper()} {zoom}x ZOOM | BASE ({anchor.base_x:.2f},{anchor.base_y:.2f})",
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 240, 200), 1, cv2.LINE_AA)
        cv2.putText(vis, f"HEAD ({hx:.3f},{hy:.3f})m | YAW {math.degrees(hyaw):.0f}deg | EXT {ext_m:.2f}m",
                    (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (100, 235, 255), 1, cv2.LINE_AA)
        ok, enc = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 86])
        return TrackedHeadState(
            target_id=anchor.target_id, kind="omx_ai", label=anchor.label,
            base_x=anchor.base_x, base_y=anchor.base_y, base_yaw=anchor.base_yaw,
            head_x=hx, head_y=hy, head_yaw=hyaw, extension_m=ext_m, vx=vx, vy=vy,
            speed_mps=speed, moving=speed >= 0.015, confidence=confidence,
            zoom=zoom, reach_m=anchor.reach_m, captured_at=captured_at,
            roi_jpeg=bytes(enc) if ok else None,
        )

    def _track_pinky_target(
        self, image: np.ndarray, captured_at: float, anchor: TargetAnchor, detections: Sequence[Detection],
        img_to_map: np.ndarray, map_to_img: np.ndarray, camera_pose: tuple[float, float, float] | None,
        scale_x: float, scale_y: float, track_bounds_m: tuple[float, float, float, float],
    ) -> tuple[TrackedHeadState | None, Detection | None]:
        with self._lock:
            prev = self._states.get(anchor.target_id)
        ref_x = prev.base_x if prev is not None else anchor.base_x
        ref_y = prev.base_y if prev is not None else anchor.base_y
        ref_yaw = prev.head_yaw if prev is not None else anchor.base_yaw

        best_blob, best_dist = None, 0.16
        for det in detections:
            d = math.hypot(det.x - ref_x, det.y - ref_y)
            if d < best_dist:
                best_dist, best_blob = d, det

        center_x = best_blob.x if best_blob is not None else ref_x
        center_y = best_blob.y if best_blob is not None else ref_y
        shrink = 1.0 if camera_pose is None else (camera_pose[2] - ROBOT_TOP_HEIGHT_M) / camera_pose[2]
        proj_x = center_x if camera_pose is None else camera_pose[0] + (center_x - camera_pose[0]) / shrink
        proj_y = center_y if camera_pose is None else camera_pose[1] + (center_y - camera_pose[1]) / shrink
        pts = geometry.apply(map_to_img, [(proj_x, proj_y)])
        if not np.all(np.isfinite(pts)):
            return None, None

        h, w = image.shape[:2]
        u_c, v_c, r_px = float(pts[0][0] * scale_x), float(pts[0][1] * scale_y), 46
        x0, y0 = max(0, int(round(u_c)) - r_px), max(0, int(round(v_c)) - r_px)
        x1, y1 = min(w, int(round(u_c)) + r_px), min(h, int(round(v_c)) + r_px)
        if x1 - x0 < 16 or y1 - y0 < 16:
            return None, None

        patch = image[y0:y1, x0:x1]
        zoom = max(2, int(anchor.zoom or 3))
        zoomed = cv2.resize(patch, (0, 0), fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        zh, zw = zoomed.shape[:2]
        uc_z, vc_z = (u_c - x0) * zoom, (v_c - y0) * zoom

        gray = cv2.cvtColor(zoomed, cv2.COLOR_BGR2GRAY)
        dark_mask = (gray < max(38.0, min(80.0, float(np.median(gray)) * 0.56))).astype(np.uint8) * 255
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

        cnts, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        scale_area = (zoom / 3.0) ** 2
        valid_cnts = []
        for c in cnts:
            area = cv2.contourArea(c)
            if not (90.0 * scale_area <= area <= 1500.0 * scale_area):
                continue
            _, _, bw, bh = cv2.boundingRect(c)
            if max(bw, bh) / max(1.0, min(bw, bh)) <= 1.85:
                valid_cnts.append(c)

        measured_x, measured_y, measured_yaw = center_x, center_y, ref_yaw
        confidence = 0.90 if best_blob is not None else 0.78
        chosen_cnt = None
        if valid_cnts:
            chosen_cnt = min(valid_cnts, key=lambda c: math.hypot(
                cv2.moments(c)["m10"] / max(1.0, cv2.moments(c)["m00"]) - uc_z,
                cv2.moments(c)["m01"] / max(1.0, cv2.moments(c)["m00"]) - vc_z,
            ))
            m = cv2.moments(chosen_cnt)
            if m["m00"] > 50.0:
                cx_z, cy_z = m["m10"] / m["m00"], m["m01"] / m["m00"]
                if best_blob is None:
                    u_cal, v_cal = (x0 + cx_z / zoom) / scale_x, (y0 + cy_z / zoom) / scale_y
                    mp = geometry.apply(img_to_map, [(u_cal, v_cal)])[0]
                    if np.all(np.isfinite(mp)):
                        rx, ry = float(mp[0]), float(mp[1])
                        if camera_pose is not None:
                            try:
                                rx, ry = geometry.parallax_correct((rx, ry), camera_pose, ROBOT_TOP_HEIGHT_M)
                            except ValueError:
                                pass
                        if math.hypot(rx - ref_x, ry - ref_y) <= 0.16:
                            measured_x, measured_y = rx, ry
                angle_img = 0.5 * math.atan2(2.0 * m["mu11"], m["mu20"] - m["mu02"])
                du, dv = math.cos(angle_img) * 12.0, math.sin(angle_img) * 12.0
                axis_map = geometry.apply(img_to_map, [
                    ((x0 + cx_z / zoom) / scale_x, (y0 + cy_z / zoom) / scale_y),
                    ((x0 + (cx_z + du) / zoom) / scale_x, (y0 + (cy_z + dv) / zoom) / scale_y),
                ])
                if np.all(np.isfinite(axis_map)):
                    cand_yaw = math.atan2(float(axis_map[1][1] - axis_map[0][1]), float(axis_map[1][0] - axis_map[0][0]))
                    if math.cos(_wrap_angle(cand_yaw - ref_yaw)) < 0.0:
                        cand_yaw = _wrap_angle(cand_yaw + math.pi)
                    measured_yaw = _blend_angle(ref_yaw, cand_yaw, 0.15)

        if 0.02 <= measured_y <= 0.49:
            nearest_bay_x = min((-0.4184, -0.1896, 0.0322), key=lambda bx: abs(measured_x - bx))
            if abs(measured_x - nearest_bay_x) <= 0.095:
                measured_x = 0.72 * nearest_bay_x + 0.28 * measured_x
                if abs(_wrap_angle(measured_yaw - (-1.5708))) <= 0.65:
                    measured_yaw = _blend_angle(measured_yaw, -1.5708, 0.55)
        elif 0.55 <= measured_x <= 0.85 and -0.34 <= measured_y <= -0.16:
            measured_y = 0.72 * (-0.2512) + 0.28 * measured_y
            if abs(_wrap_angle(measured_yaw - math.pi)) <= 0.65:
                measured_yaw = _blend_angle(measured_yaw, math.pi, 0.55)

        min_x, min_y, max_x, max_y = track_bounds_m
        measured_x, measured_y = max(min_x, min(max_x, measured_x)), max(min_y, min(max_y, measured_y))

        if prev is not None and 0.0 < captured_at - prev.captured_at < 3.0:
            dt = max(0.05, captured_at - prev.captured_at)
            alpha, beta = 0.62, 0.20
            pred_x, pred_y = prev.base_x + prev.vx * dt, prev.base_y + prev.vy * dt
            rx, ry = measured_x - pred_x, measured_y - pred_y
            fx, fy = pred_x + alpha * rx, pred_y + alpha * ry
            vx, vy = (1.0 - beta) * prev.vx + (beta / dt) * rx, (1.0 - beta) * prev.vy + (beta / dt) * ry
            speed = math.hypot(vx, vy)
            if speed > 0.035:
                motion_yaw = math.atan2(vy, vx)
                if math.cos(_wrap_angle(motion_yaw - ref_yaw)) >= -0.2:
                    measured_yaw = _blend_angle(measured_yaw, motion_yaw, 0.45)
            fyaw = _blend_angle(prev.head_yaw, measured_yaw, 0.45)
        else:
            fx, fy, vx, vy, speed, fyaw = measured_x, measured_y, 0.0, 0.0, 0.0, measured_yaw

        hx, hy = fx + math.cos(fyaw) * PINKY_HEAD_OFFSET_M, fy + math.sin(fyaw) * PINKY_HEAD_OFFSET_M
        head_proj_x = hx if camera_pose is None else camera_pose[0] + (hx - camera_pose[0]) / shrink
        head_proj_y = hy if camera_pose is None else camera_pose[1] + (hy - camera_pose[1]) / shrink
        h_px = geometry.apply(map_to_img, [(head_proj_x, head_proj_y)])[0]
        uh_z = (float(h_px[0] * scale_x) - x0) * zoom if np.all(np.isfinite(h_px)) else uc_z
        vh_z = (float(h_px[1] * scale_y) - y0) * zoom if np.all(np.isfinite(h_px)) else vc_z - 28

        vis = zoomed.copy()
        if chosen_cnt is not None:
            cv2.drawContours(vis, [chosen_cnt], -1, (80, 220, 120), 2)
        cx_i, cy_i, hx_i, hy_i = int(round(uc_z)), int(round(vc_z)), int(round(uh_z)), int(round(vh_z))
        cv2.circle(vis, (cx_i, cy_i), int(round(12 * zoom / 3.0)), (255, 190, 60), 2)
        cv2.arrowedLine(vis, (cx_i, cy_i), (hx_i, hy_i), (60, 240, 255), 3, tipLength=0.25)
        cv2.circle(vis, (hx_i, hy_i), 5, (0, 90, 255), -1)
        cv2.rectangle(vis, (0, 0), (zw, 48), (18, 22, 28), -1)
        cv2.putText(vis, f"{anchor.target_id.upper()} {zoom}x HEAD TRACKER",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (180, 240, 200), 1, cv2.LINE_AA)
        cv2.putText(vis, f"POSE ({fx:.3f},{fy:.3f})m | HEAD {math.degrees(fyaw):.0f}deg",
                    (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 235, 255), 1, cv2.LINE_AA)
        ok, enc = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 86])
        state = TrackedHeadState(
            target_id=anchor.target_id, kind="pinky", label=anchor.label,
            base_x=fx, base_y=fy, base_yaw=fyaw, head_x=hx, head_y=hy, head_yaw=fyaw,
            extension_m=PINKY_HEAD_OFFSET_M, vx=vx, vy=vy, speed_mps=speed, moving=speed >= 0.02,
            confidence=confidence, zoom=zoom, reach_m=anchor.reach_m, captured_at=captured_at,
            roi_jpeg=bytes(enc) if ok else None,
        )
        det = Detection(
            x=float(fx), y=float(fy),
            footprint_m=float(min(0.105, best_blob.footprint_m) if best_blob is not None else 0.104),
            score=float(max(confidence, best_blob.score if best_blob is not None else 0.92)),
            marker_id=anchor.marker_id,
        )
        return state, det

    def snapshot_list(self) -> list[dict]:
        with self._lock:
            out = []
            for tid, anc in self._anchors.items():
                st = self._states.get(tid)
                if st is not None:
                    out.append(st.to_dict())
                else:
                    ext = 0.08 if anc.kind == "pinky" else 0.14
                    out.append({
                        "target_id": anc.target_id, "kind": anc.kind, "label": anc.label,
                        "base_x": round(anc.base_x, 4), "base_y": round(anc.base_y, 4), "base_yaw": round(anc.base_yaw, 4),
                        "head_x": round(anc.base_x + math.cos(anc.base_yaw) * ext, 4),
                        "head_y": round(anc.base_y + math.sin(anc.base_yaw) * ext, 4),
                        "head_yaw": round(anc.base_yaw, 4), "extension_m": ext,
                        "speed_mps": 0.0, "moving": False, "confidence": 0.0,
                        "zoom": anc.zoom, "reach_m": anc.reach_m, "captured_at": 0.0,
                    })
            return out

    def roi_jpeg(self, target_id: str) -> tuple[bytes | None, float]:
        with self._lock:
            st = self._states.get(target_id)
            return (st.roi_jpeg, st.captured_at) if st is not None and st.roi_jpeg is not None else (None, 0.0)
