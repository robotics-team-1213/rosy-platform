"""CUDA OMX ACT preflight, bounded HTTP bundle manifest, and offline lerobot_train worker."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from experiment_io import identifier, read_json, write_json
from experiment_jobs import launch
from experiment_process import process_stamp
from experiment_train import GpuBusy, gpu_lease

SCHEMA = 'rosy.omx.cuda-train-request/1'
MANIFEST_SCHEMA = 'rosy.omx.bundle-manifest/1'
MANIFEST_LIMIT = 65536
FILE_LIMIT = 256 * 1024 * 1024
PREFIX = '/api/learning/omx/center'

_REQUIRED = {'request_id', 'dataset_root', 'arm_id', 'steps', 'batch_size', 'seed'}
_OPTIONAL = {
    'save_freq', 'log_freq', 'chunk_size', 'n_action_steps', 'use_vae',
    'kl_weight', 'optimizer_lr', 'optimizer_lr_backbone', 'resume',
    'output_dir', 'data_gate_receipt',
}
_INT_RANGES = {
    'steps': (1, 200000), 'batch_size': (1, 64), 'seed': (0, 2147483647),
    'save_freq': (1, 200000), 'log_freq': (1, 10000),
    'chunk_size': (1, 100), 'n_action_steps': (1, 100),
}
_FLOAT_RANGES = {
    'kl_weight': (0.0, 1000.0), 'optimizer_lr': (1e-7, 1e-1), 'optimizer_lr_backbone': (1e-7, 1e-1),
}
_SEGMENT_RE = re.compile(r'[A-Za-z0-9_.-]+')
_LOCK_PID_RE = re.compile(r'^(?:train|gpu)-(\d+)\.lock$')


def _safe_abs_path(value, label, center_root):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(ord(c) < 32 for c in value):
        raise ValueError(f'bounded path string required: {label}')
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f'non-symlink absolute path required: {label}')
    resolved = path.resolve()
    center_resolved = Path(center_root).resolve()
    if resolved.is_relative_to(center_resolved) or center_resolved.is_relative_to(resolved):
        raise ValueError(f'external path must stay separate from learning center: {label}')
    return resolved


def _valid_relpath(relpath):
    if (not isinstance(relpath, str) or not 1 <= len(relpath) <= 256
            or '\\' in relpath or '%' in relpath or relpath.startswith('/') or relpath.endswith('/')):
        raise ValueError('invalid bundle file path')
    parts = relpath.split('/')
    for part in parts:
        if not _SEGMENT_RE.fullmatch(part) or part in ('.', '..', '__pycache__'):
            raise ValueError('invalid bundle file path segment')
    return parts


def _file_sha256(path):
    if path.stat().st_size > FILE_LIMIT:
        raise ValueError('bundle file exceeds size limit')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _resolve_resume_config(train_dir):
    resolved_train = train_dir.resolve()
    for candidate in (train_dir / 'checkpoints' / 'last' / 'pretrained_model' / 'train_config.json',
                      train_dir / 'train_config.json'):
        if candidate.is_file():
            resolved = candidate.resolve()
            if not resolved.is_relative_to(resolved_train):
                raise ValueError('resume train_config.json escaped training directory')
            return resolved
    raise ValueError('resume=True requires existing train_config.json')


def check_cuda_request(body, center_root):
    if not isinstance(body, dict) or not _REQUIRED <= body.keys() or set(body) - _REQUIRED - _OPTIONAL:
        raise ValueError('CUDA training request fields differ from schema')
    spec = {
        'request_id': identifier(body['request_id']),
        'dataset_root': str(_safe_abs_path(body['dataset_root'], 'dataset_root', center_root)),
        'arm_id': body['arm_id'],
    }
    if spec['arm_id'] not in ('arm_a', 'arm_b'):
        raise ValueError('explicit arm_id (arm_a or arm_b) required')
    for key in ('output_dir', 'data_gate_receipt'):
        if key in body:
            spec[key] = str(_safe_abs_path(body[key], key, center_root))
    for key, (low, high) in _INT_RANGES.items():
        if key not in body:
            continue
        val = body[key]
        if type(val) is not int or not low <= val <= high:
            raise ValueError(f'CUDA training integer outside allowed range: {key}')
        spec[key] = val
    for key, (low, high) in _FLOAT_RANGES.items():
        if key not in body:
            continue
        val = body[key]
        if type(val) not in (int, float) or not math.isfinite(val) or not low <= float(val) <= high:
            raise ValueError(f'CUDA training number outside allowed range: {key}')
        spec[key] = float(val)
    for key, default in (('use_vae', True), ('resume', False)):
        val = body.get(key, default)
        if type(val) is not bool:
            raise ValueError(f'boolean required: {key}')
        spec[key] = val
    spec.setdefault('save_freq', min(spec['steps'], 4000))
    spec.setdefault('log_freq', 200)
    spec.setdefault('chunk_size', 16)
    spec.setdefault('n_action_steps', min(8, spec['chunk_size']))
    if spec['n_action_steps'] > spec['chunk_size']:
        raise ValueError('n_action_steps cannot exceed chunk_size')
    spec.setdefault('kl_weight', 10.0)
    spec.setdefault('optimizer_lr', 1e-4)
    spec.setdefault('optimizer_lr_backbone', 1e-5)
    return spec


def _pid_alive(pid):
    if type(pid) is not int or pid <= 0 or os.name != 'posix':
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def check_job_locks(jobs_dir):
    stale = []
    if not jobs_dir.is_dir():
        return stale
    for entry in sorted(jobs_dir.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            continue
        if not (entry.name.startswith('train-') or entry.name.startswith('gpu')) or not entry.name.endswith('.lock'):
            continue
        pid = None
        match = _LOCK_PID_RE.fullmatch(entry.name)
        if match:
            pid = int(match[1])
        else:
            raw = entry.read_bytes()[:4096].decode('utf-8', errors='replace').strip().split()
            if raw and raw[0].isdigit():
                pid = int(raw[0])
        if pid is not None and _pid_alive(pid):
            raise ValueError(f'active GPU training lock held by pid {pid}: {entry.name}')
        stale.append(entry.name)
    return stale


def preflight_cuda(spec, train_dir, *, jobs_dir=None, check_gpu=True):
    dataset_root = Path(spec['dataset_root'])
    if dataset_root.is_symlink() or not dataset_root.is_dir():
        raise ValueError('regular dataset directory required')
    info = read_json(dataset_root / 'meta' / 'info.json')
    if (not isinstance(info, dict) or type(info.get('total_episodes')) is not int
            or type(info.get('total_frames')) is not int
            or info['total_episodes'] < 1 or info['total_frames'] < 1):
        raise ValueError('dataset meta/info.json must report positive episodes and frames')
    receipt = Path(spec['data_gate_receipt']) if 'data_gate_receipt' in spec else (dataset_root / 'gate-receipt.json')
    if 'data_gate_receipt' in spec:
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError('data gate receipt file missing')
        gate = read_json(receipt)
    elif receipt.exists() or receipt.is_symlink():
        gate = read_json(receipt)
    else:
        gate = None
    if gate is not None:
        counts = gate.get('counts', gate) if isinstance(gate, dict) else None
        if (not isinstance(counts, dict) or type(counts.get('reject')) is not int
                or type(counts.get('review')) is not int
                or counts['reject'] != 0 or counts['review'] != 0):
            raise ValueError('data gate receipt has unaccepted episodes')
    resolved_train = train_dir.resolve()
    resolved_dataset = dataset_root.resolve()
    if (resolved_train == resolved_dataset or resolved_train.is_relative_to(resolved_dataset)
            or resolved_dataset.is_relative_to(resolved_train)
            or any((parent / '.git').exists() for parent in (resolved_train, *resolved_train.parents))):
        raise ValueError('training output_dir must be separate from dataset and git checkouts')
    if not spec['resume']:
        if train_dir.exists() or train_dir.is_symlink():
            raise ValueError('output_dir already exists with resume=False')
    else:
        if train_dir.is_symlink() or not train_dir.is_dir():
            raise ValueError('resume=True requires existing training output_dir')
        _resolve_resume_config(train_dir)
    stale = check_job_locks(Path.home() / 'rosy-jobs' if jobs_dir is None else Path(jobs_dir))
    if check_gpu and os.name == 'posix':
        try:
            with gpu_lease('cuda'):
                pass
        except GpuBusy as exc:
            raise ValueError(str(exc)) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('CUDA GPU probe failed') from exc
    return {'total_episodes': info['total_episodes'], 'total_frames': info['total_frames'], 'stale_locks': stale}


def start_cuda(center, body, *, jobs_dir=None, check_gpu=True):
    spec = check_cuda_request(body, center.root)
    request = json.dumps(dict(spec, execution_mode='omx_cuda_train'), sort_keys=True)
    with center.lock, center.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        center._refresh(db)
        old = db.execute('SELECT document,request FROM runs WHERE request_id=?', (spec['request_id'],)).fetchone()
        if old:
            if old[1] != request:
                raise ValueError('request identity already used with different inputs')
            return json.loads(old[0])
        act = center.methods.get('act', {})
        if not act.get('available') or 'cuda' not in act.get('devices', ()):
            raise ValueError('CUDA learner environment unavailable')
        if any(json.loads(r[0])['status'] in ('launching', 'running', 'stopping')
               for r in db.execute('SELECT document FROM runs')):
            raise ValueError('one owned learning job may run at a time')
        rid = str(uuid.uuid4())
        root = center.root / 'runs' / rid
        train_dir = Path(spec['output_dir']) if 'output_dir' in spec else (root / 'output' / 'train')
        preflight = preflight_cuda(spec, train_dir, jobs_dir=jobs_dir, check_gpu=check_gpu)
        root.mkdir()
        write_json(root / 'request.json', dict(spec, schema=SCHEMA, train_dir=str(train_dir)))
        row = {
            'id': rid, 'status': 'launching', 'created_at': time.time(),
            'method': 'act', 'device': 'cuda', 'execution_mode': 'omx_cuda_train',
            'arm_id': spec['arm_id'], 'steps': spec['steps'], 'batch_size': spec['batch_size'],
            'seed': spec['seed'], 'resume': spec['resume'], 'train_dir': str(train_dir),
            'preflight': preflight,
        }
        return launch(center, db, spec['request_id'], request, row, process_stamp)


def resolve_bundle_dir(run_root, row):
    if row.get('status') != 'succeeded':
        raise ValueError('completed learning run required')
    result = row.get('result') or {}
    out_dir = (run_root / 'output').resolve()
    candidate = None
    if result.get('checkpoint_relpath'):
        rel = Path(result['checkpoint_relpath'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('invalid checkpoint relative path')
        candidate = (out_dir / rel).resolve()
        if not candidate.is_relative_to(out_dir):
            raise ValueError('checkpoint escaped run output directory')
    elif result.get('checkpoint_dir') and row.get('train_dir'):
        allowed = Path(row['train_dir']).resolve()
        candidate = Path(result['checkpoint_dir']).resolve()
        if not candidate.is_relative_to(allowed):
            raise ValueError('checkpoint escaped declared training directory')
    elif (out_dir / 'policy').is_dir() and not (out_dir / 'policy').is_symlink():
        candidate = (out_dir / 'policy').resolve()
    elif (out_dir / 'trainer/checkpoints/last/pretrained_model').exists():
        candidate = (out_dir / 'trainer/checkpoints/last/pretrained_model').resolve()
        if not candidate.is_relative_to(out_dir):
            raise ValueError('checkpoint escaped run output directory')
    if candidate is None or not candidate.is_dir():
        raise ValueError('completed model bundle directory missing')
    weights = candidate / 'model.safetensors'
    if weights.is_symlink() or not weights.is_file():
        raise ValueError('regular model.safetensors required')
    digest = _file_sha256(weights)
    expected = result.get('policy_sha256')
    if expected is None and isinstance(result.get('artifact_files'), dict):
        expected = result['artifact_files'].get('model.safetensors')
    if expected is not None and digest != expected:
        raise ValueError('completed model weights changed')
    return candidate, digest


def bundle_manifest(run_root, rid, row, *, prefix=PREFIX):
    identifier(rid)
    bundle_dir, policy_sha256 = resolve_bundle_dir(run_root, row)
    entries = []
    for path in bundle_dir.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'symlink forbidden in bundle: {path.name}')
        rel_parts = path.relative_to(bundle_dir).parts
        if not path.is_file() or '__pycache__' in rel_parts or '.cache' in rel_parts:
            continue
        rel = '/'.join(rel_parts)
        _valid_relpath(rel)
        entries.append((rel, path))
    files, bundle_digest = [], hashlib.sha256()
    for rel, path in sorted(entries, key=lambda item: item[0]):
        size = path.stat().st_size
        digest = _file_sha256(path)
        bundle_digest.update(rel.encode() + b'\0')
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                bundle_digest.update(block)
        files.append({'path': rel, 'size': size, 'sha256': digest, 'url': f'{prefix}/run/{rid}/file/{rel}'})
    manifest = {
        'schema': MANIFEST_SCHEMA, 'run_id': rid,
        'policy_revision': policy_sha256, 'checkpoint_sha256': bundle_digest.hexdigest(),
        'files': files,
    }
    if len(json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MANIFEST_LIMIT:
        raise ValueError('bundle manifest exceeds 64 KiB')
    return manifest


def bundle_file(run_root, row, relpath):
    parts = _valid_relpath(relpath)
    bundle_dir, _ = resolve_bundle_dir(run_root, row)
    bundle_resolved = bundle_dir.resolve()
    cur = bundle_dir
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError('symlink forbidden in bundle')
    resolved = cur.resolve()
    if not resolved.is_relative_to(bundle_resolved) or not resolved.is_file():
        raise ValueError('bundle file missing')
    if resolved.stat().st_size > FILE_LIMIT:
        raise ValueError('bundle file exceeds size limit')
    return resolved.read_bytes()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        request = read_json(args.request)
        if request.get('schema') != SCHEMA:
            raise ValueError('unsupported CUDA training request schema')
        train_dir = Path(request['train_dir'])
        preflight_cuda(request, train_dir, check_gpu=False)
        if request['resume']:
            cfg = _resolve_resume_config(train_dir)
            cmd = [sys.executable, '-m', 'lerobot.scripts.lerobot_train', f'--config_path={cfg}', '--resume=true']
        else:
            cmd = [
                sys.executable, '-m', 'lerobot.scripts.lerobot_train',
                '--dataset.repo_id=local/omx',
                f"--dataset.root={request['dataset_root']}",
                '--policy.type=act', '--policy.device=cuda', '--policy.push_to_hub=false',
                f"--policy.chunk_size={request['chunk_size']}",
                f"--policy.n_action_steps={request['n_action_steps']}",
                f"--policy.use_vae={'true' if request['use_vae'] else 'false'}",
                f"--policy.kl_weight={request['kl_weight']}",
                f"--policy.optimizer_lr={request['optimizer_lr']}",
                f"--policy.optimizer_lr_backbone={request['optimizer_lr_backbone']}",
                f'--output_dir={train_dir}',
                f"--steps={request['steps']}",
                f"--batch_size={request['batch_size']}",
                f"--save_freq={request['save_freq']}",
                f"--log_freq={request['log_freq']}",
                f"--seed={request['seed']}",
            ]
        env = dict(os.environ, HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        with gpu_lease('cuda'):
            proc = subprocess.run(cmd, env=env, check=False)
        if proc.returncode:
            write_json(args.out / 'error.json', {
                'status': 'failed', 'returncode': proc.returncode,
                'error': f'lerobot_train exited with code {proc.returncode}',
            })
            return proc.returncode
        resolved_train = train_dir.resolve()
        model_dir = (train_dir / 'checkpoints' / 'last' / 'pretrained_model').resolve()
        if not model_dir.is_relative_to(resolved_train):
            raise ValueError('trained checkpoint escaped training directory')
        digest = _file_sha256(model_dir / 'model.safetensors')
        result = {
            'execution_mode': 'omx_cuda_train',
            'physical_learning_verified': False,
            'policy_activation': False,
            'policy_sha256': digest,
            'checkpoint_dir': str(model_dir),
            'steps': request['steps'],
        }
        out_resolved = args.out.resolve()
        if model_dir.is_relative_to(out_resolved):
            result['checkpoint_relpath'] = model_dir.relative_to(out_resolved).as_posix()
        write_json(args.out / 'result.json', result)
        return 0
    except Exception as exc:
        write_json(args.out / 'error.json', {'status': 'failed', 'error': str(exc)[:240]})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
