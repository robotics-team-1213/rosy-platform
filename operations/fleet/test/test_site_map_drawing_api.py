"""D-825 immutable drawing assets preserve active maps on every failure."""
import asyncio
import importlib
import subprocess
import sqlite3
from types import SimpleNamespace

import pytest

from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.site_map import SiteMap
import test_site_map_trip as trip
from test_site_map_projection import binary, registration

UPLOAD = '/api/fleet/site-map/drawings'
DATA = binary([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]])


@pytest.mark.parametrize('association', ['active', 'history', 'profile', 'hidden_active'])
@pytest.mark.parametrize('legacy_restart', [False, True])
def test_map_identity_cannot_reuse_another_drawing_frame(tmp_path, monkeypatch, association, legacy_restart):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    uploaded = client.post(UPLOAD, headers=trip.OPERATOR, content=DATA).json()
    projection = assets.project(uploaded['asset_sha256'], registration())
    body = store.active_view()['map']
    if association == 'history':
        other = {**body, 'map_id': 'other'}
        saved = store.save_draft(SiteMap.model_validate(other), expected_revision=None, principal_id='bob')
        store.activate(expected_revision=saved['revision'], principal_id='bob', route_active=False)
    elif association == 'profile':
        body = {**body, 'map_id': 'profile-only'}
        store.save_profile('template', name='Template', site_map=SiteMap.model_validate(body),
                           expected_revision=None, principal_id='bob')
    elif association == 'hidden_active':
        store.save_draft(SiteMap.model_validate({**body, 'map_id': 'other'}),
                         expected_revision=None, principal_id='bob')
    if legacy_restart:
        path = store.path
        store.close()
        with sqlite3.connect(path) as db:
            db.execute('DROP TABLE IF EXISTS site_map_frames')
        store = SiteMapStore(path, drawing_assets=assets)
    body = {**body, 'drawing': {k: projection[k] for k in ('asset_sha256', 'projection_sha256')},
            'survey': {'revision': projection['projection_sha256'], 'origin': [0, 0], 'heading_rad': 0,
                       'scale_source': 'measured', 'measured_distance_m': 1,
                       'description': 'measured drawing', 'reviewed': False}}
    candidate = SiteMap.model_validate(body)
    active, draft = store.active_view(), store.draft_view()
    with pytest.raises(SiteMapError) as error:
        store.save_draft(candidate, expected_revision=draft['revision'], principal_id='bob')
    assert error.value.code == 'SITE_MAP_DRAWING_INVALID'
    with pytest.raises(SiteMapError):
        store.save_profile('replacement', name='Replacement', site_map=candidate,
                           expected_revision=None, principal_id='bob')
    assert store.active_view() == active and store.draft_view() == draft


def test_drawing_identity_survives_restart_and_rejects_removal_or_transform_change(tmp_path):
    assets = asset_module().SiteMapAssetStore(tmp_path / 'assets')
    source = tmp_path / 'input.stl'
    source.write_bytes(DATA)
    asset = assets.put_stl(source)
    first = assets.project(asset['asset_sha256'], registration())
    second = assets.project(asset['asset_sha256'], registration().model_copy(update={'heading_rad': .5}))
    body = {**trip._line(), 'map_id': 'drawing-frame',
            'drawing': {k: first[k] for k in ('asset_sha256', 'projection_sha256')},
            'survey': {'revision': first['projection_sha256'], 'origin': [0, 0], 'heading_rad': 0,
                       'scale_source': 'measured', 'measured_distance_m': 1,
                       'description': 'measured drawing', 'reviewed': False}}
    path = tmp_path / 'maps.db'
    store = SiteMapStore(path, drawing_assets=assets)
    saved = store.save_draft(SiteMap.model_validate(body), expected_revision=None, principal_id='bob')
    store.close()
    store = SiteMapStore(path, drawing_assets=assets)
    changed = {**body, 'drawing': {k: second[k] for k in ('asset_sha256', 'projection_sha256')},
               'survey': {**body['survey'], 'revision': second['projection_sha256']}}
    for candidate in (changed, {**body, 'drawing': None, 'survey': None}):
        with pytest.raises(SiteMapError) as error:
            store.save_draft(SiteMap.model_validate(candidate), expected_revision=saved['revision'], principal_id='bob')
        assert error.value.code == 'SITE_MAP_DRAWING_INVALID'
        assert store.draft_view() == saved
    assert store.save_draft(SiteMap.model_validate(body), expected_revision=saved['revision'], principal_id='bob')


def asset_module():
    try:
        return importlib.import_module('fleet.server.site_map_assets')
    except ModuleNotFoundError as exc:
        if exc.name != 'fleet.server.site_map_assets':
            raise
        pytest.fail('drawing asset store is not implemented')


def setup_assets(tmp_path, monkeypatch):
    assets = asset_module().SiteMapAssetStore(tmp_path / 'assets')
    monkeypatch.setattr(trip, 'SiteMapStore', lambda path: SiteMapStore(path, drawing_assets=assets))
    client, _, store, _ = trip._app(tmp_path)
    return client, store, assets


def test_anonymous_and_readonly_cannot_upload(tmp_path, monkeypatch):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    for headers, expected in (({}, 401), (trip.VIEWER, 403)):
        assert client.post(UPLOAD, headers=headers, content=DATA).status_code == expected
    response = client.post(UPLOAD, headers=trip.OPERATOR, content=DATA)
    assert response.status_code == 200, response.text
    digest = response.json()['asset_sha256']
    assert client.get(f'{UPLOAD}/{digest}/source', headers=trip.VIEWER).status_code == 403
    downloaded = client.get(f'{UPLOAD}/{digest}/source', headers=trip.OPERATOR)
    assert downloaded.content == DATA
    assert downloaded.headers['content-type'] == 'application/octet-stream'
    assert downloaded.headers['x-content-type-options'] == 'nosniff'
    assert 'attachment' in downloaded.headers['content-disposition']
    projected = client.post(f'{UPLOAD}/{digest}/projections', headers=trip.OPERATOR,
                            json=registration().model_dump(mode='json'))
    assert projected.status_code == 200, projected.text
    projection = projected.json()
    assert client.get('/api/fleet/site-map/drawing-projections/' + projection['projection_sha256'],
                      headers=trip.VIEWER).json() == projection
    assert all('path' not in str(event['detail']) for event in store.events() if 'drawing' in event['action'])


