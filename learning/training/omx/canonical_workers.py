"""Subprocess-only workers for canonical OMX align, DART collect, 2-stage train, L1 eval, live check.

Never imported at startup by review_app.py or canonical_web.py. Uses zero deploy/robot/omx imports.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

_ROOT = Path(__file__).resolve().parents[3]
_OMX_CURATION = _ROOT / "learning" / "curation" / "omx"
_POLICY_REGISTRY = _ROOT / "learning" / "registry" / "policy"
_CONTRACTS_SRC = _ROOT / "contracts" / "learning" / "src"
for _p in (str(_CONTRACTS_SRC), str(_OMX_CURATION)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canonical_intake import detect_source_units, normalize_bench_task, prepare_episode_arrays, select_arm_features  # noqa: E402
from canonical_sim_eval import eval_sim_profile  # noqa: E402
from canonical_watch import scrub_text  # noqa: E402
from experiment_io import read_json, write_json  # noqa: E402
from experiment_train import gpu_lease  # noqa: E402
from rosy.contracts.learning.digest import checkpoint_sha256  # noqa: E402
from rosy.contracts.learning.omx_canonical import (  # noqa: E402
    AUTHORITY_STAMP,
    LIVE_CHECK_SCHEMA,
    canonical_envelope_from_library,
    evaluate_chunk_envelope,
    validate_canonical_spec,
)

@contextmanager
def _gpu_job_lock(jobs_dir: Path):
    """Coordinate BOTH ~/.cache/rosy-learning/gpu.lock and ~/rosy-jobs/train-<pid>.lock."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    lock_file = jobs_dir / f"train-{os.getpid()}.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    with gpu_lease("cuda"):
        try:
            fd = os.open(lock_file, flags, 0o600)
        except FileExistsError:
            if lock_file.is_symlink():
                raise
            lock_file.unlink(missing_ok=True)
            fd = os.open(lock_file, flags, 0o600)
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(fd)
        try:
            yield
        finally:
            lock_file.unlink(missing_ok=True)


def _progress(out: Path, phase: str, **extra) -> None:
    write_json(out / "progress.json", {"phase": phase, **extra})


def _wrap_pi(arr):
    return ((arr + 2.0 * math.pi) % (2.0 * math.pi)) - math.pi


def _decode_span(av_mod, path: Path, t0: float, t1: float, fps: int):
    frames = []
    with av_mod.open(str(path)) as container:
        stream = container.streams.video[0]
        container.seek(int(max(t0 - 1.0, 0.0) / stream.time_base), stream=stream, backward=True)
        for fr in container.decode(stream):
            t = float(fr.pts * stream.time_base)
            if t < t0 - 0.5 / fps:
                continue
            if t >= t1 - 0.5 / fps:
                break
            frames.append(fr.to_ndarray(format="rgb24"))
    return frames


