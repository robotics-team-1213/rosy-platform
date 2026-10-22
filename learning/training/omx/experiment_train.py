"""Pinned LeRobot ACT and HIL-SERL SAC updates on explicit offline replay only.

API reference: huggingface/lerobot v0.4.4 policies/{act,sac} and rl/learner.py.
No live actor, policy activation, or physical success is implied by this job.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np

from experiment_dataset import chunk_indices, load_dataset
from experiment_profile import action_names, policy_cameras, profile_revision
from experiment_jobs import check_learning_task


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def training_indices(dataset, method):
    indices = [(episode, index) for episode in dataset.split('train')
               for index in range(len(episode.arrays['action']))]
    if method == 'act' and dataset.source == 'robot_rollout':
        indices = [(episode, index) for episode, index in indices
                   if 'is_intervention' in episode.arrays and episode.arrays['is_intervention'][index]]
        if not indices:
            raise ValueError('ACT requires reviewed human demonstration or intervention targets')
    return indices


def fit_normalization(dataset, indices=None):
    episodes = dataset.split('train')
    stats = {'fit_episodes': [e.metadata['id'] for e in episodes]}
    for key in ('observation.state', 'action'):
        values = (np.stack([episode.arrays[key][index] for episode, index in indices]) if indices is not None
                  else np.concatenate([episode.arrays[key] for episode in episodes])).astype(np.float64)
        stats[key] = {'mean': values.mean(0).tolist(),
                      'std': np.maximum(values.std(0), 1e-6).tolist(),
                      'min': values.min(0).tolist(), 'max': values.max(0).tolist()}
    return stats


def transform_action(values, normal, *, inverse=False, declared=False):
    """Declared actor bounds retain their exact width; offline constant targets need a floor."""
    low = np.asarray(normal['min'], dtype=np.float64)
    width = np.subtract(normal['max'], low)
    if declared:
        if not np.isfinite(width).all() or np.any(width <= 0):
            raise ValueError('declared action bounds need a positive finite width')
    else:
        width = np.maximum(width, 1e-6)
    return (values + 1) / 2 * width + low if inverse else 2 * (values - low) / width - 1


def train(dataset_root: Path, output: Path, *, method='act', steps=40, batch_size=8,
          device='cpu', seed=42750, progress=None, arm_id=None, learning_task=None):
    for label, value, low, high in (('steps', steps, 1, 100000),
            ('batch_size', batch_size, 1, 256), ('seed', seed, 0, 2**32 - 1)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{label} must be an integer in {low}..{high}')
    if method not in ('act', 'hilserl') or device not in ('cpu', 'cuda'):
        raise ValueError('explicit act/hilserl method and cpu/cuda device required')
    output, dataset_root = Path(output).resolve(), Path(dataset_root).resolve()
    if (output.exists() or output.is_relative_to(dataset_root)
            or dataset_root.is_relative_to(output)
            or any((parent / '.git').exists() for parent in (output, *output.parents))):
        raise ValueError('new output directory outside dataset and source checkout required')
    dataset = load_dataset(dataset_root, method=method)
    if learning_task is not None:
        from experiment_scope import select_dataset
        _, scope = select_dataset(dataset, arm_id, method=method)
        check_learning_task(learning_task, dataset, scope)
    return train_dataset(dataset, output, method=method, steps=steps, batch_size=batch_size,
                         device=device, seed=seed, progress=progress, arm_id=arm_id, learning_task=learning_task)


def train_dataset(dataset, output, *, method, steps, batch_size, device, seed,
                  progress=None, state=None, action_bounds=None, execution_mode='offline_replay', arm_id=None,
                  learning_task=None):
    """Update one model/optimizer set; supplied state retains frozen initial normalization."""
    state = {} if state is None else state
    from experiment_scope import select_dataset
    source_width = len(action_names(dataset.profile))
    dataset, scope = select_dataset(dataset, arm_id, method=method)
    if learning_task is not None:
        check_learning_task(learning_task, scope=scope)
    if state and state.get('training_scope') != scope:
        raise ValueError('retained model training scope differs from requested arm/profile')
    if action_bounds is not None:
        bounds = np.asarray(action_bounds, dtype=np.float64)
        if bounds.shape != (source_width, 2):
            raise ValueError('full ordered source action bounds required')
        action_bounds = bounds[scope['action_indices']]
    indices = training_indices(dataset, method)
    if importlib.metadata.version('lerobot') != '0.4.4':
        raise ValueError('isolated lerobot==0.4.4 environment required')
    import torch
    from lerobot.configs.types import FeatureType, PolicyFeature

    if device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('requested CUDA device is unavailable')
    torch.set_num_threads(4)
    if not state:
        torch.manual_seed(seed)
    rng = state['rng'] if state else np.random.default_rng(seed)
    width = len(action_names(dataset.profile))
    cameras = policy_cameras(dataset.profile)
    # Both pinned backends share one image encoder and require equal model image shapes.
    image_shape = (3, 64, 64)
    features = {'observation.state': PolicyFeature(FeatureType.STATE, (width,)),
                **{key: PolicyFeature(FeatureType.VISUAL, image_shape) for key in cameras}}
    common = dict(input_features=features,
                  output_features={'action': PolicyFeature(FeatureType.ACTION, (width,))},
                  device=device)
    if method == 'act':
        from lerobot.policies.act.configuration_act import ACTConfig
        from lerobot.policies.act.modeling_act import ACTPolicy
        config = ACTConfig(**common, chunk_size=4, n_action_steps=4, use_vae=False,
            dim_model=64, n_heads=4, dim_feedforward=256, n_encoder_layers=1,
            n_decoder_layers=1, dropout=0.0, pretrained_backbone_weights=None)
        model_type = ACTPolicy
    else:
        from lerobot.policies.sac.configuration_sac import SACConfig
        from lerobot.policies.sac.modeling_sac import SACPolicy
        config = SACConfig(**common, vision_encoder_name=None, freeze_vision_encoder=False,
                           shared_encoder=True, use_torch_compile=False)
        model_type = SACPolicy
    model = state['model'] if state else model_type(config).to(device)
    stats = state['stats'] if state else fit_normalization(dataset, indices)
    if not state and action_bounds is not None:
        bounds = np.asarray(action_bounds, dtype=np.float64)
        if bounds.shape != (width, 2) or not np.isfinite(bounds).all() or np.any(bounds[:, 0] >= bounds[:, 1]):
            raise ValueError('ordered finite increasing action bounds required')
        stats['action'].update(min=bounds[:, 0].tolist(), max=bounds[:, 1].tolist())
    tensors = {}
    for episode in dataset.episodes:
        if episode.metadata['split'] == 'test':
            continue
        arrays = episode.arrays
        converted = {}
        for key, values in arrays.items():
            if key in cameras or key.startswith('next.observation.images.') and key[5:] in cameras:
                images = torch.from_numpy(values.astype(np.float32) / 255)
                converted[key] = torch.nn.functional.interpolate(images, size=image_shape[1:],
                    mode='bilinear', align_corners=False).to(device)
            elif key in ('observation.state', 'action', 'next_state'):
                normal = stats['observation.state' if key == 'next_state' else key]
                values = values.astype(np.float64)
                if method == 'hilserl' and key == 'action':
                    # Online bounds are declared by the profile; offline uses train-only observed ranges.
                    values = transform_action(values, normal, declared=action_bounds is not None)
                else:
                    values = (values - normal['mean']) / normal['std']
                converted[key] = torch.tensor(values, dtype=torch.float32, device=device)
            elif key in ('reward', 'terminated', 'truncated', 'is_intervention'):
                converted[key] = torch.from_numpy(values).to(device)
        tensors[episode.metadata['id']] = converted
    demonstration = [(e, i) for e, i in indices
                     if e.metadata.get('source', dataset.source) == 'reviewed_demonstration'
                     or 'is_intervention' in e.arrays and e.arrays['is_intervention'][i]]
    rollout = [(e, i) for e, i in indices
               if e.metadata.get('source', dataset.source) != 'reviewed_demonstration'
               and 'is_intervention' in e.arrays and not e.arrays['is_intervention'][i]]
    if state:
        optimizers = state['optimizers']
    elif method == 'act':
        optimizers = {'act': torch.optim.AdamW(model.parameters(), lr=1e-4)}
    else:
        parameters = model.get_optim_params()
        optimizers = {name: torch.optim.Adam([values] if name == 'temperature' else list(values), lr=3e-4)
                      for name, values in parameters.items()}
    if not state:
        state.update(model=model, optimizers=optimizers, stats=stats, rng=rng, total_steps=0,
                     optimizer_step_counts={name: 0 for name in optimizers}, training_scope=scope)
    output.mkdir(parents=True)
    write_json(output / 'profile.json', dataset.profile)
    write_json(output / 'normalization.json', stats)
    lineage = {'learning_task': learning_task} if learning_task is not None else {}
    write_json(output / 'request.json', dict(method=method, steps=steps, batch_size=batch_size,
        device=device, seed=seed, dataset_revision=dataset.revision,
        profile_revision=profile_revision(dataset.profile), action_names=action_names(dataset.profile),
        policy_cameras=cameras, resize_chw=list(image_shape), execution_mode=execution_mode,
        source=dataset.source, lerobot_version='0.4.4', training_scope=scope,
        episodes=[episode.metadata for episode in dataset.episodes], **lineage))

    def observation(episode, index, *, next_observation=False):
        values = tensors[episode.metadata['id']]
        result = {'observation.state': values['next_state' if next_observation else 'observation.state'][index]}
        result.update({key: values[('next.' if next_observation else '') + key][index] for key in cameras})
        return result

    history = []
    for step in range(1, steps + 1):
        picked = []
        for index in range(batch_size):
            population = indices
            if method == 'hilserl' and demonstration and rollout:
                population = demonstration if (state['total_steps'] * batch_size + index) % 2 == 0 else rollout
            picked.append(population[int(rng.integers(len(population)))])
        observations = [observation(e, i) for e, i in picked]
        current = {key: torch.stack([obs[key] for obs in observations]) for key in features}
        model.train()
        if method == 'act':
            actions, masks = [], []
            for episode, index in picked:
                source = tensors[episode.metadata['id']]['action']
                chunk = chunk_indices(episode, index, config.chunk_size)
                actions.append(torch.stack([source[i if i is not None else index] for i in chunk]))
                masks.append(torch.tensor([i is None for i in chunk], dtype=torch.bool, device=device))
            batch = {**current, 'action': torch.stack(actions), 'action_is_pad': torch.stack(masks)}
            loss, _ = model(batch)
            losses = {'act': loss}
        else:
            next_observations = [observation(e, i, next_observation=True) for e, i in picked]
            batch = {'state': current,
                'next_state': {key: torch.stack([obs[key] for obs in next_observations]) for key in features},
                'action': torch.stack([tensors[e.metadata['id']]['action'][i] for e, i in picked]),
                'reward': torch.stack([tensors[e.metadata['id']]['reward'][i] for e, i in picked]),
                # Time-limit truncation still bootstraps from the recorded next observation.
                'done': torch.stack([tensors[e.metadata['id']]['terminated'][i] for e, i in picked]).float(),
                'is_intervention': torch.tensor([bool(e.arrays['is_intervention'][i]) for e, i in picked], device=device)}
            losses = {}
        metrics = {}
        for name, optimizer in optimizers.items():
            loss = losses[name] if method == 'act' else model(batch, model=name)['loss_' + name]
            if not torch.isfinite(loss):
                raise ValueError('nonfinite learner loss')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            state['optimizer_step_counts'][name] += 1
            metrics['loss_' + name] = float(loss.detach())
        if method == 'hilserl':
            model.update_target_networks()
        state['total_steps'] += 1
        event = dict(step=step, steps=steps, total_steps=state['total_steps'],
                     loss=metrics['loss_act' if method == 'act' else 'loss_critic'], **metrics)
        history.append(event)
        write_json(output / 'progress.json', event)
        if progress:
            progress(dict(event))
    model.save_pretrained(output / 'policy')
    reloaded = model_type.from_pretrained(output / 'policy', local_files_only=True).to(device)
    reloaded.eval()
    from experiment_evaluation import evaluate_reloaded
    evaluation = evaluate_reloaded(reloaded, dataset, tensors, features, stats,
                                   method=method, declared_bounds=action_bounds is not None)
    evaluation.update(lineage)
    result = dict(method=method, steps=steps, source=dataset.source,
        optimizer_steps=state['total_steps'], optimizer_step_counts=dict(state['optimizer_step_counts']),
        execution_mode=execution_mode, physical_learning_verified=False,
        policy_activation=False, dataset_revision=dataset.revision,
        training_scope=scope,
        profile_revision=profile_revision(dataset.profile), evaluation=evaluation,
        replay=dict(demonstration_frames=len(demonstration), rollout_frames=len(rollout)),
        supervised_frames=len(indices) if method == 'act' else 0,
        policy_sha256=hashlib.sha256((output / 'policy/model.safetensors').read_bytes()).hexdigest(), **lineage)
    write_json(output / 'history.json', history)
    write_json(output / 'evaluation.json', evaluation)
    write_json(output / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    # An existing directory belongs to a prior run and must never be modified.
    if args.out.exists():
        raise ValueError('new run-owned output directory required')
    try:
        request = json.loads(args.request.read_text(encoding='utf-8'))
        if (not isinstance(request, dict)
                or set(request) - {'arm_id', 'learning_task'} != {'dataset_root', 'method', 'steps', 'batch_size', 'device', 'seed'}):
            raise ValueError('training request fields differ from schema')
        if 'learning_task' in request:
            check_learning_task(request['learning_task'])
        train(output=args.out, **request)
    except Exception as error:
        args.out.mkdir(parents=True, exist_ok=True)
        # Server-visible diagnostics never expose arbitrary host paths or credentials.
        write_json(args.out / 'error.json', {'error': type(error).__name__, 'status': 'failed'})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
