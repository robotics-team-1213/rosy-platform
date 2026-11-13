"""Site auto-update hold expiry: an expired hold still blocks but is reported loudly."""
import datetime as _dt
import json

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import FakeHost, FakeHttp, _updater, host  # noqa: F401 - host is a fixture


def _hold_run(host, hold, capsys):
    host.paths.state.write_text(json.dumps({'hold': hold, 'failed': {}}))
    assert _updater(host, FakeHttp([], {}), FakeHost(host.paths)).run() == upd.EXIT_OK
    return capsys.readouterr().out


def test_set_hold_stores_expiry_and_bounds_hours(host):
    updater = _updater(host, FakeHttp([], {}), FakeHost(host.paths))
    assert upd.set_hold(updater, 'work') == upd.EXIT_OK
    hold = updater.load_state()['hold']
    assert not upd.hold_expired(hold)
    assert 23 * 3600 < (upd.hold_until(hold) - _dt.datetime.now(_dt.timezone.utc)).total_seconds() <= 24 * 3600
    for hours in (0, -1, 169):
        assert upd.set_hold(updater, 'work', hours) == upd.EXIT_FAILED


def test_expired_hold_still_blocks_but_is_loud(host, capsys):
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=5)).isoformat()
    assert '"held-expired"' in _hold_run(host, {'reason': 'r', 'time': old, 'until': old}, capsys)
    assert json.loads(host.paths.state.read_text())['last_run']['result'] == 'held'
    # legacy hold without until: expired 24 h after it was set
    assert '"held-expired"' in _hold_run(host, {'reason': 'r', 'time': (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=25)).isoformat()}, capsys)
    fresh = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=5)).isoformat()
    assert '"held"' in _hold_run(host, {'reason': 'r', 'time': fresh, 'until': fresh}, capsys)


def _naive(hours):
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=hours)).replace(tzinfo=None).isoformat()


def test_naive_or_unparsable_until_counts_as_expired_and_never_raises(host, capsys):
    for until in (_naive(5), 'garbage', 5, None):
        out = _hold_run(host, {'reason': 'r', 'time': _naive(-1), 'until': until}, capsys)
        assert '"held-expired"' in out, until
        assert json.loads(host.paths.state.read_text())['last_run']['result'] == 'held'
    assert upd.hold_expired({'reason': 'r', 'time': _naive(-1)})  # legacy without until, naive time
    assert upd.hold_expired('not a hold')


def test_status_prints_a_hold_with_a_naive_until_as_expired(host, capsys, monkeypatch):
    host.paths.state.write_text(json.dumps({'hold': {'reason': 'r', 'time': _naive(-1), 'until': _naive(5)}, 'failed': {}}))
    monkeypatch.setattr(upd, 'Paths', lambda: host.paths)
    assert upd.main(['status']) == upd.EXIT_OK
    hold = json.loads(capsys.readouterr().out)['hold']
    assert hold['expired'] is True and hold['until'].startswith('0001-01-01')
