#!/usr/bin/env python3
"""Evaluate a six-joint ACT checkpoint or the IK teacher on a Purple-SY-like ship pick."""

import argparse
import json
from pathlib import Path
import sys


IMAGE_PREFIX = "observation.images."
REHANDLE_STEP = {"arm_a": "a1", "arm_b": "b1"}
WRIST_CAMERA = {"arm_a": "a_wrist", "arm_b": "b_wrist"}
VIDEO_SIZE = (480, 640)


def resolve_views(input_features, arm, view_map=None):
    """Return checkpoint image key -> (MuJoCo camera, (height, width))."""
    cameras = {name: name for name in ("top", "side", "a_wrist", "b_wrist")}
    cameras["wrist"] = WRIST_CAMERA[arm]
    shapes = {key.removeprefix(IMAGE_PREFIX): spec["shape"]
              for key, spec in input_features.items() if key.startswith(IMAGE_PREFIX)}
    if not shapes:
        raise ValueError("checkpoint declares no observation.images.* inputs")
    mapping = {name: name for name in ("top", "wrist")} if view_map is None else {}
    if view_map is not None:
        for entry in view_map.split(","):
            name, _, camera = (part.strip() for part in entry.partition("="))
            if name not in shapes or camera not in cameras or name in mapping:
                raise ValueError(f"invalid --view-map entry {entry!r}: use each checkpoint view once and name a sim camera")
            mapping[name] = camera
    missing = shapes.keys() - mapping.keys()
    if missing:
        raise ValueError(f"unmapped checkpoint camera views: {', '.join(sorted(missing))}; supply --view-map")
    resolved = {}
    for name, shape in shapes.items():
        if len(shape) != 3 or shape[0] != 3 or min(shape[1:]) < 1:
            raise ValueError(f"expected an RGB CHW image for {name}, got {shape}")
        resolved[IMAGE_PREFIX + name] = cameras[mapping[name]], tuple(shape[1:])
    return resolved


def load_act(path, device):
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(str(path), local_files_only=True).to(device).eval()
    pre, post = make_pre_post_processors(
        policy.config, pretrained_path=str(path),
        preprocessor_overrides={"device_processor": {"device": device}},
        postprocessor_overrides={"device_processor": {"device": "cpu"}},
    )
    return policy, pre, post


def open_episode_video(world, path, views, overview):
    import numpy as np
    from omx_two_arm_teacher_stages import open_rgb_video

    sizes = [size for _, size in views]
    if overview:
        sizes.append(VIDEO_SIZE)
    height = max(h for h, _ in sizes)
    width = sum(w for _, w in sizes)
    # The shared H.264 encoder uses yuv420p, which needs even dimensions.
    height, width = height + height % 2, width + width % 2
    encode, close = open_rgb_video(path, width, height)

    def record(data, frames=None):
        if frames is None:
            frames = [world.render(data, camera, size) for camera, size in views]
        if overview:
            frames = [*frames, world.render(data, "overview", VIDEO_SIZE)]
        strip = np.zeros((height, width, 3), dtype=np.uint8)
        left = 0
        for frame in frames:
            h, w = frame.shape[:2]
            top = (height - h) // 2
            strip[top:top + h, left:left + w] = frame
            left += w
        encode(strip)

    return record, close


