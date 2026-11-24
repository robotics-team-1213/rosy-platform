"""Run parallel simulation/training worlds publishing live state to data/worlds/.

Keeps site map, registration, Pinky+J-v3 URDF, and OMX-AI fleet identical across
environments (`isaac`, `gazebo`, `mujoco`) so ONLY the physics/environment adapter differs.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

SIM_DIR = Path(__file__).resolve().parent
REPO = SIM_DIR.parents[1] if len(SIM_DIR.parents) > 1 and (SIM_DIR.parents[1] / "middleware").is_dir() else SIM_DIR
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from world_env_adapter import (  # noqa: E402
    CANONICAL_FLEET_ROBOTS,
    ENV_DESCRIPTOR_SCHEMA,
    FACTORY_STATE_SCHEMA,
    WorldPublisher,
    build_parity_fingerprint,
    load_pinky_tray_fingerprint,
)

DEFAULT_WORKERS = (
    {
        "world_id": "isaac-train-01",
        "backend": "isaac",
        "ros_domain_id": 101,
        "physics_profile": "isaac-physx-5.1",
        "start_offset_s": 15.5,
        "speed": 1.25,
        "base_episode": 148,
        "base_reward": 0.84,
        "success_rate": 0.94,
        "sim_fps": 120.0,
    },
    {
        "world_id": "mujoco-ab-02",
        "backend": "mujoco",
        "ros_domain_id": 102,
        "physics_profile": "servo-friction-20261109",
        "start_offset_s": 36.0,
        "speed": 1.5,
        "base_episode": 312,
        "base_reward": 0.91,
        "success_rate": 0.97,
        "sim_fps": 240.0,
    },
    {
        "world_id": "gazebo-nav-03",
        "backend": "gazebo",
        "ros_domain_id": 103,
        "physics_profile": "gz-dart-nominal",
        "start_offset_s": 0.0,
        "speed": 1.0,
        "base_episode": 64,
        "base_reward": 0.78,
        "success_rate": 0.92,
        "sim_fps": 60.0,
    },
)


def _sample_keyframe(timeline: dict, elapsed_s: float) -> dict:
    frames = timeline["keyframes"]
    duration = float(timeline["duration_s"]) or 1.0
    t = elapsed_s % duration
    times = [float(f["time_s"]) for f in frames]
    idx = min(max(bisect_right(times, t) - 1, 0), len(frames) - 1)
    kf = frames[idx]
    return {
        "stage": kf["stage"],
        "simulator": kf["simulator"],
        "phase": kf["phase"],
        "sim_time_s": round(t, 3),
        "duration_s": round(duration, 3),
        "s3_box": timeline.get("s3_box"),
        "arm_bases_site": timeline.get("arm_bases_site"),
        "fleet_robots": timeline.get("fleet_robots") or CANONICAL_FLEET_ROBOTS,
        "stages": timeline.get("stages", []),
        "pinky": dict(kf["pinky"]),
        "pinkys": list(kf.get("pinkys", [])),
        "arms": dict(kf.get("arms", {})),
        "cargo": dict(kf["cargo"]),
        "arm_s_ee_m": kf.get("arm_s_ee_m"),
        "cell_ab": kf["cell_ab"],
    }


def _canonical_parity(bundle_dir: Path, timeline: dict) -> dict:
    manifest_path = bundle_dir / "manifest.json"
    site_map_sha = str(timeline.get("site_map_sha256") or "")
    reg_sha = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, item in (manifest.get("inputs") or {}).items():
            if key.endswith("_active.json") and isinstance(item, dict) and item.get("sha256"):
                site_map_sha = item["sha256"]
        reg_meta = (manifest.get("equipment") or {}).get("registration")
        if isinstance(reg_meta, dict):
            reg_sha = reg_meta.get("source_sha256")
    geom_path = REPO / "middleware" / "devices" / "pinky" / "profile" / "config" / "geometry.yaml"
    tray_fp = load_pinky_tray_fingerprint(geom_path) if geom_path.is_file() else None
    return build_parity_fingerprint(
        site_map_sha256=site_map_sha,
        registration_sha256=reg_sha,
        fleet_robots=timeline.get("fleet_robots") or CANONICAL_FLEET_ROBOTS,
        has_cargo_tray=True,
        cargo_tray=tray_fp,
    )


def build_worker_snapshot(
    worker: dict,
    timeline: dict,
    parity: dict,
    step_idx: int,
    elapsed_s: float,
    *,
    mismatch_map: bool = False,
) -> dict:
    sample = _sample_keyframe(timeline, float(worker["start_offset_s"]) + elapsed_s * float(worker["speed"]))
    ep_steps = 120
    episode = int(worker["base_episode"]) + (step_idx // ep_steps)
    step = (step_idx % ep_steps) + 1
    reward = round(float(worker["base_reward"]) + 0.08 * math.sin(step_idx * 0.15), 3)
    worker_parity = dict(parity)
    if mismatch_map:
        worker_parity["site_map_sha256"] = "0" * 64
    now_ms = time.time_ns() // 1_000_000
    env = {
        "schema": ENV_DESCRIPTOR_SCHEMA,
        "world_id": worker["world_id"],
        "backend": worker["backend"],
        "run_id": f"{worker['world_id']}-ep{episode}",
        "ros_domain_id": worker["ros_domain_id"],
        "physics_profile": worker["physics_profile"],
        "parity": worker_parity,
        "capabilities": ["reset", "step", "pause"],
    }
    return {
        "schema": FACTORY_STATE_SCHEMA,
        "stream_mode": "live",
        "world_id": worker["world_id"],
        "adapter": worker["backend"],
        "simulator": worker["backend"],
        "run_id": f"{worker['world_id']}-ep{episode}",
        "observed_at_ms": now_ms,
        "env": env,
        "parity": worker_parity,
        "training": {
            "episode": episode,
            "step": step,
            "reward": reward,
            "success_rate": float(worker["success_rate"]),
            "sim_fps": float(worker["sim_fps"]),
            "physics_profile": worker["physics_profile"],
        },
        **{k: v for k, v in sample.items() if k != "simulator"},
    }


def _make_publisher(
    bundle_dir: Path,
    world_id: str,
    world_url: str | None,
    token: str | None,
    *,
    world_mdns_host: str | None = None,
    world_mdns_port: int = 8140,
) -> WorldPublisher:
    remote = bool(world_url or world_mdns_host)
    worlds_dir = None if remote else (bundle_dir / "data" / "worlds")
    return WorldPublisher(
        world_id=world_id,
        worlds_dir=worlds_dir,
        world_url=world_url,
        world_mdns_host=world_mdns_host,
        world_mdns_port=world_mdns_port,
        token=token,
        best_effort=remote,
    )


def publish_once(
    bundle_dir: Path,
    *,
    inject_mismatch_world: str | None = None,
    world_url: str | None = None,
    world_mdns_host: str | None = None,
    world_mdns_port: int = 8140,
    token: str | None = None,
) -> list[Path]:
    timeline = json.loads((bundle_dir / "data" / "factory-timeline.json").read_text(encoding="utf-8"))
    parity = _canonical_parity(bundle_dir, timeline)
    worlds_dir = bundle_dir / "data" / "worlds"
    written = []
    remote = bool(world_url or world_mdns_host)
    for idx, worker in enumerate(DEFAULT_WORKERS):
        snap = build_worker_snapshot(
            worker, timeline, parity, step_idx=idx * 17 + 1, elapsed_s=idx * 0.4,
            mismatch_map=(worker["world_id"] == inject_mismatch_world),
        )
        pub = WorldPublisher(
            world_id=worker["world_id"],
            worlds_dir=None if remote else worlds_dir,
            world_url=world_url,
            world_mdns_host=world_mdns_host,
            world_mdns_port=world_mdns_port,
            token=token,
            best_effort=False,
        )
        pub.publish(snap)
        written.append(worlds_dir / f"{worker['world_id']}.json")
    return written


def run_swarm(
    bundle_dir: Path,
    *,
    duration_s: float = 0.0,
    hz: float = 8.0,
    inject_mismatch_world: str | None = None,
    world_url: str | None = None,
    world_mdns_host: str | None = None,
    world_mdns_port: int = 8140,
    token: str | None = None,
) -> None:
    timeline = json.loads((bundle_dir / "data" / "factory-timeline.json").read_text(encoding="utf-8"))
    parity = _canonical_parity(bundle_dir, timeline)
    stop_event = threading.Event()
    started = time.monotonic()

    def _run_worker(worker: dict) -> None:
        step_idx = 0
        period = 1.0 / max(1.0, hz)
        pub = _make_publisher(
            bundle_dir,
            worker["world_id"],
            world_url,
            token,
            world_mdns_host=world_mdns_host,
            world_mdns_port=world_mdns_port,
        )
        while not stop_event.is_set():
            elapsed = time.monotonic() - started
            if duration_s > 0.0 and elapsed >= duration_s:
                break
            snap = build_worker_snapshot(
                worker, timeline, parity, step_idx, elapsed,
                mismatch_map=(worker["world_id"] == inject_mismatch_world),
            )
            pub.publish(snap)
            step_idx += 1
            if stop_event.wait(period):
                break

    threads = [threading.Thread(target=_run_worker, args=(w,), daemon=True) for w in DEFAULT_WORKERS]
    for t in threads:
        t.start()
    try:
        if duration_s > 0.0:
            time.sleep(duration_s)
        else:
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--world-url", help="optional Rosy World HTTP server base URL for remote push")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-mdns-port", type=int, default=8140)
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    parser.add_argument("--hz", type=float, default=8.0)
    parser.add_argument("--duration-s", type=float, default=0.0, help="0 runs until interrupted")
    parser.add_argument("--once", action="store_true", help="write one snapshot per worker and exit")
    parser.add_argument("--inject-mismatch", help="world_id to intentionally corrupt map sha256 for parity UI testing")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    token = os.environ.get(args.ingest_token_env, "").strip() or None
    if args.once:
        paths = publish_once(
            bundle,
            inject_mismatch_world=args.inject_mismatch,
            world_url=args.world_url,
            world_mdns_host=args.world_mdns_host,
            world_mdns_port=args.world_mdns_port,
            token=token,
        )
        print(json.dumps({"worlds": [p.stem for p in paths]}, ensure_ascii=False))
        return
    run_swarm(
        bundle,
        duration_s=args.duration_s,
        hz=args.hz,
        inject_mismatch_world=args.inject_mismatch,
        world_url=args.world_url,
        world_mdns_host=args.world_mdns_host,
        world_mdns_port=args.world_mdns_port,
        token=token,
    )


if __name__ == "__main__":
    main()
