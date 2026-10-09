"""D-531: translate a held lane instruction into expiring camera context."""
from __future__ import annotations

from pydantic import ValidationError

from core_common.protocol.route_context import RouteContext


def route_context(junction, arc, *, mono_now, ros_now, odom_key, odometer, mode="CAMERA_LINE"):
    if mode != "CAMERA_LINE" or odom_key is None:
        return None
    if arc is not None and arc.get("state") == "running":
        if arc.get("key") != odom_key:
            return None
        source = dict(seq=arc.get("instruction_seq"), place_id=arc.get("from"),
                      map_id=arc.get("map_id"), kind="ring", curvature_1pm=arc.get("k"))
        expires_at = arc.get("deadline")
    elif junction is not None and junction.get("state") not in ("done", "aborted", "idle", "unresolved"):
        window = junction.get("window")
        if window is not None and window.get("key") != odom_key:
            return None
        kind = "bend" if junction.get("action") == "bend" else "junction"
        source = dict(seq=junction.get("seq"), place_id=junction.get("place_id"),
                      map_id=junction.get("map_id"), kind=kind)
        if kind == "bend":
            if junction.get("bend_in") is not None and junction.get("tol") is not None:
                distance = junction["bend_in"] - junction.get("travel", 0.)
                source["ahead_m"] = (round(distance-junction["tol"], 3),
                                     round(distance+junction["tol"], 3))
            source["lane_turn_deg"] = junction.get("turn_deg")
        else:
            if window is not None and odometer is not None:
                distance = (window["expect_in"] - (junction.get("pivot") or 0.)
                            - (odometer-window["odometer"]))
                source["ahead_m"] = (round(distance-window["tol"], 3),
                                     round(distance+window["tol"], 3))
            source["lane_turn_deg"] = junction.get("lane_turn")
        expires_at = junction.get("expires_at")
    else:
        return None
    if not source.get("map_id") or expires_at is None or expires_at <= mono_now:
        return None
    try:
        return RouteContext(v=1, stamp_s=ros_now,
                            valid_until_s=round(ros_now+min(.5, expires_at-mono_now), 6), **source)
    except (TypeError, ValueError, ValidationError):
        return None
