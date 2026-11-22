"""Download completed artifacts and package self-validated cell ACT bundles."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from experiment_jobs import check_learning_task  # noqa: E402
from rosy.contracts.learning.digest import checkpoint_sha256  # noqa: E402

CELL_CAMERA_ROLES = ('top', 'side', 'wrist')
_VIEW_RE = re.compile(r'[A-Za-z0-9_.-]+')
_IMAGE_PREFIX = 'observation.images.'


def version_root(root, row):
    value = row.get('progress', {}).get('latest_version')
    if not str(value).isdigit() or not 1 <= int(value) <= 999999:
        raise ValueError('completed continuous policy version required')
    return root / 'versions' / f'{int(value):06}'


def model_archive(root, result, learning_task=None):
    names = ['normalization.json', 'profile.json', 'request.json', 'result.json',
             'evaluation.json', 'policy/config.json', 'policy/model.safetensors']
    if any((root / name).is_symlink() or not (root / name).is_file() for name in names):
        raise ValueError('regular model artifact files required')
    if sum((root / name).stat().st_size for name in names) > 256 * 1024 * 1024:
        raise ValueError('model archive exceeds 256 MiB')
    files = {name: (root / name).read_bytes() for name in names}
    if hashlib.sha256(files['policy/model.safetensors']).hexdigest() != result['policy_sha256']:
        raise ValueError('completed model weights changed')
    if learning_task is not None:
        check_learning_task(learning_task)
        if result.get('learning_task') != learning_task:
            raise ValueError('completed result task lineage differs from run')
        for name in ('request.json', 'result.json', 'evaluation.json'):
            if json.loads(files[name]).get('learning_task') != learning_task:
                raise ValueError('model artifact task lineage differs from run')
        if (json.loads(files['result.json']) != result
                or not isinstance(result.get('evaluation'), dict)
                or json.loads(files['evaluation.json']) != result['evaluation']):
            raise ValueError('completed task evaluation differs from stored result')
        files['learning-task.json'] = json.dumps(dict(learning_task=learning_task,
            evaluation_sha256=hashlib.sha256(files['evaluation.json']).hexdigest()),
            ensure_ascii=False, allow_nan=False).encode('utf-8')
    elif result.get('learning_task') is not None or any(
            json.loads(files[name]).get('learning_task') is not None
            for name in ('request.json', 'result.json', 'evaluation.json')):
        raise ValueError('task lineage requires a task-bound learning run')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def _rename_image_key(key, pairs):
    if key.startswith(_IMAGE_PREFIX):
        rest = key[len(_IMAGE_PREFIX):]
        head, sep, tail = rest.partition('.')
        if head in pairs:
            return f'{_IMAGE_PREFIX}{pairs[head]}{sep}{tail}'
    return key


def _rewrite_json_obj(obj, pairs, target_device):
    if isinstance(obj, list):
        return [_rewrite_json_obj(item, pairs, target_device) for item in obj]
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            new_key = _rename_image_key(key, pairs) if isinstance(key, str) else key
            if new_key in out:
                raise ValueError(f'duplicate JSON key after view rename: {new_key}')
            if key == 'device' and isinstance(val, str) and (val in ('cpu', 'mps') or val == 'cuda' or val.startswith('cuda:')):
                out[new_key] = target_device
            else:
                out[new_key] = _rewrite_json_obj(val, pairs, target_device)
        return out
    if isinstance(obj, str) and pairs:
        return _rename_image_key(obj, pairs)
    return obj


def _validate_cell_config(config):
    if not isinstance(config, dict) or config.get('type') != 'act':
        raise ValueError('only LeRobot ACT checkpoint supported in cell bundle')
    features, outputs = config.get('input_features'), config.get('output_features')
    if not isinstance(features, dict) or not isinstance(outputs, dict):
        raise ValueError('checkpoint features and outputs must be mappings')
    state_spec, action_spec = features.get('observation.state'), outputs.get('action')
    if not isinstance(state_spec, dict) or state_spec.get('shape') != [6]:
        raise ValueError('checkpoint observation.state must have shape [6]')
    if not isinstance(action_spec, dict) or action_spec.get('shape') != [6]:
        raise ValueError('checkpoint action must have shape [6]')
    views = []
    for key, spec in features.items():
        if not key.startswith(_IMAGE_PREFIX):
            continue
        role = key[len(_IMAGE_PREFIX):]
        shape = spec.get('shape') if isinstance(spec, dict) else None
        if (not isinstance(shape, list) or len(shape) != 3 or shape[0] != 3
                or any(type(v) is not int or v < 1 for v in shape[1:])):
            raise ValueError(f'{key} must have shape [3, H, W]')
        if role not in CELL_CAMERA_ROLES:
            raise ValueError(f'camera view {role!r} is not in cell roles {CELL_CAMERA_ROLES}')
        views.append(role)
    if not views:
        raise ValueError('cell bundle requires at least one camera input')
    return sorted(views)


def package_cell_bundle(src_dir, dst_dir, *, arm_id, rename_views=None, target_device='cpu'):
    """Rewrite camera roles/device into a self-validated, symlink-free cell bundle directory."""
    if arm_id not in ('arm_a', 'arm_b'):
        raise ValueError('explicit arm_id (arm_a or arm_b) required')
    if target_device not in ('cpu', 'cuda'):
        raise ValueError("target_device must be 'cpu' or 'cuda'")
    pairs = {} if rename_views is None else dict(rename_views)
    for src_name, dst_name in pairs.items():
        if (not isinstance(src_name, str) or not isinstance(dst_name, str)
                or not _VIEW_RE.fullmatch(src_name) or not _VIEW_RE.fullmatch(dst_name)):
            raise ValueError('valid non-empty camera view names required')
    if len(set(pairs.values())) != len(pairs):
        raise ValueError('duplicate target camera view in rename_views')
    src = Path(src_dir)
    if src.is_symlink() or not src.is_dir():
        raise ValueError('source checkpoint must be a regular directory')
    src_res = src.resolve(strict=True)
    dst = Path(dst_dir)
    if dst.exists() or dst.is_symlink():
        raise ValueError('destination bundle path already exists')
    dst_res = dst.resolve()
    if dst_res.exists() or dst_res == src_res or dst_res.is_relative_to(src_res) or src_res.is_relative_to(dst_res):
        raise ValueError('destination bundle path conflicts with source or existing path')
    if not (src / 'config.json').is_file() or not (src / 'model.safetensors').is_file():
        raise ValueError('source checkpoint requires config.json and model.safetensors')
    if any(p.is_symlink() for p in src.rglob('*')):
        raise ValueError('symlink forbidden in source checkpoint')

    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.parent / f'.{dst.name}.partial.{os.getpid()}'
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    try:
        final_config = None
        for path in sorted(src.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            rel = path.relative_to(src)
            if rel.as_posix() in ('UNITS.json', 'VIEW_NAMES.json'):
                continue
            out_path = partial / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            name = path.name
            if name == 'config.json' or (
                    name.endswith('.json') and ('preprocessor' in name or 'postprocessor' in name)):
                obj = _rewrite_json_obj(json.loads(path.read_text(encoding='utf-8')), pairs, target_device)
                if rel.as_posix() == 'config.json':
                    final_config = obj
                out_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            elif name != 'model.safetensors' and name.endswith('.safetensors') and pairs:
                from safetensors.numpy import load_file, save_file

                tensors = load_file(str(path))
                renamed = {}
                for tkey, tensor in tensors.items():
                    new_tkey = _rename_image_key(tkey, pairs)
                    if new_tkey in renamed:
                        raise ValueError(f'duplicate tensor key after view rename: {new_tkey}')
                    renamed[new_tkey] = tensor
                save_file(renamed, str(out_path))
            else:
                shutil.copyfile(path, out_path)

        views = _validate_cell_config(final_config)
        (partial / 'UNITS.json').write_text(
            json.dumps({'state': 'sim_rad', 'gripper': 'sim_jaw', 'arm': arm_id}, indent=2) + '\n',
            encoding='utf-8',
        )
        (partial / 'VIEW_NAMES.json').write_text(
            json.dumps({'pairs': pairs}, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
        files = {
            p.relative_to(partial).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(partial.rglob('*')) if p.is_file()
        }
        policy_revision = files['model.safetensors']
        ckpt_sha = checkpoint_sha256(partial, allow_symlinks=False)
        partial.rename(dst)
        return {
            'bundle_dir': str(dst), 'arm_id': arm_id, 'views': views,
            'policy_revision': policy_revision, 'checkpoint_sha256': ckpt_sha, 'files': files,
        }
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def _check_regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular file required: {path.name}')
    return path


def export_cell_onnx(bundle_dir, *, opset=17, parity_tol=1e-4):
    """Atomically export model.onnx (opset 17) + ONNX_EXPORT.json for a validated cell bundle."""
    import importlib.util
    import sys

    dst = Path(bundle_dir)
    if dst.is_symlink() or not dst.is_dir():
        raise ValueError('bundle directory must be a regular directory')
    if any(p.is_symlink() for p in dst.rglob('*')):
        raise ValueError('symlink forbidden in cell bundle')

    config_path = _check_regular_file(dst / 'config.json')
    weights_path = _check_regular_file(dst / 'model.safetensors')

    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config.get('type') != 'act':
        raise ValueError(f"unsupported policy type {config.get('type')!r}: only ACT ONNX export is supported")
    _validate_cell_config(config)
    _check_regular_file(dst / 'policy_preprocessor.json')
    _check_regular_file(dst / 'policy_postprocessor.json')

    with weights_path.open('rb') as stream:
        policy_revision = hashlib.file_digest(stream, 'sha256').hexdigest()

    import onnx
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy

    prev_hub_offline = os.environ.get('HF_HUB_OFFLINE')
    os.environ['HF_HUB_OFFLINE'] = '1'
    try:
        policy = ACTPolicy.from_pretrained(str(dst), local_files_only=True)
    finally:
        if prev_hub_offline is None:
            os.environ.pop('HF_HUB_OFFLINE', None)
        else:
            os.environ['HF_HUB_OFFLINE'] = prev_hub_offline
    policy.config.device = 'cpu'
    policy.to('cpu').eval()

    input_features = dict(policy.config.input_features)
    image_keys = list(policy.config.image_features)
    input_names = ['observation.state']
    if 'observation.environment_state' in input_features:
        input_names.append('observation.environment_state')
    for key in image_keys:
        if key not in input_names:
            input_names.append(key)

    class _OnnxChunkWrapper(torch.nn.Module):
        def __init__(self, act_policy, names, imgs):
            super().__init__()
            self.act_policy = act_policy
            self.names = list(names)
            self.imgs = list(imgs)

        def forward(self, *tensors):
            batch = dict(zip(self.names, tensors))
            if self.imgs:
                batch['observation.images'] = [batch[key] for key in self.imgs]
            return self.act_policy.model(batch)[0]

    gen = torch.Generator().manual_seed(0)
    inputs = {
        name: torch.randn((1, *input_features[name].shape), generator=gen, dtype=torch.float32)
        for name in input_names
    }
    wrapper = _OnnxChunkWrapper(policy, input_names, image_keys).eval()

    tag = f'{os.getpid()}.{secrets.token_hex(4)}'
    partial_onnx = dst / f'.model.onnx.{tag}'
    partial_meta = dst / f'.ONNX_EXPORT.json.{tag}'
    try:
        with torch.no_grad():
            torch_out = wrapper(*(inputs[name].clone() for name in input_names)).detach().cpu().numpy()
            torch.onnx.export(
                wrapper,
                tuple(inputs[name].clone() for name in input_names),
                str(partial_onnx),
                input_names=input_names,
                output_names=['action'],
                opset_version=int(opset),
                dynamo=False,
                do_constant_folding=True,
            )
        external_data = partial_onnx.with_name(f'{partial_onnx.name}.data')
        if external_data.exists():
            external_data.unlink(missing_ok=True)
            raise ValueError('ONNX export unexpectedly emitted external weight data')

        onnx.checker.check_model(str(partial_onnx), full_check=True)

        ov_parity_diff = None
        if 'openvino' in sys.modules or importlib.util.find_spec('openvino') is not None:
            import numpy as np
            import openvino as ov

            core = ov.Core()
            compiled = core.compile_model(str(partial_onnx), 'CPU', {'PERFORMANCE_HINT': 'LATENCY'})
            feed = {name: np.ascontiguousarray(inputs[name].numpy(), dtype=np.float32) for name in input_names}
            ov_out = np.asarray(compiled(feed)[compiled.output(0)], dtype=np.float32)
            ov_parity_diff = float(np.max(np.abs(ov_out - torch_out)))
            if not np.isfinite(ov_parity_diff) or ov_parity_diff > parity_tol:
                raise ValueError(f'OpenVINO ONNX parity {ov_parity_diff:.6g} exceeds tolerance {parity_tol}')

        with partial_onnx.open('rb') as stream:
            onnx_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()

        meta = {
            'schema': 'rosy.omx-onnx-export.v1',
            'policy_revision': policy_revision,
            'onnx_sha256': onnx_sha256,
            'opset': int(opset),
            'inputs': {name: list(inputs[name].shape) for name in input_names},
            'output_name': 'action',
            'output_shape': list(torch_out.shape),
            'torch_version': torch.__version__,
            'onnx_checker': True,
            'openvino_parity_max_abs_diff': ov_parity_diff,
        }
        partial_meta.write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
        partial_onnx.replace(dst / 'model.onnx')
        partial_meta.replace(dst / 'ONNX_EXPORT.json')
        return meta
    except Exception:
        partial_onnx.unlink(missing_ok=True)
        partial_meta.unlink(missing_ok=True)
        partial_onnx.with_name(f'{partial_onnx.name}.data').unlink(missing_ok=True)
        raise
