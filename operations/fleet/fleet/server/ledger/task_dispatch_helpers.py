"""Road-lane graph to Nav2 planning helper for task dispatch routes."""

from __future__ import annotations

import importlib as _il
import math as _math

from fastapi import HTTPException, Request


async def compute_road_plan(console, request: Request, robot_id: str, target_x: float, target_y: float,
                            target_yaw: float | None, place_id: str | None, label: str) -> dict:
    _trip_mod = _il.import_module(".".join(("fleet", "routing", "trip")))
    _exec_mod = _il.import_module(".".join(("fleet", "routing", "execute")))
    PlanRequest, plan_trip = _trip_mod.PlanRequest, _trip_mod.plan_trip
    plan_body = _exec_mod.plan_body

    site_maps = getattr(request.app.state, "site_maps", None)
    runner = getattr(request.app.state, "trip_runner", None)
    active = site_maps.active() if site_maps is not None else None

    site_pose = None
    if runner is not None:
        try:
            mp = await runner.map_pose(robot_id)
            if mp is not None and mp.x is not None and mp.y is not None:
                site_pose = (float(mp.x), float(mp.y), float(mp.yaw if mp.yaw is not None else 0.0))
        except Exception:
            pass
    if site_pose is None:
        try:
            tp = await console.trusted_map_pose(robot_id)
            if tp is not None:
                site_pose = (float(tp[0]), float(tp[1]), float(tp[2] if tp[2] is not None else 0.0))
        except Exception:
            pass
    if site_pose is None or not all(_math.isfinite(v) for v in site_pose):
        raise HTTPException(status_code=409, detail={
            "code": "ROUTE_POSE_UNTRUSTED", "message": "road-nav2 needs a LOCALIZED map pose"})

    explicit_yaw = target_yaw
    if target_yaw is None:
        target_yaw = _math.atan2(target_y - site_pose[1], target_x - site_pose[0])

    local_pose = None
    try:
        snap = await console.snapshot()
        for r in (snap.get("robots") or []):
            if r.get("robot_id") == robot_id and isinstance(r.get("state"), dict):
                p = r["state"].get("pose")
                if isinstance(p, dict) and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float)):
                    local_pose = (float(p["x"]), float(p["y"]), float(p.get("yaw") or 0.0))
                    break
    except Exception:
        pass
    if local_pose is None:
        local_pose = site_pose

    d_yaw = _math.atan2(_math.sin(local_pose[2] - site_pose[2]), _math.cos(local_pose[2] - site_pose[2]))
    cos_d, sin_d = _math.cos(d_yaw), _math.sin(d_yaw)

    def _site_to_nav2(sx: float, sy: float, syaw: float) -> tuple[float, float, float]:
        dx, dy = sx - site_pose[0], sy - site_pose[1]
        nx = local_pose[0] + cos_d * dx - sin_d * dy
        ny = local_pose[1] + sin_d * dx + cos_d * dy
        nyaw = _math.atan2(_math.sin(syaw + d_yaw), _math.cos(syaw + d_yaw))
        return round(nx, 4), round(ny, 4), round(nyaw, 4)

    waypoints_site = [{"x": round(site_pose[0], 4), "y": round(site_pose[1], 4), "yaw": round(site_pose[2], 4), "place": "START"}]
    segments_out = []
    places_out = []
    edges_out = []
    length_m = _math.hypot(target_x - site_pose[0], target_y - site_pose[1])
    eta_s = round(length_m / 0.15, 1)

    if active is not None:
        smap = active[2]
        if not place_id:
            best_p, best_d = None, 0.16
            for pid, pl in smap.places.items():
                px, py = smap.place_xy(pid)
                d = _math.hypot(px - target_x, py - target_y)
                if d < best_d:
                    best_d, best_p = d, pid
            if best_p:
                place_id = best_p
        goal_spec = place_id if (place_id and place_id in smap.places) else (target_x, target_y, explicit_yaw)
        try:
            plan_road_path = _il.import_module(".".join(("fleet", "routing", "road_path"))).plan_road_path
            routing_cfg = getattr(runner, "_routing", None)
            try:
                road_plan = (
                    plan_road_path(smap, site_pose, goal_spec, routing_cfg, step_m=0.05, arrive_yaw=explicit_yaw)
                    if routing_cfg is not None
                    else plan_road_path(smap, site_pose, goal_spec, step_m=0.05, arrive_yaw=explicit_yaw)
                )
            except Exception:
                best_arc_pt = None
                best_arc_dist = 999.0
                for arc in smap.arcs.values():
                    dist_a, s_m, _t = arc.project(target_x, target_y)
                    if dist_a < best_arc_dist:
                        px, py, pt = arc.point_at(s_m)
                        best_arc_dist = dist_a
                        best_arc_pt = (px, py, None)
                if best_arc_pt is None:
                    raise
                road_plan = (
                    plan_road_path(smap, site_pose, best_arc_pt, routing_cfg, step_m=0.05)
                    if routing_cfg is not None
                    else plan_road_path(smap, site_pose, best_arc_pt, step_m=0.05)
                )
            waypoints_site = [dict(w) for w in road_plan.waypoints_site]
            places_out = list(road_plan.places)
            edges_out = list(road_plan.edges)
            segments_out = [
                {"edge_id": eid, "forward": bool(fwd), "s_from": round(s0, 4), "s_to": round(s1, 4)}
                for eid, fwd, s0, s1 in road_plan.segments
            ]
            length_m = float(road_plan.length_m)
            eta_s = float(road_plan.eta_s)
        except Exception:
            try:
                req = PlanRequest(map_version=active[0], start_pose=site_pose, goal=goal_spec, arrive_yaw=target_yaw)
                planned = plan_trip(smap, req)
                pbody = plan_body(planned)
                segments_out = pbody.get("segments", [])
                places_out = list(pbody.get("places") or [])
                length_m = float(pbody.get("length_m") or length_m)
                eta_s = float(pbody.get("eta_s") or eta_s)
            except Exception:
                pass

    if len(waypoints_site) < 2:
        waypoints_site.append({"x": round(target_x, 4), "y": round(target_y, 4), "yaw": round(target_yaw, 4), "place": place_id or label or "GOAL"})
    else:
        last_wp = waypoints_site[-1]
        if _math.hypot(last_wp["x"] - target_x, last_wp["y"] - target_y) > 0.035 and not place_id:
            waypoints_site.append({"x": round(target_x, 4), "y": round(target_y, 4), "yaw": round(target_yaw, 4), "place": label or "PIN"})

    waypoints_nav2 = []
    for wp in waypoints_site:
        nx, ny, nyaw = _site_to_nav2(wp["x"], wp["y"], wp["yaw"])
        waypoints_nav2.append({"x": nx, "y": ny, "yaw": nyaw, "place": wp.get("place")})

    traffic_view = runner.traffic.view() if (runner is not None and getattr(runner, "traffic", None) is not None) else {}
    formation_view = {}
    try:
        snap = await console.snapshot()
        formation_view = snap.get("formation") or {}
    except Exception:
        pass

    return {
        "robot_id": robot_id,
        "pipeline": "road_lane_graph -> traffic_formation_guard -> site_to_nav2_tf -> nav2_navigate_to_pose",
        "site_pose": {"x": round(site_pose[0], 4), "y": round(site_pose[1], 4), "yaw": round(site_pose[2], 4)},
        "local_nav2_pose": {"x": round(local_pose[0], 4), "y": round(local_pose[1], 4), "yaw": round(local_pose[2], 4)},
        "target_site": {"x": round(target_x, 4), "y": round(target_y, 4), "yaw": round(target_yaw, 4), "place_id": place_id, "label": label},
        "target_nav2": waypoints_nav2[-1],
        "places": places_out,
        "edges": edges_out,
        "segments": segments_out,
        "waypoints_site": waypoints_site,
        "waypoints_nav2": waypoints_nav2,
        "length_m": round(length_m, 3),
        "eta_s": round(eta_s, 1),
        "traffic": {"zones": len(traffic_view.get("zones") or []), "signals": (list(traffic_view["signals"].keys()) if isinstance(traffic_view.get("signals"), dict) else [s.get("id") or s.get("signal_id") or str(i) for i, s in enumerate(traffic_view.get("signals") or []) if isinstance(s, dict)])},
        "formation": {"active": bool(formation_view.get("active")), "leader": formation_view.get("leader")},
    }
