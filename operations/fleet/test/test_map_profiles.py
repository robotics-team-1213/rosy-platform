"""D-631 profile library never changes the active map or draft."""
import pytest
import json
import sqlite3
from fleet.server.site_map_store import SiteMapStore, SiteMapError
from fleet.site_map import SiteMap
from test_site_map_trip import _app, _line, OPERATOR, VIEWER


def test_profile_basic_information_survives_updates_and_restart(tmp_path):
    client, _, store, _ = _app(tmp_path)
    with client:
        body = {'name': '축구장', 'map': _line(), 'kind': 'soccer', 'description': '연습 경기장',
                'soccer_field': {'length_m': 2.0, 'width_m': 1.4, 'goal_width_m': 0.35}}
        url = '/api/fleet/site-map/profiles/pitch'
        saved = client.put(url, json=body, headers=OPERATOR)
        assert saved.status_code == 200, saved.text
        assert saved.json()['soccer_field'] == body['soccer_field']
        revision = saved.json()['revision']
        body.update(description='수정한 설명', expected_revision=revision)
        updated = client.put(url, json=body, headers=OPERATOR)
        assert updated.status_code == 200
        assert updated.json()['revision'] != revision
        assert client.put(url, json=body, headers=OPERATOR).status_code == 409
        assert store.profiles()[0]['description'] == '수정한 설명'
        old_client = client.put(url, json={'name': 'old client', 'map': _line(),
                                         'expected_revision': updated.json()['revision']}, headers=OPERATOR)
        assert old_client.status_code == 200
        assert old_client.json()['kind'] == 'soccer'
        assert old_client.json()['description'] == '수정한 설명'
        assert old_client.json()['soccer_field'] == body['soccer_field']
    path = store.path
    expected = store.profiles()
    store.close()
    again = SiteMapStore(path)
    assert again.profiles() == expected
    again.close()


@pytest.mark.parametrize('info', [
    {'kind': 'soccer'}, {'kind': 'unknown'}, {'description': 'x' * 1001},
    {'kind': 'soccer', 'soccer_field': {'length_m': -1, 'width_m': 1.4, 'goal_width_m': 0.35}},
    {'kind': 'soccer', 'soccer_field': {'length_m': 2, 'width_m': 1.4, 'goal_width_m': 2}},
    {'kind': 'general', 'soccer_field': {'length_m': 2, 'width_m': 1.4, 'goal_width_m': 0.35}},
])
def test_profile_rejects_invalid_type_specific_information(tmp_path, info):
    client, _, _, _ = _app(tmp_path)
    with client:
        result = client.put('/api/fleet/site-map/profiles/invalid',
                            json={'name': 'map', 'map': _line(), **info}, headers=OPERATOR)
        assert result.status_code == 422, result.text


def test_existing_profile_database_gets_default_information_without_losing_map(tmp_path):
    path = tmp_path / 'old.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE site_map_profiles (profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, '
                   'body TEXT NOT NULL, revision TEXT NOT NULL, saved_by TEXT NOT NULL, saved_at REAL NOT NULL)')
        db.execute('INSERT INTO site_map_profiles VALUES (?, ?, ?, ?, ?, ?)',
                   ('old', 'old map', json.dumps(_line()), 'revision', 'bob', 100))
    store = SiteMapStore(path)
    row = store.profiles()[0]
    assert row['kind'] == 'lane_course' and row['description'] == '' and row['soccer_field'] is None
    assert row['map'] == _line() and row['revision'] == 'revision'
    store.close()
    again = SiteMapStore(path)
    assert again.profiles()[0] == row
    again.close()


def test_profiles_survive_restart_and_refuse_lost_updates(tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    store = SiteMapStore(path)
    site = SiteMap.model_validate(_line())
    first = store.save_profile('first', name='첫 지도', site_map=site,
                               expected_revision=None, principal_id='bob')
    store.save_profile('second', name='다른 지도', site_map=site.model_copy(update={'map_id': 'other'}),
                       expected_revision=None, principal_id='bob')
    with pytest.raises(SiteMapError) as err:
        store.save_profile('first', name='덮어쓰기', site_map=site,
                           expected_revision=None, principal_id='eve')
    assert err.value.code == 'SITE_MAP_PROFILE_CHANGED'
    assert store.active_view() is None
    assert store.draft_view()['map'] is None
    assert store.events()[0]['action'] == 'profile_saved'
    store.close()
    again = SiteMapStore(path)
    assert len(again.profiles()) == 2
    assert again.profiles()[0] == first
    again.close()


def test_profile_api_permissions_validation_and_conflict(tmp_path):
    client, tasks, store, robot = _app(tmp_path)
    with client:
        active = client.get('/api/fleet/site-map/active', headers=VIEWER).json()
        url = '/api/fleet/site-map/profiles/room-1'
        body = {'name': '연습장', 'map': _line(), 'expected_revision': None}
        assert client.get('/api/fleet/site-map/profiles').status_code == 401
        assert client.put(url, json=body, headers=VIEWER).status_code == 403
        saved = client.put(url, json=body, headers=OPERATOR)
        assert saved.status_code == 200, saved.text
        assert client.put(url, json=body, headers=OPERATOR).status_code == 409
        body['expected_revision'] = saved.json()['revision']
        body['map']['edges'][0]['to'] = 'missing'
        assert client.put(url, json=body, headers=OPERATOR).status_code == 422
        assert client.put('/api/fleet/site-map/profiles/bad%20id', json=body, headers=OPERATOR).status_code == 422
        body['map'] = _line()
        body['name'] = ' '
        assert client.put(url, json=body, headers=OPERATOR).status_code == 422
        body['name'] = 'updated'
        updated = client.put(url, json=body, headers=OPERATOR)
        assert updated.status_code == 200
        assert updated.json()['revision'] != saved.json()['revision']
        assert client.put(url, content=b'x' * (2 * 1024 * 1024 + 1), headers=OPERATOR).status_code == 413
        rows = client.get('/api/fleet/site-map/profiles', headers=VIEWER).json()['profiles']
        assert rows == [updated.json()]
        assert client.get('/api/fleet/site-map/active', headers=VIEWER).json() == active


def test_profile_limit_does_not_prevent_revision_checked_updates():
    store = SiteMapStore()
    site = SiteMap.model_validate(_line())
    for index in range(100):
        row = store.save_profile(str(index), name='map', site_map=site,
                                 expected_revision=None, principal_id='bob')
    with pytest.raises(SiteMapError) as err:
        store.save_profile('overflow', name='map', site_map=site,
                           expected_revision=None, principal_id='bob')
    assert err.value.code == 'SITE_MAP_PROFILE_LIMIT'
    updated = store.save_profile('99', name='update', site_map=site,
                                 expected_revision=row['revision'], principal_id='bob')
    assert updated['name'] == 'update' and len(store.profiles()) == 100
    store.close()
