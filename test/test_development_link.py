"""D-432 private, code-free development provisioning without IP pins or motor enablement."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'middleware/core/gateway'))
spec = importlib.util.spec_from_file_location('development_link', ROOT / 'tools/development_link.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_bundle_round_trips_real_consumers_and_never_enables_motion(tmp_path):
    from core_common.protocol.link_policy import LinkPolicy
    from core_common.protocol.site_link import validate
    from fleet.swarm.robots import load_robots
    output = tmp_path / 'private-development'
    module.provision(output, site='bench-a', robots=[('rosy_01', 'robot-a.local')])
    policy = LinkPolicy.from_file(output / 'link-policy.json')
    robots = load_robots(output / 'robots.yaml')
    assert policy.mode == 'development'
    assert len(robots) == 1 and robots[0].discovery
    assert robots[0].base_url == 'https://robot-a.local:8080'
    assert robots[0].link_policy_file == str(output / 'link-policy.json')
    core = yaml.safe_load((output / 'rosy_01/core.yaml').read_text())
    assert core['runtime']['mode'] == 'core'
    assert core['network']['connection_mode'] == 'development'
    assert core['auth']['tokens'][0]['role'] == 'operator'
    assert 'token' not in core['auth']['tokens'][0]
    assert 'hardware' not in core and 'approved' not in repr(core)
    camera = json.loads((output / 'cam-development.json').read_text())
    assert validate(camera['site_link']) is None
    assert camera['source'] == 'overhead-1'
    assert camera['site_link']['tls_host'] == 'bench-a.local'
    assert camera['site_link']['credential'] != robots[0].token
    assert policy.permits(camera['source'], '_rosy-overhead._tcp', 'bench-a.local', authenticated=True)
    assert not (output / 'ca.key').exists(), 'bootstrap must discard the CA signing key'
    pilot = json.loads((output / 'pilot-development.json').read_text())
    assert pilot['robots'][0]['credential'] == robots[0].token
    assert pilot['robots'][0]['tls_host'] == 'robot-a.local'
    from core.api_tls import server_tls_options
    assert server_tls_options(core)['ssl_certfile'] == str(output / 'rosy_01/chain.pem')


def test_cross_host_linux_install_paths_are_not_windows_relative_paths(tmp_path):
    output = module.provision(tmp_path / 'scope', site='lab', robots=[('rosy_01', 'robot-a.local')],
                              runtime_root='/etc/rosy/development')
    core = yaml.safe_load((output / 'rosy_01/core.yaml').read_text())
    assert core['network']['tls']['cert_file'] == '/etc/rosy/development/rosy_01/chain.pem'


def test_refuses_existing_output_and_production_profile(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    keep = output / 'keep'
    keep.write_text('original')
    with pytest.raises(ValueError):
        module.provision(output, site='bench-a', robots=[('rosy_01', 'robot-a.local')])
    assert keep.read_text() == 'original'
    with pytest.raises(ValueError, match='development'):
        module.provision(tmp_path / 'prod', site='bench-a', robots=[('rosy_01', 'robot-a.local')],
                         mode='paired')
    assert not (tmp_path / 'prod').exists()


@pytest.mark.parametrize('robots', [[('rosy_01', '192.168.1.1')],
                                    [('rosy_01', 'robot-a.local'), ('rosy_02', 'robot-a.local')],
                                    [('rosy_01', 'robot-a.local'), ('rosy_01', 'robot-b.local')]])
def test_refuses_unscoped_or_duplicate_identity_before_writing(tmp_path, robots):
    with pytest.raises(ValueError):
        module.provision(tmp_path / 'bad', site='bench-a', robots=robots)
    assert not (tmp_path / 'bad').exists()