def run_align_real(req: dict, out: Path) -> dict:
    import av
    import numpy as np
    import pandas as pd
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import data_gate

    arm = req["arm_id"]
    spec = validate_canonical_spec(req["spec"])
    params = req["params"]
    src = Path(params["source_path"]).resolve()
    dst = out / "aligned"
    if dst.exists():
        shutil.rmtree(dst)
    _progress(out, "aligning", arm=arm)

    info = json.loads((src / "meta" / "info.json").read_text(encoding="utf-8"))
    src_fps = int(info["fps"])
    fps = 15 if src_fps in (15, 30) else src_fps
    robot_type = str(info.get("robot_type") or "")
    src_units = str(params.get("unit_mode") or "") or detect_source_units(src, arm, info)
    tasks_df = pd.read_parquet(src / "meta" / "tasks.parquet")
    task_text = {int(row.task_index): text for text, row in tasks_df.iterrows()}
    ep_df = pd.concat([pd.read_parquet(f) for f in sorted((src / "meta" / "episodes").rglob("*.parquet"))]).sort_values("episode_index")
    data_df = pd.concat([pd.read_parquet(f) for f in sorted((src / "data").rglob("*.parquet"))]).sort_values("index")

    axes = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    vec = dict(dtype="float32", shape=(6,), names=axes)
    img = dict(dtype="video", shape=(480, 640, 3), names=["height", "width", "channels"])
    filtered_feats, arm_legacy = select_arm_features(
        info["features"], arm, dict(data_gate.LEGACY_TABLE, **(params.get("legacy_map") or {}))
    )
    src_cams = {role: key for key, role in data_gate.camera_map(filtered_feats, arm_legacy).items()}
    out_cams = {"top": "observation.images.rs", "side": "observation.images.side", "wrist": "observation.images.wrist"}
    features = {"observation.state": vec, "action": vec, **{v: img for v in out_cams.values()}}

    ds = LeRobotDataset.create(
        f"local/omx-real-{arm}-canon", fps, root=dst, robot_type="omx_sim_arm", features=features,
        video_backend="pyav", vcodec="h264", streaming_encoding=True,
        encoder_threads=2, encoder_queue_maxsize=512, metadata_buffer_size=1,
    )
    home24 = np.asarray(data_gate.HOME[arm][1:4], dtype=np.float64)
    flip, trim = bool(params["wrist_flip"]) and arm == "arm_b", bool(params["trim_dead_idle"])
    t_starts, kept_counts, view_episodes = [], [], []
    try:
        for _, ep in ep_df.iterrows():
            ep_idx = int(ep.episode_index)
            rows = data_df[data_df.episode_index == ep_idx].sort_values("frame_index")
            n_raw, task = len(rows), normalize_bench_task(task_text[int(rows.task_index.iloc[0])])
            st = np.stack(rows["observation.state"].to_numpy()).astype(np.float64)
            ac = np.stack(rows["action"].to_numpy()).astype(np.float64)
            st, ac, stride, _ = prepare_episode_arrays(st, ac, spec=spec, arm_id=arm, robot_type=robot_type, src_fps=src_fps, target_fps=fps, units=src_units)
            n = len(st)
            if flip:
                st[:, 4], ac[:, 4] = _wrap_pi(st[:, 4]), _wrap_pi(ac[:, 4])
            imgs = {}
            for role, key in src_cams.items():
                prefix = f"videos/{key}/"
                vpath = src / info["video_path"].format(
                    video_key=key, chunk_index=int(ep[prefix + "chunk_index"]), file_index=int(ep[prefix + "file_index"]))
                decoded = _decode_span(av, vpath, float(ep[prefix + "from_timestamp"]), float(ep[prefix + "to_timestamp"]), src_fps)
                if len(decoded) != n_raw:
                    raise ValueError(f"ep {ep_idx} {role} decoded {len(decoded)} != {n_raw}")
                imgs[role] = decoded[::stride][:n]
            if flip:
                imgs["wrist"] = [fr[::-1, ::-1].copy() for fr in imgs["wrist"]]
            t_start = 0
            if trim:
                diff = np.abs(st[:, :5] - st[0:1, :5]).max(axis=1)
                onset = np.flatnonzero(diff > 0.04)
                i_on = int(onset[0]) if len(onset) else 0
                in_env = np.flatnonzero((np.arange(n) >= i_on) & (st[:, 1] > -59.5 * math.pi / 100.0) & (st[:, 2] < 52.5 * math.pi / 100.0))
                fallback = np.flatnonzero(st[:, 1] > -61.0 * math.pi / 100.0)
                t_start = min(int(in_env[0]) if len(in_env) else (int(fallback[0]) if len(fallback) else i_on), max(0, n - 80))
                while t_start > i_on and float(np.abs(st[t_start, 1:4] - home24).max()) > 0.32:
                    t_start -= 1
                while t_start > 0 and float(np.abs(st[t_start, 1:4] - home24).max()) > 0.32:
                    t_start -= 1
            if n - t_start < data_gate.LIMITS["min_frames"]:
                raise ValueError(f"ep {ep_idx} too short after trim: {n - t_start}")
            for i in range(t_start, n):
                ds.add_frame({"task": task, "observation.state": st[i].astype(np.float32), "action": ac[i].astype(np.float32),
                              **{out_k: imgs[role][i] for role, out_k in out_cams.items()}})
            ds.save_episode()
            view_episodes.append({"episode_index": len(view_episodes), "source_episode_index": ep_idx})
            t_starts.append(t_start); kept_counts.append(n - t_start)
    finally:
        ds.finalize()

    _progress(out, "gating", arm=arm)
    view_file = "meta/camera_views.json"
    write_json(dst / view_file, {"kind": "captured", "source_id": params["source_id"], "roles": src_cams,
                                 "angles_deg": None, "wrist_rotated_180": flip, "episodes": view_episodes})
    receipt = data_gate.gate(dst, arm=arm, source={"kind": "real", "layout": "random", "camera_views": view_file}, canonical_spec=spec)
    admitted = data_gate.check_receipt(dst)
    if not admitted:
        raise ValueError(f"data_gate admitted 0 episodes (reject={receipt['counts'].get('reject')}, review={receipt['counts'].get('review')})")
    return {"kind": "align_real", "arm_id": arm, "episodes": len(admitted), "frames_total": int(sum(kept_counts)),
            "t_start_median": float(statistics.median(t_starts)) if t_starts else 0.0, "gate_counts": receipt["counts"],
            "spec_sha256": req["spec_sha256"], **AUTHORITY_STAMP}


