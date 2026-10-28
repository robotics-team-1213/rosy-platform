"""No-JSON first use, private proof, activation and normal archive lifecycle."""
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import threading
import time

import pytest

from review_app import make_server
from test_review_app import open_store
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401
from test_storage_jobs import Remote
from test_learning_collaboration import request


@pytest.fixture
def setup_server(tmp_path, accounts, pool_setup, monkeypatch):
    _, actor, config, now = pool_setup
    for quota in config['quotas'].values(): quota['remaining_bytes'] = 1048576
    remote = Remote()
    if importlib.util.find_spec('storage_setup'):
        import storage_setup
        original = storage_setup.StorageSetup.__init__
        def configured(self, *args, **kwargs):
            kwargs.update(clock=lambda: now[0], transport=remote)
            original(self, *args, **kwargs)
        monkeypatch.setattr(storage_setup.StorageSetup, '__init__', configured)
    folder = tmp_path / 'review'; folder.mkdir()
    store = open_store(folder)
    @contextmanager
    def running(**server_options):
        server = make_server(store, 0, accounts=accounts, **server_options)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try: yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    body = dict(revision=0, targets=config['targets'], quotas=config['quotas'], reserve_bytes=0,
                cache_policy=dict(enabled=False, max_bytes=1048576))
    return running, body, remote, store.db.parent, now


def session_for(url, accounts, name='alice'):
    session, _ = sign_in(accounts, name)
    token = request(url, '/api/accounts/session', session)[1]['token']
    return session, token


def idle(url, session):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, data = request(url, '/api/learning/storage/settings', session)
        assert status == 200
        if not data.get('operation'): return data
        time.sleep(.02)
    pytest.fail('storage setup operation did not finish')


def test_no_json_http_setup_verifies_activates_prepares_and_archives(setup_server, accounts):
    running, body, remote, folder, now = setup_server
    with running() as url:
        assert request(url, '/api/learning/storage/settings')[0] == 401
        session, token = session_for(url, accounts)
        status, data = request(url, '/api/learning/storage/settings', session)
        assert status == 200 and data['can_manage'] and not data['enabled']
        assert str(folder) not in json.dumps(data) and 'hf_0' not in json.dumps(data)
        assert request(url, '/api/learning/storage/settings', session, body)[0] == 403
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 200
        assert request(url, '/api/learning/storage/settings/activate', session, dict(revision=1), token)[0] == 400
        assert request(url, '/api/learning/storage/settings/verify', session, dict(revision=1, confirm=True), token)[0] == 202
        assert idle(url, session)['result']['status'] == 'verified'
        assert request(url, '/api/learning/storage/settings/activate', session, dict(revision=1), token)[0] == 200
        assert request(url, '/api/learning/storage/pool', session)[1]['enabled'] is True
        exports = folder / 'storage-data' / 'exports'
        data = exports / 'episode-one'; data.mkdir(); (data / 'episode.json').write_text('{"frames":5}')
        status, sources = request(url, '/api/learning/storage/sources', session)
        assert status == 200 and any(row['artifact_id'] == 'episode-one' for row in sources['folders'])
        prepare = dict(kind='folder', artifact_id='episode-one', profile='dataset',
            provenance=dict(source_revision='c' * 40), confirm_completed=True, archive=True)
        assert request(url, '/api/learning/storage/sources/prepare', session, prepare, token)[0] == 202
        state = idle(url, session)
        assert state['result']['status'] == 'verified' and state['result']['bytes_verified']
        assert (data / 'storage-source.json').is_file()
        prefix = '/api/learning/storage/jobs/' + state['result']['id']
        assert request(url, prefix + '/reclaim', session, dict(confirm=state['result']['id']), token)[0] == 202
        from test_storage_jobs_http import finished
        assert finished(url, session, state['result']['id'])['local_present'] is False
        assert request(url, prefix + '/restore', session, {}, token)[0] == 202
        assert finished(url, session, state['result']['id'])['local_present'] is True
    with running() as url:
        session, token = session_for(url, accounts)
        assert request(url, '/api/learning/storage/settings', session)[1]['enabled'] is True
        assert request(url, '/api/learning/storage/jobs', session)[1]['jobs']
        assert request(url, '/api/learning/storage/settings', session, dict(body, revision=2, targets=[], quotas={}), token)[0] == 200
        assert request(url, '/api/learning/storage/jobs', session)[1]['jobs']
        assert request(url, prefix + '/reclaim', session, dict(confirm=state['result']['id']), token)[0] == 202
        assert finished(url, session, state['result']['id'])['local_present'] is False
        assert request(url, prefix + '/restore', session, {}, token)[0] == 202
        assert finished(url, session, state['result']['id'])['local_present'] is True


