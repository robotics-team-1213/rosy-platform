"""Offline LeRobot 0.4.4 ACT study -> common research PolicyArtifact, never promotion.

act_job.py --train-export <LeRobot-root>... --eval-export <root> --out <new-dir>
CPU only; source episode groups are disjoint. No robot, ROS, GPU, or network command.
"""
import argparse
from collections import deque
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


def _in_checkout(path) -> bool:
    """True inside a git working tree: artifacts stay out of source checkouts, on any drive."""
    path = Path(path).resolve()
    return any((p / '.git').exists() for p in (path, *path.parents))


def verify_reader_image(pixels, original, expected_sha256):
    """Recheck consumed RGB against validated PNG using the exporter's lossy bound."""
    from io import BytesIO
    from PIL import Image
    data = Path(original).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("LeRobot source PNG hash differs from validated row")
    with Image.open(BytesIO(data)) as image:
        expected = np.asarray(image, dtype=np.uint8)
    pixels = np.asarray(pixels)
    if (pixels.ndim != 3 or pixels.shape[0] != 3
            or pixels.transpose(1, 2, 0).shape != expected.shape
            or not np.issubdtype(pixels.dtype, np.floating)
            or not np.isfinite(pixels).all() or (pixels < 0).any() or (pixels > 1).any()):
        raise ValueError("LeRobot source image dimensions/range differ")
    error = float(np.abs(pixels.transpose(1, 2, 0) * 255 - expected).mean())
    if error > 8:
        raise ValueError("LeRobot source image differs beyond export lossy encoding tolerance")
    return error


def chunk_indices(count, start, size):
    if not 0 <= start < count or size < 1:
        raise ValueError("valid episode offset and positive chunk required")
    return [i if i < count else None for i in range(start, start + size)]


def training_sample_indices(rows, joint_names, *, sampling):
    """Select original frames only; action labels and chunk chronology stay unchanged."""
    if sampling == 'all_frames':
        return list(range(len(rows)))
    if sampling != 'command_entry' or list(joint_names) != [f'joint{i}' for i in range(1,6)]+['gripper_joint_1']:
        raise ValueError('command_entry sampling requires the fixed six-joint OMX SIM rig')
    selected = {}
    commands = {(row['command_id'],row['ros_goal_id']) for row in rows}
    for index,row in enumerate(rows):
        bounds = [.035]*5+[.04]  # Arm training margin; preserve the calibrated gripper target.
        if all(abs(target-state)<=bound for target,state,bound in
               zip(row['action'],row['observation.state'],bounds)):
            selected.setdefault((row['command_id'],row['ros_goal_id']),index)
    if not commands or set(selected) != commands:
        raise ValueError('command_entry sampling must represent every command')
    return sorted(selected.values())


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


def export_truth(export, source, validated):
    """A missing automatic proof cannot become an operator judgement."""
    report = json.loads((export/'rosy_export.json').read_bytes())
    judge = report.get('task_outcome_judge', 'operator')
    proof = export/'rosy_sim_truth/truth.json'
    if report['status'] != 'verified' or judge not in {'operator','sim_ground_truth'}:
        raise ValueError('verified export with a known source judge required')
    if judge == 'sim_ground_truth':
        from rosy.contracts.learning.sim_object_truth import validate_truth
        validate_truth(proof, validated, source=source)
        return proof
    if proof.exists():
        raise ValueError('export judge contradicts automatic SIM proof')
    return None


