#!/usr/bin/env python3
"""Pipeline CLI for ROSY Pinky Fleet status, localization confirm, D-1022 sampling, and map-binding."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from pinky_loc_client import FleetClient, PipelineError, _read_token

MIN_SPREAD_M = 0.05
MAX_RESIDUAL_M = 0.05
MIN_SPAN_M = 1.0
MAX_HOLDOUT_M = 0.05
DEFAULT_MIN_FIT = 0.85
STILL_LINEAR_MPS = 0.01
STILL_ANGULAR_RADPS = 0.02
D1022_CODES = frozenset({
    "TOO_FEW_PAIRS", "COLLINEAR", "MIRRORED", "RESIDUAL",
    "AMBIGUOUS_FLIP", "SPAN", "HOLDOUT_REQUIRED", "HOLDOUT",
})
Point = tuple[float, float]


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    return val if math.isfinite(val) else None



def _mean(pts: Sequence[Point]) -> Point:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _spread(pts: Sequence[Point]) -> float:
    mx, my = _mean(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts) / len(pts)
    syy = sum((p[1] - my) ** 2 for p in pts) / len(pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / len(pts)
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    return math.sqrt(max(0.0, tr / 2 - math.sqrt(max(0.0, tr * tr / 4 - det))))


def _apply_fit(yaw: float, tx: float, ty: float, p: Point) -> Point:
    c, s = math.cos(yaw), math.sin(yaw)
    return (c * p[0] - s * p[1] + tx, s * p[0] + c * p[1] + ty)


def _with_yaw(robot: Sequence[Point], site: Sequence[Point], yaw: float) -> tuple[float, float, float, tuple[float, ...]]:
    c, s = math.cos(yaw), math.sin(yaw)
    (rx, ry), (sx, sy) = _mean(robot), _mean(site)
    tx, ty = sx - (c * rx - s * ry), sy - (s * rx + c * ry)
    residuals = tuple(math.dist(_apply_fit(yaw, tx, ty, r), q) for r, q in zip(robot, site))
    return yaw, tx, ty, residuals


def _fit_rigid(robot: Sequence[Point], site: Sequence[Point]) -> tuple[float, float, float, tuple[float, ...]]:
    if len(robot) != len(site) or len(robot) < 3:
        raise PipelineError("TOO_FEW_PAIRS", "a binding needs at least 3 point pairs")
    for name, pts in (("robot map", robot), ("site", site)):
        if _spread(pts) < MIN_SPREAD_M:
            raise PipelineError("COLLINEAR", f"{name} points lie on one line; add a point off the line")
    (rx, ry), (sx, sy) = _mean(robot), _mean(site)
    num = sum((r[0] - rx) * (q[1] - sy) - (r[1] - ry) * (q[0] - sx) for r, q in zip(robot, site))
    den = sum((r[0] - rx) * (q[0] - sx) + (r[1] - ry) * (q[1] - sy) for r, q in zip(robot, site))
    return _with_yaw(robot, site, math.atan2(num, den))


def judge_pairs(pairs: Sequence[Mapping[str, Sequence[float]]], holdout: Sequence[Mapping[str, Sequence[float]]] = (),
                *, max_residual: float = MAX_RESIDUAL_M, min_span: float = MIN_SPAN_M,
                max_holdout: float = MAX_HOLDOUT_M, require_holdout: bool = True) -> dict[str, Any]:
    """Verify D-1022 point pairs and holdout samples with exact parity to fleet.localization.map_binding."""
    robot = [(float(p["robot"][0]), float(p["robot"][1])) for p in pairs]
    site = [(float(p["site"][0]), float(p["site"][1])) for p in pairs]
    hold_pairs = [((float(p["robot"][0]), float(p["robot"][1])), (float(p["site"][0]), float(p["site"][1]))) for p in holdout]
    if set(robot + site) & {point for pair in hold_pairs for point in pair}:
        raise PipelineError("BAD_POINTS", "a holdout point repeats a fit point; measure it separately")
    yaw, tx, ty, residuals = _fit_rigid(robot, site)
    max_res = max(residuals)
    if max_res > max_residual:
        _, _, _, mirror_res = _fit_rigid([(p[0], -p[1]) for p in robot], site)
        code = "MIRRORED" if max(mirror_res) <= max_residual else "RESIDUAL"
        raise PipelineError(code, f"max residual {max_res:.3f} m exceeds {max_residual} m")
    if max(_with_yaw(robot, site, yaw + math.pi)[3]) <= max_residual:
        raise PipelineError("AMBIGUOUS_FLIP", "the 180 degree alternative fits as well; add points off the symmetry")
    span = max((math.dist(a, b) for a in site for b in site), default=0.0)
    if span < min_span:
        raise PipelineError("SPAN", f"pairs span {span:.2f} m, need at least {min_span} m")
    if require_holdout and not hold_pairs:
        raise PipelineError("HOLDOUT_REQUIRED", "at least one held-out point pair is required")
    errors = [math.dist(_apply_fit(yaw, tx, ty, r), q) for r, q in hold_pairs]
    if any(e > max_holdout for e in errors):
        raise PipelineError("HOLDOUT", f"held-out error {max(errors):.3f} m exceeds {max_holdout} m")
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    return {"yaw": yaw, "tx": tx, "ty": ty, "max_residual_m": max_res, "rms_residual_m": rms,
            "span_m": span, "holdout_errors_m": errors}


# --------------------------------------------------------------------------- status & inspection


def _state_block(robot_row: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not isinstance(robot_row, Mapping):
        return {}
    inner = robot_row.get("state")
    return inner if isinstance(inner, Mapping) else robot_row


def _loc_block(robot_row: Optional[Mapping[str, Any]], loc_payload: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if isinstance(loc_payload, Mapping) and isinstance(loc_payload.get("localization"), Mapping):
        return loc_payload["localization"]
    state = _state_block(robot_row)
    if isinstance(state.get("localization"), Mapping):
        return state["localization"]
    if isinstance(robot_row, Mapping) and isinstance(robot_row.get("localization"), Mapping):
        return robot_row["localization"]
    return {}


def classify_robot(robot_row: Optional[Mapping[str, Any]], loc_payload: Optional[Mapping[str, Any]],
                   binding_payload: Optional[Mapping[str, Any]], track_row: Optional[Mapping[str, Any]],
                   map_pose_payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compute a deterministic readiness stage and exact next action for one robot."""
    state, loc = _state_block(robot_row), _loc_block(robot_row, loc_payload)
    robot_id = str((robot_row or {}).get("robot_id") or state.get("robot_id")
                   or (loc_payload or {}).get("robot_id") or (track_row or {}).get("robot_id") or "unknown")
    online = bool((robot_row or {}).get("online", False) or state.get("online", False))
    loc_state = loc.get("state")
    map_grid_id = state.get("map_grid_id") or (binding_payload or {}).get("robot_grid_id")
    cand_report = (loc_payload or {}).get("candidates")
    candidates = cand_report.get("candidates") if isinstance(cand_report, Mapping) and isinstance(cand_report.get("candidates"), list) else []
    fits = [f for c in candidates if isinstance(c, Mapping) and (f := _finite(c.get("scan_fit"))) is not None]
    best_scan_fit = max(fits) if fits else None
    binding_matches = bool((binding_payload or {}).get("matches", False))
    binding_reason = (binding_payload or {}).get("reason")
    slam_camera_gap_m = _finite((binding_payload or {}).get("slam_camera_gap_m"))
    if slam_camera_gap_m is None and isinstance(map_pose_payload, Mapping):
        slam_camera_gap_m = _finite(map_pose_payload.get("camera_residual_m"))
    tx, ty = _finite((track_row or {}).get("x")), _finite((track_row or {}).get("y"))
    track_xy = [tx, ty] if tx is not None and ty is not None else None

    if not online:
        stage, next_action = "OFFLINE", f"Check robot power and Wi-Fi for {robot_id}"
    elif loc_state != "LOCALIZED":
        if not candidates:
            stage, next_action = "NO_CANDIDATES", f"Move/rotate {robot_id} or trigger relocalize until LiDAR candidates appear"
        else:
            stage, next_action = "NEEDS_CONFIRM", f"python tools/calibration/pinky_loc_pipeline.py confirm --robot {robot_id}"
    elif not binding_matches:
        stage = "NEEDS_MAP_BINDING"
        next_action = (f"python tools/calibration/pinky_loc_pipeline.py sample --robot {robot_id} --out <pairs.json> "
                       f"(>=4 poses, span>=1.0m) then bind --robot {robot_id} --pairs <pairs.json> --approve")
    else:
        stage, next_action = "READY", "none (LOCALIZED and map-binding matched)"

    return {"robot_id": robot_id, "stage": stage, "online": online, "loc_state": loc_state,
            "map_grid_id": map_grid_id, "candidates_count": len(candidates), "best_scan_fit": best_scan_fit,
            "binding_matches": binding_matches, "binding_reason": binding_reason,
            "track_state": (track_row or {}).get("state"), "track_xy": track_xy,
            "slam_camera_gap_m": slam_camera_gap_m, "next_action": next_action}


