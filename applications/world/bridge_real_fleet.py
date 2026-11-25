#!/usr/bin/env python3
"""Strict read-only Fleet -> Rosy World real-site bridge.

Polls Fleet's GET /api/fleet/state endpoint and publishes live `adapter: "real"`
snapshots into ROSY World (`data/worlds/real-site.json` and/or HTTP ingest).
Never issues control commands to Fleet or CORE, and never fabricates offline motion.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request

CANONICAL_FLEET_ROBOTS = {
    "pinkys": ["rosy_42", "rosy_45", "rosy_46"],
    "arms": ["arm_s", "arm_a", "arm_b"],
}
_DEFAULT_PARKED_PINKYS = {
    "rosy_42": [-0.414, 0.47, 0.0],
    "rosy_45": [-0.1914, 0.47, 0.0],
    "rosy_46": [0.032, 0.47, 0.0],
}
_REST_ARM_JOINTS = [0.0, -1.0, 0.7, 0.3, 0.0, 0.0]


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _bundle_site_map_sha256(bundle_dir: Path | None) -> str:
    if bundle_dir is None:
        return ""
    manifest_path = bundle_dir / "data" / "manifest.json"
    if not manifest_path.is_file():
        manifest_path = bundle_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for key, entry in (manifest.get("inputs") or {}).items():
        if key.endswith("_active.json") and isinstance(entry, dict) and entry.get("sha256"):
            return str(entry["sha256"]).lower()
    return ""


def _read_secret(env_name: str, file_env_name: str, file_path: Path | None = None) -> str | None:
    raw = os.environ.get(env_name, "").strip()
    if raw:
        return raw
    file_path = file_path or os.environ.get(file_env_name, "").strip()
    if file_path:
        try:
            text = Path(file_path).read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    return None


def _default_parked_pose(rid: str, idx: int) -> list[float]:
    if rid in _DEFAULT_PARKED_PINKYS:
        return list(_DEFAULT_PARKED_PINKYS[rid])
    return [round(-0.414 + 0.223 * idx, 4), 0.47, 0.0]


def _csv_env_ids(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default)
    seen: list[str] = []
    for part in raw.split(","):
        rid = part.strip()
        if rid and rid not in seen:
            seen.append(rid)
    return seen or list(default)


def _resolve_fleet_robots(fleet_payload: dict[str, Any]) -> dict[str, list[str]]:
    pinkys = _csv_env_ids("ROSY_WORLD_PINKY_IDS", CANONICAL_FLEET_ROBOTS["pinkys"])
    arms = _csv_env_ids("ROSY_WORLD_ARM_IDS", CANONICAL_FLEET_ROBOTS["arms"])
    known = set(pinkys) | set(arms)
    for row in fleet_payload.get("robots") or ():
        if not isinstance(row, dict) or not row.get("robot_id"):
            continue
        rid = str(row["robot_id"]).strip()
        if not rid or rid in known:
            continue
        kind = str(row.get("kind") or row.get("robot_type") or "").strip().lower()
        state = row.get("state") if isinstance(row.get("state"), dict) else {}
        if kind in {"arm", "manipulator"} or rid.startswith("arm"):
            arms.append(rid)
        elif kind in {"pinky", "amr"} or rid.startswith(("rosy", "pinky")) or isinstance(state.get("pose"), dict):
            pinkys.append(rid)
        known.add(rid)
    return {"pinkys": pinkys, "arms": arms}


def fleet_state_to_world_state(
    fleet_payload: dict[str, Any],
    *,
    site_map_sha256: str,
    world_id: str = "real-site",
    now_ms: int | None = None,
    arm_live_states: dict | None = None,
    active_map: dict | None = None,
) -> dict[str, Any] | None:
    """Translate a Fleet `/api/fleet/state` payload into canonical Real World state.

    Requires an online Pinky or observed arm joints.
    """
    if not isinstance(fleet_payload, dict) or not isinstance(fleet_payload.get("robots"), list):
        return None
    by_id = {
        str(row.get("robot_id")): row
        for row in fleet_payload["robots"]
        if isinstance(row, dict) and row.get("robot_id")
    }
    roster = _resolve_fleet_robots(fleet_payload)

    pinkys: list[dict[str, Any]] = []
    online_count = 0
    estop_robots: list[str] = []
    for idx, rid in enumerate(roster["pinkys"]):
        row = by_id.get(rid) or {}
        state = row.get("state") if isinstance(row.get("state"), dict) else {}
        pose = state.get("pose") if isinstance(state.get("pose"), dict) else {}
        px = _finite_number(pose.get("x"))
        py = _finite_number(pose.get("y"))
        yaw = _finite_number(pose.get("yaw"))
        online = bool(row.get("online"))
        safety = state.get("safety") if isinstance(state.get("safety"), dict) else {}
        if online:
            online_count += 1
        if safety.get("estop") is True:
            estop_robots.append(rid)
        loc = row.get("localization")
        unlocalized = isinstance(loc, dict) and (loc.get("trusted") is False or loc.get("pose_frame") == "odom")
        has_pose = online and px is not None and py is not None and yaw is not None
        battery = state.get("battery")
        entry = {
            "id": rid,
            "pose_m": [round(px, 5), round(py, 5), 0.0] if has_pose else _default_parked_pose(rid, idx),
            "yaw_rad": round(yaw, 5) if has_pose else -1.5708,
            "observed": has_pose and not unlocalized,
            "online": online,
            "has_cargo": False,
            "state_age_s": _finite_number(row.get("state_age_s")),
            "battery_percent": _finite_number(battery.get("percent")) if isinstance(battery, dict) else None,
            "estop": safety.get("estop"),
        }
        if unlocalized:
            entry.update(localized=False, loc_label=str(loc.get("label") or "위치 모름"))
        pinkys.append(entry)

    pinky_online = online_count > 0
    arms: dict[str, list[float]] = {arm_id: list(_REST_ARM_JOINTS) for arm_id in roster["arms"]}
    arms_observed, arms_fresh, arms_age_s = {}, {}, {}
    for arm_id in roster["arms"]:
        row = by_id.get(arm_id) or {}
        state = row.get("state") if isinstance(row.get("state"), dict) else {}
        safety = state.get("safety") if isinstance(state.get("safety"), dict) else {}
        if bool(row.get("online")):
            online_count += 1
        if safety.get("estop") is True:
            estop_robots.append(arm_id)
        live = (arm_live_states or {}).get(arm_id)
        live = live if isinstance(live, dict) else {}
        joints = live.get("joints_deg")
        parsed = [_finite_number(v) for v in joints] if isinstance(joints, list) and len(joints) == 6 else []
        valid = len(parsed) == 6 and all(v is not None for v in parsed)
        observed = valid and live.get("observed") is True and live.get("source") != "boot_default"
        if observed:
            arms[arm_id] = [math.radians(v) for v in parsed]
        arms_observed[arm_id] = observed
        arms_fresh[arm_id] = observed and live.get("fresh") is True
        arms_age_s[arm_id] = _finite_number(live.get("age_s"))

    if not pinky_online and not any(arms_observed.values()):
        return None

    primary = next((p for p in pinkys if p["observed"]), None)
    if primary is None:
        fallback_pinky = pinkys[min(1, len(pinkys) - 1)] if pinkys else {
            "id": None, "pose_m": [0.0, 0.0, 0.0], "yaw_rad": -1.5708, "observed": False, "online": False,
        }
        primary = next((p for p in pinkys if p["online"]), fallback_pinky)
    px, py, _ = primary["pose_m"]
    s3_in_bounds = bool(primary.get("observed")) and abs(px - 0.745) <= 0.04 and abs(py + 0.207) <= 0.025
    observed_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    gathered_at = _finite_number(fleet_payload.get("gathered_at"))
    gathered_ms = _finite_number(gathered_at * 1000) if gathered_at is not None else None
    active_map = active_map or {}
    live_map_sha = active_map.get("sha256")
    total_robots = len(roster["pinkys"]) + len(roster["arms"])
    parity = {
        "schema": "rosy.world.parity.v1",
        "site_map_sha256": str(site_map_sha256 or "").lower(),
        "registration_sha256": None,
        "fleet_robots": roster,
        "has_cargo_tray": True,
    }
    return {
        "schema": "rosy.world.factory-state.v1",
        "stream_mode": "live",
        "world_id": world_id,
        "adapter": "real",
        "simulator": "real",
        "run_id": world_id,
        "sim_time_s": 0.0,
        "observed_at_ms": observed_ms,
        "fleet_gathered_at_ms": int(gathered_ms) if gathered_ms is not None else None,
        "has_cargo_tray": True,
        "site_map_sha256": parity["site_map_sha256"],
        "site_map_body_sha256": str(live_map_sha).lower() if live_map_sha else None,
        "site_map_version": active_map.get("version"),
        "fleet_robots": roster,
        "parity": parity,
        "stage": "s3_stop" if s3_in_bounds else "c2_departure",
        "phase": "real_fleet_live",
        "pinky": {
            **primary,
            "s3_in_bounds": s3_in_bounds,
            "observed": bool(primary.get("observed")),
        },
        "pinkys": pinkys,
        "arms": arms,
        "arms_observed": arms_observed,
        "arms_fresh": arms_fresh,
        "arms_age_s": arms_age_s,
        "safety": {
            "estop": bool(estop_robots),
            "estop_all": total_robots > 0 and len(estop_robots) == total_robots,
            "estop_robots": estop_robots,
        },
        "fleet_summary": {"online": online_count, "total": total_robots},
        "cargo": {
            "zone": "unknown",
            "pose_m": [px, py, 0.115],
            "yaw_rad": primary["yaw_rad"],
            "observed": False,
        },
        "cell_ab": {"active_arm": None, "active_step": None, "stacked": []},
    }


def _fetch_fleet_state(
    fleet_url: str,
    *,
    token: str | None = None,
    ca_file: Path | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    return _get_fleet_json(fleet_url, "/api/fleet/state", token, ca_file, timeout_s)


def _get_fleet_json(fleet_url: str, path: str, token: str | None, ca_file: Path | None, timeout_s: float) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{fleet_url.rstrip('/')}{path}", headers=headers, method="GET")
    context = ssl.create_default_context(cafile=str(ca_file)) if ca_file else None
    with urllib.request.urlopen(req, timeout=timeout_s, context=context) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_optional(fleet_url: str, path: str, token: str | None, ca_file: Path | None) -> dict | None:
    try:
        payload = _get_fleet_json(fleet_url, path, token, ca_file, 2.0)
    except (OSError, http.client.HTTPException, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _fetch_active_map(fleet_url: str, token: str | None, ca_file: Path | None) -> dict | None:
    return _fetch_optional(fleet_url, "/api/fleet/site-map/active", token, ca_file)


def _write_local(worlds_dir: Path, world_id: str, payload: dict[str, Any]) -> None:
    worlds_dir.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(worlds_dir / f"{world_id}.json", raw)


def _atomic_write(path: Path, raw: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as h:
            temp_path = Path(h.name)
            h.write(raw)
            h.flush()
            os.fsync(h.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _push_http(world_url: str, world_id: str, payload: dict[str, Any], token: str | None) -> None:
    raw = (json.dumps(payload, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{world_url.rstrip('/')}/api/worlds/{world_id}", data=raw, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=1.5).close()


def _resolve_mdns(role: str, mdns_host: str, port: int, *, ca_file: Path | None = None) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import world_mdns

    if role == "fleet":
        return world_mdns.discover_fleet_endpoint(mdns_host, default_port=port, ca_file=ca_file)
    return world_mdns.discover_world_endpoint(mdns_host, default_port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    fleet_src = parser.add_mutually_exclusive_group(required=True)
    fleet_src.add_argument("--fleet-url", help="Fleet HTTP/HTTPS base URL")
    fleet_src.add_argument("--fleet-mdns-host", help="Fleet .local mDNS hostname (resolved via _rosy-fleet._tcp or NSS)")
    parser.add_argument("--fleet-port", type=int, default=8443, help="Fleet HTTPS port when using --fleet-mdns-host")
    parser.add_argument("--fleet-timeout", type=float, default=10.0, help="Fleet state timeout in seconds (1.0-30.0)")
    parser.add_argument("--bundle", type=Path, help="optional built World bundle root")
    parser.add_argument("--world-url", help="optional Rosy World HTTP base URL")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140, help="World port when using --world-mdns-host")
    parser.add_argument("--worlds-dir", type=Path, help="optional local data/worlds output dir")
    parser.add_argument("--world-id", default="real-site")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--fleet-token-env", default="ROSY_FLEET_TOKEN")
    parser.add_argument("--fleet-token-file", type=Path)
    parser.add_argument("--fleet-token-file-env", default="ROSY_FLEET_TOKEN_FILE")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    parser.add_argument("--ca-file", type=Path, help="optional PEM CA file (or use SSL_CERT_FILE)")
    parser.add_argument("--interval", type=float, default=0.5, help="polling interval in seconds (0.2-10.0)")
    parser.add_argument("--heartbeat-file", type=Path, help="write Fleet poll time after a successful fetch")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()

    bundle = args.bundle.resolve() if args.bundle else None
    has_world_dest = bool(args.world_url or args.world_mdns_host)
    worlds_dir = args.worlds_dir or ((bundle / "data" / "worlds") if (bundle and not has_world_dest) else None)
    if worlds_dir is None and not has_world_dest:
        parser.error("provide --worlds-dir, --world-url, --world-mdns-host, or --bundle")
    site_map_sha = (args.site_map_sha256 or _bundle_site_map_sha256(bundle)).lower()
    ca_env = os.environ.get("SSL_CERT_FILE", "").strip()
    ca_file = args.ca_file or (Path(ca_env) if ca_env else None)
    interval = max(0.2, min(10.0, float(args.interval)))
    fleet_timeout = max(1.0, min(30.0, args.fleet_timeout)) if math.isfinite(args.fleet_timeout) else 10.0
    cached_fleet_url: str | None = args.fleet_url
    cached_world_url: str | None = args.world_url
    last_err_at: dict[str, float] = {}
    map_url: str | None = None
    map_expires_at = 0.0
    active_map = None

    def warn(key: str, exc: object) -> None:
        now = time.monotonic()
        if (now - last_err_at.get(key, -1e9)) >= 10.0:
            last_err_at[key] = now
            print(f"real-bridge [{key}]: {exc}", file=sys.stderr, flush=True)

    def tick() -> bool:
        nonlocal cached_fleet_url, cached_world_url, map_url, map_expires_at, active_map
        fleet_token = _read_secret(args.fleet_token_env, args.fleet_token_file_env, args.fleet_token_file)
        ingest_token = os.environ.get(args.ingest_token_env, "").strip() or None
        if cached_fleet_url is None and args.fleet_mdns_host:
            try:
                cached_fleet_url = _resolve_mdns("fleet", args.fleet_mdns_host, args.fleet_port, ca_file=ca_file)
            except (OSError, ValueError) as exc:
                warn("fleet-mdns", exc)
                return False
        if not cached_fleet_url:
            return False
        try:
            fleet_payload = _fetch_fleet_state(cached_fleet_url, token=fleet_token, ca_file=ca_file, timeout_s=fleet_timeout)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            warn("fleet-fetch", exc)
            if args.fleet_mdns_host:
                cached_fleet_url = None
            return False
        if args.heartbeat_file is not None:
            try:
                _atomic_write(args.heartbeat_file, f"{time.time()}\n".encode("ascii"))
            except OSError as exc:
                warn("heartbeat", exc)
        cell_tasks = _fetch_optional(cached_fleet_url, "/api/fleet/pipeline/cell-tasks", fleet_token, ca_file)
        arm_live_states = (cell_tasks or {}).get("arm_live_states")
        if map_url != cached_fleet_url or time.monotonic() >= map_expires_at:
            active_map = _fetch_active_map(cached_fleet_url, fleet_token, ca_file)
            map_url = cached_fleet_url
            map_expires_at = time.monotonic() + 30.0
        world_payload = fleet_state_to_world_state(
            fleet_payload, site_map_sha256=site_map_sha, world_id=args.world_id,
            arm_live_states=arm_live_states if isinstance(arm_live_states, dict) else None,
            active_map=active_map,
        )
        if world_payload is None:
            return False
        if worlds_dir is not None:
            _write_local(worlds_dir, args.world_id, world_payload)
        if cached_world_url is None and args.world_mdns_host:
            try:
                cached_world_url = _resolve_mdns("world", args.world_mdns_host, args.world_port)
            except (OSError, ValueError) as exc:
                warn("world-mdns", exc)
                return False
        if cached_world_url:
            try:
                _push_http(cached_world_url, args.world_id, world_payload, ingest_token)
            except (OSError, urllib.error.URLError) as exc:
                warn("world-push", exc)
                if args.world_mdns_host:
                    cached_world_url = None
                return False
        return True

    if args.once:
        ok = tick()
        print(json.dumps({"ok": ok, "world_id": args.world_id}))
        return
    try:
        while True:
            tick()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
