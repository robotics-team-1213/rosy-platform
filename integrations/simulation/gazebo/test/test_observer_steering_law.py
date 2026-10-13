"""Simulation forwards public steering parameters instead of CORE private config."""
import importlib.util
import os
from pathlib import Path

import pytest
import yaml


PARTS = Path(__file__).resolve().parents[1] / 'launch/gz_multi_parts.py'


def test_standalone_suite_reads_committed_core_loader_and_default_bundle():
    from core_common import config
    foundation = PARTS.parents[4] / 'contracts' / 'foundation'
    assert Path(config.__file__).resolve() == (foundation / 'core_common/config.py').resolve()
    assert config._find_default_config().resolve() == (foundation / 'config/rosy_default.yaml').resolve()


def _parts():
    spec = importlib.util.spec_from_file_location('observer_law_parts', PARTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_law_uses_same_overlay_and_keeps_private_environment(tmp_path, monkeypatch):
    overlay = tmp_path/'core.yaml'
    overlay.write_text(yaml.safe_dump(dict(line_follow=dict(cruise_speed=.06, steering_gain=1.7),
        auth=dict(tokens=[dict(token='never-forward-to-camera')]))))
    monkeypatch.setenv('ROSY_CONFIG', '/caller-private.yaml')
    law = _parts().observer_steering_law(str(overlay))
    assert law['core_cruise_speed'] == .06 and law['core_steering_gain'] == 1.7
    assert set(law) == {'core_'+key for key in ('cruise_speed','max_linear','steering_gain','min_confidence')}
    assert os.environ['ROSY_CONFIG'] == '/caller-private.yaml'


def test_failed_overlay_loading_restores_environment(tmp_path, monkeypatch):
    overlay = tmp_path/'core.yaml'
    overlay.write_text('line_follow: []')
    monkeypatch.delenv('ROSY_CONFIG', raising=False)
    with pytest.raises((TypeError, KeyError)):
        _parts().observer_steering_law(str(overlay))
    assert 'ROSY_CONFIG' not in os.environ
