"""The curation output policy resolves paths without touching source bytes."""
import importlib.util
from pathlib import Path

import pytest


def policy():
    source = Path(__file__).resolve().parents[1] / 'omx_output_paths.py'
    assert source.is_file(), 'curation needs one shared output-path policy'
    spec = importlib.util.spec_from_file_location('omx_output_paths', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.in_source_checkout


@pytest.mark.parametrize('linked', [False, True])
def test_uncreated_output_in_checkout_is_refused_without_writes(tmp_path, linked):
    inside = policy()
    root = tmp_path / 'source'
    root.mkdir()
    marker = root / '.git'
    marker.write_text('gitdir: elsewhere\n') if linked else marker.mkdir()
    output = root / 'new' / 'dataset'
    assert inside(output)
    assert not inside(tmp_path / 'external' / 'new')
    assert not output.exists()
    assert sorted(p.name for p in root.iterdir()) == ['.git']


@pytest.mark.parametrize('target_inside', [False, True])
def test_output_policy_follows_symlink_destination(tmp_path, target_inside):
    inside = policy()
    root, external = tmp_path / 'source', tmp_path / 'external'
    root.mkdir(); external.mkdir(); (root / '.git').mkdir()
    link = (external if target_inside else root) / 'link'
    target = root if target_inside else external
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'symlink creation unavailable: {exc}')
    assert inside(link / 'new') is target_inside
    assert not (target / 'new').exists()