def _safe_get(client: FleetClient, path: str) -> Any:
    try:
        return client.request_json("GET", path)
    except PipelineError:
        return None


def _collect_status(client: FleetClient, robot_filter: Optional[str] = None) -> list[dict[str, Any]]:
    fleet_state = client.request_json("GET", "/api/fleet/state")
    identity = client.request_json("GET", "/api/fleet/tracking/identity")
    tracks = {str(r["robot_id"]): r for r in (identity.get("robots") or []) if isinstance(r, Mapping) and r.get("robot_id")}
    rows_out: list[dict[str, Any]] = []
    for r in fleet_state.get("robots") or []:
        if not isinstance(r, Mapping) or not r.get("robot_id"):
            continue
        rid = str(r["robot_id"])
        if robot_filter and rid != robot_filter:
            continue
        loc = _safe_get(client, f"/api/fleet/robots/{rid}/localization") if r.get("online") else None
        bind = _safe_get(client, f"/api/fleet/robots/{rid}/map-binding") if r.get("online") else None
        mpose = _safe_get(client, f"/api/fleet/robots/{rid}/map-pose") if r.get("online") else None
        rows_out.append(classify_robot(r, loc, bind, tracks.get(rid), mpose))
    if robot_filter and not rows_out:
        raise PipelineError("UNKNOWN_ROBOT", f"robot {robot_filter!r} not found in /api/fleet/state")
    return rows_out


