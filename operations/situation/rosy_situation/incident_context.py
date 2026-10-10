"""Source-aware, shadow cause drafts for open line-stuck episodes."""

from __future__ import annotations

import math

SOURCE = "analyzer:incident_context@1"
CAUSE = {"lane_lost": "line_marking", "obstacle_ahead": "obstacle"}


class ContextDraft:
    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()

    def __call__(self, snapshot: dict) -> list[dict]:
        pending = (snapshot.get("line_stuck") or {}).get("pending") or []
        robots = {row.get("robot_id"): row for row in (snapshot.get("state") or {}).get("robots") or []}
        context = snapshot.get("incident_context") or {}
        facts = []
        for stuck in pending:
            rid, sid = str(stuck.get("robot_id") or ""), str(stuck.get("stuck_id") or "")
            if not rid or not sid or (rid, sid) in self.seen:
                continue
            self.seen.add((rid, sid))
            row = robots.get(rid) or {}
            state = row.get("state") or {}
            cause = str(stuck.get("cause") or "")
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
            sensors = {key: stuck.get(key) for key in ("rear_state", "rear_clearance_m") if stuck.get(key) is not None}
            sensors["state_age_s"] = row.get("state_age_s")
            sensors["line_follow"] = {key: (state.get("line_follow") or {}).get(key)
                                      for key in ("mode", "stuck")}
            support.append({"source": "core_sensor", "field": "stuck_and_line_follow", "value": sensors})
            missing.append("interpreted_front_image")
            facts.append({"kind": "incident_context", "robot_ids": [rid],
                          "value": {"cause_draft": CAUSE.get(cause, "unknown"), "status": "needs_review",
                                    "support": support, "missing": missing},
                          "confidence": 0.45 if cause in CAUSE else 0.2,
                          "evidence": {"stuck_id": sid, "context_observed_at": snapshot["observed_at"],
                                       "camera_frame_interpreted": False},
                          "source": SOURCE, "observed_at": snapshot["observed_at"], "ttl_s": 3.0})
        return facts
