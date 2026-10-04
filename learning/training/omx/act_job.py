"""Offline LeRobot 0.4.4 ACT study -> common research PolicyArtifact, never promotion.

act_job.py --train-export <LeRobot-root>... --eval-export <root> --out <new-dir>
CPU only; source episode groups are disjoint. No robot, ROS, GPU, or network command.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "contracts/learning/src", ROOT / "learning/curation/omx"):
    sys.path.insert(0, str(path))


def chunk_indices(count, start, size):
    if not 0 <= start < count or size < 1:
        raise ValueError("valid episode offset and positive chunk required")
    return [i if i < count else None for i in range(start, start + size)]


def compatible_sources(sources):
    keys = ("joint_names", "position_limits_rad", "camera", "fps", "calibration_revision", "world_sha256")
    if not sources or any(any(s.get(k) != sources[0].get(k) for k in keys) for s in sources):
        raise ValueError("source rig/joint order/limits/calibration/world differ")


def offline_report(truth, prediction, baseline, training_actions, limits):
    truth, prediction = np.asarray(truth), np.asarray(prediction)
    if truth.shape != prediction.shape or truth.ndim != 2 or not len(truth):
        raise ValueError("matching nonempty action arrays required")
    finite = bool(np.isfinite(prediction).all())
    baseline_mae = float(np.abs(truth - baseline).mean())
    mae = float(np.abs(truth - prediction).mean()) if finite else None
    limits = np.asarray(limits)
    violations = int(((prediction < limits[:, 0]) | (prediction > limits[:, 1])).sum())
    diversity = len(np.unique(np.round(np.asarray(training_actions) / .001), axis=0))
    reasons = []
    if not finite:
        reasons.append("nonfinite_prediction")
    if violations:
        reasons.append("joint_limit_violation")
    if diversity < 3:
        reasons.append("insufficient_target_diversity")
    if mae is None or mae >= baseline_mae:
        reasons.append("does_not_beat_constant_target_baseline")
    return {"verdict": "reject" if reasons else "offline_only", "reasons": reasons,
            "mae_rad": mae, "constant_baseline_mae_rad": baseline_mae,
            "limit_violations": violations, "target_clusters_0_001_rad": diversity,
            "eval_frames": len(truth), "independent_task_success": "unverified"}


def _write(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _ref(path, root):
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def run(train_exports, eval_export, out, *, steps=40, seed=42750, n_action_steps=4):
    if type(n_action_steps) is not int or not 1<=n_action_steps<=4:
        raise ValueError('n_action_steps must be an integer in 1..4 within chunk_size=4')
    if importlib.metadata.version("lerobot") != "0.4.4":
        raise ValueError("separate lerobot==0.4.4 environment required")
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError("steps must be an integer in 1..10000")
    out = Path(out).resolve()
    if out.exists() or out.drive.upper() == "F:":
        raise ValueError("new artifact directory outside F: required")
    exports = [Path(p).resolve() for p in [*train_exports, eval_export]]
    if len(exports) < 3 or len(set(exports)) != len(exports):
        raise ValueError("two train and one disjoint eval Episode exports required")
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in exports):
        raise ValueError("output must be separate from source exports")
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.configs.types import PolicyFeature, FeatureType
    from common_episode import convert, validate_omx
    from rosy.contracts.learning import seal, validate_dataset, validate_policy

    torch.set_num_threads(4)
    torch.manual_seed(seed)
    np.random.seed(seed)
    source_paths, sources, original_rows = [], [], []
    for export in exports:
        paths = sorted((export / "rosy_provenance").glob("*/manifest.json"))
        if len(paths) != 1:
            raise ValueError("one original validated Episode per export required")
        validated = validate_omx(paths[0].parent)
        source_paths.append(paths[0].parent)
        sources.append(validated["manifest"]["provenance"])
        original_rows.append(validated["samples"])
    ids = [p.name for p in source_paths]
    if len(set(ids)) != len(ids):
        raise ValueError("same original Episode cannot straddle train/eval")
    compatible_sources(sources)
    durations = {r["duration_s"] for rows in original_rows for r in rows}
    if len(durations) != 1:
        raise ValueError("joint-only study requires one explicit source duration")
    out.mkdir(parents=True)
    _write(out / "state.json", {"status": "reading", "steps": steps, "seed": seed, "source_episodes": ids})
    try:
        episodes, arrays = [], []
        for export, source, rows in zip(exports, source_paths, original_rows):
            snapshot = out / "reader-inputs" / source.name
            shutil.copytree(export, snapshot)
            source = snapshot / "rosy_provenance" / source.name
            copied = validate_omx(source)
            if copied["samples"] != rows:
                raise ValueError("source rows changed during input snapshot")
            common = out / "episodes" / source.name
            episode = convert(source, common)
            episodes.append(episode)
            reader = LeRobotDataset("rosy-local/omx-sim", root=snapshot, video_backend="pyav", download_videos=False)
            if reader.num_episodes != 1 or reader.num_frames != len(rows):
                raise ValueError("LeRobot frame/Episode count differs")
            images, states, actions = [], [], []
            for index, row in enumerate(rows):
                actual = reader[index]
                for key in ("observation.state", "action"):
                    np.testing.assert_allclose(actual[key].numpy(), row[key], atol=1e-7, rtol=1e-6)
                for field in ("capture_time_ns", "state_time_ns", "state_sequence"):
                    if int(actual["source." + field].item()) != row[field]:
                        raise ValueError("LeRobot source clock/sequence differs")
                if int(actual["source.received_wall_time_ns"].item()) != row["received_at_ns"]:
                    raise ValueError("LeRobot wall receipt clock differs")
                np.testing.assert_allclose(actual["action.duration_s"].numpy(), [row["duration_s"]],
                                           atol=1e-7, rtol=1e-6)
                images.append(torch.nn.functional.interpolate(actual["observation.images.front"].unsqueeze(0),
                                                              size=(64, 64), mode="bilinear", align_corners=False)[0])
                states.append(actual["observation.state"])
                actions.append(actual["action"])
            arrays.append((torch.stack(images), torch.stack(states), torch.stack(actions)))
        train_actions = torch.cat([a[2] for a in arrays[:-1]])
        train_states = torch.cat([a[1] for a in arrays[:-1]])
        state_mean, action_mean = train_states.mean(0), train_actions.mean(0)
        state_std, action_std = train_states.std(0, unbiased=False), train_actions.std(0, unbiased=False)
        state_std = torch.where(state_std < 1e-6, torch.ones_like(state_std), state_std)
        action_std = torch.where(action_std < 1e-6, torch.ones_like(action_std), action_std)
        stats = {"state_mean": state_mean.tolist(), "state_std": state_std.tolist(),
                 "action_mean": action_mean.tolist(), "action_std": action_std.tolist(),
                 "fit_episodes": ids[:-1], "image": {"resize_hw": [64, 64], "color": "rgb", "scale": 1/255},
                 "fixed_source_duration_s": next(iter(durations))}
        _write(out / "normalization.json", stats)
        for i, (images, states, actions) in enumerate(arrays):
            arrays[i] = (images, (states - state_mean) / state_std, (actions - action_mean) / action_std)
        names = sources[0]["joint_names"]
        config = ACTConfig(input_features={"observation.state": PolicyFeature(FeatureType.STATE, (len(names),)),
                           "observation.images.front": PolicyFeature(FeatureType.VISUAL, (3, 64, 64))},
                           output_features={"action": PolicyFeature(FeatureType.ACTION, (len(names),))},
                           chunk_size=4, n_action_steps=n_action_steps, dim_model=64, n_heads=4, dim_feedforward=256,
                           n_encoder_layers=1, n_decoder_layers=1, use_vae=False, dropout=0.0,
                           pretrained_backbone_weights=None, device="cpu",
                           optimizer_lr=1e-3, optimizer_lr_backbone=1e-3, optimizer_weight_decay=1e-4)
        policy = ACTPolicy(config)
        optimizer = torch.optim.AdamW(policy.parameters(), lr=config.optimizer_lr,
                                      weight_decay=config.optimizer_weight_decay)
        indices = [(e, i) for e, a in enumerate(arrays[:-1]) for i in range(len(a[0]))]
        history = []
        _write(out / "state.json", {"status": "training", "steps": steps, "seed": seed, "source_episodes": ids})
        for step in range(steps):
            picked = [indices[i] for i in torch.randint(len(indices), (8,)).tolist()]
            batch = {k: [] for k in ("observation.state", "observation.images.front", "action", "action_is_pad")}
            for e, i in picked:
                images, states, actions = arrays[e]
                chunk = chunk_indices(len(actions), i, 4)
                batch["observation.state"].append(states[i])
                batch["observation.images.front"].append(images[i])
                batch["action"].append(torch.stack([actions[j] if j is not None else actions[-1] for j in chunk]))
                batch["action_is_pad"].append(torch.tensor([j is None for j in chunk], dtype=torch.bool))
            batch = {k: torch.stack(v) for k, v in batch.items()}
            policy.train()
            loss, _ = policy(batch)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite training loss")
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            optimizer.step()
            history.append(float(loss.detach()))
        policy.save_pretrained(out / "policy")
        _write(out / "history.json", {"loss": history})

        def predict(model):
            model.eval()
            model.reset()
            images, states, _ = arrays[-1]
            with torch.no_grad():
                predictions = [model.select_action({"observation.state": states[i:i+1],
                               "observation.images.front": images[i:i+1]}).squeeze(0)
                               for i in range(len(states))]
            return (torch.stack(predictions) * action_std + action_mean).numpy()

        prediction = predict(policy)
        reloaded = ACTPolicy.from_pretrained(out / "policy", local_files_only=True)
        np.testing.assert_allclose(predict(reloaded), prediction, atol=1e-6, rtol=1e-6)
        truth = np.asarray([r["action"] for r in original_rows[-1]])
        limits = [sources[0]["position_limits_rad"][name] for name in names]
        report = offline_report(truth, prediction, action_mean.numpy(), train_actions.numpy(), limits)
        report.update(algorithm="lerobot-act", lerobot_version="0.4.4", torch_version=str(torch.__version__),
                      device="cpu", seed=seed, steps=steps, n_action_steps=n_action_steps,
                      train_episodes=ids[:-1], eval_episode=ids[-1],
                      optimizer={"type": "AdamW", "parameter_grouping": "all_policy_parameters",
                                 "parameter_groups": [{key: group[key] for key in
                                     ("lr", "weight_decay", "betas", "eps", "amsgrad", "maximize",
                                      "foreach", "capturable", "differentiable", "fused")}
                                     for group in optimizer.param_groups],
                                 "gradient_clip_norm": 1.0},
                      reloaded_prediction_verified=True, task_outcome_source="operator_source_only")
        _write(out / "offline-report.json", report)
        refs = [_ref(p, out) for folder in ("episodes", "reader-inputs")
                for p in sorted((out / folder).rglob('*')) if p.is_file()]
        dataset = seal({"schema": "rosy.dataset-manifest/1", "episodes": [e["revision"] for e in episodes],
                       "transformation": {"tool_revision": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                          "config_sha256": hashlib.sha256(json.dumps(stats, sort_keys=True).encode()).hexdigest()},
                       "files": refs})
        validate_dataset(dataset, root=out)
        _write(out / "dataset-manifest.json", dataset)
        artifact = seal({"schema": "rosy.policy-artifact/1", "profile": "omx_joint_target_v1",
                         "robot_type": "omx_sim_ros", "environment": "sim",
                         "device_profile_revision": "sim-world:" + sources[0]["world_sha256"],
                         "camera_profile_revision": None,
                         "cameras": [{"name": "front", "identity": sources[0]["camera"]["identity"],
                                      "calibration_sha256": sources[0]["camera"]["camera_info_sha256"],
                                      "source_shape": [3, sources[0]["camera"]["height"], sources[0]["camera"]["width"]],
                                      "model_shape": [3, 64, 64], "color": "rgb", "scale": 1/255}],
                         "joint_names": names, "normalization": _ref(out / "normalization.json", out),
                         "observation": {"names": names, "units": ["rad"]*len(names), "shape": [len(names)]},
                         "action": {"names": names, "units": ["rad"]*len(names), "limits": limits,
                                    "semantics": "absolute_joint_position_target_rad"},
                         "owner": {"kind": "omx_local_controller", "controller_revision": "unregistered-act-study",
                                   "envelope_revision": "unregistered-source-limits-study"},
                         "timing": {"period_ns": 1_000_000_000 // sources[0]["fps"],
                                    "max_observation_age_ns": 50_000_000, "max_action_age_ns": 50_000_000},
                         "failure_mode": "hold", "reset_events": ["stop", "hold", "lease_change", "episode_change"],
                         "dataset_revisions": [dataset["revision"]], "evaluations": [_ref(out / "offline-report.json", out)],
                         "tool_revision": dataset["transformation"]["tool_revision"],
                         "files": [_ref(p, out) for p in sorted((out / "policy").rglob('*')) if p.is_file()]})
        validate_policy(artifact, root=out)
        _write(out / "policy-artifact.json", artifact)
        _write(out / "state.json", {"status": "research_exported", "promotion": "not_eligible",
                                    "revision": artifact["revision"], "offline_verdict": report["verdict"]})
        return report
    except BaseException as exc:
        _write(out / "state.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train-export", type=Path, nargs='+', required=True)
    ap.add_argument("--eval-export", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42750)
    ap.add_argument("--n-action-steps", type=int, default=4, choices=range(1,5))
    args = ap.parse_args()
    print(json.dumps(run(args.train_export, args.eval_export, args.out, steps=args.steps, seed=args.seed,
                         n_action_steps=args.n_action_steps)))


if __name__ == "__main__":
    main()
