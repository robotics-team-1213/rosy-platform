"""Artifact construction and native configuration contracts, without installing a service."""

from pathlib import Path

import pytest

from rosy.monitoring.config import load_config, load_credentials
from rosy.monitoring.web_assets import ASSETS, build_web


ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / 'operations/monitoring/deploy'


def test_bundle_contains_canonical_bytes_and_refuses_existing_output(tmp_path):
    target = tmp_path / 'web'
    build_web(ROOT, target)
    assert {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()} == set(ASSETS.values())
    for name in ASSETS.values():
        owner = 'shared/web' if name.startswith('common/') else 'applications/monitoring/web'
        assert (target / name).read_bytes() == (ROOT / owner / Path(name).name).read_bytes()
    with pytest.raises(FileExistsError):
        build_web(ROOT, target)
    assert (target / 'index.html').is_file()


def test_missing_asset_does_not_publish_partial_bundle(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    with pytest.raises(FileNotFoundError):
        build_web(checkout, tmp_path / 'web')
    assert not (tmp_path / 'web').exists()


@pytest.mark.parametrize('name', ['site', 'aggregate', 'direct-central'])
def test_deployment_profiles_use_valid_scopes_and_separate_credentials(name):
    config = load_config(DEPLOY / f'{name}.yaml')
    references = [r.token_env for r in config.readers] + [s.token_env for s in config.sources if s.token_env]
    credentials = load_credentials(config, {ref: f'{index:032d}' for index, ref in enumerate(references, 1)})
    assert credentials
    assert all('.example.invalid' in s.url for s in config.sources if s.url)


def test_native_unit_does_not_couple_lifecycle_to_fleet():
    unit = (DEPLOY / 'rosy-monitoring.service').read_text()
    assert 'User=rosy-monitoring' in unit and 'StateDirectoryMode=0700' in unit
    assert 'ProtectSystem=strict' in unit and 'CapabilityBoundingSet=\n' in unit
    assert 'Requires=' not in unit and 'PartOf=' not in unit
    assert '--web-root /opt/rosy-monitoring/web' in unit