def rollout_act(teacher, here, step, actor, views, seconds, device, record=None):
    import numpy as np
    import torch
    from omx_two_arm_teacher import FPS
    from palletizing_gripper import angle_for_gap_clipped, gap_m

    cell_tools = str(Path(__file__).resolve().parents[2] / "deploy/robot/omx")
    if cell_tools not in sys.path:
        sys.path.insert(0, cell_tools)
    from cell_arm_cal import default_profile
    from cell_control_core import norm_to_rad, rad_to_norm

    policy, pre, post = actor
    world, arm, container = teacher.world, step["arm"], step["container"]
    # Use the nominal A/B jaw calibration until matching measured profiles are available.
    jaw_cal = default_profile(arm)
    held, slope = jaw_cal["held_30mm"], jaw_cal["gap_mm_per_unit"]
    data = teacher.fresh(here)
    before = {name: world.pose(data, name) for name in here if name != container}
    start_z = world.pose(data, container)[0][2]
    peak = 0.0
    idle = {other: world.layout.sim_arms[other].wait for other in world.layout.arms if other != arm}
    teacher.contacts = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())
    teacher.carried, teacher.phase = container, "act"
    policy.reset()
    trajectory = []
    with torch.inference_mode():
        for frame in range(round(seconds * FPS)):
            q = teacher.q_now(data, arm)
            grip = np.clip(held + (1000 * gap_m(q[5]) - 30) / slope, 0, 100)
            state = [*(rad_to_norm(value) for value in q[:5]), grip]
            batch = {"observation.state": torch.tensor([state], dtype=torch.float32, device=device)}
            frames = []
            for key, (camera, size) in views.items():
                rgb = world.render(data, camera, size)
                if record is not None:
                    frames.append(rgb)
                batch[key] = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(device).float() / 255
            action = post(policy.select_action(pre(batch))).cpu().numpy()[0]
            if action.shape != (6,) or not np.isfinite(action).all():
                raise ValueError("ACT must emit six finite normalized joints")
            if frame % 5 == 0:
                trajectory.append(dict(frame=frame, state=np.asarray(state).tolist(), action=action.tolist()))
            if record is not None:
                record(data, frames)
            joints = [norm_to_rad(value) for value in np.clip(action[:5], -100, 100)]
            gap = (30 + (np.clip(action[5], 0, 100) - held) * slope) / 1000
            teacher.frame(data, {arm: np.array([*joints, angle_for_gap_clipped(gap)]), **idle}, "act")
            peak = max(peak, world.pose(data, container)[0][2] - start_z)
    row = dict(step=step["id"], arm=arm, container=container,
               source=step["from"], target=step["to"], lifted=bool(peak > .015), joint_trajectory=trajectory)
    return teacher.verdict(data, step, row, before)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=REHANDLE_STEP, required=True)
    parser.add_argument("--model", required=True, help="local ACT pretrained_model directory or 'ik'")
    parser.add_argument("--view-map", help="comma-separated checkpoint_suffix=sim_camera pairs")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--seed-base", type=int, default=200000)
    parser.add_argument("--seconds", type=int, default=30, help="ACT rollout duration in simulated seconds")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--choice", action="append", help="two-arm geometry choice, e.g. wrist_camera=v21-b")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--video", type=Path, metavar="DIR", help="write an MP4 for each episode")
    args = parser.parse_args(argv)
    if args.episodes < 1 or args.seconds < 1 or args.seed_base < 0:
        parser.error("episodes and seconds must be positive and seed-base must be non-negative")

    views = {}
    if args.model == "ik":
        if args.view_map is not None:
            parser.error("--view-map applies to a checkpoint")
    else:
        try:
            config = json.loads((Path(args.model) / "config.json").read_text(encoding="utf-8"))
            inputs, outputs = config["input_features"], config["output_features"]
            if (config["type"] != "act" or inputs["observation.state"]["shape"] != [6]
                    or outputs["action"]["shape"] != [6]):
                raise ValueError("expected an ACT checkpoint with six state and six action joints")
            views = resolve_views(inputs, args.arm, args.view_map)
        except (OSError, KeyError, ValueError) as exc:
            parser.error(str(exc))

    import omx_two_arm_sites as sites
    import omx_two_arm_tasks as tasks
    import omx_two_arm_teacher as teaching
    from omx_two_arm_world import World

    layout = sites.Layout(**sites.parse_choices(args.choice))
    world = World(layout)
    available = {world.model.camera(i).name for i in range(world.model.ncam)}
    for key, (camera, _) in views.items():
        if camera not in available:
            parser.error(f"{key} maps to {camera}, which is absent from this world")
    task = tasks.get_task(layout, "rehandle")
    step = next(step for step in task["steps"] if step["id"] == REHANDLE_STEP[args.arm])
    actor = load_act(args.model, args.device) if views else None
    if args.video is not None:
        args.video.mkdir(parents=True, exist_ok=True)
        video_views = list(views.values()) if actor else [
            (camera, VIDEO_SIZE) for camera in ("top", "side", WRIST_CAMERA[args.arm]) if camera in available
        ]
    rows = []
    for seed in range(args.seed_base, args.seed_base + args.episodes):
        record = close = hook = None
        if args.video is not None:
            kind = "act" if actor else "ik"
            path = args.video / f"{kind}-{args.arm}-{seed}.mp4"
            record, close = open_episode_video(world, path, video_views, "overview" in available)
            if actor is None:
                hook = lambda data, _label: record(data)  # noqa: E731
        try:
            teacher = teaching.Teacher(world, seed=seed, frame_hook=hook)
            if actor is None:
                row = teacher.run_single(task["start"], step)
            else:
                row = rollout_act(teacher, task["start"], step, actor, views, args.seconds, args.device, record)
        finally:
            if close is not None:
                close()
        rows.append(dict(row, seed=seed))
        print(json.dumps(rows[-1]), flush=True)
    report = dict(task=task["name"], arm=args.arm, step=step["id"], model=args.model,
                  choices=layout.choices, views=views, fps=teaching.FPS,
                  act_seconds=args.seconds if actor else None,
                  passed=sum(row["result"] == "pass" for row in rows), rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
