"""Shared canonical telemetry helpers wiring real MuJoCo/ACT/Isaac trainers into Rosy World."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

from world_env_adapter import TrainingWorldHook, load_pinky_tray_fingerprint

DEFAULT_SITE_MAP_SHA256 = "d65a2275674f227be00f74895ad076fece8c382d70262fa7a4a79b2f635068cc"
DEFAULT_SITE_FROM_CELL = {
    "translation_m": [0.7930000763136793, 0.35499999696746065, 9.228515625001044e-06],
    "yaw_rad": -1.5707962747612703,
}
DEFAULT_REST_ARMS = {
    "arm_s": [0.18, -0.78, 0.74, 0.72, 1.5708, 0.72],
    "arm_a": [-0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
    "arm_b": [0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
}
DEFAULT_S3_PINKY = {
    "id": "rosy_45",
    "pose_m": [0.745, -0.207, 0.0],
    "yaw_rad": 3.141592,
    "has_cargo": True,
    "s3_in_bounds": True,
}


def canonical_parity_inputs(
    repo_root: Path | None,
    *,
    site_map_sha256: str | None = None,
) -> dict[str, Any]:
    """Load invariant site map SHA-256, J-v3 tray fingerprint, and cell->site registration."""
    sha = (site_map_sha256 or "").strip().lower()
    reg = dict(DEFAULT_SITE_FROM_CELL)
    cargo_tray = None
    reg_sha = None
    if repo_root is not None:
        geom = repo_root / "middleware" / "devices" / "pinky" / "profile" / "config" / "geometry.yaml"
        if geom.is_file():
            cargo_tray = load_pinky_tray_fingerprint(geom)
        for rel in ("applications/world/data/site-registration.json", "applications/world/data/registration.json"):
            cand = repo_root / rel
            if cand.is_file():
                try:
                    raw = json.loads(cand.read_text(encoding="utf-8"))
                    if isinstance(raw.get("site_from_cell"), dict):
                        reg = raw["site_from_cell"]
                    if not sha:
                        bundle_sha = (raw.get("bundle") or {}).get("site_map_sha256")
                        if isinstance(bundle_sha, str) and len(bundle_sha) == 64:
                            sha = bundle_sha.lower()
                    break
                except (OSError, ValueError):
                    pass
    if not sha:
        sha = DEFAULT_SITE_MAP_SHA256
    return {
        "site_map_sha256": sha,
        "registration_sha256": reg_sha,
        "cargo_tray": cargo_tray,
        "site_from_cell": reg,
    }


def cell_to_site(xyz: tuple[float, float, float] | list[float], reg: dict[str, Any]) -> list[float]:
    """Transform 3D coordinates from the OMX cell frame to the site map frame."""
    yaw = float(reg["yaw_rad"])
    tx, ty, tz = (float(v) for v in reg["translation_m"])
    cx, cy, cz = float(xyz[0]), float(xyz[1]), float(xyz[2])
    c, s = math.cos(yaw), math.sin(yaw)
    return [round(tx + cx * c - cy * s, 5), round(ty + cx * s + cy * c, 5), round(tz + cz, 5)]


def _finite_joints(values: Any) -> list[float]:
    out = [round(float(v), 4) for v in list(values)[:6]]
    if len(out) < 6:
        out.extend([0.0] * (6 - len(out)))
    return out


def make_mujoco_two_arm_hook(
    world: Any,
    hook: TrainingWorldHook,
    *,
    reg: dict[str, Any],
    task_name: str,
    episode_ref: list[int],
    fps: float = 15.0,
) -> Callable[[Any, str], None]:
    """Build an `omx_two_arm_teacher.Teacher` frame hook emitting live MuJoCo joint & cargo states."""
    frame_idx = 0
    last_wall = time.monotonic()
    last_frames = 0
    smoothed_fps = float(fps)
    cell_yaw = float(reg.get("yaw_rad", DEFAULT_SITE_FROM_CELL["yaw_rad"]))
    stage = "ab_rehandle" if "rehandle" in task_name else ("outbound_dispatch" if "outbound" in task_name else "ab_stack")

    def _on_frame(data: Any, label: str) -> None:
        nonlocal frame_idx, last_wall, last_frames, smoothed_fps
        frame_idx += 1
        now = time.monotonic()
        dt = now - last_wall
        if dt >= 0.25 and frame_idx > last_frames:
            smoothed_fps = (frame_idx - last_frames) / dt
            last_wall = now
            last_frames = frame_idx

        arms = {"arm_s": list(DEFAULT_REST_ARMS["arm_s"])}
        for arm in ("arm_a", "arm_b"):
            if arm in getattr(world, "q", {}):
                arms[arm] = _finite_joints(data.qpos[world.q[arm]])

        active_cargo = None
        stacked: list[dict[str, Any]] = []
        total_slots = None
        layout = getattr(world, "layout", None)
        if layout is not None:
            ship_cells = getattr(layout, "ship_cells", None)
            if isinstance(ship_cells, dict) and ship_cells:
                total_slots = len(ship_cells)
        if layout is not None and hasattr(world, "pose"):
            for cid, _site in layout.containers():
                try:
                    pos, cyaw, _tilt = world.pose(data, cid)
                except Exception:
                    continue
                if len(pos) >= 3 and float(pos[0]) > -1.0 and all(math.isfinite(float(v)) for v in pos[:3]):
                    site_xyz = cell_to_site(pos[:3], reg)
                    site_yaw = round(math.remainder(cell_yaw + float(cyaw), math.tau), 5)
                    item = {"id": str(cid), "pose_m": site_xyz, "yaw_rad": site_yaw, "observed": True}
                    stacked.append(item)
                    if active_cargo is None:
                        active_cargo = {"zone": "cell_ab", "pose_m": site_xyz, "yaw_rad": site_yaw, "observed": True}

        label_text = str(label or "")
        active_arm = "arm_a" if "arm_a" in label_text else ("arm_b" if "arm_b" in label_text else None)
        cell_ab: dict[str, Any] = {"active_arm": active_arm, "active_step": label_text or None, "stacked": stacked}
        if total_slots is not None:
            cell_ab["total_slots"] = total_slots
        hook.publish_step(
            sim_time_s=frame_idx / max(1.0, float(fps)),
            stage=stage,
            phase=f"mujoco_{task_name}",
            pinky=dict(DEFAULT_S3_PINKY),
            arms=arms,
            cargo=active_cargo or {"zone": "s3", "pose_m": list(DEFAULT_S3_PINKY["pose_m"]), "yaw_rad": DEFAULT_S3_PINKY["yaw_rad"], "observed": False},
            cell_ab=cell_ab,
            episode=episode_ref[0],
            step=frame_idx,
            sim_fps=round(smoothed_fps, 1),
        )

    return _on_frame


def make_experiment_train_progress(
    hook: TrainingWorldHook,
    *,
    method: str,
    total_steps: int,
    base_progress: Callable[[dict[str, Any]], None] | None = None,
    arm_id: str | None = None,
) -> Callable[[dict[str, Any]], None]:
    """Wrap `experiment_train` progress callbacks to stream live loss/step telemetry to Rosy World."""
    started = time.monotonic()

    def _on_progress(event: dict[str, Any]) -> None:
        if base_progress is not None:
            base_progress(event)
        step = int(event.get("step") or 0)
        elapsed = max(1e-3, time.monotonic() - started)
        sim_fps = round(step / elapsed, 1) if step > 0 else 0.0
        loss_val = event.get("loss")
        finite_loss = round(float(loss_val), 5) if isinstance(loss_val, (int, float)) and math.isfinite(loss_val) else None
        phase_angle = step * 0.2
        arms = {
            "arm_s": list(DEFAULT_REST_ARMS["arm_s"]),
            "arm_a": [round(DEFAULT_REST_ARMS["arm_a"][0] + (0.18 * math.sin(phase_angle) if arm_id in (None, "arm_a") else 0.0), 4), *DEFAULT_REST_ARMS["arm_a"][1:]],
            "arm_b": [round(DEFAULT_REST_ARMS["arm_b"][0] + (-0.18 * math.sin(phase_angle) if arm_id in (None, "arm_b") else 0.0), 4), *DEFAULT_REST_ARMS["arm_b"][1:]],
        }
        hook.publish_step(
            sim_time_s=round(elapsed, 3),
            stage="ab_stack",
            phase=f"{method}_train",
            pinky=dict(DEFAULT_S3_PINKY),
            arms=arms,
            cell_ab={"active_arm": arm_id or "arm_a", "active_step": f"{method}:step-{step}", "stacked": []},
            episode=1,
            step=step,
            loss=finite_loss,
            sim_fps=sim_fps,
            force=(step <= 1 or step >= total_steps),
        )

    return _on_progress


def add_world_monitor_args(parser: Any) -> None:
    """Register optional Rosy World telemetry CLI arguments."""
    parser.add_argument("--world-url", help="optional Rosy World HTTP server base URL for live telemetry")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140, help="Rosy World port for --world-mdns-host")
    parser.add_argument("--worlds-dir", type=Path, help="optional Rosy World data/worlds directory")
    parser.add_argument("--world-id", default="isaac-map-rl", help="parallel world_id for Rosy World monitor")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256 for World parity")
    parser.add_argument("--world-token-env", default="ROSY_WORLD_INGEST_TOKEN")


def open_isaac_map_rl_world_hook(args: Any, track_sha256: str) -> TrainingWorldHook | None:
    """Create a best-effort TrainingWorldHook for `run_map_rl` when a World target is given."""
    import os

    if not (args.world_url or args.world_mdns_host or args.worlds_dir):
        return None
    return TrainingWorldHook(
        world_id=args.world_id,
        backend="isaac",
        run_id=f"{args.world_id}-{args.source_revision[:8]}",
        site_map_sha256=(args.site_map_sha256 or track_sha256).lower(),
        worlds_dir=args.worlds_dir,
        world_url=args.world_url,
        world_mdns_host=args.world_mdns_host,
        world_mdns_port=args.world_port,
        token=os.environ.get(args.world_token_env, "").strip() or None,
        physics_profile="physx-gpu-rl",
        best_effort=True,
    )


def publish_isaac_map_rl_step(
    world_hook: TrainingWorldHook | None,
    *,
    elapsed: float,
    phase: str,
    pose: list[float] | tuple[float, ...],
    epoch: int,
    step: int,
    reward: float,
) -> None:
    """Forward a `run_map_rl` step to Rosy World if telemetry is enabled."""
    if world_hook is None:
        return
    world_hook.publish_step(
        sim_time_s=elapsed,
        stage="c2_departure",
        phase=f"rl_{phase}",
        pinky={
            "id": "rosy_45",
            "pose_m": [round(float(pose[0]), 5), round(float(pose[1]), 5), 0.0],
            "yaw_rad": round(float(pose[2]), 5),
            "has_cargo": True,
            "s3_in_bounds": False,
        },
        episode=epoch,
        step=step,
        reward=round(float(reward), 3),
    )


def add_world_telemetry_args(parser: Any) -> None:
    """Register optional Rosy World live telemetry CLI arguments on a teacher/runner parser."""
    parser.add_argument("--world-id", help="optional Rosy World parallel world_id for live 3D telemetry")
    parser.add_argument("--world-url", help="optional Rosy World HTTP base URL")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140, help="Rosy World port for --world-mdns-host")
    parser.add_argument("--worlds-dir", type=Path, help="optional directory for worlds/<world_id>.json")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--world-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    parser.add_argument("--episode", type=int, default=1, help="starting episode number reported to Rosy World")
    parser.add_argument("--repeat", type=int, default=1, help="repeat the MuJoCo task this many episodes")


def attach_mujoco_two_arm_hook(
    args: Any,
    world: Any,
    writer: Callable[[Any, str], None] | None,
    episode_ref: list[int],
) -> tuple[TrainingWorldHook | None, Callable[[Any, str], None] | None]:
    """Wire a MuJoCo two-arm teacher run into Rosy World telemetry if configured."""
    if not (args.world_id and (args.world_url or args.world_mdns_host or args.worlds_dir)):
        return None, writer
    repo_root = Path(__file__).resolve().parents[2]
    parity_in = canonical_parity_inputs(repo_root, site_map_sha256=args.site_map_sha256)
    world_hook = TrainingWorldHook(
        world_id=args.world_id,
        backend="mujoco",
        run_id=f"{args.world_id}-{args.task}",
        site_map_sha256=parity_in["site_map_sha256"],
        worlds_dir=args.worlds_dir,
        world_url=args.world_url,
        world_mdns_host=args.world_mdns_host,
        world_mdns_port=args.world_port,
        token=os.environ.get(args.world_token_env, "").strip() or None,
        physics_profile=f"mujoco-{args.cone}",
        cargo_tray=parity_in["cargo_tray"],
    )
    live_hook = make_mujoco_two_arm_hook(
        world, world_hook, reg=parity_in["site_from_cell"], task_name=args.task, episode_ref=episode_ref,
    )
    if writer is None:
        return world_hook, live_hook

    def _chained(data: Any, label: str) -> None:
        writer(data, label)
        live_hook(data, label)

    return world_hook, _chained
