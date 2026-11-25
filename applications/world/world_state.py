"""Shared state, timeline interpolation, parity verification, and atomic persistence for Rosy World."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time

LIVE_FRESH_MS = 3_000
REAL_FRESH_MS = 10_000
BACKENDS = ("real", "isaac", "gazebo", "mujoco")
ADAPTER_LABELS = {
    "real": "Real 현장",
    "isaac": "Isaac Sim",
    "gazebo": "Gazebo",
    "mujoco": "MuJoCo",
}
WORLD_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_FLEET_ROBOTS = {
    "pinkys": ["rosy_42", "rosy_45", "rosy_46"],
    "arms": ["arm_s", "arm_a", "arm_b"],
}


def _lerp_vec(a: list[float], b: list[float], u: float) -> list[float]:
    return [round(x + (y - x) * u, 5) for x, y in zip(a, b)]


def _lerp_yaw(a: float, b: float, u: float) -> float:
    return round(math.remainder(a + math.remainder(b - a, math.tau) * u, math.tau), 5)


def _lerp_arms(a_arms: dict | None, b_arms: dict | None, u: float) -> dict:
    if not isinstance(a_arms, dict):
        return {}
    out = {}
    for k, qa in a_arms.items():
        qb = b_arms.get(k) if isinstance(b_arms, dict) else None
        out[k] = _lerp_vec(qa, qb, u) if isinstance(qb, list) and len(qb) == len(qa) else list(qa)
    return out


def _lerp_pinkys(a_list: list | None, b_list: list | None, u: float) -> list[dict]:
    if not isinstance(a_list, list):
        return []
    b_map = {item["id"]: item for item in b_list if isinstance(item, dict)} if isinstance(b_list, list) else {}
    out = []
    for item in a_list:
        nxt = b_map.get(item.get("id"))
        if nxt and item.get("pose_m") and nxt.get("pose_m"):
            out.append({
                **item,
                "pose_m": _lerp_vec(item["pose_m"], nxt["pose_m"], u),
                "yaw_rad": _lerp_yaw(item["yaw_rad"], nxt["yaw_rad"], u),
            })
        else:
            out.append(dict(item))
    return out


def sample_timeline(timeline: dict, elapsed_s: float) -> dict:
    """Interpolate a ros.world.factory-timeline.v1 document at elapsed_s."""
    frames = timeline["keyframes"]
    duration = float(timeline["duration_s"]) or 1.0
    t = (elapsed_s % duration) if elapsed_s >= 0 else 0.0
    times = [float(f["time_s"]) for f in frames]
    idx = min(max(bisect_right(times, t) - 1, 0), len(frames) - 1)
    nxt = min(idx + 1, len(frames) - 1)
    a, b = frames[idx], frames[nxt]
    span = float(b["time_s"]) - float(a["time_s"])
    u = 0.0 if span <= 1e-9 or a["stage"] != b["stage"] else max(0.0, min(1.0, (t - float(a["time_s"])) / span))
    return {
        "schema": "rosy.world.factory-state.v1",
        "stream_mode": "verified_replay",
        "world_id": "verified-replay",
        "adapter": "mujoco",
        "has_cargo_tray": True,
        "site_map_sha256": timeline.get("site_map_sha256"),
        "run_id": timeline["run_id"],
        "sim_time_s": round(t, 3),
        "duration_s": round(duration, 3),
        "observed_at_ms": time.time_ns() // 1_000_000,
        "stage": a["stage"],
        "simulator": a["simulator"],
        "phase": a["phase"],
        "s3_box": timeline.get("s3_box"),
        "arm_bases_site": timeline.get("arm_bases_site"),
        "fleet_robots": timeline.get("fleet_robots"),
        "stages": timeline.get("stages", []),
        "pinky": {
            "id": a["pinky"].get("id", "rosy_45"),
            "pose_m": _lerp_vec(a["pinky"]["pose_m"], b["pinky"]["pose_m"], u),
            "yaw_rad": _lerp_yaw(a["pinky"]["yaw_rad"], b["pinky"]["yaw_rad"], u),
            "has_cargo": a["pinky"]["has_cargo"],
            "s3_in_bounds": a["pinky"]["s3_in_bounds"],
        },
        "pinkys": _lerp_pinkys(a.get("pinkys"), b.get("pinkys"), u),
        "arms": _lerp_arms(a.get("arms"), b.get("arms"), u),
        "cargo": {
            "zone": a["cargo"]["zone"],
            "pose_m": _lerp_vec(a["cargo"]["pose_m"], b["cargo"]["pose_m"], u),
            "yaw_rad": _lerp_yaw(a["cargo"].get("yaw_rad", 0.0), b["cargo"].get("yaw_rad", 0.0), u),
            "color_idx": a["cargo"].get("color_idx", 0),
        },
        "arm_s_ee_m": _lerp_vec(a["arm_s_ee_m"], b["arm_s_ee_m"], u) if a.get("arm_s_ee_m") and b.get("arm_s_ee_m") else a.get("arm_s_ee_m"),
        "cell_ab": a["cell_ab"],
    }


def _reject_constant(token: str):
    raise ValueError(f"non-finite JSON constant: {token}")


def _read_json_strict(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_fresh_json(path: Path, now_ms: int) -> dict | None:
    data = _read_json_strict(path)
    if data is None:
        return None
    return data if _is_fresh(data, path.stem, now_ms) else None


def _is_fresh(data: dict, world_id: str, now_ms: int) -> bool:
    obs = data.get("observed_at_ms")
    real = data.get("adapter") == "real" or world_id == "real-site" or data.get("world_id") == "real-site"
    return type(obs) is int and abs(now_ms - obs) <= (REAL_FRESH_MS if real else LIVE_FRESH_MS)


def _valid_sha256(value: object) -> str | None:
    return value.lower() if isinstance(value, str) and SHA256_RE.fullmatch(value.lower()) else None


ACTIVE_SITE_MAP_PATH = "/api/worlds/real-site/site-map"
ACTIVE_SITE_MAP_FILE = ".active-site-map.snapshot"
ACTIVE_SITE_MAP_FRESH_MS = 45_000
# Fleet accepts map drafts up to 2 MiB. The map projection drops metadata.
MAX_ACTIVE_SITE_MAP_BYTES = 2 * 1024 * 1024


def active_site_map_snapshot(view: dict, observed_at_ms: int) -> dict | None:
    """Project Fleet's active map to the geometry World can display."""
    version, sha = view.get("version"), _valid_sha256(view.get("sha256"))
    body = view.get("map")
    activated_at = view.get("activated_at")
    if (type(version) is not int or version < 1 or not sha
            or type(observed_at_ms) is not int or not isinstance(body, dict)
            or not isinstance(body.get("map_id"), str) or not body["map_id"]
            or not isinstance(activated_at, (int, float, str))):
        return None

    def finite(value: object) -> bool:
        return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max

    places, edges = body.get("places"), body.get("edges")
    if not isinstance(places, list) or not isinstance(edges, list) or not (places or edges):
        return None
    if isinstance(activated_at, (int, float)) and not finite(activated_at):
        return None
    if not all(isinstance(place, dict) and isinstance(place.get("id"), str)
               and finite(place.get("x")) and finite(place.get("y")) for place in places):
        return None
    lines = [edge.get("polyline") if isinstance(edge, dict) else None for edge in edges]
    if not all(isinstance(line, (list, tuple)) and len(line) >= 2
               and all(isinstance(point, (list, tuple)) and len(point) == 2 and all(map(finite, point))
                       for point in line) for line in lines):
        return None
    return {
        "version": version, "sha256": sha, "activated_at": activated_at, "observed_at_ms": observed_at_ms,
        "map": {
            "map_id": body["map_id"],
            "places": [{key: place[key] for key in ("id", "x", "y")} for place in places],
            "edges": [{"polyline": line} for line in lines],
        },
    }


