"""Closed-loop MuJoCo evaluation for canonical ACT policies."""
from collections import deque
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS_SRC = _ROOT / "contracts" / "learning" / "src"
if str(_CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_SRC))
from rosy.contracts.learning.omx_recording_todo import H1_POLICY_GOALS  # noqa: E402

_SIM_TASK_MAP = {"ship-h1": "stack", "stack-t1": "stack-t1", "stack-t2": "stack-t2", "stack-t3": "stack-t3"}
_EVAL_ROLLOUT_FRAMES = 440


def _step_and_here(plan: dict, arm: str, ep_idx: int) -> tuple[dict, dict]:
    arm_indices = [idx for idx, s in enumerate(plan["steps"]) if s["arm"] == arm]
    target_idx = arm_indices[ep_idx % len(arm_indices)]
    here = dict(plan.get("start") or {})
    for s in plan["steps"][:target_idx]:
        here[s["container"]] = s["to"]
        if s.get("outbound"):
            here.pop(s["container"], None)
    return plan["steps"][target_idx], here


def eval_sim_profile(policy, pre, post, spec: dict, arm: str, *, task_name: str, episodes: int, delay_frames: int, seed_base: int,
                      camera_cases=None):
    import numpy as np
    import torch

    sim_dir = str(_ROOT / "tools" / "sim")
    if sim_dir not in sys.path:
        sys.path.insert(0, sim_dir)
    import omx_two_arm_sites as sites
    import omx_two_arm_tasks as tasks
    import omx_two_arm_teacher as teaching
    import omx_two_arm_world as sim
    from omx_camera_pose import camera_angle_sampler

    canon_q = {a: np.asarray(spec["canonical_start"][a]["sim_rad"], dtype=np.float64) for a in ("arm_a", "arm_b")}
    idle_q = {a: np.asarray(spec["idle_park"][a]["sim_rad"], dtype=np.float64) for a in ("arm_a", "arm_b")}
    other = "arm_b" if arm == "arm_a" else "arm_a"
    arm_view = {"arm_a": "a_wrist", "arm_b": "b_wrist"}[arm]

    layout = sites.Layout(preset="v24-20261114", wrist_camera="v21-b")
    for a in ("arm_a", "arm_b"):
        layout.arms[a].wait = (canon_q[a] if a == arm else idle_q[a]).copy()
        layout.sim_arms[a].wait = (canon_q[a] if a == arm else idle_q[a]).copy()
    plan = tasks.get_task(layout, _SIM_TASK_MAP[task_name])
    in_feats = getattr(getattr(policy, "config", None), "input_features", None) or {}
    goal_feat = in_feats.get("observation.environment_state")
    if goal_feat is not None and tuple(goal_feat.shape) != (len(H1_POLICY_GOALS),):
        raise ValueError("expected the 10-slot H1 policy goal feature")
    world = sim.World(layout)
    camera_deg = spec.get("camera_angle_jitter_deg", 0.0)
    set_camera_angles = camera_angle_sampler(world, arm_view, camera_deg, 1) if camera_cases is not None and camera_deg else None
    top_key = "top" if "observation.images.top" in in_feats else "rs"
    successes, teacher_ok, neighbour_hits, contact_hits = 0, 0, 0, 0
    layer_stats = {}
    try:
        for i in range(episodes):
            seed = seed_base + i
            angles = set_camera_angles(seed) if set_camera_angles else None
            step, here = _step_and_here(plan, arm, i)
            goal_arr = None
            if goal_feat is not None:
                goal_arr = np.zeros((1, len(H1_POLICY_GOALS)), dtype=np.float32)
                goal_arr[0, H1_POLICY_GOALS.index(step["to"])] = 1.0
            layer_key = step["to"].split("-")[-1] if "-" in step["to"] else "l0"
            row_l = layer_stats.setdefault(layer_key, {"episodes": 0, "lifted": 0, "sustained_lift": 0, "successes": 0})
            row_l["episodes"] += 1
            teacher = teaching.Teacher(world, seed=seed)
            t_res = teacher.run_single(here, step)
            if t_res.get("result") == "pass":
                teacher_ok += 1

            teacher = teaching.Teacher(world, seed=seed)
            data = teacher.fresh(here)
            idle = {other: idle_q[other].copy()}
            if step["from"] == "belt":
                teacher.belt_in(data, step, idle)
            teacher.contacts = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())
            teacher.carried = step["container"]
            before = {k: world.pose(data, k) for k in here if k != step["container"]}
            start_z = world.pose(data, step["container"])[0][2]
            peak, held, held_max = 0.0, 0, 0
            policy.reset()
            hist = deque(maxlen=delay_frames + 1)
            with torch.inference_mode():
                for _ in range(_EVAL_ROLLOUT_FRAMES):
                    obs = {
                        "observation.state": torch.from_numpy(data.qpos[world.q[arm]].astype(np.float32))[None],
                    }
                    if goal_arr is not None:
                        obs["observation.environment_state"] = torch.from_numpy(goal_arr)
                    for key, cam in ((top_key, "top"), ("side", "side"), ("wrist", arm_view)):
                        obs[f"observation.images.{key}"] = torch.from_numpy(world.render(data, cam)).permute(2, 0, 1)[None].float() / 255.0
                    hist.append(obs)
                    cmd = post(policy.select_action(pre(hist[0]))).cpu().numpy()[0]
                    teacher.frame(data, {arm: cmd, **idle}, step["id"])
                    dz = world.pose(data, step["container"])[0][2] - start_z
                    peak = max(peak, dz)
                    held = held + 1 if dz > 0.015 else 0
                    held_max = max(held_max, held)
            verdict = teacher.verdict(data, step, {"lifted": peak > 0.015, "sustained_lift": held_max >= sim.FPS}, before)
            if peak > 0.015:
                row_l["lifted"] += 1
            if held_max >= sim.FPS:
                row_l["sustained_lift"] += 1
            if verdict.get("result") == "pass":
                successes += 1
                row_l["successes"] += 1
            if angles is not None:
                camera_cases.append({"scenario_seed": seed, "step": step["id"], "layer": layer_key,
                                     "angles_deg": angles, "success": verdict.get("result") == "pass"})
            neighbour_hits += len(set(teacher.contacts.get("pad_neighbour", ())) | set(verdict.get("neighbours_disturbed", ())))
            contact_hits += len(teacher.contacts.get("arm_arm", ())) + len(teacher.contacts.get("arm_other", ()))
    finally:
        for r in world.renderers.values():
            r.close()
    return {
        "n_action_steps": int(policy.config.n_action_steps),
        "delay_frames": delay_frames,
        "policy_episodes": episodes, "policy_successes": successes,
        "teacher_episodes": episodes, "teacher_successes": teacher_ok,
        "neighbour_disturbed": neighbour_hits, "arm_link_contacts": contact_hits,
    }, layer_stats