# --------------------------------------------------------------------------- subcommands


def run_status(client: FleetClient, *, robot: Optional[str], as_json: bool) -> int:
    rows = _collect_status(client, robot_filter=robot)
    if as_json:
        print(json.dumps({"robots": rows}, indent=2))
        return 0
    for row in rows:
        fit_txt = f"{row['best_scan_fit']:.4f}" if row["best_scan_fit"] is not None else "-"
        bind_txt = "ok" if row["binding_matches"] else (row["binding_reason"] or "MISSING")
        trk_txt = f"{row['track_state']}@{row['track_xy']}" if row["track_xy"] else str(row["track_state"] or "-")
        print(f"{row['robot_id']}: stage={row['stage']} online={row['online']} loc={row['loc_state'] or '-'} "
              f"cands={row['candidates_count']}(best={fit_txt}) binding={bind_txt} track={trk_txt} -> {row['next_action']}")
    return 0


def run_confirm(client: FleetClient, *, robot_id: str, candidate_id: Optional[int], min_fit: float, wait_s: float,
                poll_s: float = 0.5, sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic) -> int:
    loc = client.request_json("GET", f"/api/fleet/robots/{robot_id}/localization")
    if ((loc.get("localization") or {}).get("state") if isinstance(loc, Mapping) else None) == "LOCALIZED":
        raise PipelineError("ALREADY_LOCALIZED", f"{robot_id} is already LOCALIZED")
    report = loc.get("candidates") if isinstance(loc, Mapping) else None
    candidates = report.get("candidates") if isinstance(report, Mapping) else None
    if not isinstance(candidates, list) or not candidates:
        raise PipelineError("NO_CANDIDATES", f"{robot_id} currently reports 0 localization candidates")
    if candidate_id is None:
        if len(candidates) != 1:
            raise PipelineError("CANDIDATE_AMBIGUOUS", f"{robot_id} reports {len(candidates)} candidates; pass --candidate-id explicitly")
        idx = 0
    else:
        if not 0 <= candidate_id < len(candidates):
            raise PipelineError("BAD_CANDIDATE_ID", f"--candidate-id {candidate_id} out of range (0..{len(candidates) - 1})")
        idx = candidate_id
    fit = _finite(candidates[idx].get("scan_fit"))
    if fit is None or fit < min_fit:
        raise PipelineError("SCAN_FIT_LOW", f"candidate {idx} scan_fit {fit} below min_fit {min_fit:.2f}")

    client.request_json("POST", f"/api/fleet/robots/{robot_id}/localization/confirm", {"candidate_id": idx})
    deadline = clock() + max(0.0, wait_s)
    while True:
        cur_loc = client.request_json("GET", f"/api/fleet/robots/{robot_id}/localization")
        st = cur_loc.get("localization") if isinstance(cur_loc, Mapping) else None
        if isinstance(st, Mapping) and st.get("state") == "LOCALIZED":
            state_all = client.request_json("GET", "/api/fleet/state")
            match_row = next((r for r in (state_all.get("robots") or []) if isinstance(r, Mapping) and r.get("robot_id") == robot_id), None)
            inner = _state_block(match_row)
            print(json.dumps({
                "robot_id": robot_id, "status": "LOCALIZED", "candidate_id": idx, "scan_fit": fit,
                "map_grid_id": inner.get("map_grid_id"), "pose": inner.get("pose"),
                "navigation_readiness": (inner.get("diagnostics_summary") or {}).get("navigation_readiness"),
            }, indent=2))
            return 0
        if clock() >= deadline:
            reason = st.get("reason") if isinstance(st, Mapping) else None
            cur_s = st.get("state") if isinstance(st, Mapping) else None
            raise PipelineError("CONFIRM_TIMEOUT", f"{robot_id} did not reach LOCALIZED within {wait_s:.1f}s (state={cur_s}, reason={reason})")
        sleep(poll_s)


