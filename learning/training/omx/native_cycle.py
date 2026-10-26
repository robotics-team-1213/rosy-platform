"""Reviewed native splits -> official ACT -> fresh-process reload and offline evaluation."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'curation/omx'))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # experiment_dataset sits beside this file
import native_review as native
from experiment_dataset import dataset_lease


def validate_split(root):
    root = Path(root).resolve()
    try:
        receipt = json.loads((root / 'split-receipt.json').read_text(encoding='utf-8'))
        if receipt.get('reader_verified') is not True:
            raise ValueError('split reader verification is required')
        if receipt['source']['source_mode'] not in ('leader_native', 'scripted_teacher'):
            raise ValueError('a declared native capture source is required')
        source = receipt['source']
        bound = native.bind_capture(source['episodes'], source['files'], source_mode=source['source_mode'],
                                     body_units=source['body_units'], rig_revision=source['rig_revision'],
                                     calibration_revision=source['calibration_revision'],
                                     provenance=source.get('capture_provenance'))
        if bound['episodes'] != source['episodes']:
            raise ValueError('capture episode grouping differs from declared provenance')
        if 'segment_selection' in receipt:
            from native_segments import validate_receipt
            selected = validate_receipt(receipt)
        else:
            selected = native.reviewed_splits(receipt['source'], receipt['decisions'])
        coverage = native.split_coverage(native.validate_environment(source), receipt['decisions'])
        if ('environment_summary' in source or 'environment_coverage' in receipt
                or source.get('environment_evidence') is not None):
            if receipt.get('environment_coverage') != coverage:
                raise ValueError('environment coverage differs from original episode evidence')
        if selected != receipt['splits'] or set(receipt['outputs']) != set(selected):
            raise ValueError('split receipt selection differs from reviewed episodes')
        for name in selected:
            if native.dataset_files(root / name) != receipt['outputs'][name]:
                raise ValueError(f'{name} split bytes no longer match receipt')
        return receipt
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('incomplete reviewed split receipt, including output hashes') from exc


def _artifact_files(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('model artifact must not contain links')
        if path.is_file():
            with path.open('rb') as stream:
                files[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    for required in ('config.json', 'model.safetensors', 'policy_preprocessor.json', 'policy_postprocessor.json'):
        if required not in files:
            raise ValueError(f'missing model artifact: {required}')
    return files


def policy_revision(artifact_files):
    """D-793: the stage ledger names a trained model by the hash of its exact file set."""
    canonical = json.dumps(dict(sorted(artifact_files.items())), separators=(',', ':')).encode()
    return 'act-' + hashlib.sha256(canonical).hexdigest()[:16]


def _invoke(command, output, environment, timeout, *, lease_fd=None):
    with output.open('x', encoding='utf-8') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                env=environment, timeout=timeout,
                                pass_fds=() if lease_fd is None else (lease_fd,))
    if result.returncode:
        tail = output.read_text(encoding='utf-8', errors='replace')[-5000:]
        raise ValueError(f'pipeline process failed ({result.returncode}): {tail}')


def evaluation_joints(train_info, eval_info):
    names = native.joint_layout(train_info)
    if native.joint_layout(eval_info) != names:
        raise ValueError('train/eval joint layouts differ')
    return names


def _evaluate(model, splits, repo_id, output):
    with dataset_lease(splits):
        return _evaluate_inputs(model, splits, repo_id, output)


def _evaluate_inputs(model, splits, repo_id, output):
    receipt = validate_split(splits)
    if receipt['source']['repo_id'] != repo_id:
        raise ValueError('evaluation repo identity differs from reviewed source')
    _artifact_files(model)
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    torch.set_num_threads(2)
    train = native.load_dataset(splits / 'train', repo_id + '_train')
    evaluation = native.load_dataset(splits / 'eval', repo_id + '_eval')
    names = evaluation_joints(train.meta.info, evaluation.meta.info)
    size = len(names)
    policy = ACTPolicy.from_pretrained(model)
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(model))
    policy.eval()
    mean = torch.as_tensor(train.meta.stats['action']['mean'], dtype=torch.float32).reshape(1, size)
    error, baseline, samples, previous = torch.zeros(size), torch.zeros(size), 0, None
    with torch.inference_mode():
        for batch in torch.utils.data.DataLoader(evaluation, batch_size=1, shuffle=False):
            episode = int(batch['episode_index'].item())
            if episode != previous:
                policy.reset()
            previous = episode
            target = batch['action'].detach().clone().cpu()
            action = post(policy.select_action(pre(batch))).detach().cpu()
            if action.shape != (1, size) or target.shape != (1, size) or not torch.isfinite(action).all():
                raise ValueError('reloaded model returned an invalid joint action')
            error += (action - target).abs().reshape(size)
            baseline += (mean - target).abs().reshape(size)
            samples += 1
    if not samples:
        raise ValueError('independent evaluation contains no frames')
    native.write_json(output, dict(samples=samples, split='eval', model_reloaded_in_new_process=True,
                                   mae_per_joint=(error / samples).tolist(),
                                   train_mean_baseline_mae_per_joint=(baseline / samples).tolist(),
                                   joint_names=names, physical_task_success=None,
                                   environment_coverage=native.split_coverage(
                                       native.validate_environment(receipt['source']), receipt['decisions'])))


def run_cycle(splits, output, *, steps=100, batch_size=8, device='cpu', timeout=5400):
    with dataset_lease(splits) as lease_fd:
        return _run_cycle(splits, output, steps=steps, batch_size=batch_size,
                          device=device, timeout=timeout, lease_fd=lease_fd)


def _run_cycle(splits, output, *, steps, batch_size, device, timeout, lease_fd):
    splits = Path(splits).resolve()
    output = native._new_output(output, splits)
    if (type(steps) is not int or steps < 1 or type(batch_size) is not int or batch_size < 1
            or device not in ('cpu', 'cuda') or type(timeout) not in (int, float) or not 0 < timeout <= 86400):
        raise ValueError('explicit positive training budgets and cpu/cuda device are required')
    receipt = validate_split(splits)
    receipt_hash = hashlib.sha256((splits / 'split-receipt.json').read_bytes()).hexdigest()
    # Verify actual train/eval readers before starting any training process. Final test remains sealed.
    for name in ('train', 'eval'):
        data = native.load_dataset(splits / name, receipt['source']['repo_id'] + '_' + name)
        native.inspect_frames(data.meta.info, (data[i] for i in range(len(data))))
    train_info = json.loads((splits / 'train/meta/info.json').read_text())
    config = json.loads(Path(__file__).with_name('native-act.example.json').read_text())
    config['dataset'].update(root=str(splits / 'train'), repo_id=receipt['source']['repo_id'] + '_train')
    config['policy']['device'] = device
    config.update(output_dir=str(output / 'trainer'), steps=steps, save_freq=steps,
                  batch_size=min(batch_size, train_info['total_frames']), log_freq=1)
    output.mkdir()
    native.write_json(output / 'train-config.json', config)
    environment = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
                   'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
    try:
        native.write_json(output / 'environment.json', dict(
            python=sys.version, packages={name: importlib.metadata.version(name)
                                         for name in ('lerobot', 'torch', 'torchvision', 'av', 'datasets')}))
        _invoke([sys.executable, '-m', 'lerobot.scripts.lerobot_train',
                 f'--config_path={output / "train-config.json"}'],
                output / 'train.log', environment, timeout, lease_fd=lease_fd)
        model = (output / 'trainer/checkpoints/last/pretrained_model').resolve()
        if not model.is_relative_to(output):
            raise ValueError('trainer model resolved outside the new run')
        before = _artifact_files(model)
        _invoke([sys.executable, str(Path(__file__).resolve()), 'verify', '--model', str(model),
                 '--splits', str(splits), '--repo-id', receipt['source']['repo_id'],
                 '--out', str(output / 'evaluation.json')], output / 'reload.log', environment, timeout,
                lease_fd=lease_fd)
        if (validate_split(splits) != receipt
                or hashlib.sha256((splits / 'split-receipt.json').read_bytes()).hexdigest() != receipt_hash
                or _artifact_files(model) != before):
            raise ValueError('split inputs or model bytes changed during training/evaluation')
        result = dict(offline_only=True, source_mode=receipt['source']['source_mode'],
                      split_receipt_sha256=receipt_hash, split_files=receipt['outputs'], artifact_files=before,
                      policy_revision=policy_revision(before), rig_revision=receipt['source']['rig_revision'],
                      calibration_revision=receipt['source']['calibration_revision'],
                      evaluation=json.loads((output / 'evaluation.json').read_text()),
                      body_units=receipt['source']['body_units'], gripper_units='normalized_0_100',
                      environment_summary=native.validate_environment(receipt['source']),
                      environment_coverage=native.split_coverage(
                          native.validate_environment(receipt['source']), receipt['decisions']),
                      device_execution=False, promotion=False)
        native.write_json(output / 'cycle-receipt.json', result)
        return result
    except Exception as exc:
        native.write_json(output / 'failed.json', dict(error=f'{type(exc).__name__}: {exc}', offline_only=True))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run')
    run.add_argument('--splits', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--steps', type=int, default=100)
    run.add_argument('--batch-size', type=int, default=8)
    run.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    verify = commands.add_parser('verify')
    verify.add_argument('--model', type=Path, required=True)
    verify.add_argument('--splits', type=Path, required=True)
    verify.add_argument('--repo-id', required=True)
    verify.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'run':
            run_cycle(args.splits, args.out, steps=args.steps, batch_size=args.batch_size, device=args.device)
        else:
            _evaluate(args.model, args.splits, args.repo_id, args.out)
    except (ValueError, OSError, ImportError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'refused: {exc}\n')


if __name__ == '__main__':
    main()
