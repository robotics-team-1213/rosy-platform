"""Overhead tracking anchor configuration, state ingestion, and snapshot rendering."""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

from fleet.server.tracking_match import Track


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _render(track: Track, source_id: str) -> dict:
    return {
        "robot_id": track.robot_id, "status": track.status, "source_id": source_id, "offset_m": track.offset_m,
        "camera": None if track.camera is None else {
            "x": track.camera.x, "y": track.camera.y,
            "footprint_m": track.camera.footprint_m, "score": track.camera.score},
        "pose": None if track.pose is None else {"x": track.pose.x, "y": track.pose.y},
        "pose_frame_verified": None if track.pose is None else track.pose.verified,
    }


def default_anchors(now_init: float) -> dict[str, dict]:
    return {
        "rosy_46": {"target_id": "rosy_46", "kind": "pinky", "label": "rosy-pinky-b8xy (rosy_46)",
                    "base_x": -0.4197, "base_y": 0.470, "base_yaw": -1.5708, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
        "rosy_45": {"target_id": "rosy_45", "kind": "pinky", "label": "rosy-pinky-y8xs (rosy_45)",
                    "base_x": -0.1861, "base_y": 0.470, "base_yaw": -1.5708, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
        "rosy_42": {"target_id": "rosy_42", "kind": "pinky", "label": "rosy-pinky-geg6 (rosy_42)",
                    "base_x": 0.6987, "base_y": -0.2512, "base_yaw": 3.1416, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
        "arm_a": {"target_id": "arm_a", "kind": "omx_ai", "label": "OMX-AI #1 (북동 상차 · Arm A)",
                  "base_x": 0.551, "base_y": 0.365, "base_yaw": -1.5708, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
        "arm_b": {"target_id": "arm_b", "kind": "omx_ai", "label": "OMX-AI #2 (동북 상차 · Arm B)",
                  "base_x": 0.956, "base_y": 0.370, "base_yaw": -1.5708, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
        "arm_s": {"target_id": "arm_s", "kind": "omx_ai", "label": "OMX-AI #3 (동남 분류 · Arm S)",
                  "base_x": 0.960, "base_y": -0.035, "base_yaw": 3.1416, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
    }


def anchor_configs(self) -> list[dict]:
    return [dict(item) for item in self._anchors.values()]


def accept_anchors(self, authorization: Optional[str], body: Mapping) -> dict:
    source = self.authenticate(authorization)
    now = self._clock()
    targets = body.get("targets") if isinstance(body, Mapping) else None
    if not isinstance(targets, Sequence):
        return {"accepted": False, "count": 0}
    count = 0
    for row in targets:
        if not isinstance(row, Mapping):
            continue
        tid = str(row.get("target_id") or "")
        if not tid:
            continue
        self._anchor_states[tid] = {**dict(row), "source_id": source.source_id, "received_at": now}
        count += 1
    return {"accepted": True, "source_id": source.source_id, "count": count}


def set_anchor(self, body: Mapping, *, principal_id: str, error_cls: type[Exception]) -> dict:
    tid = str(body.get("target_id") or "").strip()
    if not tid:
        raise error_cls(422, "INVALID_ANCHOR", "target_id is required")
    try:
        bx, by = float(body["base_x"]), float(body["base_y"])
        byaw = float(body.get("base_yaw", -1.5708))
        reach = float(body.get("reach_m", 0.28 if tid.startswith("arm_") else 0.38))
        zoom = int(body.get("zoom", 4 if tid.startswith("arm_") else 3))
    except (KeyError, TypeError, ValueError) as exc:
        raise error_cls(422, "INVALID_ANCHOR", str(exc)) from exc
    if not _finite(bx, by, byaw, reach):
        raise error_cls(422, "INVALID_ANCHOR", "anchor coordinates must be finite")
    now = self._clock()
    prior = self._anchors.get(tid, {})
    kind = str(body.get("kind") or prior.get("kind") or ("omx_ai" if tid.startswith("arm_") else "pinky"))
    label = str(body.get("label") or prior.get("label") or tid)
    self._anchors[tid] = {
        "target_id": tid, "kind": kind, "label": label,
        "base_x": round(bx, 4), "base_y": round(by, 4), "base_yaw": round(byaw, 4),
        "reach_m": round(max(0.12, min(0.80, reach)), 3), "zoom": max(2, min(6, zoom)),
        "updated_at": now, "updated_by": principal_id,
    }
    return self._anchors[tid]


def anchors_snapshot(self, now: Optional[float] = None) -> dict:
    if now is None:
        now = self._clock()
    out = []
    for tid, anc in self._anchors.items():
        live = self._anchor_states.get(tid)
        fresh = live is not None and (now - float(live.get("received_at") or 0.0) <= self.lease_s * 2.0)
        ext = 0.08 if anc.get("kind") == "pinky" else 0.14
        byaw = float(anc.get("base_yaw") or -1.5708)
        default_hx = round(float(anc["base_x"]) + math.cos(byaw) * ext, 4)
        default_hy = round(float(anc["base_y"]) + math.sin(byaw) * ext, 4)
        row = {
            **anc,
            "head_x": round(float(live["head_x"]), 4) if fresh and "head_x" in live else default_hx,
            "head_y": round(float(live["head_y"]), 4) if fresh and "head_y" in live else default_hy,
            "head_yaw": round(float(live["head_yaw"]), 4) if fresh and "head_yaw" in live else round(byaw, 4),
            "extension_m": round(float(live.get("extension_m", ext)), 4) if fresh else ext,
            "speed_mps": round(float(live.get("speed_mps", 0.0)), 4) if fresh else 0.0,
            "moving": bool(live.get("moving", False)) if fresh else False,
            "confidence": round(float(live.get("confidence", 0.0)), 3) if fresh else 0.0,
            "source_id": live.get("source_id", "ceiling_north") if live else "ceiling_north",
            "age_ms": round(max(0.0, (now - float(live.get("captured_at") or now)) * 1000.0)) if fresh else None,
            "live": fresh,
        }
        if anc.get("kind") == "pinky" and fresh:
            row["base_x"] = round(float(live.get("base_x", anc["base_x"])), 4)
            row["base_y"] = round(float(live.get("base_y", anc["base_y"])), 4)
        cell = self._omx_cells.get(tid)
        if cell and cell.get("reachable"):
            row["cell_status"] = f"{cell.get('state', 'IDLE')}{' · 토크ON' if cell.get('torque') else ''}"
            if cell.get("joints_summary"):
                row["joints_summary"] = cell["joints_summary"]
        out.append(row)
    return {"ts": now, "targets": out}