def _recolor_world(world, layout, rng) -> None:
    import numpy as np
    palette = ((.92, .45, .62), (.62, .31, .14), (.78, .13, .12), (.86, .66, .10), (.10, .10, .10), (.18, .62, .24))
    m = world.model
    for cid, _ in layout.containers():
        bid = m.body(cid).id
        rgb = np.asarray(palette[int(rng.integers(len(palette)))]) * float(rng.uniform(.9, 1.1))
        for g in np.where(m.geom_bodyid == bid)[0]:
            if m.geom_rgba[g][3] > 0:
                m.geom_rgba[g][:3] = np.clip(rgb, 0, 1)


def run_collect_dart(req: dict, out: Path) -> dict:
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import data_gate

    sim_dir = str(_ROOT / "tools" / "sim")
    if sim_dir not in sys.path:
        sys.path.insert(0, sim_dir)
    import omx_two_arm_sites as sites
    import omx_two_arm_tasks as tasks
    import omx_two_arm_teacher as teaching
    import omx_two_arm_world as sim
    from omx_camera_pose import camera_angle_sampler

    arm = req["arm_id"]
    spec = validate_canonical_spec(req["spec"])
    params = req["params"]
    dst = out / "dataset"
    if dst.exists():
        shutil.rmtree(dst)
    canon_q = {a: np.asarray(spec["canonical_start"][a]["sim_rad"], dtype=np.float64) for a in ("arm_a", "arm_b")}
    idle_q = {a: np.asarray(spec["idle_park"][a]["sim_rad"], dtype=np.float64) for a in ("arm_a", "arm_b")}
    jitter_rad = math.radians(float(params["jitter_deg"]))
    camera_deg = spec.get("camera_angle_jitter_deg", 0.0)
    axes = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    vec = dict(dtype="float32", shape=(6,), names=axes)
    img = dict(dtype="video", shape=(480, 640, 3), names=["height", "width", "channels"])
    features = {"observation.state": vec, "action": vec,
                "observation.images.rs": img, "observation.images.side": img, "observation.images.wrist": img}
    arm_view = {"arm_a": "a_wrist", "arm_b": "b_wrist"}[arm]

    with _gpu_job_lock(Path(req["jobs_dir"])):
        _progress(out, "collecting", arm=arm, episodes=params["episodes"])
        ds = LeRobotDataset.create(
            f"local/omx-dart-{arm}-canon", sim.FPS, root=dst, robot_type="omx_sim_arm", features=features,
            video_backend="pyav", vcodec="h264", streaming_encoding=True,
            encoder_threads=2, encoder_queue_maxsize=512, metadata_buffer_size=1,
        )
        layout = sites.Layout(preset="v24-20261114", wrist_camera="v21-b")
        world = sim.World(layout)
        set_camera_angles = camera_angle_sampler(world, arm_view, camera_deg, 0) if camera_deg else None
        rng = np.random.default_rng([int(params["seed"]), 31415])
        saved = 0
        view_episodes = []
        try:
            for ep_i in range(params["episodes"]):
                ep_seed = int(params["seed"]) + ep_i
                # A mount stays fixed for a complete scenario. Keep every fourth scenario at the reference pose.
                angles = set_camera_angles(ep_seed if ep_i % 4 != 3 else None) if set_camera_angles else None
                for a in ("arm_a", "arm_b"):
                    q = canon_q[a].copy() if a == arm else idle_q[a].copy()
                    if a == arm and jitter_rad > 0:
                        q[:5] += rng.uniform(-jitter_rad, jitter_rad, 5)
                    layout.arms[a].wait = q.copy()
                    layout.sim_arms[a].wait = q.copy()
                if params["color_random"]:
                    _recolor_world(world, layout, rng)
                teacher = teaching.Teacher(world, seed=ep_seed if params.get("pose_random", True) else 0)
                plan = tasks.get_task(layout, "stack")
                here = dict(plan["start"])
                for step in plan["steps"]:
                    if step["arm"] == arm:
                        step_frames = []
                        def _rec(d, targets, lbl=None, _frames=step_frames):
                            if lbl == "settle":
                                return
                            _frames.append((
                                d.qpos[world.q[arm]].astype(np.float32),
                                np.asarray(targets[arm], dtype=np.float32),
                                world.render(d, "top"), world.render(d, "side"), world.render(d, arm_view),
                            ))
                        teacher.hook = lambda d, lbl, _fn=_rec: _fn(d, {arm: d.ctrl[world.act[arm]]}, lbl)
                        res = teacher.run_single(here, step)
                        if res.get("result") == "pass" and len(step_frames) >= 60:
                            for st_q, ac_q, rs_i, sd_i, wr_i in step_frames:
                                ds.add_frame({
                                    "task": f"Move the designated container from {step['from']} to {step['to']}.",
                                    "observation.state": st_q, "action": ac_q,
                                    "observation.images.rs": rs_i, "observation.images.side": sd_i, "observation.images.wrist": wr_i,
                                })
                            ds.save_episode()
                            if angles is not None:
                                view_episodes.append({"episode_index": saved, "scenario_seed": ep_seed, "angles_deg": angles})
                            saved += 1
                    here[step["container"]] = step["to"]
                    if step.get("outbound"):
                        here.pop(step["container"], None)
        finally:
            ds.finalize()
            for r in world.renderers.values():
                r.close()

    _progress(out, "gating", arm=arm, saved=saved)
    source = {"kind": "sim", "layout": "random"}
    if camera_deg:
        view_file = "meta/camera_views.json"
        (dst / "meta").mkdir(parents=True, exist_ok=True)
        write_json(dst / view_file, {"kind": "simulated", "max_deg_per_axis": camera_deg, "episodes": view_episodes})
        source["camera_views"] = view_file
    receipt = data_gate.gate(dst, arm=arm, source=source, canonical_spec=spec)
    admitted = data_gate.check_receipt(dst)
    return {
        "kind": "collect_dart", "arm_id": arm, "episodes": len(admitted),
        "gate_counts": receipt["counts"], "spec_sha256": req["spec_sha256"],
        **AUTHORITY_STAMP,
    }


