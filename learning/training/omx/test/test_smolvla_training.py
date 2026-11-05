"""Offline source snapshots, portable artifacts, and explicit model identities."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


def training_module():
    path = Path(__file__).resolve().parents[1]/'smolvla_training.py'
    assert path.is_file(), 'reviewed SmolVLA training support is required'
    spec = importlib.util.spec_from_file_location('smolvla_training_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources(root):
    base, vlm = root/'base', root/'vlm'
    base.mkdir()
    vlm.mkdir()
    (base/'config.json').write_text(json.dumps(dict(type='smolvla', input_features={'old_camera': {}},
        output_features={}, max_state_dim=32, max_action_dim=32, chunk_size=50)))
    (base/'model.safetensors').write_bytes(b'synthetic weights, not a trained model')
    pre = dict(steps=[dict(registry_name='tokenizer_processor', config=dict(tokenizer_name='external/model'))])
    (base/'policy_preprocessor.json').write_text(json.dumps(pre))
    (base/'policy_postprocessor.json').write_text(json.dumps(dict(steps=[])))
    for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json'):
        (vlm/name).write_text(json.dumps({'synthetic': name}))
    return base, vlm


def test_preparation_snapshots_explicit_local_sources_and_resets_dataset_features(tmp_path):
    module = training_module()
    base, vlm = sources(tmp_path)
    prepared = module.prepare(base, vlm, tmp_path/'inputs', device='cpu')
    policy = prepared['policy']
    assert policy['type'] == 'smolvla' and policy['device'] == 'cpu'
    assert policy['pretrained_path'] == str(tmp_path/'inputs/base')
    assert policy['vlm_model_name'] == str(tmp_path/'inputs/vlm')
    assert policy['input_features'] == {} and policy['output_features'] == {}
    assert policy['n_action_steps'] == 1 and policy['load_vlm_weights'] is False
    assert policy['push_to_hub'] is False
    assert module.input_files(tmp_path/'inputs') == prepared['input_files']
    assert (tmp_path/'inputs/base/model.safetensors').read_bytes() == (base/'model.safetensors').read_bytes()
    assert json.loads((base/'policy_preprocessor.json').read_text())['steps'][0]['config']['tokenizer_name'] == 'external/model'


@pytest.mark.parametrize('fault', ['base_missing', 'wrong_type', 'tokenizer_missing', 'remote_base', 'existing_output'])
def test_invalid_training_sources_are_rejected_without_downloading(tmp_path, fault):
    module = training_module()
    base, vlm = sources(tmp_path)
    output = tmp_path/'inputs'
    if fault == 'base_missing': (base/'model.safetensors').unlink()
    if fault == 'wrong_type': (base/'config.json').write_text('{"type":"act"}')
    if fault == 'tokenizer_missing': (vlm/'tokenizer.json').unlink()
    if fault == 'remote_base': base = 'not-installed/smolvla'
    if fault == 'existing_output': output.mkdir()
    with pytest.raises((ValueError, OSError)):
        module.prepare(base, vlm, output, device='cpu')


def test_sealed_model_contains_portable_metadata_and_detects_later_changes(tmp_path):
    module = training_module()
    base, vlm = sources(tmp_path)
    model = tmp_path/'model'
    shutil.copytree(base, model)
    module.seal(model, vlm)
    config = json.loads((model/'config.json').read_text())
    assert config['vlm_model_name'] == 'rosy-bundled-vlm'
    assert config['load_vlm_weights'] is False and config['pretrained_path'] is None
    assert (model/'vlm/tokenizer.json').read_bytes() == (vlm/'tokenizer.json').read_bytes()
    assert json.loads((model/'policy_preprocessor.json').read_text())['steps'][0]['config']['tokenizer_name'] == 'rosy-bundled-vlm'
    assert json.loads((model/'rosy-smolvla-assets.json').read_text())['schema'] == 'rosy.omx.smolvla-assets/1'