def _live_stream_mode(data: dict) -> str:
    return "synthetic_demo" if data.get("stream_mode") == "synthetic_demo" else "live"


def _canonical_reference(bundle_dir: Path) -> dict:
    site_map_sha = ""
    reg_sha = None
    manifest = _read_json_strict(bundle_dir / "manifest.json")
    if manifest:
        for key, entry in (manifest.get("inputs") or {}).items():
            if key.endswith("_active.json") and isinstance(entry, dict) and entry.get("sha256"):
                site_map_sha = str(entry["sha256"]).lower()
        reg_meta = (manifest.get("equipment") or {}).get("registration")
        if isinstance(reg_meta, dict) and reg_meta.get("source_sha256"):
            reg_sha = str(reg_meta["source_sha256"]).lower()
    timeline = _read_json_strict(bundle_dir / "data" / "factory-timeline.json")
    if not site_map_sha and timeline:
        site_map_sha = str(timeline.get("site_map_sha256") or "").lower()
    fleet_robots = (timeline.get("fleet_robots") if timeline else None) or CANONICAL_FLEET_ROBOTS
    site_map = _read_json_strict(bundle_dir / "data" / "site-map.json") or {}
    body_sha = _valid_sha256(site_map.get("sha256"))
    if body_sha is None and isinstance(site_map.get("map"), dict):
        raw = json.dumps(site_map["map"], sort_keys=True, ensure_ascii=False).encode("utf-8")
        body_sha = hashlib.sha256(raw).hexdigest()
    return {
        "site_map_sha256": site_map_sha,
        "site_map_body_sha256": body_sha,
        "site_map_version": site_map.get("version"),
        "registration_sha256": reg_sha,
        "fleet_robots": fleet_robots,
        "has_cargo_tray": True,
    }


