"""Tests for self-validated cell ACT bundle packaging."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [
    str(ROOT / 'learning/training/omx'),
    str(ROOT / 'contracts/learning/src'),
    str(ROOT / 'deploy/robot/omx'),
]

import cell_lerobot_shadow as shadow  # noqa: E402
from experiment_artifact import package_cell_bundle  # noqa: E402
from rosy.contracts.learning.digest import checkpoint_sha256  # noqa: E402


def _make_src_ckpt(src: Path, *, top_view='rs', device='cuda:0', extra_views=None):
    src.mkdir(parents=True, exist_ok=True)
    weights = b'act-weights-bytes'
    (src / 'model.safetensors').write_bytes(weights)
    features = {
        'observation.state': {'type': 'STATE', 'shape': [6]},
        'observation.environment_state': {'type': 'ENV', 'shape': [10]},
        f'observation.images.{top_view}': {'type': 'VISUAL', 'shape': [3, 480, 640]},
        'observation.images.side': {'type': 'VISUAL', 'shape': [3, 480, 640]},
        'observation.images.wrist': {'type': 'VISUAL', 'shape': [3, 480, 640]},
    }
    for view in (extra_views or ()):
        features[f'observation.images.{view}'] = {'type': 'VISUAL', 'shape': [3, 480, 640]}
    (src / 'config.json').write_text(json.dumps({
        'type': 'act',
        'device': device,
        'input_features': features,
        'output_features': {'action': {'type': 'ACTION', 'shape': [6]}},
    }), encoding='utf-8')
    (src / 'policy_preprocessor.json').write_text(json.dumps({
        'name': 'policy_preprocessor',
        'steps': [
            {'registry_name': 'device_processor', 'config': {'device': device}},
            {'registry_name': 'normalizer_processor', 'config': {
                'features': {
                    f'observation.images.{top_view}': {'type': 'VISUAL', 'shape': [3, 480, 640]},
                    'observation.images.side': {'type': 'VISUAL', 'shape': [3, 480, 640]},
                    'observation.images.wrist': {'type': 'VISUAL', 'shape': [3, 480, 640]},
                    'observation.state': {'type': 'STATE', 'shape': [6]},
                },
            }},
        ],
    }), encoding='utf-8')
    return hashlib.sha256(weights).hexdigest()


def test_package_cell_bundle_rewrites_views_device_and_matches_cell_reader(tmp_path):
    src = tmp_path / 'src-ckpt'
    raw_sha = _make_src_ckpt(src, top_view='rs', device='cuda:0')
    dst = tmp_path / 'cell-bundle'

    summary = package_cell_bundle(src, dst, arm_id='arm_b', rename_views={'rs': 'top'})
    assert summary['arm_id'] == 'arm_b'
    assert summary['policy_revision'] == raw_sha
    assert summary['views'] == ['side', 'top', 'wrist']
    assert summary['checkpoint_sha256'] == checkpoint_sha256(dst, allow_symlinks=False)
    assert hashlib.sha256((dst / 'model.safetensors').read_bytes()).hexdigest() == raw_sha

    cfg = json.loads((dst / 'config.json').read_text(encoding='utf-8'))
    assert cfg['device'] == 'cpu'
    views, action_dim, goal_dim = shadow.read_features(cfg)
    assert set(views) == {'top', 'side', 'wrist'} and action_dim == 6 and goal_dim == 10

    pre = json.loads((dst / 'policy_preprocessor.json').read_text(encoding='utf-8'))
    assert pre['steps'][0]['config']['device'] == 'cpu'
    norm_features = pre['steps'][1]['config']['features']
    assert 'observation.images.top' in norm_features and 'observation.images.rs' not in norm_features

    assert json.loads((dst / 'UNITS.json').read_text(encoding='utf-8')) == {
        'state': 'sim_rad', 'gripper': 'sim_jaw', 'arm': 'arm_b',
    }
    assert json.loads((dst / 'VIEW_NAMES.json').read_text(encoding='utf-8')) == {'pairs': {'rs': 'top'}}
    assert set(shadow.checkpoint_digest(dst)) == set(summary['files'])


def test_package_cell_bundle_guards_collisions_paths_and_symlinks(tmp_path):
    src = tmp_path / 'src-ckpt'
    _make_src_ckpt(src, top_view='rs', device='cuda')

    with pytest.raises(ValueError, match='cell roles'):
        package_cell_bundle(src, tmp_path / 'unmapped', arm_id='arm_a')

    with pytest.raises(ValueError, match='duplicate target'):
        package_cell_bundle(src, tmp_path / 'dup-target', arm_id='arm_a', rename_views={'rs': 'top', 'side': 'top'})

    with pytest.raises(ValueError, match='conflicts with source'):
        package_cell_bundle(src, src / 'nested-dst', arm_id='arm_a', rename_views={'rs': 'top'})

    collide_src = tmp_path / 'src-collide'
    _make_src_ckpt(collide_src, top_view='rs', extra_views=('top',))
    with pytest.raises(ValueError, match='duplicate JSON key'):
        package_cell_bundle(collide_src, tmp_path / 'collide-dst', arm_id='arm_b', rename_views={'rs': 'top'})

    dst = tmp_path / 'existing'
    dst.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        package_cell_bundle(src, dst, arm_id='arm_a', rename_views={'rs': 'top'})

    try:
        (src / 'link.txt').symlink_to(src / 'config.json')
    except OSError:
        return  # Windows without Developer Mode refuses symlink creation
    with pytest.raises(ValueError, match='symlink'):
        package_cell_bundle(src, tmp_path / 'linked', arm_id='arm_a', rename_views={'rs': 'top'})


def test_package_cell_bundle_rewrites_normalizer_safetensors(tmp_path):
    sf = pytest.importorskip('safetensors.numpy')
    src = tmp_path / 'src-sf'
    _make_src_ckpt(src, top_view='rs', device='cuda')
    sf.save_file({
        'observation.images.rs.mean': np.array([0.5], dtype=np.float32),
        'observation.images.side.mean': np.array([0.5], dtype=np.float32),
        'observation.images.wrist.mean': np.array([0.5], dtype=np.float32),
        'observation.state.mean': np.zeros(6, dtype=np.float32),
    }, str(src / 'policy_preprocessor_step_3_normalizer_processor.safetensors'))

    dst = tmp_path / 'dst-sf'
    summary = package_cell_bundle(src, dst, arm_id='arm_b', rename_views={'rs': 'top'})
    tensors = sf.load_file(str(dst / 'policy_preprocessor_step_3_normalizer_processor.safetensors'))
    assert 'observation.images.top.mean' in tensors and 'observation.images.rs.mean' not in tensors
    assert summary['checkpoint_sha256'] == checkpoint_sha256(dst, allow_symlinks=False)
