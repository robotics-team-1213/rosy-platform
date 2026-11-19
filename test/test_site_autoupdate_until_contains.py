"""Site auto-update `hold --until-contains`: the hold lifts itself on proven ancestry."""
import json

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import (NEW, OLD, FakeHost, FakeHttp, _updater, _world,  # noqa: F401
                                  host)

CONTAINED = '0' * 40  # an ancestor of NEW in the fake compare API
MISSING = '9' * 40  # never an ancestor of NEW


def _hold_state(*shas):
    hold = {'reason': 'Keep FleetR hot-patch; resume after signed main release',
            'time': '2026-11-17T00:00:00+00:00', 'until': '2099-01-01T00:00:00+00:00'}
    if shas:
        hold['until_contains'] = list(shas)
    return json.dumps({'hold': hold, 'failed': {}})


def _candidate_world(host):
    releases, blobs = _world((NEW, '2026-11-18T02:00:00Z'))
    return FakeHttp(releases, blobs), FakeHost(host.paths)


class UnprovenHttp(FakeHttp):
    """The compare endpoint answers nothing provable."""

    def get(self, url, limit):
        if '/compare/' in url:
            raise upd.Transient('commit comparison is unavailable')
        return super().get(url, limit)


def test_until_contains_hold_clears_and_installs_when_candidate_has_every_sha(host, capsys):
    host.paths.state.write_text(_hold_state(CONTAINED))
    http, fake = _candidate_world(host)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert 'hold' not in state and state['last_run']['result'] == 'installed'
    assert state['installed']['commit'] == NEW
    assert fake.running == NEW
    out = capsys.readouterr().out
    assert 'hold-cleared' in out and 'Keep FleetR hot-patch' in out


def test_until_contains_hold_stays_held_while_one_sha_is_missing(host, capsys):
    host.paths.state.write_text(_hold_state(CONTAINED, MISSING))
    http, fake = _candidate_world(host)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert state['last_run']['result'] == 'held'
    assert state['hold']['until_contains'] == [CONTAINED, MISSING]
    assert http.downloads == [] and fake.calls == []
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == OLD
    assert MISSING in capsys.readouterr().out  # the audit line names the waiting shas


def test_until_contains_hold_stays_held_when_ancestry_cannot_be_proven(host):
    host.paths.state.write_text(_hold_state(CONTAINED))
    releases, blobs = _world((NEW, '2026-11-18T02:00:00Z'))
    http, fake = UnprovenHttp(releases, blobs), FakeHost(host.paths)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert state['last_run']['result'] == 'held'
    assert state['hold']['until_contains'] == [CONTAINED]
    assert http.downloads == [] and fake.calls == []
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == OLD


class IdenticalHttp(FakeHttp):
    """The candidate commit is the waited sha itself: git counts that as contained."""

    def get(self, url, limit):
        if '/compare/' in url and url.rsplit('/', 1)[-1].startswith(NEW + '...'):
            return json.dumps({'status': 'identical', 'merge_base_commit': {'sha': NEW}}).encode()
        return super().get(url, limit)


def test_until_contains_hold_clears_when_candidate_is_the_waited_sha(host):
    host.paths.state.write_text(_hold_state(NEW))
    releases, blobs = _world((NEW, '2026-11-18T02:00:00Z'))
    http, fake = IdenticalHttp(releases, blobs), FakeHost(host.paths)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert 'hold' not in state and fake.running == NEW


def test_plain_hold_still_blocks_without_until_contains(host, capsys):
    host.paths.state.write_text(_hold_state())
    http, fake = _candidate_world(host)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert state['last_run']['result'] == 'held' and state['hold']['reason']
    assert 'until_contains' not in state['hold']
    assert http.downloads == [] and fake.calls == []
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == OLD
    assert 'until_contains' not in capsys.readouterr().out


def test_until_contains_cli_stores_shas_status_shows_them_and_rejects_bad_ones(
        tmp_path, monkeypatch, capsys):
    paths = upd.Paths(tmp_path)
    paths.state.parent.mkdir(parents=True)
    monkeypatch.setattr(upd, 'Paths', lambda: paths)
    monkeypatch.setattr(upd, 'load_config', lambda path: {})
    assert upd.main(['hold', 'hot-patch staged', '--until-contains', CONTAINED, NEW]) == upd.EXIT_OK
    hold = json.loads(paths.state.read_text())['hold']
    assert hold['until_contains'] == [CONTAINED, NEW]
    assert upd.main(['status']) == upd.EXIT_OK
    assert CONTAINED in capsys.readouterr().out
    assert upd.main(['hold', 'nope', '--until-contains', 'deadbeef']) == upd.EXIT_FAILED
    assert json.loads(paths.state.read_text())['hold'] == hold
