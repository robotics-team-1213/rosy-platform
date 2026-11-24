"""Publish the existing isolated OMX MuJoCo top view as a World JPEG snapshot."""
from __future__ import annotations

import argparse
import math
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import time


AB_PRESET = "v24-20261114-cad194"
PREVIEW_HZ = 5


def publish_jpeg(image, destination):
    from PIL import Image

    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            Image.fromarray(image).save(stream, format="JPEG", quality=85)
            stream.close()
            for attempt in range(4):
                try:
                    staged.replace(destination)
                    return True
                except PermissionError as error:
                    if getattr(error, "winerror", None) not in {5, 32}:
                        raise
                    if attempt == 3:
                        return False
                    time.sleep(.02)
        finally:
            staged.unlink(missing_ok=True)


def run_cell(profile, profile_digest, emit):
    from omx_cell_sim import Cell, FPS

    cell = Cell(profile)
    publication_stride = FPS // PREVIEW_HZ
    print(json.dumps({"engine": "MuJoCo", "source": "omx_cell_sim", "camera": "top",
                      "profile_sha256": profile_digest}), flush=True)
    try:
        while True:
            data, xy, yaw = cell.reset(0, xy_range=0, yaw_range=0)
            for step, target in enumerate(cell.teacher(data, xy, yaw)):
                tick = time.monotonic()
                cell.advance(data, target)
                if step % publication_stride == 0:
                    cell.renderer.update_scene(data, camera="top", scene_option=cell.show_link5)
                    if emit(cell.renderer.render()):
                        return
                time.sleep(max(0, tick + 1 / FPS - time.monotonic()))
    finally:
        cell.renderer.close()


def run_ab(preset, emit, *, world_hook=None):
    from omx_two_arm_sites import layout_digest
    from omx_two_arm_world import FPS, PREFIX, World

    world = World(preset=preset)
    data = world.reset()
    for (container, _), (_, site, _) in zip(world.layout.containers(), world.layout.plan_order()):
        world.put(data, container, site)
    world.advance(data, {}, FPS)
    neutral = {arm: data.qpos[addresses].copy() for arm, addresses in world.q.items()}
    limits = {arm: world.model.jnt_range[world.model.joint(prefix + "joint1").id] for arm, prefix in PREFIX.items()}
    print(json.dumps({"engine": "MuJoCo", "source": "omx_two_arm_world", "camera": "top",
                      "preset": preset, "layout_sha256": layout_digest(world.layout),
                      "motion": "joint1 preview"}), flush=True)
    period = 1 / PREVIEW_HZ
    started = time.monotonic()
    step_idx = 0
    try:
        while True:
            tick = time.monotonic()
            swing = math.radians(6) * math.sin((tick - started) * math.tau / 3)
            targets = {arm: home.copy() for arm, home in neutral.items()}
            for (arm, target), direction in zip(targets.items(), (1, -1)):
                lower, upper = limits[arm]
                target[0] = min(upper, max(lower, target[0] + direction * swing))
            world.advance(data, targets, FPS // PREVIEW_HZ)
            if world_hook is not None:
                arms = {
                    arm: [round(float(v), 4) for v in list(data.qpos[addr])[:6]]
                    for arm, addr in world.q.items()
                }
                world_hook.publish_step(
                    sim_time_s=tick - started,
                    stage="ab_rehandle",
                    phase="mujoco_ab",
                    pinky={"id": "rosy_45", "pose_m": [0.745, -0.207, 0.0], "yaw_rad": 3.141592, "has_cargo": True, "s3_in_bounds": True},
                    arms=arms,
                    episode=1,
                    step=step_idx,
                )
            step_idx += 1
            if emit(world.render(data, "top")):
                return
            time.sleep(max(0, tick + period - time.monotonic()))
    finally:
        for renderer in world.renderers.values():
            renderer.close()


def _resolve_site_map_sha256(explicit: str | None, out_path: Path, repo_root: Path) -> str:
    if explicit and explicit.strip():
        return explicit.strip().lower()
    manifest_path = out_path.resolve().parent.parent / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key, entry in (manifest.get("inputs") or {}).items():
                if key.endswith("_active.json") and isinstance(entry, dict) and entry.get("sha256"):
                    return str(entry["sha256"]).lower()
        except (OSError, ValueError):
            pass
    try:
        for candidate in (Path(__file__).resolve().parent, repo_root / "tools" / "sim"):
            c_str = str(candidate)
            if candidate.is_dir() and c_str not in sys.path:
                sys.path.insert(0, c_str)
        from world_training_hooks import canonical_parity_inputs

        sha = canonical_parity_inputs(repo_root).get("site_map_sha256")
        if sha:
            return str(sha).lower()
    except Exception:
        pass
    return "0" * 64


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cell", type=Path, help="OMX ladder cell configuration")
    source.add_argument("--preset", choices=(AB_PRESET,), help="checked-in two-arm layout")
    parser.add_argument("--out", type=Path, required=True, help="World bundle data/mujoco-top.jpg")
    parser.add_argument("--frames", type=int, help="stop after this many published frames")
    parser.add_argument("--world-id", help="optional Rosy World parallel world_id for live 3D telemetry")
    parser.add_argument("--world-url", help="optional Rosy World HTTP server base URL")
    parser.add_argument("--worlds-dir", type=Path, help="optional directory for worlds/<world_id>.json")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    args = parser.parse_args()
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be positive")
    if os.name == "nt":
        os.environ.setdefault("MUJOCO_GL", "glfw")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "sim"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    world_hook = None
    if args.world_id:
        from world_env_adapter import TrainingWorldHook

        worlds_dir = args.worlds_dir if args.worlds_dir is not None else (None if args.world_url else args.out.parent / "worlds")
        world_hook = TrainingWorldHook(
            world_id=args.world_id,
            backend="mujoco",
            run_id=f"{args.world_id}-ab",
            site_map_sha256=_resolve_site_map_sha256(args.site_map_sha256, args.out, Path(__file__).resolve().parents[2]),
            worlds_dir=worlds_dir,
            world_url=args.world_url,
            token=os.environ.get(args.ingest_token_env, "").strip() or None,
            physics_profile=AB_PRESET,
        )
    written = 0

    def emit(frame):
        nonlocal written
        if publish_jpeg(frame, args.out):
            written += 1
        return written == args.frames

    try:
        if args.preset:
            run_ab(args.preset, emit, world_hook=world_hook)
        else:
            try:
                profile_digest = sha256(args.cell.read_bytes()).hexdigest()
            except OSError as error:
                parser.error(str(error))
            run_cell(args.cell, profile_digest, emit)
    except KeyboardInterrupt:
        pass
    finally:
        if world_hook is not None:
            world_hook.close()


if __name__ == "__main__":
    main()