def verify_world_parity(canonical: dict, payload: dict | None) -> dict:
    """Fail-closed parity verification guaranteeing only the environment backend differs."""
    reasons: list[str] = []
    if not isinstance(payload, dict):
        return {"ok": False, "map_match": False, "robot_match": False, "tray_match": False, "reasons": ["missing_payload"]}
    p_src = payload.get("parity") if isinstance(payload.get("parity"), dict) else {}
    ref_map = str(canonical.get("site_map_sha256") or "").lower()
    cand_map = str(p_src.get("site_map_sha256") or payload.get("site_map_sha256") or "").lower()
    ref_body = _valid_sha256(canonical.get("site_map_body_sha256"))
    cand_body = _valid_sha256(payload.get("site_map_body_sha256"))
    versions = {}
    if payload.get("adapter") == "real" or (ref_body and cand_body):
        versions = {"bundle_map_version": canonical.get("site_map_version"), "live_map_version": payload.get("site_map_version")}
        map_match = bool(ref_body and cand_body and ref_body == cand_body)
        if not cand_body:
            reasons.append("live_site_map_unavailable")
        elif not ref_body:
            reasons.append("bundle_site_map_unavailable")
        elif not map_match:
            reasons.append("site_map_sha256_mismatch")
    else:
        map_match = bool(SHA256_RE.fullmatch(ref_map) and cand_map == ref_map)
        if not map_match:
            reasons.append("site_map_sha256_mismatch")

    ref_reg = canonical.get("registration_sha256")
    cand_reg = p_src.get("registration_sha256")
    if ref_reg and cand_reg and str(cand_reg).lower() != str(ref_reg).lower():
        map_match = False
        reasons.append("registration_sha256_mismatch")

    ref_robots = canonical.get("fleet_robots") or CANONICAL_FLEET_ROBOTS
    cand_robots = p_src.get("fleet_robots") or payload.get("fleet_robots")
    if not isinstance(cand_robots, dict) and isinstance(payload.get("pinkys"), list) and isinstance(payload.get("arms"), dict):
        cand_robots = {"pinkys": [p.get("id") for p in payload["pinkys"]], "arms": list(payload["arms"].keys())}
    robot_match = (
        isinstance(cand_robots, dict)
        and cand_robots.get("pinkys") == ref_robots.get("pinkys")
        and sorted(cand_robots.get("arms") or []) == sorted(ref_robots.get("arms") or [])
    )
    if not robot_match:
        reasons.append("fleet_robots_mismatch")

    has_tray = (
        p_src.get("has_cargo_tray") is True
        or payload.get("has_cargo_tray") is True
    )
    if not has_tray:
        reasons.append("missing_pinky_cargo_tray")

    return {
        **versions,
        "ok": map_match and robot_match and has_tray and not reasons,
        "map_match": map_match,
        "robot_match": robot_match,
        "tray_match": has_tray,
        "reasons": reasons,
    }


