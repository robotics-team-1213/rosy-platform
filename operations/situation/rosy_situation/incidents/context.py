"""Source-aware, shadow cause drafts for open line-stuck episodes."""

from __future__ import annotations

import math
from rosy_situation.assessment import finite
from rosy_situation.snapshot_assessment import robot_input

SOURCE = "analyzer:incident_context@1"
CAUSE = {"lane_lost": "line_marking", "obstacle_ahead": "obstacle"}


class ContextDraft:
    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()
        self._last: dict[tuple[str, str], float] = {}

    def due(self, stuck: dict, now: float) -> bool:
        key = (str(stuck.get('robot_id') or ''), str(stuck.get('stuck_id') or ''))
        previous = self._last.get(key)
        return bool(all(key) and (previous is None or now < previous or now - previous >= 3.0))

    def __call__(self, snapshot: dict) -> list[dict]:
        pending = (snapshot.get("line_stuck") or {}).get("pending") or []
        robots = {row.get("robot_id"): row for row in (snapshot.get("state") or {}).get("robots") or []}
        context = snapshot.get("incident_context") or {}
        active = {(str(row.get('robot_id') or ''), str(row.get('stuck_id') or '')) for row in pending}
        self._last = {key: value for key, value in self._last.items() if key in active}
        self.seen.intersection_update(active)
        facts = []
        for stuck in pending:
            rid, sid = str(stuck.get("robot_id") or ""), str(stuck.get("stuck_id") or "")
            if not self.due(stuck, snapshot['observed_at']):
                continue
            row = robots.get(rid) or {}
            state = row.get("state") or {}
            age = row.get('state_age_s')
            if row.get('online') is False or ('state_age_s' in row and (not finite(age) or not 0 <= age < 3.0)):
                continue
            line = state.get('line_follow') or {}
            current = line.get('stuck')
            if 'stuck' in line and current is None:
                continue
            if isinstance(current, dict) and current.get('stuck_id') != sid:
                continue
            if 'seq' in state or 'timestamp' in state:
                request = robot_input(row, now=snapshot['observed_at'],
                                      sampled_at=snapshot.get('_state_requested_at', snapshot['observed_at']),
                                      pending=stuck)
                observed = request.evidence[0].observed_at
                if not finite(observed) or not 0 <= snapshot['observed_at'] - observed < 3.0:
                    continue
            self.seen.add((rid, sid))
            self._last[(rid, sid)] = snapshot['observed_at']
            cause = str((current.get('cause') if isinstance(current, dict) else None) or stuck.get("cause") or "")
            camera = (context.get("cameras") or {}).get(rid)
            site_map = context.get("map")
            support = [{"source": "core", "field": "line_stuck.cause", "value": cause}]
            missing = []
            if camera and not camera.get("stale"):
                support.append({"source": "rosy_cam", "field": "sighting", "value": camera})
            else:
                missing.append("fresh_rosy_cam_sighting")
            localization = row.get("localization") or {}
            if site_map and localization.get("trusted") is True and localization.get("legacy") is False:
                pose = (state.get("pose") or {})
                places = site_map.get("places") or []
                try:
                    x, y = float(pose["x"]), float(pose["y"])
                    nearest = min(places, key=lambda p: math.hypot(x - float(p["x"]), y - float(p["y"])))
                    support.append({"source": "fleet_map", "field": "nearest_place", "value": {
                        "map_id": site_map.get("map_id"), "place_id": nearest["id"],
                        "distance_m": round(math.hypot(x - float(nearest["x"]), y - float(nearest["y"])), 2)}})
                except (KeyError, ValueError, TypeError):
                    missing.append("map_place_match")
            else:
                missing.append("trusted_map_pose_and_active_map")
            sensors = {key: stuck.get(key) for key in ("front_clearance_m", "rear_state", "rear_clearance_m")
                       if stuck.get(key) is not None}
            sensors["state_age_s"] = row.get("state_age_s")
            line_follow = state.get("line_follow") or {}
            sensors["line_follow"] = {"mode": line_follow.get("mode"), "stuck": bool(line_follow.get("stuck"))}
            support.append({"source": "core_sensor", "field": "stuck_and_line_follow", "value": sensors})
            missing.append("interpreted_front_image")
            draft = CAUSE.get(cause, "unknown")
            if cause == "no_motion" and isinstance(sensors.get("front_clearance_m"), (int, float)):
                if 0 <= sensors["front_clearance_m"] <= 0.3:
                    draft = "obstacle"
            facts.append({"kind": "incident_context", "robot_ids": [rid],
                          "value": {"cause_draft": draft, "status": "needs_review",
                                    "support": support, "missing": missing},
                          "confidence": 0.45 if cause in CAUSE else 0.35 if draft == "obstacle" else 0.2,
                          "evidence": {"stuck_id": sid, "context_observed_at": snapshot["observed_at"],
                                       "camera_frame_interpreted": False},
                          "source": SOURCE, "observed_at": snapshot["observed_at"], "ttl_s": 3.0})
        return facts