def test_setup_routes_preserve_roles_csrf_and_fenced_updates(setup_server, accounts):
    running, body, remote, folder, now = setup_server
    with running() as url:
        session, token = session_for(url, accounts)
        bob, bob_token = session_for(url, accounts, 'bob')
        public = request(url, '/api/learning/storage/settings', bob)[1]
        assert public['can_manage'] is False and 'targets' not in public
        assert request(url, '/api/learning/storage/settings', bob, body, bob_token)[0] == 403
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 200
        assert request(url, '/api/learning/storage/settings', session, body, token)[0] == 400
        assert request(url, '/api/learning/storage/settings/verify', session, dict(revision=1), token)[0] == 400
        assert remote.commits == 0
        bad = dict(kind='folder', artifact_id='../private', profile='dataset', provenance={}, confirm_completed=True, archive=True)
        assert request(url, '/api/learning/storage/sources/prepare', session, bad, token)[0] == 400
        assert not (folder.parent / 'private').exists()


def test_setup_filesystem_failure_does_not_expose_host_paths(setup_server, accounts, monkeypatch):
    from storage_setup import StorageSetup
    running, body, remote, folder, now = setup_server
    def unavailable(*args): raise OSError('private-host-path-must-not-leak')
    monkeypatch.setattr(StorageSetup, '_directories', unavailable)
    with running() as url:
        session, token = session_for(url, accounts)
        status, result = request(url, '/api/learning/storage/settings', session, body, token)
        assert status == 400 and 'private-host-path-must-not-leak' not in json.dumps(result)


