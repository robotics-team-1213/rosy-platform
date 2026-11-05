"""Snapshot installed SmolVLA inputs and seal portable offline training outputs."""
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'contracts/learning/src'))
from rosy.contracts.learning import policy_assets as assets


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def _tokenizer(path, name):
    value = json.loads(path.read_text(encoding='utf-8'))
    steps = [step for step in value['steps'] if step.get('registry_name') == 'tokenizer_processor']
    if len(steps) != 1:
        raise ValueError('exactly one saved SmolVLA tokenizer processor is required')
    steps[0]['config']['tokenizer_name'] = name
    _write(path, value)


def _snapshot(source, output, names):
    output.mkdir()
    original = {}
    for name in sorted(names):
        path = source/name
        original[name] = assets.file_hash(path)
        shutil.copyfile(path, output/name)
        if assets.file_hash(output/name) != original[name] or assets.file_hash(path) != original[name]:
            raise ValueError('model input changed while it was being snapshotted')
    return original


def input_files(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('linked training input snapshot')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = assets.file_hash(path)
    return result


def prepare(base_model, vlm_assets, output, *, device):
    if not base_model or not vlm_assets or device not in ('cpu', 'cuda'):
        raise ValueError('explicit local base policy, VLM metadata and cpu/cuda device are required')
    base, vlm, output = Path(base_model), Path(vlm_assets), Path(output)
    if not base.is_dir() or not vlm.is_dir() or output.exists():
        raise ValueError('installed local model inputs and a new snapshot directory are required')
    policy = json.loads((base/'config.json').read_text(encoding='utf-8'))
    if policy.get('type') != 'smolvla':
        raise ValueError('the base checkpoint must declare smolvla')
    base_names = {'config.json', 'model.safetensors', 'policy_preprocessor.json', 'policy_postprocessor.json'}
    for name in ('policy_preprocessor.json', 'policy_postprocessor.json'):
        saved = json.loads((base/name).read_text(encoding='utf-8'))
        for step in saved['steps']:
            state = step.get('state_file')
            if state:
                if not isinstance(state, str) or Path(state).name != state or not state.endswith('.safetensors'):
                    raise ValueError('saved processor state must be a local safetensors filename')
                base_names.add(state)
    vlm_names = {name for name in assets.VLM_FILES if (vlm/name).is_file()}
    if not assets.REQUIRED <= vlm_names or not all((base/name).is_file() for name in base_names):
        raise ValueError('missing installed policy weights, processors or VLM metadata')
    output.mkdir()
    source = dict(base=_snapshot(base, output/'base', base_names),
                  vlm=_snapshot(vlm, output/'vlm', vlm_names))
    assets.vlm_files(output/'vlm')
    _tokenizer(output/'base/policy_preprocessor.json', str(output/'vlm'))
    policy.update(device=device, pretrained_path=str(output/'base'), vlm_model_name=str(output/'vlm'),
                  load_vlm_weights=False, input_features={}, output_features={}, n_action_steps=1,
                  push_to_hub=False, use_amp=device == 'cuda')
    return dict(policy=policy, source_files=source, input_files=input_files(output))


def seal(model, vlm_assets):
    model, vlm_assets = Path(model), Path(vlm_assets)
    before = assets.vlm_files(vlm_assets)
    shutil.copytree(vlm_assets, model/'vlm')
    if assets.vlm_files(model/'vlm') != before or assets.vlm_files(vlm_assets) != before:
        raise ValueError('VLM metadata changed while sealing the model')
    config = json.loads((model/'config.json').read_text(encoding='utf-8'))
    if config.get('type') != 'smolvla':
        raise ValueError('only SmolVLA outputs can be sealed with VLM metadata')
    config.update(vlm_model_name=assets.MARKER, load_vlm_weights=False, pretrained_path=None)
    _write(model/'config.json', config)
    _tokenizer(model/'policy_preprocessor.json', assets.MARKER)
    _write(model/'rosy-smolvla-assets.json', dict(schema=assets.SCHEMA, files=before))
