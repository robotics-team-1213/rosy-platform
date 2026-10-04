"""Approved model destinations follow hints without changing SSH trust."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/training/perception/model'))
import peer_targets
from core_common.discover import DiscoveredDevice
from core_common.protocol.discovery_txt import ROBOT, REQUIRED
from deliver import SshFailure


class Cache:
    def __init__(self, rows):
        self.rows = rows

    def wait(self, kind, *, timeout_s):
        assert kind == ROBOT and 0 <= timeout_s <= 3
        return self.rows


def row(address='192.168.1.21', **kw):
    return DiscoveredDevice(kw.get('instance', 'ROSY pinky'), ROBOT,
                            'pinky.local', 8080, (address,),
                            tuple(kw.get('txt', REQUIRED[ROBOT]).items()))


def test_live_dhcp_hint_changes_address_not_approved_identity():
    robot = {'name': 'pinky', 'expected_hostname': 'pinky.local'}
    cache = Cache([row()])
    assert peer_targets.resolve(robot, cache=cache) == '192.168.1.21'
    cache.rows = [row('192.168.1.22')]
    assert peer_targets.resolve(robot, cache=cache) == '192.168.1.22'
    assert robot == {'name': 'pinky', 'expected_hostname': 'pinky.local'}
    cache.rows = []  # removal/expiry never reuses the old address
    with pytest.raises(SshFailure, match='unavailable'):
        peer_targets.resolve(robot, cache=cache)


@pytest.mark.parametrize('rows', [[row(), row('192.168.1.22', instance='other')],
                                 [row(txt={'product': 'rosy'})],
                                 [row(txt={**REQUIRED[ROBOT], 'robot_id': 'other-robot'})]])
def test_conflict_or_malformed_hint_blocks_even_explicit_dns_fallback(rows):
    robot = {'name': 'pinky', 'expected_hostname': 'pinky.example.test',
             'mdns_hostname': 'pinky.local', 'allow_dns_fallback': True}
    with pytest.raises(SshFailure):
        peer_targets.resolve(robot, cache=Cache(rows))


def test_cross_network_dns_is_explicit_approved_policy():
    robot = {'name': 'pinky', 'expected_hostname': 'pinky.example.test'}
    assert peer_targets.resolve(robot, cache=Cache([])) == 'pinky.example.test'
    robot['mdns_hostname'] = 'pinky.local'
    with pytest.raises(SshFailure):
        peer_targets.resolve(robot, cache=Cache([]))
    robot['allow_dns_fallback'] = True
    assert peer_targets.resolve(robot, cache=Cache([])) == 'pinky.example.test'


def test_legacy_profile_only_when_no_declared_approved_profile():
    assert peer_targets.resolve({'name': 'pinky', 'host': 'old.local'}) == 'old.local'
    with pytest.raises(ValueError):
        peer_targets.validate({'name': 'pinky', 'expected_hostname': '', 'host': 'old.local'})


@pytest.mark.parametrize('profile', [
    {'expected_hostname': 'https://host.test'},
    {'expected_hostname': 'pinky.test', 'allow_dns_fallback': 'true'},
    {'expected_hostname': 'pinky.test', 'mdns_hostname': 'other.test'},
    {'expected_hostname': 'pinky.local', 'mdns_hostname': 'other.local'},
])
def test_invalid_profile_is_not_legacy(profile):
    with pytest.raises(ValueError):
        peer_targets.validate({'name': 'pinky', 'host': 'old.local', **profile})


def test_watch_resolves_again_before_push_preserving_keys_and_logical_alias(tmp_path, monkeypatch):
    import deliver
    import watch
    import test_model_watch_inbox as ti
    from core_common import discover
    cache = Cache([row()])
    monkeypatch.setattr(discover, 'get_shared_cache', lambda: cache)
    robot = {'name': 'pinky', 'expected_hostname': 'pinky.local'}
    config_path = ti._config(tmp_path, robots=[robot])
    cfg = watch.load_config(config_path)
    observed, pushed = [], []
    def observe(host, **kw):
        observed.append((host, kw))
        cache.rows = [row('192.168.1.22')]
        return {'shadow': None, 'hold': None}
    monkeypatch.setattr(deliver, 'observe', observe)
    monkeypatch.setattr(deliver, 'main', lambda argv: pushed.append(argv) or 0)
    assert watch.default_observer(cfg)(robot)['hold'] is None
    assert watch.default_deliverer(cfg)(robot, 'rev-m1') == 0
    assert observed[0][0] == '192.168.1.21'
    assert observed[0][1]['host_key_alias'] == 'pinky'
    assert observed[0][1]['known_hosts'] == cfg['ssh']['known_hosts']
    argv = pushed[0]
    assert argv[:3] == ['push', '192.168.1.22', 'rev-m1']
    assert argv[argv.index('--host-key-alias') + 1] == 'pinky'
    assert argv[argv.index('--known-hosts') + 1] == cfg['ssh']['known_hosts']
    assert '--unless-held' in argv


@pytest.mark.parametrize('fault', ['expired', 'conflict'])
def test_hint_lost_after_observation_spends_no_push_attempt(tmp_path, monkeypatch, fault):
    import deliver
    import watch
    import test_model_watch_inbox as ti
    from core_common import discover
    cache = Cache([row()])
    monkeypatch.setattr(discover, 'get_shared_cache', lambda: cache)
    cfg_path = ti._config(tmp_path, robots=[{'name': 'pinky', 'expected_hostname': 'pinky.local'}])
    ti._drop(tmp_path, 'm1')
    fakes = ti.Fakes()
    def observe(host, **kw):
        cache.rows = [] if fault == 'expired' else [row(), row('192.168.1.22', instance='other')]
        return {'shadow': None, 'hold': None}
    monkeypatch.setattr(deliver, 'observe', observe)
    monkeypatch.setattr(deliver, 'main', lambda _argv: pytest.fail('unapproved push attempted'))
    assert watch.main(['--config', str(cfg_path)], intake_fn=fakes.intake) == (77 if fault == 'expired' else 79)
    state = ti._state(tmp_path)
    assert state['commits']['m1']['robots']['pinky']['attempts'] == 0
    assert state['commits']['m1']['robots']['pinky']['status'] == 'pending'


def test_ssh_identity_failure_never_retries_approved_dns_as_a_different_target(tmp_path, monkeypatch):
    import deliver
    import watch
    import test_model_watch_inbox as ti
    from core_common import discover
    monkeypatch.setattr(discover, 'get_shared_cache', lambda: Cache([row()]))
    cfg_path = ti._config(tmp_path, robots=[{'name': 'pinky', 'expected_hostname': 'pinky.example.test',
                                           'mdns_hostname': 'pinky.local', 'allow_dns_fallback': True}])
    ti._drop(tmp_path, 'm1')
    calls = []
    def observe(host, **kw):
        calls.append((host, kw['host_key_alias']))
        raise SshFailure('hostkey', 'fixture: pinned host key rejected')
    monkeypatch.setattr(deliver, 'observe', observe)
    monkeypatch.setattr(deliver, 'main', lambda _argv: pytest.fail('unauthenticated push'))
    assert watch.main(['--config', str(cfg_path)], intake_fn=ti.Fakes().intake) == 79
    assert calls == [('192.168.1.21', 'pinky')]
    assert ti._state(tmp_path)['commits']['m1']['robots']['pinky']['attempts'] == 0


def test_operator_watch_adapter_preserves_alias_and_refreshes_dhcp(tmp_path, monkeypatch):
    import rosy_ml
    import watch
    import test_model_watch_inbox as ti
    from core_common import discover
    cache = Cache([row()])
    monkeypatch.setattr(discover, 'get_shared_cache', lambda: cache)
    cfg_path = ti._config(tmp_path, robots=[{'name': 'pinky', 'expected_hostname': 'pinky.local'}])
    cfg = watch.load_config(cfg_path)
    first = rosy_ml.config_from_watch(cfg)
    cache.rows = [row('192.168.1.22')]
    second = rosy_ml.config_from_watch(cfg)
    assert first['robots'] == {'pinky': '192.168.1.21'}
    assert second['robots'] == {'pinky': '192.168.1.22'}
    assert second['ssh'] == cfg['ssh']
    assert rosy_ml._ssh_argv(second, 'pinky')[-2:] == ['--host-key-alias', 'pinky']


def test_doctor_missing_approved_robot_reports_network_failure_not_config_crash(tmp_path, monkeypatch, capsys):
    import rosy_ml
    import test_model_watch_inbox as ti
    from core_common import discover
    monkeypatch.setattr(discover, 'get_shared_cache', lambda: Cache([]))
    cfg_path = ti._config(tmp_path, robots=[{'name': 'pinky', 'expected_hostname': 'pinky.local'}])
    assert rosy_ml.main(['doctor', '--watch-config', str(cfg_path)]) == 77
    text = capsys.readouterr().out
    assert 'unavailable' in text and 'network' in text
