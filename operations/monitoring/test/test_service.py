"""The API reads one scoped cache and never performs an upstream request."""

from fastapi.testclient import TestClient

from rosy.monitoring.config import load_credentials
from rosy.monitoring.service import Collector, create_app
from rosy.monitoring.store import MonitoringStore
from test_cache import runtime, observed_node


TOKEN = 'reader-secret-for-tests-only-00000000'


def test_cache_api_auth_scope_errors_and_history(runtime, tmp_path):
    cache, clock = runtime
    credentials = load_credentials(cache.config, {'READ': TOKEN})
    collector = Collector(cache.config, credentials,
                          MonitoringStore(tmp_path / 'monitoring.sqlite3', cache.config.collector_id))
    collector.cache.update_local('pc-a', nodes=(observed_node(),))
    client = TestClient(create_app(collector))
    headers = {'Authorization': f'Bearer {TOKEN}'}
    assert client.get('/health').status_code == 200
    assert client.get('/api/monitoring/v1/snapshot').status_code == 401
    reply = client.get('/api/monitoring/v1/snapshot?site_id=site-a', headers=headers)
    assert reply.status_code == 200 and reply.headers['cache-control'] == 'no-store'
    assert reply.json()['scope_sites'] == ['site-a']
    assert all(item['site_id'] == 'site-a' for item in reply.json()['nodes'])
    denied = client.get('/api/monitoring/v1/snapshot?site_id=secret-site', headers=headers)
    assert denied.status_code == 403 and 'secret-site' not in denied.text
    bad = client.get('/api/monitoring/v1/sites/site-a/events?after=private-value', headers=headers)
    assert bad.status_code == 400 and 'private-value' not in bad.text
    events = client.get('/api/monitoring/v1/sites/site-a/events', headers=headers)
    assert events.status_code == 200 and events.json()['events']
    assert TOKEN not in reply.text + events.text
    assert client.post('/api/monitoring/v1/snapshot', headers=headers).status_code == 405
    assert not any(route.path in {'/docs', '/openapi.json'} for route in client.app.routes)


def test_another_reader_cannot_request_peer_site(runtime, tmp_path):
    cache, clock = runtime
    config = cache.config.model_copy(update={'readers': (
        cache.config.readers[0].model_copy(update={'sites': ('site-a',)}),)})
    collector = Collector(config, load_credentials(config, {'READ': TOKEN}),
                          MonitoringStore(tmp_path / 'monitoring.sqlite3', config.collector_id))
    client = TestClient(create_app(collector))
    headers = {'Authorization': f'Bearer {TOKEN}'}
    assert client.get('/api/monitoring/v1/snapshot', headers=headers).json()['scope_sites'] == ['site-a']
    assert client.get('/api/monitoring/v1/sites/site-b/events', headers=headers).status_code == 403


def test_storage_error_response_does_not_reflect_exception(runtime, tmp_path, monkeypatch):
    cache, clock = runtime
    store = MonitoringStore(tmp_path / 'monitoring.sqlite3', cache.config.collector_id)
    collector = Collector(cache.config, load_credentials(cache.config, {'READ': TOKEN}), store)
    from rosy.monitoring.store import StoreUnavailable
    def broken(*args, **kwargs):
        raise StoreUnavailable()
    monkeypatch.setattr(store, 'events', broken)
    response = TestClient(create_app(collector)).get('/api/monitoring/v1/sites/site-a/events',
                                                     headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 503
    assert response.json() == {'error': {'code': 'MONITORING_STORAGE'}}
