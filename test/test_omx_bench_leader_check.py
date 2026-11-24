import json
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from test_omx_bench_record import (
    _LeaderProc,
    _arm_s_live_files,
    _leader_popen,
    _setup,
    bench_record,
)


def test_check_leader_home_status_and_http_endpoint(tmp_path, monkeypatch):
    import bench_record_leader

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    (bench.prep / 'chunks-arm-s-inplace-live.json').write_text(json.dumps({'chunks': {'home': [[0, -50, 50, 50, 45, 50]]}}))
    (bench.prep / 'cell-arm-a-stack.json').write_text('{}')
    (bench.prep / 'chunks-topdown-guard-arma-test.json').write_text(json.dumps({'chunks': {'home': [[0, -50, 50, 50, 45, 50]]}}))
    (bench.prep / 'arm-a-robot-profile.json').write_text('{}')
    (bench.prep / 'caps-arm-a-test.json').write_text('{}')
    monkeypatch.setattr(bench_record_leader, 'arm_connectivity',
                        lambda _prep, a: {'leader_connected': a != 'arm_b', 'follower_connected': True})
    seen_cmds = []

    def fake_run(cmd, **_kw):
        seen_cmds.append(cmd)
        arm = cmd[cmd.index('--arm') + 1]
        if arm == 'arm_s':
            return SimpleNamespace(returncode=2, stdout=json.dumps({
                'ok': False, 'arm': 'arm_s', 'max_deg': 347.9, 'worst_joint': 'shoulder_pan',
                'over_limit': True, 'max_travel_deg': 100, 'message': '손으로 가깝게 옮기세요',
            }) + '\n', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'ok': True, 'arm': arm, 'max_deg': 2.8, 'worst_joint': 'shoulder_pan',
            'over_limit': False, 'max_travel_deg': 100, 'message': '한도 이내',
        }) + '\n', stderr='')

    monkeypatch.setattr(bench_record_leader.subprocess, 'run', fake_run)
    res = bench.check_leader_home_status('all')
    assert res['ok'] is True and res['skipped'] is False
    assert res['arms']['arm_a']['over_limit'] is False and res['arms']['arm_a']['max_deg'] == 2.8
    assert res['arms']['arm_s']['over_limit'] is True and res['arms']['arm_s']['max_deg'] == 347.9
    assert res['arms']['arm_b'] == {'ok': False, 'skipped': True, 'reason': '리더 USB 미연결'}
    assert len(seen_cmds) == 2 and all('--check-home' in c and '--attest' not in c for c in seen_cmds)
    assert any('--target-follower-ticks' in c for c in seen_cmds)

    bench.state = {'status': 'homing'}
    assert bench.check_leader_home_status('all')['skipped'] is True
    bench.state = {'status': 'idle'}
    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f'http://127.0.0.1:{srv.server_port}'
        with urllib.request.urlopen(base + '/api/leader_check?arm=arm_a', timeout=5) as r:
            body = json.loads(r.read())
            assert r.status == 200 and body['arms']['arm_a']['max_deg'] == 2.8
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + '/api/leader_check?arm=bogus', timeout=5)
        assert exc.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_match_leader_hands_over_active_observer_and_defers_restore_on_manual_hold(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    events = []
    obs_active = {'arm_a': True}

    def run(*args):
        calls.append(args)
        events.append(('unit', *args))
        if args[:2] == ('is-active', 'rosy-omx-observer@arm_a.service'):
            return SimpleNamespace(stdout='active\n' if obs_active['arm_a'] else 'inactive\n', returncode=0)
        if args[:2] == ('stop', 'rosy-omx-observer@arm_a.service'):
            obs_active['arm_a'] = False
        elif args[:2] == ('start', 'rosy-omx-observer@arm_a.service'):
            obs_active['arm_a'] = True
        return SimpleNamespace(stdout='', returncode=0)

    bench.run = run
    _leader_popen(bench, _LeaderProc(), monkeypatch)
    orig_popen = bench.popen
    bench.popen = lambda *a, **kw: (events.append(('popen',)), orig_popen(*a, **kw))[1]
    bench._match_leader('arm_a', str(bench.prep / 'record-config-arm-a.json'))
    unit_seq = [e for e in events if e[0] == 'popen' or (e[0] == 'unit' and e[1] in ('stop', 'start'))]
    assert unit_seq == [
        ('unit', 'stop', 'rosy-omx-observer@arm_a.service'),
        ('popen',),
        ('unit', 'start', 'rosy-omx-observer@arm_a.service'),
    ]
    assert obs_active['arm_a'] is True and not bench.pending.exists()

    # On manual hold, the stopped observer stays recorded on disk and is NOT restarted
    calls.clear()
    _leader_popen(bench, _LeaderProc(rc=1, out='follower torque is still ON'), monkeypatch)
    with pytest.raises(ValueError, match='토크'):
        bench._match_leader('arm_a', str(bench.prep / 'record-config-arm-a.json'))
    assert obs_active['arm_a'] is False
    assert bench.manual.is_file() and bench.pending.is_file()
    assert json.loads(bench.pending.read_text(encoding='utf-8')) == ['rosy-omx-observer@arm_a.service']
    assert not any(c[:2] == ('start', 'rosy-omx-observer@arm_a.service') for c in calls)