def run(train_exports, eval_export, out, *, steps=40, seed=42750, n_action_steps=4, sampling='all_frames',
        action_representation='absolute',state_noise_std_rad=0.):
    if action_representation not in ('absolute','joint_delta_from_chunk_source_v1','joint_delta_tanh_from_chunk_source_v1'):
        raise ValueError('unknown action representation')
    if (type(state_noise_std_rad) not in (int,float) or not np.isfinite(state_noise_std_rad)
            or state_noise_std_rad<0):
        raise ValueError('state noise standard deviation must be finite and nonnegative')
    if state_noise_std_rad and action_representation=='absolute':
        raise ValueError('state noise requires source-relative targets')
    if sampling not in ('all_frames','command_entry'):
        raise ValueError('unknown training sampling')
    if type(n_action_steps) is not int or not 1<=n_action_steps<=4:
        raise ValueError('n_action_steps must be an integer in 1..4 within chunk_size=4')
    if importlib.metadata.version("lerobot") != "0.4.4":
        raise ValueError("separate lerobot==0.4.4 environment required")
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError("steps must be an integer in 1..10000")
    out = Path(out).resolve()
    if out.exists() or _in_checkout(out):
        raise ValueError("new artifact directory outside the source checkout required")
    eval_exports = [eval_export] if isinstance(eval_export, (str, Path)) else list(eval_export)
    train_count = len(train_exports)
    exports = [Path(p).resolve() for p in [*train_exports, *eval_exports]]
    if train_count < 2 or not eval_exports or len(set(exports)) != len(exports):
        raise ValueError("at least two train and one disjoint eval Episode exports required")
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
    source_paths, sources, original_rows, automatic = [], [], [], []
    for export in exports:
        paths = sorted((export / "rosy_provenance").glob("*/manifest.json"))
        if len(paths) != 1:
            raise ValueError("one original validated Episode per export required")
        validated = validate_omx(paths[0].parent)
        automatic.append(export_truth(export, paths[0].parent, validated) is not None)
        source_paths.append(paths[0].parent)
        sources.append(validated["manifest"]["provenance"])
        original_rows.append(validated["samples"])
    ids = [p.name for p in source_paths]
    if len(set(ids)) != len(ids):
        raise ValueError("same original Episode cannot straddle train/eval")
    compatible_sources(sources)
    if sampling == 'command_entry' and not all(automatic):
        raise ValueError('command_entry sampling requires independently verified SIM object truth')
    selected_indices = [training_sample_indices(rows,sources[0]['joint_names'],sampling=sampling)
                        for rows in original_rows]
    # D-794 B: the image key and the artifact camera name follow the recorded camera name.
    image_key = "observation.images." + sources[0]["camera"]["name"]
    durations = {r["duration_s"] for rows in original_rows for r in rows}
    if len(durations) != 1:
        raise ValueError("joint-only study requires one explicit source duration")
    out.mkdir(parents=True)
    sampling_ref = None
    if sampling == 'command_entry':
        selection = dict(sampling=sampling,arm_margin_rad=.005,gripper_margin_claim='none',
                         original_arrays_and_chunk_order=True,
                         train_indices=dict(zip(ids[:train_count],selected_indices[:train_count])))
        _write(out/'training-index.json',selection)
        sampling_ref = _ref(out/'training-index.json',out)
    _write(out / "state.json", {"status": "reading", "steps": steps, "seed": seed, "source_episodes": ids})
    try:
        episodes, arrays = [], []
        for export, source, rows, was_automatic in zip(exports, source_paths, original_rows, automatic):
            snapshot = out / "reader-inputs" / source.name
            shutil.copytree(export, snapshot)
            source = snapshot / "rosy_provenance" / source.name
            copied = validate_omx(source)
            if copied["samples"] != rows:
                raise ValueError("source rows changed during input snapshot")
            common = out / "episodes" / source.name
            proof = export_truth(snapshot, source, copied)
            if (proof is not None) != was_automatic:
                raise ValueError('source outcome judge changed during snapshot')
            episode = convert(source, common, sim_ground_truth=proof)
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
                verify_reader_image(actual[image_key].numpy(), source / row["image_path"], row["image_sha256"])
                images.append(torch.nn.functional.interpolate(actual[image_key].unsqueeze(0),
                                                              size=(64, 64), mode="bilinear", align_corners=False)[0])
                states.append(actual["observation.state"])
                actions.append(actual["action"])
            arrays.append((torch.stack(images), torch.stack(states), torch.stack(actions)))
        train_actions = torch.cat([a[2] for a in arrays[:train_count]])
        train_states = torch.cat([a[1] for a in arrays[:train_count]])
        absolute_baseline=train_actions.mean(0)
        action_values=train_actions if action_representation=='absolute' else train_actions-train_states
        state_mean, action_mean = train_states.mean(0), action_values.mean(0)
        state_std, action_std = train_states.std(0, unbiased=False), action_values.std(0, unbiased=False)
        state_std = torch.where(state_std < 1e-6, torch.ones_like(state_std), state_std)
        action_std = torch.where(action_std < 1e-6, torch.ones_like(action_std), action_std)
        stats = {"state_mean": state_mean.tolist(), "state_std": state_std.tolist(),
                 "action_mean": action_mean.tolist(), "action_std": action_std.tolist(),
                 "fit_episodes": ids[:train_count], "image": {"resize_hw": [64, 64], "color": "rgb", "scale": 1/255},
                 "fixed_source_duration_s": next(iter(durations))}
        if action_representation!='absolute':
            del stats['action_mean'],stats['action_std']
            stats['action_transform']=dict(type=action_representation,mean=action_mean.tolist(),
                std=action_std.tolist(),absolute_baseline=absolute_baseline.tolist())
            if action_representation=='joint_delta_tanh_from_chunk_source_v1':
                stats['action_transform']['max_delta_rad']=.035
        noise_rng=None
        if state_noise_std_rad:
            noise_rng=torch.Generator().manual_seed(seed+1)
            stats['training_augmentation']=dict(type='gaussian_state_noise_v1',std_rad=state_noise_std_rad,
                seed=seed+1,joint_names=sources[0]['joint_names'],train_only=True,
                source_kind='synthetic_training_inputs')
        _write(out / "normalization.json", stats)
        for i, (images, states, actions) in enumerate(arrays):
            arrays[i] = (images, (states - state_mean) / state_std, (actions - action_mean) / action_std)
        names = sources[0]["joint_names"]
        config = ACTConfig(input_features={"observation.state": PolicyFeature(FeatureType.STATE, (len(names),)),
                           image_key: PolicyFeature(FeatureType.VISUAL, (3, 64, 64))},
                           output_features={"action": PolicyFeature(FeatureType.ACTION, (len(names),))},
                           chunk_size=4, n_action_steps=n_action_steps, dim_model=64, n_heads=4, dim_feedforward=256,
                           n_encoder_layers=1, n_decoder_layers=1, use_vae=False, dropout=0.0,
                           pretrained_backbone_weights=None, device="cpu",
                           optimizer_lr=1e-4, optimizer_lr_backbone=1e-5, optimizer_weight_decay=1e-4)
        policy = ACTPolicy(config)
        from act_inference import install_action_head_transform
        install_action_head_transform(policy,stats)
        optimizer = torch.optim.AdamW(policy.get_optim_params(), lr=config.optimizer_lr,
                                      weight_decay=config.optimizer_weight_decay)
        indices = [(e, i) for e, chosen in enumerate(selected_indices[:train_count]) for i in chosen]
        history = []
        _write(out / "state.json", {"status": "training", "steps": steps, "seed": seed, "source_episodes": ids})
        for step in range(steps):
            picked = [indices[i] for i in torch.randint(len(indices), (8,)).tolist()]
            batch = {k: [] for k in ("observation.state", image_key, "action", "action_is_pad")}
            for e, i in picked:
                images, states, actions = arrays[e]
                chunk = chunk_indices(len(actions), i, 4)
                state=states[i]
                origin=state*state_std+state_mean
                if noise_rng is not None:
                    # Synthetic train input only; all original absolute targets stay fixed.
                    origin=origin+torch.randn(origin.shape,generator=noise_rng)*state_noise_std_rad
                    state=(origin-state_mean)/state_std
                batch["observation.state"].append(state)
                batch[image_key].append(images[i])
                targets=torch.stack([actions[j] if j is not None else actions[-1] for j in chunk])
                if action_representation!='absolute':
                    targets=targets-origin/action_std
                batch["action"].append(targets)
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
            predictions = []
            with torch.no_grad():
                for images, states, _ in arrays[train_count:]:
                    model.reset()
                    queue=deque()
                    for i in range(len(states)):
                        if not queue:
                            chunk=model.predict_action_chunk({"observation.state":states[i:i+1],
                                                              image_key:images[i:i+1]})
                            actions=chunk[0,:n_action_steps]*action_std+action_mean
                            if action_representation!='absolute':
                                actions=actions+states[i]*state_std+state_mean
                            queue.extend(actions)
                        predictions.append(queue.popleft())
            return torch.stack(predictions).numpy()

        prediction = predict(policy)
        reloaded = ACTPolicy.from_pretrained(out / "policy", local_files_only=True)
        install_action_head_transform(reloaded,stats)
        np.testing.assert_allclose(predict(reloaded), prediction, atol=1e-6, rtol=1e-6)
        truth = np.asarray([r["action"] for rows in original_rows[train_count:] for r in rows])
        limits = [sources[0]["position_limits_rad"][name] for name in names]
        report = offline_report(truth, prediction, absolute_baseline.numpy(), train_actions.numpy(), limits)
        report.update(algorithm="lerobot-act", lerobot_version="0.4.4", torch_version=str(torch.__version__),
                      device="cpu", seed=seed, steps=steps, n_action_steps=n_action_steps,
                      train_episodes=ids[:train_count], eval_episodes=ids[train_count:],
                      optimizer={"type": "AdamW", "parameter_grouping": "act_get_optim_params",
                                 "parameter_groups": [{key: group[key] for key in
                                     ("lr", "weight_decay", "betas", "eps", "amsgrad", "maximize",
                                      "foreach", "capturable", "differentiable", "fused")}
                                     for group in optimizer.param_groups],
                                 "gradient_clip_norm": 1.0},
                      reloaded_prediction_verified=True,
                      task_outcome_judges={e['episode_id']:e['outcome']['judge'] for e in episodes})
        offset = 0
        per_episode = {}
        for episode_id, rows in zip(ids[train_count:], original_rows[train_count:]):
            count = len(rows)
            per_episode[episode_id] = offline_report(truth[offset:offset+count], prediction[offset:offset+count],
                absolute_baseline.numpy(), train_actions.numpy(), limits)
            offset += count
        report['per_episode'] = per_episode
        if noise_rng is not None:
            report['training_augmentation']=stats['training_augmentation']
        if sampling_ref is not None:
            report['training_sampling'] = dict(rule=sampling,index=sampling_ref,
                selected_training_frames=len(indices),all_training_frames=sum(len(rows) for rows in original_rows[:train_count]))
        if len(eval_exports) == 1:
            report['eval_episode'] = ids[-1]
        judges = set(report['task_outcome_judges'].values())
        report['task_outcome_source'] = ('operator_source_only' if judges == {'operator'}
                                         else 'sim_ground_truth' if judges == {'sim_ground_truth'} else 'mixed')
        _write(out / "offline-report.json", report)
        refs = [_ref(p, out) for folder in ("episodes", "reader-inputs")
                for p in sorted((out / folder).rglob('*')) if p.is_file()]
        transformation_config = stats
        if sampling_ref is not None:
            refs.append(sampling_ref)
            transformation_config = dict(normalization=stats,training_sampling=sampling_ref)
        dataset = seal({"schema": "rosy.dataset-manifest/1", "episodes": [e["revision"] for e in episodes],
                       "transformation": {"tool_revision": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                          "config_sha256": hashlib.sha256(json.dumps(transformation_config, sort_keys=True).encode()).hexdigest()},
                       "files": refs})
        validate_dataset(dataset, root=out)
        _write(out / "dataset-manifest.json", dataset)
        artifact = seal({"schema": "rosy.policy-artifact/1", "profile": "omx_joint_target_v1",
                         "robot_type": "omx_sim_ros", "environment": "sim",
                         "device_profile_revision": "sim-world:" + sources[0]["world_sha256"],
                         "camera_profile_revision": None,
                         "cameras": [{"name": sources[0]["camera"]["name"], "identity": sources[0]["camera"]["identity"],
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
    ap.add_argument("--eval-export", type=Path, nargs='+', required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42750)
    ap.add_argument("--n-action-steps", type=int, default=4, choices=range(1,5))
    ap.add_argument("--sampling", choices=('all_frames','command_entry'), default='all_frames')
    ap.add_argument("--action-representation",choices=('absolute','joint_delta_from_chunk_source_v1','joint_delta_tanh_from_chunk_source_v1'),default='absolute')
    ap.add_argument('--state-noise-std-rad',type=float,default=0.)
    args = ap.parse_args()
    print(json.dumps(run(args.train_export, args.eval_export, args.out, steps=args.steps, seed=args.seed,
                         n_action_steps=args.n_action_steps,sampling=args.sampling,
                         action_representation=args.action_representation,state_noise_std_rad=args.state_noise_std_rad)))


if __name__ == "__main__":
    main()
