"""Serve a built ROSY World application, live observations, and SSE factory stream."""

import argparse
from bisect import bisect_right
from functools import partial
import hmac
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit


DEFAULT_PORT = 8140
LIVE_FRESH_MS = 3000
MAX_INGEST_BYTES = 262_144
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
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
LIVE_PATHS = {
    "/data/pinky-sim.json", "/data/pinky-camera.jpg", "/data/isaac-live.json",
    "/data/mujoco-top.jpg", "/data/field-live.jpg", "/data/isaac-view.json",
    "/data/factory-live.json",
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
    obs = data.get("observed_at_ms")
    if not isinstance(obs, int) or abs(now_ms - obs) > LIVE_FRESH_MS:
        return None
    return data


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
    return {
        "site_map_sha256": site_map_sha,
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
    has_live_real = False

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
                    "world_id": path.stem, "adapter": "mujoco", "status": "stalled",
                    "run_id": path.stem, "observed_at_ms": None, "age_ms": None,
                    "parity": {"ok": False, "map_match": False, "robot_match": False, "tray_match": False, "reasons": ["invalid_json"]},
                    "training": None,
                })
                continue
            adapter = str(data.get("adapter") or (data.get("env") or {}).get("backend") or data.get("simulator") or "mujoco")
            if adapter not in BACKENDS:
                adapter = "mujoco"
            obs = data.get("observed_at_ms")
            age_ms = max(0, now_ms - obs) if isinstance(obs, int) else None
            fresh = age_ms is not None and age_ms <= LIVE_FRESH_MS
            status = "live" if fresh else "stalled"
            if adapter == "real" and fresh:
                has_live_real = True
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

    if not has_live_real:
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
        live_n = sum(1 for w in matched if w["status"] in ("live", "replay"))
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
        return {**factory_live, "stream_mode": "live"}
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


class WorldHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".webmanifest": "application/manifest+json"}

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def json_reply(self, status, value):
        data = json.dumps(value, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return BytesIO(data)

    def _worlds_dir(self) -> Path:
        return getattr(self.server, "worlds_dir", Path(self.directory) / "data" / "worlds")

    def _authorize_ingest(self) -> tuple[bool, int, str]:
        token = getattr(self.server, "ingest_token", None)
        if token:
            header = self.headers.get("Authorization") or ""
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer" or not supplied:
                return False, 401, "missing ingest bearer token"
            if not hmac.compare_digest(supplied.strip(), token):
                return False, 403, "invalid ingest bearer token"
            return True, 200, ""
        client_ip = (self.client_address[0] if self.client_address else "")
        if client_ip in LOOPBACK_HOSTS:
            return True, 200, ""
        return False, 403, "remote ingest requires ROSY_WORLD_INGEST_TOKEN"

    def _parse_world_ingest_id(self) -> str | None:
        path = urlsplit(self.path).path
        if not path.startswith("/api/worlds/"):
            return None
        return path.removeprefix("/api/worlds/")

    def send_head(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/mdns":
            port = self.server.server_port
            mdns_host = getattr(self.server, "mdns_host", None)
            fleet_host = getattr(self.server, "fleet_mdns_host", None)
            return self.json_reply(200, {
                "schema": "rosy.world.mdns.v1",
                "service_type": "_rosy-world._tcp",
                "hostname": mdns_host,
                "port": port,
                "fleet_mdns_host": fleet_host,
                "worlds_api": "/api/worlds",
            })
        if parts.path == "/api/worlds":
            query = parse_qs(parts.query)
            adapter_filter = (query.get("adapter") or [None])[0]
            if adapter_filter and adapter_filter not in ("all", *BACKENDS):
                return self.json_reply(400, {"error": f"invalid adapter: {adapter_filter}"})
            now_ms = time.time_ns() // 1_000_000
            return self.json_reply(
                200, discover_worlds(Path(self.directory), now_ms, adapter_filter, worlds_dir=self._worlds_dir()),
            )
        if self.path == "/sim/control":
            controller = getattr(self.server, "sim_control", None)
            if controller is not None:
                return self.json_reply(200, controller.status())
            self.send_error(404)
            return None
        if parts.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.server.health)))
            self.end_headers()
            return BytesIO(self.server.health)
        return super().send_head()

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/sim/stream":
            return self._stream_factory(parse_qs(parts.query))
        return super().do_GET()

    def _stream_factory(self, query: dict[str, list[str]]) -> None:
        mode = (query.get("mode") or ["auto"])[0]
        if mode not in ("auto", "live", "timeline"):
            mode = "auto"
        world_id = (query.get("world") or [None])[0]
        adapter = (query.get("adapter") or [None])[0]
        if adapter and adapter not in ("all", *BACKENDS):
            with self.json_reply(400, {"error": f"invalid adapter: {adapter}"}) as reply:
                self.copyfile(reply, self.wfile)
            return

        bundle_dir = Path(self.directory)
        data_dir = bundle_dir / "data"
        worlds_dir = self._worlds_dir()
        canonical = _canonical_reference(bundle_dir)
        world_file: Path | None = None
        if world_id is not None:
            if world_id not in ("verified-replay", "real-site"):
                world_file = _safe_world_path(worlds_dir, world_id)
                if world_file is None:
                    with self.json_reply(400, {"error": "invalid world id"}) as reply:
                        self.copyfile(reply, self.wfile)
                    return
                if not world_file.is_file():
                    with self.json_reply(404, {"error": f"unknown world: {world_id}"}) as reply:
                        self.copyfile(reply, self.wfile)
                    return

        speed = _clamp(query.get("speed"), 1.0, 0.25, 8.0)
        hz = _clamp(query.get("hz"), 25.0, 5.0, 30.0)
        start_s = _clamp(query.get("start_s"), 0.0, 0.0, 3600.0)
        max_events = None
        if "max_events" in query:
            try:
                max_events = max(1, int(query["max_events"][0]))
            except ValueError:
                max_events = 1

        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close" if max_events is not None else "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        timeline_path = data_dir / "factory-timeline.json"
        cached_timeline: tuple[int, dict] | None = None
        started = time.monotonic()
        stop_event = getattr(self.server, "stop_event", None)
        sent = 0
        period = 1.0 / hz
        try:
            while max_events is None or sent < max_events:
                if stop_event is not None and stop_event.is_set():
                    break
                now_ms = time.time_ns() // 1_000_000
                payload = None
                event_name = "state"

                if world_id == "real-site" or adapter == "real":
                    # Anti-faking guardrail: real mode never falls back to simulation replay.
                    live_real = _read_fresh_json(world_file, now_ms) if world_file else None
                    if live_real is None and worlds_dir.is_dir():
                        for cand_path in sorted(worlds_dir.glob("*.json")):
                            cand = _read_fresh_json(cand_path, now_ms)
                            if cand and cand.get("adapter") == "real":
                                live_real = cand
                                break
                    if live_real is not None:
                        payload = {**live_real, "stream_mode": "live", "adapter": "real", "parity": verify_world_parity(canonical, live_real)}
                    else:
                        event_name = "idle"
                        payload = {
                            "schema": "rosy.world.factory-state.v1",
                            "stream_mode": "waiting",
                            "state": "waiting",
                            "adapter": "real",
                            "world_id": "real-site",
                            "reason": "실물 현장 미연결",
                            "observed_at_ms": now_ms,
                        }
                elif world_file is not None:
                    snap = _read_fresh_json(world_file, now_ms)
                    if snap is not None:
                        snap_adapter = str(snap.get("adapter") or snap.get("simulator") or "mujoco")
                        payload = {
                            **snap,
                            "world_id": world_id,
                            "adapter": snap_adapter,
                            "stream_mode": "live",
                            "parity": verify_world_parity(canonical, snap),
                        }
                    else:
                        event_name = "idle"
                        payload = {
                            "schema": "rosy.world.factory-state.v1",
                            "stream_mode": "waiting",
                            "state": "stalled",
                            "world_id": world_id,
                            "reason": "시뮬레이션 갱신 중단",
                            "observed_at_ms": now_ms,
                        }
                else:
                    if world_id != "verified-replay" and mode in ("auto", "live"):
                        payload = _live_state(data_dir, now_ms)
                    if payload is None and mode in ("auto", "timeline") and timeline_path.is_file():
                        try:
                            mtime = timeline_path.stat().st_mtime_ns
                            if cached_timeline is None or cached_timeline[0] != mtime:
                                cached_timeline = (mtime, json.loads(timeline_path.read_bytes()))
                            payload = sample_timeline(cached_timeline[1], start_s + (time.monotonic() - started) * speed)
                            payload["parity"] = verify_world_parity(canonical, payload)
                        except (OSError, ValueError, KeyError):
                            payload = None
                    if payload is None:
                        event_name = "idle"
                        payload = {"schema": "rosy.world.factory-state.v1", "state": "waiting", "observed_at_ms": now_ms}

                chunk = f"event: {event_name}\ndata: {json.dumps(payload, allow_nan=False)}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
                sent += 1
                if max_events is not None and sent >= max_events:
                    break
                wait_s = 1.0 if event_name == "idle" else period
                if stop_event is not None and stop_event.wait(wait_s):
                    break
                if stop_event is None:
                    time.sleep(wait_s)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def end_headers(self):
        path = urlsplit(self.path).path
        if (
            path in LIVE_PATHS
            or path in ("/", "/healthz", "/api/mdns", "/api/worlds", "/sim/control", "/sim/stream")
            or path.endswith((".html", ".js", ".css", ".json", ".webmanifest"))
        ):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def _reply_json(self, status: int, value: dict) -> None:
        with self.json_reply(status, value) as reply:
            self.copyfile(reply, self.wfile)

    def _ingest_world(self, raw_id: str) -> None:
        allowed, auth_status, auth_err = self._authorize_ingest()
        if not allowed:
            return self._reply_json(auth_status, {"error": auth_err})
        if raw_id == "verified-replay":
            return self._reply_json(400, {"error": "verified-replay cannot be overwritten"})
        target = _safe_world_path(self._worlds_dir(), raw_id)
        if target is None:
            return self._reply_json(400, {"error": "invalid world id"})
        if self.headers.get_content_type() != "application/json":
            return self._reply_json(400, {"error": "expected application/json"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._reply_json(400, {"error": "invalid Content-Length"})
        if size <= 0:
            return self._reply_json(400, {"error": "empty JSON body"})
        if size > MAX_INGEST_BYTES:
            return self._reply_json(413, {"error": f"payload exceeds {MAX_INGEST_BYTES} bytes"})
        try:
            self.connection.settimeout(2)
            body = json.loads(self.rfile.read(size).decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError, OSError) as error:
            return self._reply_json(400, {"error": str(error)})
        if not isinstance(body, dict) or body.get("schema") != "rosy.world.factory-state.v1":
            return self._reply_json(400, {"error": "expected rosy.world.factory-state.v1 object"})
        adapter = str(
            body.get("adapter")
            or (body.get("env") or {}).get("backend")
            or body.get("simulator")
            or ""
        )
        if adapter not in BACKENDS:
            return self._reply_json(400, {"error": f"unsupported adapter: {adapter!r}"})
        if adapter == "real" or raw_id == "real-site":
            if body.get("stream_mode") not in (None, "live"):
                return self._reply_json(403, {"error": "real world rejects non-live stream_mode"})
            adapter = "real"
            body["stream_mode"] = "live"
        body["world_id"] = raw_id
        body["adapter"] = adapter
        body.setdefault("observed_at_ms", time.time_ns() // 1_000_000)
        canonical = _canonical_reference(Path(self.directory))
        parity = verify_world_parity(canonical, body)
        _atomic_write_json(target, body)
        return self._reply_json(200, {"ok": True, "world_id": raw_id, "adapter": adapter, "parity": parity})

    def do_POST(self):
        raw_id = self._parse_world_ingest_id()
        if raw_id is not None:
            return self._ingest_world(raw_id)
        controller = getattr(self.server, "sim_control", None)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if controller is None or self.path != "/sim/control":
            self.send_error(404)
            return
        if self.headers.get("Origin") != origin or self.headers.get("Host") != origin.removeprefix("http://"):
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 512 or self.headers.get_content_type() != "application/json":
                raise ValueError("expected a small JSON control message")
            self.connection.settimeout(2)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("expected a control object")
            if body.get("adapter") == "real" or body.get("world_id") == "real-site":
                status, value = 403, {"error": "real hardware control forbidden"}
            else:
                status, value = controller.command(body)
        except (ValueError, OSError) as error:
            status, value = 400, {"error": str(error)}
        self._reply_json(status, value)

    def do_DELETE(self):
        raw_id = self._parse_world_ingest_id()
        if raw_id is None:
            self.send_error(404)
            return
        allowed, auth_status, auth_err = self._authorize_ingest()
        if not allowed:
            return self._reply_json(auth_status, {"error": auth_err})
        if raw_id == "verified-replay":
            return self._reply_json(400, {"error": "verified-replay cannot be deleted"})
        target = _safe_world_path(self._worlds_dir(), raw_id)
        if target is None:
            return self._reply_json(400, {"error": "invalid world id"})
        existed = target.is_file()
        target.unlink(missing_ok=True)
        return self._reply_json(200, {"ok": True, "world_id": raw_id, "deleted": existed})

    def log_message(self, fmt, *args):
        if sys.stderr is not None:
            super().log_message(fmt, *args)


class WorldHTTPServer(ThreadingHTTPServer):
    """HTTP/SSE server sized for concurrent static asset + EventSource loads on Windows and Linux."""

    request_queue_size = 128
    allow_reuse_address = True


def make_server(
    root: Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    *,
    worlds_dir: Path | None = None,
    ingest_token: str | None = None,
    mdns_host: str | None = None,
    fleet_mdns_host: str | None = None,
) -> ThreadingHTTPServer:
    handler = partial(WorldHandler, directory=str(root))
    server = WorldHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.stop_event = threading.Event()
    server.worlds_dir = (worlds_dir if worlds_dir is not None else (root / "data" / "worlds")).resolve()
    resolved_token = ingest_token if ingest_token is not None else os.environ.get("ROSY_WORLD_INGEST_TOKEN", "")
    server.ingest_token = resolved_token.strip() or None
    default_mdns = f"{socket.gethostname().split('.')[0].lower()}.local"
    resolved_mdns = (mdns_host if mdns_host is not None else os.environ.get("ROSY_WORLD_MDNS_HOST", "")).strip()
    server.mdns_host = resolved_mdns or default_mdns
    resolved_fleet = (fleet_mdns_host if fleet_mdns_host is not None else os.environ.get("ROSY_FLEET_MDNS_HOST", "")).strip()
    server.fleet_mdns_host = resolved_fleet or None
    server.health = b'{"application":"rosy-world","status":"ready"}\n'
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).parent)
    parser.add_argument("--worlds-dir", type=Path, default=None, help="writable directory for live world JSON snapshots")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN", help="env var holding bearer token for remote POST/DELETE /api/worlds/<id>")
    parser.add_argument("--mdns-host", default=None, help="advertised .local hostname (or $ROSY_WORLD_MDNS_HOST)")
    parser.add_argument("--fleet-mdns-host", default=None, help="paired Fleet .local hostname (or $ROSY_FLEET_MDNS_HOST)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    root = args.bundle.resolve()
    env_worlds = os.environ.get("ROSY_WORLD_WORLDS_DIR", "").strip()
    worlds_dir = args.worlds_dir if args.worlds_dir is not None else (Path(env_worlds) if env_worlds else None)
    ingest_token = os.environ.get(args.ingest_token_env, "").strip() or None
    try:
        for name in ("index.html", "app.js", "SHA256SUMS.txt"):
            if not (root / name).is_file():
                raise ValueError(f"incomplete bundle: {name} is missing")
        manifest = json.loads((root / "manifest.json").read_bytes())
        if not isinstance(manifest.get("inputs"), dict):
            raise ValueError("invalid ROSY World manifest")
        with make_server(
            root,
            args.host,
            args.port,
            worlds_dir=worlds_dir,
            ingest_token=ingest_token,
            mdns_host=args.mdns_host,
            fleet_mdns_host=args.fleet_mdns_host,
        ) as server:
            try:
                server.serve_forever()
            finally:
                server.stop_event.set()
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, AttributeError) as error:
        parser.exit(1, f"rosy-world: {error}\n")


if __name__ == "__main__":
    main()