def _parse_manual_pair(spec: str) -> tuple[Point, Point]:
    try:
        lhs, rhs = spec.split("=", 1)
        rx_s, ry_s = lhs.split(",", 1)
        sx_s, sy_s = rhs.split(",", 1)
        vals = (float(rx_s), float(ry_s), float(sx_s), float(sy_s))
    except ValueError:
        raise PipelineError("BAD_PAIR", f"--pair must look like rx,ry=sx,sy (got {spec!r})") from None
    if not all(math.isfinite(v) for v in vals):
        raise PipelineError("BAD_PAIR", f"--pair contains non-finite coordinate: {spec!r}")
    return (vals[0], vals[1]), (vals[2], vals[3])


def _find_robot_state(fleet_state: Mapping[str, Any], robot_id: str) -> Mapping[str, Any]:
    for r in fleet_state.get("robots") or []:
        if isinstance(r, Mapping) and r.get("robot_id") == robot_id:
            if not r.get("online"):
                raise PipelineError("ROBOT_OFFLINE", f"{robot_id} is offline")
            return _state_block(r)
    raise PipelineError("UNKNOWN_ROBOT", f"{robot_id} not found in /api/fleet/state")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _active_site(client: FleetClient) -> tuple[str, int]:
    active = client.request_json("GET", "/api/fleet/site-map/active")
    map_id, version = (active.get("map") or {}).get("map_id"), active.get("version")
    if not isinstance(map_id, str) or type(version) is not int:
        raise PipelineError("SITE_MAP_NOT_ACTIVE", "Fleet did not report an active site map revision")
    return map_id, version


def _aruco_sample(client: FleetClient, robot_id: str, source_id: str, map_id: str,
                  max_age_s: float) -> Mapping[str, Any]:
    response = client.request_json("GET", "/api/fleet/sightings")
    row = next((row for row in response.get("sightings", []) if row.get("robot_id") == robot_id
                and row.get("source_id") == source_id), {})
    age_ms = _finite(row.get("age_ms"))
    if (row.get("stale") is not False or age_ms is None or not 0 <= age_ms <= 1000 * min(1.0, max_age_s)
            or row.get("map_id") != map_id or row.get("calibration_source") != "approved_record"
            or not row.get("calibration_revision") or not str(row.get("processor_revision", "")).startswith("aruco-")
            or type(row.get("seq")) is not int or _finite(row.get("captured_at")) is None):
        raise PipelineError("ARUCO_UNAVAILABLE", f"{robot_id} needs a fresh approved ArUco sighting on {map_id}")
    return row


def _aruco_aligned(state: Mapping[str, Any], captured_at: float, max_age_s: float, *, after: bool) -> bool:
    evidence = state.get("evidence") or {}
    for key, field in (("pose", "received_at"), ("velocity", "sampled_at")):
        row = evidence.get(key) or {}
        try:
            stamp = _dt.datetime.fromisoformat(row[field])
        except (KeyError, TypeError, ValueError):
            return False
        if row.get("evidence") != "fresh" or stamp.utcoffset() is None:
            return False
        offset = stamp.timestamp() - captured_at
        if (offset > 0) != after or abs(offset) > max_age_s:
            return False
    return True