def _safe_world_path(worlds_dir: Path, world_id: str) -> Path | None:
    if not isinstance(world_id, str) or ".." in world_id or not WORLD_ID_RE.fullmatch(world_id):
        return None
    root = worlds_dir.resolve()
    candidate = (root / f"{world_id}.json").resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _atomic_write_json(target: Path, payload: dict) -> None:
    root = target.parent.resolve()
    root.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=f".{target.stem}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temp_path, target)
                temp_path = None
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def discover_worlds(
    bundle_dir: Path,
    now_ms: int,
    adapter_filter: str | None = None,
    worlds_dir: Path | None = None,
) -> dict:
    """List parallel simulation worlds, verified replay, and explicit read-only Real status."""
    data_dir = bundle_dir / "data"
    canonical = _canonical_reference(bundle_dir)
    worlds: list[dict] = []

    worlds_dir = worlds_dir if worlds_dir is not None else (data_dir / "worlds")
    if worlds_dir.is_dir():
        resolved_dir = worlds_dir.resolve()
        for path in sorted(worlds_dir.glob("*.json")):
            if path.name.startswith(".") or not WORLD_ID_RE.fullmatch(path.stem):
                continue
            try:
                if not path.resolve().is_relative_to(resolved_dir):
                    continue
            except OSError:
                continue
            data = _read_json_strict(path)
            if data is None:
                worlds.append({
                    "world_id": path.stem, "adapter": "real" if path.stem == "real-site" else "mujoco", "status": "stalled",
                    "run_id": path.stem, "observed_at_ms": None, "age_ms": None,
                    "parity": {"ok": False, "map_match": False, "robot_match": False, "tray_match": False, "reasons": ["invalid_json"]},
                    "training": None,
                })
                continue
            adapter = "real" if path.stem == "real-site" else str(
                data.get("adapter") or (data.get("env") or {}).get("backend") or data.get("simulator") or "mujoco"
            )
            if adapter not in BACKENDS:
                adapter = "mujoco"
            obs = data.get("observed_at_ms")
            age_ms = max(0, now_ms - obs) if isinstance(obs, int) else None
            fresh = _is_fresh(data, path.stem, now_ms)
            if adapter == "real" and data.get("stream_mode") not in (None, "live"):
                fresh = False
            status = _live_stream_mode(data) if fresh else "stalled"
            stages = data.get("stages") or []
            stage_ids = [s.get("id") for s in stages if isinstance(s, dict)]
            stage = data.get("stage")
            worlds.append({
                "world_id": path.stem,
                "adapter": adapter,
                "adapter_label": ADAPTER_LABELS.get(adapter, adapter),
                "status": status,
                "run_id": data.get("run_id") or path.stem,
                "observed_at_ms": obs if isinstance(obs, int) else None,
                "age_ms": age_ms,
                "stage": stage,
                "stage_idx": (stage_ids.index(stage) + 1) if stage in stage_ids else None,
                "total_stages": len(stage_ids) or None,
                "sim_time_s": data.get("sim_time_s"),
                "duration_s": data.get("duration_s"),
                "training": data.get("training"),
                "safety": data.get("safety") if isinstance(data.get("safety"), dict) else None,
                "fleet_summary": data.get("fleet_summary") if isinstance(data.get("fleet_summary"), dict) else None,
                "parity": verify_world_parity(canonical, data),
            })

    timeline_path = data_dir / "factory-timeline.json"
    timeline = _read_json_strict(timeline_path)
    if timeline is not None:
        stages = timeline.get("stages") or []
        worlds.append({
            "world_id": "verified-replay",
            "adapter": "mujoco",
            "adapter_label": ADAPTER_LABELS["mujoco"],
            "status": "replay",
            "run_id": timeline.get("run_id") or "verified-replay",
            "observed_at_ms": now_ms,
            "age_ms": 0,
            "stage": stages[0].get("id") if stages else None,
            "stage_idx": 1 if stages else None,
            "total_stages": len(stages) or None,
            "sim_time_s": 0.0,
            "duration_s": timeline.get("duration_s"),
            "training": None,
            "parity": verify_world_parity(canonical, {
                "site_map_sha256": timeline.get("site_map_sha256"),
                "fleet_robots": timeline.get("fleet_robots"),
                "has_cargo_tray": True,
            }),
        })

    if not any(w["world_id"] == "real-site" or (w["adapter"] == "real" and w["status"] == "live") for w in worlds):
        worlds.append({
            "world_id": "real-site",
            "adapter": "real",
            "adapter_label": ADAPTER_LABELS["real"],
            "status": "waiting",
            "run_id": "real-site",
            "observed_at_ms": None,
            "age_ms": None,
            "stage": None,
            "stage_idx": None,
            "total_stages": None,
            "sim_time_s": None,
            "duration_s": None,
            "training": None,
            "parity": {
                "ok": bool(SHA256_RE.fullmatch(str(canonical.get("site_map_sha256") or ""))),
                "map_match": True,
                "robot_match": True,
                "tray_match": True,
                "reasons": [],
            },
        })

    adapters = []
    for aid in BACKENDS:
        matched = [w for w in worlds if w["adapter"] == aid]
        live_n = sum(1 for w in matched if w["status"] in ("live", "replay", "synthetic_demo"))
        adapters.append({"id": aid, "label": ADAPTER_LABELS[aid], "count": len(matched), "live_count": live_n})

    filtered = [w for w in worlds if w["adapter"] == adapter_filter] if adapter_filter in BACKENDS else worlds
    return {
        "schema": "rosy.world.registry.v1",
        "observed_at_ms": now_ms,
        "canonical": canonical,
        "adapters": adapters,
        "worlds": filtered,
    }


