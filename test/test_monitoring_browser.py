"""Real Chromium reads the independent Monitoring backend; never intercept its API."""

import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, launch_options, safe_listener


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in real Chromium Monitoring scenario')
ROOT = Path(__file__).resolve().parents[1]
KEY_A, KEY_B = 'a' * 32, 'b' * 32


@pytest.fixture
def monitoring_backend(tmp_path):
    from rosy.monitoring.config import MonitoringConfig, load_credentials
    from rosy.monitoring.service import Collector, create_app
    from rosy.monitoring.store import MonitoringStore

    sources = []
    for site in ('a', 'b'):
        path = tmp_path / f'host-{site}.json'
        path.write_text(json.dumps({'time': int(time.time()), 'fixed': [], 'drift': [],
                                    'awaiting_approval': [], 'errors': [] if site == 'a' else ['private owner detail']}))
        sources.append({'id': f'host-{site}', 'site_id': f'site-{site}', 'kind': 'host_state', 'path': str(path)})
    config = MonitoringConfig(collector_id='browser-monitoring', site_id='site-a', sources=sources,
                              readers=[{'principal_id': f'operator-{site}', 'token_env': f'READ_{site.upper()}',
                                        'sites': [f'site-{site}']} for site in ('a', 'b')])
    store = MonitoringStore(tmp_path / 'monitoring.sqlite3', config.collector_id)
    collector = Collector(config, load_credentials(config, {'READ_A': KEY_A, 'READ_B': KEY_B}), store)
    app = create_app(collector)
    listener = safe_listener()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False,
                                         proxy_headers=False, timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield origin
    finally:
        server.should_exit = True
        worker.join(15)
        listener.close()
        assert not worker.is_alive()


@pytest.fixture
def monitoring_page(monitoring_backend):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        options = launch_options()
        options['args'] = [f'--explicitly-allowed-ports={urlsplit(monitoring_backend).port}']
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            page.goto(monitoring_backend + '/health')
            yield page
        finally:
            browser.close()


def read(page, path, key):
    return page.evaluate('''async ({path, key}) => {
      const response = await fetch(path, {cache: 'no-store', credentials: 'omit',
        headers: key ? {Authorization: 'Bearer ' + key} : {}});
      return {status: response.status, cache: response.headers.get('cache-control'), body: await response.json()};
    }''', {'path': path, 'key': key})


def test_browser_reads_scoped_cache_without_fleet(monitoring_page):
    response = read(monitoring_page, '/api/monitoring/v1/snapshot', KEY_A)
    assert response['status'] == 200 and response['cache'] == 'no-store'
    assert response['body']['scope_sites'] == ['site-a']
    assert all(row['site_id'] == 'site-a' for row in response['body']['nodes'])
    assert KEY_A not in json.dumps(response['body'])


def test_browser_cannot_read_another_site_or_without_key(monitoring_page):
    assert read(monitoring_page, '/api/monitoring/v1/snapshot', None)['status'] == 401
    denied = read(monitoring_page, '/api/monitoring/v1/snapshot?site_id=site-b', KEY_A)
    assert denied['status'] == 403 and 'site-b' not in json.dumps(denied['body'])
    other = read(monitoring_page, '/api/monitoring/v1/snapshot', KEY_B)
    assert other['body']['scope_sites'] == ['site-b']


def test_browser_history_keeps_the_same_reader_scope(monitoring_page):
    assert read(monitoring_page, '/api/monitoring/v1/sites/site-b/events', KEY_A)['status'] == 403
    response = read(monitoring_page, '/api/monitoring/v1/sites/site-a/events', KEY_A)
    assert response['status'] == 200 and response['cache'] == 'no-store'
    assert 'private owner detail' not in json.dumps(response['body'])
