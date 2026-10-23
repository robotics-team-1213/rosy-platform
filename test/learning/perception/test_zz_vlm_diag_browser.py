import threading
import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import make_server
from test_review_app import open_store

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='diag')


@pytest.mark.parametrize('route', ['/learning/vlm', '/learning/sim'])
def test_diag(tmp_path, route):
    playwright = pytest.importorskip('playwright.sync_api')
    server = make_server(open_store(tmp_path), free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    events = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.on('request', lambda r: events.append('REQ ' + r.url))
            page.on('requestfinished', lambda r: events.append('FIN ' + r.url))
            page.on('requestfailed', lambda r: events.append('FAIL ' + r.url + ' ' + str(r.failure)))
            page.on('load', lambda: events.append('LOAD'))
            page.on('domcontentloaded', lambda: events.append('DCL'))
            page.on('console', lambda m: events.append('CONSOLE ' + m.text))
            page.on('pageerror', lambda e: events.append('ERR ' + str(e)))
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}{route}', wait_until='networkidle', timeout=8000)
                events.append('IDLE')
            except Exception as error:
                events.append('TIMEOUT ' + type(error).__name__)
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
    reqs = {e[4:] for e in events if e.startswith('REQ ')}
    done = {e[4:] for e in events if e.startswith('FIN ')} | {e[5:].split(' ')[0] for e in events if e.startswith('FAIL ')}
    print('\n'.join(events)); print('PENDING', sorted(reqs - done))
    assert 'IDLE' in events, ('PENDING', sorted(reqs - done), [e for e in events if not e.startswith(('REQ', 'FIN'))])