@pytest.mark.parametrize('width,theme', [(320, 'light'), (1440, 'dark')])
def test_setup_browser_completes_first_use_without_json(setup_server, accounts, width, theme):
    from browser_harness import browser_tests_enabled, open_page, save_temp_screenshot
    if not browser_tests_enabled(): pytest.skip('requires explicit Chromium browser run')
    playwright = pytest.importorskip('playwright.sync_api')
    running, body, remote, folder, now = setup_server
    now[0] = int(time.time())
    with running() as url, playwright.sync_playwright() as runtime:
        browser, page, errors = open_page(runtime, width, 900, url=url)
        try:
            session, _ = session_for(url, accounts)
            page.context.add_cookies([dict(name='rosy_learning_session', value=session, url=url)])
            page.goto(url + '/learning', wait_until='networkidle')
            if theme == 'light': page.locator('[data-theme-cycle]').click()
            playwright.expect(page.locator('html')).to_have_attribute('data-theme', theme)
            expect = playwright.expect
            expect(page.locator('#storage-setup')).to_be_visible()
            page.locator('#storage-settings-open').click()
            for target in body['targets']:
                page.get_by_role('button', name='저장 대상 추가', exact=True).click()
                row = page.locator('.storage-settings-target').last
                row.locator('[data-field=connection_id]').select_option(target['connection_id'])
                row.locator('[data-field=repo_id]').fill(target['repo_id'])
                row.locator('[data-field=repo_id]').press('Tab')
            expect(page.locator('#storage-verify')).to_be_disabled()
            for row in page.locator('.storage-quota').all():
                row.locator('[data-field=remaining_bytes]').fill('1')
                row.locator('[data-field=reserve_bytes]').fill('0')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#storage-settings-open').scroll_into_view_if_needed()
            save_temp_screenshot(page, f'learning-storage-settings-{width}-{theme}.png')
            page.get_by_role('button', name='저장 설정 저장', exact=True).click()
            expect(page.locator('#storage-setup-status')).to_contain_text('검증')
            page.locator('#storage-check-consent').check()
            page.get_by_role('button', name='소량 전송으로 연결 검증', exact=True).click()
            expect(page.locator('#storage-setup-result')).to_contain_text('검증 완료', timeout=15000)
            page.get_by_role('button', name='새 보관 활성화', exact=True).click()
            expect(page.locator('#storage-setup-status')).to_contain_text('활성화')
            data = folder / 'storage-data/exports/episode-ui'; data.mkdir()
            (data / 'episode.json').write_text('{"frames":5}')
            page.get_by_role('button', name='준비할 자료 새로 확인', exact=True).click()
            page.locator('#storage-prepare-folder').select_option('episode-ui')
            page.locator('#storage-prepare-profile').select_option('dataset')
            page.locator('#storage-source-revision').fill('c' * 40)
            page.locator('#storage-completed-consent').check()
            page.get_by_role('button', name='준비하고 보관', exact=True).click()
            expect(page.locator('#storage-setup-result')).to_contain_text('원격 검증 완료', timeout=15000)
            state = idle(url, session); job_id = state['result']['id']
            row = page.locator('[data-job="' + job_id + '"]')
            expect(row).to_contain_text('원격 검증 완료')
            row.get_by_role('button', name='로컬 정리', exact=True).click()
            page.locator('#storage-confirm-id').fill(job_id)
            page.get_by_role('button', name='확인한 로컬 사본 정리', exact=True).click()
            expect(row).to_contain_text('로컬 사본 없음')
            row.get_by_role('button', name='필요 자료 복원', exact=True).click()
            expect(row).to_contain_text('로컬 사본 있음')
            assert remote.commits == 3 and not errors
            page.locator('#storage-setup-title').scroll_into_view_if_needed()
            save_temp_screenshot(page, f'learning-storage-setup-{width}-{theme}.png')
            overflow = page.evaluate('''[...document.querySelectorAll('body *')].filter(e=>{
              const r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1;
            }).map(e=>({tag:e.tagName,id:e.id,left:e.getBoundingClientRect().left,
              right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,
              parent:e.parentElement.id||e.parentElement.tagName,
              parentWidth:e.parentElement.getBoundingClientRect().width,
              parentDisplay:getComputedStyle(e.parentElement).display,
              parentDirection:getComputedStyle(e.parentElement).flexDirection,
              parentWrap:getComputedStyle(e.parentElement).flexWrap,
              parentColumns:getComputedStyle(e.parentElement).gridTemplateColumns,
              parentHeight:getComputedStyle(e.parentElement).height,
              basis:getComputedStyle(e).flexBasis})).slice(0,12)''')
            fits = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if not fits: print('overflow: ' + json.dumps(overflow))
            assert fits, overflow
            for identifier in ('storage-settings-save', 'storage-verify', 'storage-activate', 'storage-prepare-submit'):
                button = page.locator('#' + identifier)
                if button.is_visible(): assert button.bounding_box()['height'] >= 44
            page.locator('#storage-setup').scroll_into_view_if_needed()
            save_temp_screenshot(page, f'learning-storage-setup-{width}-{theme}.png')
            page.reload(wait_until='networkidle')
            expect(page.locator('#storage-setup-status')).to_contain_text('활성화')
            page.locator('#storage-settings-open').click()
            page.locator('#storage-cache-limit').fill('11')
            expect(page.locator('#storage-verify')).to_be_disabled()
            expect(page.locator('#storage-prepare-submit')).to_be_disabled()
        finally: browser.close()