def run_train_stage(req: dict, out: Path) -> dict:
    import data_gate

    arm = req["arm_id"]
    params = req["params"]
    ds_root = Path(params["dataset_root"]).resolve()
    admitted = data_gate.check_receipt(ds_root, expected_scope="h1")
    if not admitted:
        raise ValueError("data_gate admitted zero episodes")

    train_dir = out / "train"
    resume_dir = Path(params["resume_train_dir"]).resolve() if params.get("resume_train_dir") else None
    if train_dir.exists() or train_dir.is_symlink():
        raise ValueError("fresh training output dir already exists")

    _progress(out, "training", arm=arm, steps=params["steps"])
    cmd = [
        sys.executable, "-m", "lerobot.scripts.lerobot_train",
        "--dataset.repo_id=local/omx-canon", f"--dataset.root={ds_root}",
        f"--dataset.episodes={json.dumps(admitted)}",
        "--policy.type=act", "--policy.device=cuda", "--policy.push_to_hub=false",
        f"--policy.chunk_size={params['chunk_size']}", f"--policy.n_action_steps={params['n_action_steps']}",
        f"--policy.use_vae={'true' if params['use_vae'] else 'false'}",
        f"--policy.kl_weight={params['kl_weight']}",
        f"--policy.optimizer_lr={params['lr']}", f"--policy.optimizer_lr_backbone={params['lr'] * 0.1}",
        f"--output_dir={train_dir}", f"--steps={params['steps']}",
        f"--batch_size={params['batch_size']}", f"--save_freq={params['save_freq']}",
        f"--seed={params['seed']}",
    ]
    if resume_dir is not None:
        resume_ckpt = (resume_dir / "checkpoints" / "last" / "pretrained_model").resolve()
        if not resume_ckpt.is_relative_to(resume_dir) or not (resume_ckpt / "model.safetensors").is_file():
            raise ValueError("resume_train_dir missing checkpoints/last/pretrained_model")
        cmd.append(f"--policy.pretrained_path={resume_ckpt}")
    active_train = train_dir

    env = dict(os.environ, HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    with _gpu_job_lock(Path(req["jobs_dir"])):
        proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode:
        raise RuntimeError(f"lerobot_train exited with code {proc.returncode}")

    ckpt_dir = (active_train / "checkpoints" / "last" / "pretrained_model").resolve()
    if not ckpt_dir.is_relative_to(active_train.resolve()) or not (ckpt_dir / "model.safetensors").is_file():
        raise ValueError("trained pretrained_model missing or escaped")
    weights_sha = hashlib.sha256((ckpt_dir / "model.safetensors").read_bytes()).hexdigest()
    bundle_sha = checkpoint_sha256(ckpt_dir, allow_symlinks=False)
    return {
        "kind": "train_stage", "arm_id": arm, "steps": params["steps"],
        "admitted_episodes": len(admitted), "policy_sha256": weights_sha,
        "checkpoint_sha256": bundle_sha, "spec_sha256": req["spec_sha256"],
        **AUTHORITY_STAMP,
    }


def run_eval_ladder(req: dict, out: Path) -> dict:
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    if str(_POLICY_REGISTRY) not in sys.path:
        sys.path.insert(0, str(_POLICY_REGISTRY))
    from sim_l1 import sim_l1_assessment

    spec = validate_canonical_spec(req["spec"])
    arm = req["arm_id"]
    params = req["params"]
    ckpt_dir = Path(params["checkpoint_dir"]).resolve()
    ckpt_sha = checkpoint_sha256(ckpt_dir, allow_symlinks=False)

    with _gpu_job_lock(Path(req["jobs_dir"])):
        _progress(out, "evaluating", arm=arm, task=params["task"])
        policy = ACTPolicy.from_pretrained(ckpt_dir, local_files_only=True).to("cuda").eval()
        policy.config.n_action_steps = params["n_action_steps"]
        pre, post = make_pre_post_processors(policy.config, pretrained_path=str(ckpt_dir))
        nom, layers_nom = eval_sim_profile(
            policy, pre, post, spec, arm, task_name=params["task"],
            episodes=params["nominal_episodes"], delay_frames=0, seed_base=params["seed_base"],
        )
        dly, _ = eval_sim_profile(
            policy, pre, post, spec, arm, task_name=params["task"],
            episodes=params["delayed_episodes"], delay_frames=params["delay_frames"], seed_base=params["seed_base"] + 1000,
        )
        if camera_deg := spec.get("camera_angle_jitter_deg", 0.0):
            camera_cases = []
            varied, varied_layers = eval_sim_profile(
                policy, pre, post, spec, arm, task_name=params["task"], episodes=params["nominal_episodes"],
                delay_frames=0, seed_base=params["seed_base"], camera_cases=camera_cases,
            )
            write_json(out / "camera_robustness.json", {
                "checkpoint_sha256": ckpt_sha, "spec_sha256": req["spec_sha256"], "arm_id": arm, "task": params["task"],
                "max_deg_per_axis": camera_deg, "nominal": nom, "varied_views": varied,
                "per_layer": varied_layers, "episodes": camera_cases,
            })

    reasons = []
    if nom["policy_successes"] < nom["teacher_successes"]:
        reasons.append("nominal_below_teacher")
    if dly["policy_successes"] < dly["teacher_successes"]:
        reasons.append("delayed_below_teacher")
    if nom["neighbour_disturbed"] + nom["arm_link_contacts"] + dly["neighbour_disturbed"] + dly["arm_link_contacts"] > 0:
        reasons.append("collision_detected")
    if any(v["successes"] == 0 for v in layers_nom.values()):
        reasons.append("layer_zero_success")

    report = {
        "schema": "rosy.sim-l1-eval/2",
        "task": params["task"],
        "physics_candidate": f"canonical-{req['spec_sha256'][:12]}",
        "randomisation": {"start_jitter_rad": [-spec["start_jitter_rad"], spec["start_jitter_rad"]]},
        "checkpoint_sha256": ckpt_sha,
        "profiles": {"nominal": nom, "delayed": dly},
        "per_layer": layers_nom,
        "verdict": "reject" if reasons else "pass",
    }
    assessed = sim_l1_assessment(report)
    write_json(out / "eval_l1.json", assessed)
    return {"kind": "eval_ladder", "arm_id": arm, "assessment": assessed, **AUTHORITY_STAMP}


def run_cell_live_check(req: dict, out: Path) -> dict:
    import cv2
    import numpy as np
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from experiment_artifact import export_cell_onnx, package_cell_bundle

    spec = validate_canonical_spec(req["spec"])
    arm = req["arm_id"]
    params = req["params"]
    ckpt_dir, frames_dir, lib_path = (Path(params[k]).resolve() for k in ("checkpoint_dir", "frames_dir", "envelope_path"))

    _progress(out, "packaging_bundle", arm=arm)
    bundle_dir = out / "bundle"
    shutil.rmtree(bundle_dir, ignore_errors=True)
    bundle_info = package_cell_bundle(ckpt_dir, bundle_dir, arm_id=arm, rename_views={"rs": "top"}, target_device="cpu")
    onnx_meta = export_cell_onnx(bundle_dir) if params.get("export_onnx", True) else None
    env = canonical_envelope_from_library(read_json(lib_path, max_bytes=8 * 1048576))
    frames = {}
    for role in ("top", "side", "wrist"):
        img = cv2.imread(str(frames_dir / f"cell-live-{role}.jpg"))
        if img is None:
            raise ValueError(f"missing cell-live-{role}.jpg")
        frames[role] = img

    policy = ACTPolicy.from_pretrained(bundle_dir, local_files_only=True).to("cpu").eval()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(bundle_dir))
    norm2rad = math.pi / 100.0
    jaw0, jaw1 = float(spec["sim_jaw_closed"]), float(spec["sim_jaw_open"])
    g0, g1 = float(spec["idle_park"][arm]["gripper_units"]), float(spec["canonical_start"][arm]["gripper_units"])
    to_grip = lambda j: g0 + (j - jaw0) * (g1 - g0) / max(jaw1 - jaw0, 1e-6)
    states = {
        "legacy_home_closed": list(spec["idle_park"][arm]["norm"]) + [g0],
        "canonical_start_open": list(spec["canonical_start"][arm]["norm"]) + [g1],
    }

    _progress(out, "checking_states", arm=arm)
    n_steps = max(1, int(getattr(policy.config, "n_action_steps", 1)))
    checked_states = {}
    for sname, norm6 in states.items():
        rad_state = np.array([*(v * norm2rad for v in norm6[:5]), jaw1 if "canonical" in sname else jaw0], dtype=np.float32)
        goals, goal_feat = {}, policy.config.input_features.get("observation.environment_state")
        for gslot in (3, 9):
            batch = {"observation.state": torch.from_numpy(rad_state)[None]}
            if goal_feat is not None:
                n_slots = int(goal_feat.shape[0])
                batch["observation.environment_state"] = torch.nn.functional.one_hot(torch.tensor([min(gslot, n_slots - 1)]), n_slots).float()
            for role in ("top", "side", "wrist"):
                if (key := f"observation.images.{role}") in policy.config.input_features:
                    rgb = cv2.cvtColor(frames[role], cv2.COLOR_BGR2RGB)
                    batch[key] = torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255.0
            with torch.inference_mode():
                policy.reset()
                proc = pre(batch)
                acts = [post(policy.select_action(proc)).cpu().numpy()[0] for _ in range(n_steps)]
            chunk_rows = [[*(float(v) / norm2rad for v in a[:5]), to_grip(float(a[5]))] for a in acts]
            goals[f"goal_{gslot}"] = evaluate_chunk_envelope(chunk_rows, env)
        checked_states[sname] = goals

    payload = {
        "schema": LIVE_CHECK_SCHEMA, "arm_id": arm,
        "policy_revision": bundle_info["policy_revision"], "checkpoint_sha256": bundle_info["checkpoint_sha256"],
        "envelope_low": [round(float(v), 3) for v in env.low], "envelope_high": [round(float(v), 3) for v in env.high],
        "home_roll": round(env.home_roll, 3), "states": checked_states,
        **({"onnx_export": onnx_meta} if onnx_meta is not None else {}), **AUTHORITY_STAMP,
    }
    write_json(out / "cell_live_check.json", payload)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("align_real", "collect_dart", "train_stage", "eval_ladder", "cell_live_check"))
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        req = read_json(args.request, max_bytes=4 * 1048576)
        if req.get("kind") != args.kind:
            raise ValueError("canonical worker kind mismatch")
        runners = {"align_real": run_align_real, "collect_dart": run_collect_dart, "train_stage": run_train_stage,
                   "eval_ladder": run_eval_ladder, "cell_live_check": run_cell_live_check}
        write_json(args.out / "result.json", runners[args.kind](req, args.out))
        _progress(args.out, "finished")
        return 0
    except Exception as exc:
        write_json(args.out / "error.json", {"status": "failed", "error": scrub_text(f"{type(exc).__name__}: {exc}", 200)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