def test_chunked_upload_enforces_actual_bytes(tmp_path, monkeypatch):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    routes = importlib.import_module('fleet.server.site_map_drawing_routes')
    monkeypatch.setattr(routes, 'MAX_SOURCE_BYTES', 20)
    active, draft = store.active_view(), store.draft_view()
    response = client.post(UPLOAD, headers=trip.OPERATOR, content=iter([b'x' * 11, b'y' * 11]))
    assert response.status_code == 413
    assert store.active_view() == active and store.draft_view() == draft
    assert not list(assets.root.glob('*.tmp'))


def test_retry_deduplicates_and_restart_preserves_source(tmp_path):
    module = asset_module()
    assets = module.SiteMapAssetStore(tmp_path / 'assets')
    path = tmp_path / 'input.stl'
    path.write_bytes(DATA)
    one = assets.put_stl(path)
    assert assets.put_stl(path) == one
    projection = assets.project(one['asset_sha256'], registration())
    reopened = module.SiteMapAssetStore(assets.root)
    assert reopened.source(one['asset_sha256']).read_bytes() == DATA
    assert reopened.projection(projection['projection_sha256']) == projection
    assert len(list(assets.root.glob('*.stl'))) == 1
    link = assets.root / ('f' * 64 + '.stl')
    link.symlink_to(path)
    with pytest.raises(SiteMapError):
        reopened.source('f' * 64)
    with pytest.raises(SiteMapError):
        reopened.source('../input')


def test_worker_timeout_and_busy_are_bounded(tmp_path, monkeypatch):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    assert assets.slot.acquire(blocking=False)
    try:
        assert client.post(UPLOAD, headers=trip.OPERATOR, content=DATA).status_code == 429
    finally:
        assets.slot.release()
    killed = []
    class Worker:
        returncode = -9
        def communicate(self, **kwargs):
            assert kwargs['timeout'] == 5
            raise subprocess.TimeoutExpired('converter', 5)
        def kill(self):
            killed.append(True)
        def wait(self):
            return -9
    monkeypatch.setattr(asset_module().subprocess, 'Popen', lambda *a, **kw: Worker())
    response = client.post(UPLOAD, headers=trip.OPERATOR, content=DATA)
    assert response.status_code == 503 and killed
    assert assets.slot.acquire(blocking=False)
    assets.slot.release()


@pytest.mark.parametrize('failure', [asyncio.CancelledError, TimeoutError])
def test_cancelled_or_slow_upload_releases_slot(tmp_path, monkeypatch, failure):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    endpoint = next(r.endpoint for r in client.app.routes if r.path == UPLOAD)
    class Request:
        headers = {}
        async def stream(self):
            yield b'partial'
            raise failure()
    async def run():
        if failure is asyncio.CancelledError:
            with pytest.raises(asyncio.CancelledError):
                await endpoint(Request(), SimpleNamespace(principal_id='bob'))
        else:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as error:
                await endpoint(Request(), SimpleNamespace(principal_id='bob'))
            assert error.value.status_code == 503
    asyncio.run(run())
    assert assets.slot.acquire(blocking=False)
    assets.slot.release()
    assert not list(assets.root.glob('*.tmp'))


def test_disk_full_preserves_map(tmp_path, monkeypatch):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    before_active, before_draft = store.active_view(), store.draft_view()
    monkeypatch.setattr(asset_module(), 'MAX_STORE_BYTES', 10)
    response = client.post(UPLOAD, headers=trip.OPERATOR, content=DATA)
    assert response.status_code == 507
    assert store.active_view() == before_active and store.draft_view() == before_draft


def test_missing_or_mismatched_reference_cannot_save_or_activate(tmp_path, monkeypatch):
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    body = trip._line()
    body.update(drawing={'asset_sha256': 'a' * 64, 'projection_sha256': 'b' * 64},
                survey={'revision': 'b' * 64, 'origin': [0, 0], 'heading_rad': 0,
                        'scale_source': 'measured', 'measured_distance_m': 1,
                        'description': 'measured CAD', 'reviewed': False})
    before = store.draft_view()
    with pytest.raises(SiteMapError):
        store.save_draft(SiteMap.model_validate(body), expected_revision=None, principal_id='bob')
    assert store.draft_view() == before
    uploaded = client.post(UPLOAD, headers=trip.OPERATOR, content=DATA).json()
    projection = assets.project(uploaded['asset_sha256'], registration())
    body['drawing'] = {k: projection[k] for k in ('asset_sha256', 'projection_sha256')}
    body['survey']['revision'] = projection['projection_sha256']
    body['map_id'] = 'new-drawing-frame'
    saved = store.save_draft(SiteMap.model_validate(body), expected_revision=None, principal_id='bob')
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved['revision'], principal_id='bob', route_active=False)
    assert error.value.code == 'SITE_MAP_SURVEY_UNREVIEWED'
    assets.source(uploaded['asset_sha256']).unlink()
    with pytest.raises(SiteMapError):
        store.save_profile('missing', name='Missing', site_map=SiteMap.model_validate(body),
                           expected_revision=None, principal_id='bob')