def run_sample(client: FleetClient, *, robot_id: str, out_path: Path, pair_spec: Optional[str],
               grid_id_override: Optional[str], site_map_id_override: Optional[str],
               holdout: bool, max_track_age_s: float, aruco_source: Optional[str] = None,
               surveyed_site: Optional[Sequence[float]] = None) -> int:
    site_map_id = site_map_id_override
    sighting = None
    doc = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"samples": []}
    site_version = doc.get("site_map_version")
    if surveyed_site is not None and (not holdout or pair_spec is not None or aruco_source or grid_id_override
                                      or len(surveyed_site) != 2 or any(_finite(v) is None for v in surveyed_site)):
        raise PipelineError("BAD_PAIR", "surveyed site needs --holdout and measured finite site X Y only")
    live_frame = bool(aruco_source) or surveyed_site is not None
    if live_frame and site_version is None and doc.get("samples"):
        raise PipelineError("MAP_BINDING_SITE_UNVERIFIED", "start a new file for samples tied to an active site revision")
    if live_frame or site_version is not None:
        active_id, active_version = _active_site(client)
        if (doc.get("site_map_id") not in (None, active_id) or site_map_id not in (None, active_id)
                or site_version not in (None, active_version)):
            raise PipelineError("MAP_BINDING_SITE_CHANGED", "samples belong to a different site map revision")
        site_map_id, site_version = active_id, active_version
    if aruco_source and (pair_spec is not None or holdout):
        raise PipelineError("BAD_PAIR", "ArUco is for fit samples only; holdout requires --pair with a floor measurement")
    if site_version is not None and holdout and pair_spec is None and surveyed_site is None:
        raise PipelineError("BAD_PAIR", "holdout requires --pair with a floor measurement")
    if pair_spec is not None:
        robot_pt, site_pt = _parse_manual_pair(pair_spec)
        map_grid_id = grid_id_override or _find_robot_state(client.request_json("GET", "/api/fleet/state"), robot_id).get("map_grid_id")
        if not map_grid_id:
            raise PipelineError("MAP_GRID_UNKNOWN", f"{robot_id} has no map_grid_id; pass --grid-id")
        source = "manual"
    else:
        st = _find_robot_state(client.request_json("GET", "/api/fleet/state"), robot_id)
        loc = st.get("localization") if isinstance(st.get("localization"), Mapping) else {}
        if loc.get("state") != "LOCALIZED" or loc.get("pose_frame") != "map":
            raise PipelineError("ROBOT_NOT_LOCALIZED", f"{robot_id} must be LOCALIZED in map frame before sampling")
        vel = st.get("velocity") if isinstance(st.get("velocity"), Mapping) else {}
        lin, ang = _finite(vel.get("linear", 0.0)), _finite(vel.get("angular", 0.0))
        if lin is None or ang is None or abs(lin) >= STILL_LINEAR_MPS or abs(ang) >= STILL_ANGULAR_RADPS:
            raise PipelineError("ROBOT_MOVING", f"{robot_id} must stand still to sample (v={lin}, w={ang})")
        map_grid_id = st.get("map_grid_id")
        if not isinstance(map_grid_id, str) or not map_grid_id:
            raise PipelineError("MAP_GRID_UNKNOWN", f"{robot_id} has no map_grid_id")
        pose = st.get("pose") if isinstance(st.get("pose"), Mapping) else {}
        rx, ry = _finite(pose.get("x")), _finite(pose.get("y"))
        if rx is None or ry is None:
            raise PipelineError("ROBOT_POSE_MISSING", f"{robot_id} pose is missing")
        if surveyed_site is not None:
            if (_finite(vel.get("linear")) is None or _finite(vel.get("angular")) is None
                    or not _aruco_aligned(st, time.time(), 1.0, after=False)):
                raise PipelineError("SAMPLE_EVIDENCE_STALE", "survey requires fresh measured pose and velocity")
            track = {"x": surveyed_site[0], "y": surveyed_site[1]}
        elif aruco_source:
            track = sighting = _aruco_sample(client, robot_id, aruco_source, site_map_id, max_track_age_s)
            if doc.get("aruco_calibration_revision") not in (None, sighting["calibration_revision"]):
                raise PipelineError("ARUCO_CALIBRATION_CHANGED", "ArUco calibration changed between samples")
            if any(s.get("captured_at") == sighting["captured_at"] for s in doc.get("samples", [])):
                raise PipelineError("ARUCO_DUPLICATE", "ArUco frame was already recorded")
            captured_at, max_age = sighting["captured_at"], min(1.0, max_track_age_s)
            if not _aruco_aligned(st, captured_at, max_age, after=False):
                raise PipelineError("SAMPLE_EVIDENCE_STALE", "CORE pose and measured velocity must precede the ArUco capture")
            deadline = time.monotonic() + max_age
            while True:
                after = _find_robot_state(client.request_json("GET", "/api/fleet/state"), robot_id)
                if _aruco_aligned(after, captured_at, max_age, after=True):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PipelineError("SAMPLE_EVIDENCE_STALE", "CORE must report fresh pose and velocity after the ArUco capture")
                time.sleep(min(0.1, remaining))
            if after.get("map_grid_id") != map_grid_id:
                raise PipelineError("MAP_BINDING_GRID_CHANGED", "CORE grid changed while reading ArUco")
            after_loc = after.get("localization") or {}
            after_velocity = after.get("velocity") or {}
            after_linear = _finite(after_velocity.get("linear"))
            after_angular = _finite(after_velocity.get("angular"))
            after_pose = after.get("pose") or {}
            after_x, after_y = _finite(after_pose.get("x")), _finite(after_pose.get("y"))
            if (after_loc.get("state") != "LOCALIZED" or after_loc.get("pose_frame") != "map"
                    or after_linear is None or after_angular is None
                    or abs(after_linear) >= STILL_LINEAR_MPS or abs(after_angular) >= STILL_ANGULAR_RADPS
                    or after_x is None or after_y is None or math.hypot(after_x - rx, after_y - ry) > 0.01):
                raise PipelineError("SAMPLE_STATE_CHANGED", "CORE must remain localized and stopped while reading ArUco")
        else:
            ident = client.request_json("GET", "/api/fleet/tracking/identity")
            track = next((row for row in (ident.get("robots") or []) if isinstance(row, Mapping) and row.get("robot_id") == robot_id), None)
            if not isinstance(track, Mapping) or track.get("state") != "CONFIRMED":
                raise PipelineError("TRACK_NOT_CONFIRMED", f"{robot_id} ceiling camera track is not CONFIRMED")
            age_s = _finite(track.get("age_s"))
            if age_s is None or age_s < 0.0 or age_s > max_track_age_s:
                raise PipelineError("TRACK_STALE", f"{robot_id} track age_s={age_s} exceeds {max_track_age_s}s")
        sx, sy = _finite(track.get("x")), _finite(track.get("y"))
        if sx is None or sy is None:
            raise PipelineError("TRACK_XY_MISSING", f"{robot_id} track coordinates missing")
        robot_pt, site_pt, source = (rx, ry), (sx, sy), "approved_aruco" if sighting else "live_camera"
        if surveyed_site is not None:
            source = "manual"
        site_map_id = site_map_id or track.get("map_id")

    if doc.get("robot_id") not in (None, robot_id):
        raise PipelineError("ROBOT_MISMATCH", f"{out_path} belongs to {doc.get('robot_id')}, not {robot_id}")
    if doc.get("map_grid_id") not in (None, map_grid_id):
        raise PipelineError("MAP_BINDING_GRID_CHANGED", f"{out_path} was recorded for {doc.get('map_grid_id')}, live is {map_grid_id}")
    doc.update({"robot_id": robot_id, "map_grid_id": map_grid_id})
    if site_map_id is not None:
        doc["site_map_id"] = site_map_id
    if site_version is not None:
        doc["site_map_version"] = site_version
    if sighting:
        doc["aruco_calibration_revision"] = sighting["calibration_revision"]
    doc.setdefault("samples", []).append({
        "robot": [round(robot_pt[0], 6), round(robot_pt[1], 6)],
        "site": [round(site_pt[0], 6), round(site_pt[1], 6)],
        "holdout": bool(holdout), "source": source,
        **({k: sighting[k] for k in ("source_id", "seq", "captured_at")} if sighting else {}),
        **({"robot_pose_received_at": st["evidence"]["pose"]["received_at"],
            "velocity_sampled_at": st["evidence"]["velocity"]["sampled_at"]} if surveyed_site is not None else {}),
        "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    })
    _write_json_atomic(out_path, doc)
    print(json.dumps({**_sample_readiness(doc), "out": str(out_path)}, indent=2))
    return 0


def _sample_readiness(doc):
    fit_samples, checks = _binding_samples(doc)
    try:
        _sample_verdict(doc, fit_samples, checks)
        refusal = None
    except PipelineError as exc:
        refusal = {"code": exc.code, "message": exc.message}
    site_pts = [(float(s["site"][0]), float(s["site"][1])) for s in fit_samples]
    span_m = max((math.dist(a, b) for a in site_pts for b in site_pts), default=0.0)
    progress = {} if doc.get("site_map_version") is None else {
        "fit_geometry": _fit_progress(fit_samples, site_pts, span_m),
        "manual_holdout_missing": refusal is not None and refusal["code"] == "HOLDOUT_REQUIRED",
    }
    return {"robot_id": doc.get("robot_id"), "map_grid_id": doc.get("map_grid_id"),
            "samples_total": len(doc["samples"]), "span_m": round(span_m, 3),
            "ready_for_bind": refusal is None, "binding_refusal": refusal, **progress}


def _binding_samples(doc):
    samples = doc["samples"]
    holdout = [s for s in samples if s.get("holdout")]
    if doc.get("site_map_version") is None and not holdout and len(samples) >= 4:
        return samples[:-1], samples[-1:]
    return [s for s in samples if not s.get("holdout")], holdout


def _sample_verdict(doc, fit_pairs, holdout):
    if doc.get("site_map_version") is not None and (not holdout or any(s.get("source") != "manual" for s in holdout)):
        raise PipelineError("HOLDOUT_REQUIRED", "ArUco fit needs an independently measured manual holdout")
    return judge_pairs(fit_pairs, holdout)


def _fit_progress(fit_samples, site_pts, span_m):
    try:
        judge_pairs(fit_samples, require_holdout=False)
        refusal = None
    except PipelineError as exc:
        refusal = {"code": exc.code, "message": exc.message}
    robot_pts = [(float(s["robot"][0]), float(s["robot"][1])) for s in fit_samples]
    return {
        "refusal": refusal,
        "pairs": len(fit_samples),
        "pairs_remaining": max(0, 3 - len(fit_samples)),
        "site_span_shortfall_m": round(max(0.0, MIN_SPAN_M - span_m), 3),
        "robot_spread_m": round(_spread(robot_pts), 4) if robot_pts else 0.0,
        "site_spread_m": round(_spread(site_pts), 4) if site_pts else 0.0,
        "minimum_spread_m": MIN_SPREAD_M,
    }


def run_bind(client: FleetClient, *, robot_id: str, pairs_path: Path, approve: bool) -> int:
    doc = json.loads(pairs_path.read_text(encoding="utf-8"))
    if doc.get("robot_id") not in (None, robot_id):
        raise PipelineError("ROBOT_MISMATCH", f"{pairs_path} belongs to {doc.get('robot_id')}, not {robot_id}")
    samples = doc.get("samples") if isinstance(doc, Mapping) else None
    if not isinstance(samples, list) or not samples:
        raise PipelineError("TOO_FEW_PAIRS", f"{pairs_path} contains no samples")
    fit_pairs, holdout = _binding_samples(doc)
    verdict = _sample_verdict(doc, fit_pairs, holdout)
    if (approve and doc.get("site_map_version") is not None
            and _active_site(client) != (doc.get("site_map_id"), doc["site_map_version"])):
        raise PipelineError("MAP_BINDING_SITE_CHANGED", "samples belong to a different site map revision")
    payload_pairs = [{"robot": s["robot"], "site": s["site"]} for s in fit_pairs]
    payload_hold = [{"robot": s["robot"], "site": s["site"]} for s in holdout]
    if not approve:
        print(json.dumps({"dry_run": True, "robot_id": robot_id, "map_grid_id": doc.get("map_grid_id"), **verdict}, indent=2))
        return 0
    live_grid_id = _find_robot_state(client.request_json("GET", "/api/fleet/state"), robot_id).get("map_grid_id")
    if doc.get("map_grid_id") and live_grid_id != doc.get("map_grid_id"):
        raise PipelineError("MAP_BINDING_GRID_CHANGED", f"pairs map_grid_id={doc.get('map_grid_id')} != live {live_grid_id}")
    payload = {"pairs": payload_pairs, "holdout": payload_hold}
    if doc.get("site_map_version") is not None:
        payload["expected_frame"] = {"site_map_id": doc["site_map_id"], "site_map_version": doc["site_map_version"],
                                     "robot_grid_id": doc["map_grid_id"]}
    client.request_json("POST", f"/api/fleet/robots/{robot_id}/map-binding", payload)
    read = client.request_json("GET", f"/api/fleet/robots/{robot_id}/map-binding")
    if not read.get("matches"):
        raise PipelineError("BINDING_NOT_MATCHED", f"post-approve read returned matches={read.get('matches')} reason={read.get('reason')}")
    print(json.dumps({"approved": True, "robot_id": robot_id, "robot_grid_id": read.get("robot_grid_id"),
                      "slam_camera_gap_m": read.get("slam_camera_gap_m"), **verdict}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.environ.get("ROSY_FLEET_URL", "https://127.0.0.1:8090"))
    ap.add_argument("--token-file", type=Path, default=None, help="Bearer token file path (or ROSY_FLEET_TOKEN env)")
    ap.add_argument("--ca-file", type=Path, default=None, help="Site CA certificate path")
    ap.add_argument("--insecure", action="store_true", help="Skip TLS certificate verification")
    ap.add_argument("--timeout-s", type=float, default=5.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_stat = sub.add_parser("status", help="Show localization and map-binding stage for Pinky robots")
    p_stat.add_argument("--robot", default=None)
    p_stat.add_argument("--json", action="store_true")
    p_conf = sub.add_parser("confirm", help="Confirm a single strong localization candidate via named operator auth")
    p_conf.add_argument("--robot", required=True)
    p_conf.add_argument("--candidate-id", type=int, default=None)
    p_conf.add_argument("--min-fit", type=float, default=DEFAULT_MIN_FIT)
    p_conf.add_argument("--wait-s", type=float, default=20.0)
    p_samp = sub.add_parser("sample", help="Record a (robot_xy, site_xy) D-1022 calibration correspondence")
    p_samp.add_argument("--robot", required=True)
    p_samp.add_argument("--out", type=Path, required=True)
    p_samp.add_argument("--pair", default=None, help="Manual floor measurement rx,ry=sx,sy")
    p_samp.add_argument("--grid-id", default=None, help="Explicit map_grid_id when using --pair offline")
    p_samp.add_argument("--site-map-id", default=None)
    p_samp.add_argument("--surveyed-site", type=float, nargs=2, metavar=("X", "Y"),
                        help="Measured site coordinates of the stationary robot centre; read grid pose from CORE")
    p_samp.add_argument("--holdout", action="store_true")
    p_samp.add_argument("--max-track-age-s", type=float, default=1.0)
    p_samp.add_argument("--aruco-source", help="Use a fresh approved ArUco sighting as a fit sample")
    p_bind = sub.add_parser("bind", help="Judge D-1022 pairs and optionally POST /map-binding")
    p_bind.add_argument("--robot", required=True)
    p_bind.add_argument("--pairs", type=Path, required=True)
    p_bind.add_argument("--approve", action="store_true")
    sub.add_parser("inspect", help="Report readiness from a saved pairs file without contacting Fleet").add_argument(
        "--pairs", type=Path, required=True)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "inspect":
            doc = json.loads(args.pairs.read_text(encoding="utf-8"))
            if not isinstance(doc, Mapping) or not isinstance(doc.get("samples"), list):
                raise PipelineError("BAD_PAIR", "pairs file must contain a samples list")
            print(json.dumps({**_sample_readiness(doc), "out": str(args.pairs)}, indent=2))
            return 0
        client = FleetClient(args.base_url, token=_read_token(args.token_file), ca_file=args.ca_file,
                             insecure=args.insecure, timeout_s=args.timeout_s)
        if args.cmd == "status":
            return run_status(client, robot=args.robot, as_json=args.json)
        if args.cmd == "confirm":
            return run_confirm(client, robot_id=args.robot, candidate_id=args.candidate_id,
                               min_fit=args.min_fit, wait_s=args.wait_s)
        if args.cmd == "sample":
            return run_sample(client, robot_id=args.robot, out_path=args.out, pair_spec=args.pair,
                              grid_id_override=args.grid_id, site_map_id_override=args.site_map_id,
                              holdout=args.holdout, max_track_age_s=args.max_track_age_s,
                              aruco_source=args.aruco_source, surveyed_site=args.surveyed_site)
        if args.cmd == "bind":
            return run_bind(client, robot_id=args.robot, pairs_path=args.pairs, approve=args.approve)
    except PipelineError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 3 if exc.code in D1022_CODES else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