def _live_state(data_dir: Path, now_ms: int) -> dict | None:
    factory_live = _read_fresh_json(data_dir / "factory-live.json", now_ms)
    if factory_live and factory_live.get("schema") == "rosy.world.factory-state.v1":
        return {**factory_live, "stream_mode": _live_stream_mode(factory_live)}
    pinky = _read_fresh_json(data_dir / "pinky-sim.json", now_ms)
    if pinky and pinky.get("schema") == "rosy.world.pinky-sim.v1":
        isaac = _read_fresh_json(data_dir / "isaac-live.json", now_ms)
        pose = pinky["pose_m"]
        return {
            "schema": "rosy.world.factory-state.v1",
            "stream_mode": "live",
            "run_id": pinky["run_id"],
            "sim_time_s": pinky["sim_time_s"],
            "duration_s": None,
            "observed_at_ms": now_ms,
            "stage": "s3_stop" if abs(pose[0] - 0.745) <= 0.04 and abs(pose[1] + 0.207) <= 0.025 else "c2_departure",
            "simulator": "isaac" if isaac and isaac.get("state") == "running" else "gazebo",
            "phase": "live_sim",
            "pinky": {"pose_m": pose, "yaw_rad": pinky["yaw_rad"], "has_cargo": True,
                      "s3_in_bounds": abs(pose[0] - 0.745) <= 0.04 and abs(pose[1] + 0.207) <= 0.025},
            "cargo": {"zone": "pinky_tray", "pose_m": [pose[0], pose[1], 0.115], "yaw_rad": pinky["yaw_rad"]},
            "arm_s_ee_m": None,
            "cell_ab": {"active_arm": None, "active_step": None, "stacked": []},
        }
    return None


def _clamp(raw: list[str] | None, default: float, lo: float, hi: float) -> float:
    try:
        value = float(raw[0]) if raw else default
        return max(lo, min(hi, value)) if math.isfinite(value) else default
    except (ValueError, IndexError):
        return default
