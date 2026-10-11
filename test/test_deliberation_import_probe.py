import pytest

from deploy.ai_pc import deliberation_import_probe as module


@pytest.mark.parametrize('change', ['valid', 'dependency', 'venv', 'platform'])
def test_probe_only_checks_import_codec_and_never_admits_runtime(monkeypatch, change):
    versions = dict(module.PINS)
    if change == 'dependency': versions['pydantic-core'] = 'foreign'
    monkeypatch.setattr(module, 'version', lambda name: versions[name])
    monkeypatch.setattr(module.sys, 'prefix', module.sys.base_prefix if change == 'venv' else '/fixture-venv')
    monkeypatch.setattr(module.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(module.platform, 'machine', lambda: 'foreign' if change == 'platform' else 'x86_64')
    if change == 'valid':
        result = module.probe()
        assert result['state'] == 'PASS_V2_IMPORT_CODEC_ONLY'
        assert result['actual_model_calls'] == 0 and result['runtime_admitted'] is False
        assert result['cost_verified'] is False and result['action_admissible'] is False
    else:
        with pytest.raises(ValueError, match='V2_DEPENDENCY_CLOSURE_NOT_VERIFIED'):
            module.probe()
