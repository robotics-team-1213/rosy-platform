"""Portable SmolVLA metadata is verified before any model or tokenizer is loaded."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


def assets_module():
    path = (Path(__file__).resolve().parents[1] /
            'contracts/learning/src/rosy/contracts/learning/policy_assets.py')
    assert path.is_file(), 'portable policy assets loader is required'
    spec = importlib.util.spec_from_file_location('policy_assets_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(root):
    vlm = root/'vlm'
    vlm.mkdir(parents=True)
    files = {}
    for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json'):
        raw = json.dumps({'fixture': name}).encode()
        (vlm/name).write_bytes(raw)
        files[name] = hashlib.sha256(raw).hexdigest()
    (root/'rosy-smolvla-assets.json').write_text(json.dumps(
        dict(schema='rosy.omx.smolvla-assets/1', files=files)))
    return vlm


def test_bundled_policy_relocates_tokenizer_and_vlm_without_original_paths(tmp_path):
    module = assets_module()
    original = tmp_path/'original'
    bundle(original)
    moved = tmp_path/'moved'
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    config = SimpleNamespace(type='smolvla', vlm_model_name='rosy-bundled-vlm', load_vlm_weights=True)
    overrides = module.loading_overrides(moved, config)
    assert config.vlm_model_name == str(moved/'vlm')
    assert config.load_vlm_weights is False
    assert overrides == {'tokenizer_processor': {'tokenizer_name': str(moved/'vlm')}}


@pytest.mark.parametrize('fault', ['changed', 'missing', 'unlisted', 'link', 'manifest'])
def test_bundled_policy_refuses_incomplete_or_changed_metadata(tmp_path, fault):
    module = assets_module()
    vlm = bundle(tmp_path/'model')
    if fault == 'changed': (vlm/'tokenizer.json').write_text('{}')
    if fault == 'missing': (vlm/'tokenizer.json').unlink()
    if fault == 'unlisted': (vlm/'extra.json').write_text('{}')
    if fault == 'link':
        target = tmp_path/'outside.json'
        target.write_text('{}')
        (vlm/'tokenizer.json').unlink()
        (vlm/'tokenizer.json').symlink_to(target)
    if fault == 'manifest': (tmp_path/'model/rosy-smolvla-assets.json').unlink()
    config = SimpleNamespace(type='smolvla', vlm_model_name='rosy-bundled-vlm', load_vlm_weights=True)
    with pytest.raises((ValueError, OSError)):
        module.loading_overrides(tmp_path/'model', config)
    assert config.vlm_model_name == 'rosy-bundled-vlm'


def test_legacy_act_and_unbundled_benchmark_loading_remain_unchanged(tmp_path):
    module = assets_module()
    for kind, vlm in [('act', None), ('smolvla', 'existing/local/benchmark')]:
        config = SimpleNamespace(type=kind, vlm_model_name=vlm)
        assert module.loading_overrides(tmp_path, config) == {}
        assert config.vlm_model_name == vlm
