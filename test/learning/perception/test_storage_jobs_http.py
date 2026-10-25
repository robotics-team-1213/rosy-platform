"""Storage routes keep project, publish, manage and CSRF authority distinct."""
from contextlib import contextmanager
import json
import threading
import time

import pytest

from review_app import make_server
from test_learning_accounts import accounts, sign_in  # noqa: F401
from test_learning_collaboration import request
from test_review_app import open_store
from test_storage_jobs import jobs_setup  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401


@contextmanager
def running(tmp_path, accounts, storage, jobs):
    folder = tmp_path / 'review'; folder.mkdir()
    server = make_server(open_store(folder), 0, accounts=accounts, storage=storage, storage_jobs=jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def finished(url, session, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, data = request(url, '/api/learning/storage/jobs', session)
        assert status == 200
        job = next(row for row in data['jobs'] if row['id'] == job_id)
        if not job.get('operation'): return job
        time.sleep(.02)
    pytest.fail('storage operation did not finish')


def test_storage_http_archive_reclaim_restore_and_role_boundaries(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    with running(tmp_path, accounts, inventory, build()) as url:
        assert request(url, '/api/learning/storage/pool')[0] == 401
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        status, data = request(url, '/api/learning/storage/pool', session)
        assert status == 200 and len(data['targets']) == 2
        assert str(artifact.parent) not in json.dumps(data) and 'hf_' not in json.dumps(data)
        body = dict(source_id='raw', artifact_id='run-one', profile='isaac')
        assert request(url, '/api/learning/storage/jobs', session, body)[0] == 403
        status, job = request(url, '/api/learning/storage/jobs', session, body, token)
        assert status == 201
        prefix = '/api/learning/storage/jobs/' + job['id']
        assert request(url, prefix + '/run', session, {}, token)[0] == 202
        assert finished(url, session, job['id'])['status'] == 'verified'
        assert request(url, prefix + '/reclaim', session, {'confirm': 'wrong'}, token)[0] == 400
        assert artifact.exists()
        assert request(url, prefix + '/reclaim', session, {'confirm': job['id']}, token)[0] == 202
        assert finished(url, session, job['id'])['local_present'] is False
        assert request(url, prefix + '/restore', session, {}, token)[0] == 202
        assert finished(url, session, job['id'])['local_present'] is True
        bob, _ = sign_in(accounts, 'bob')
        bob_token = request(url, '/api/accounts/session', bob)[1]['token']
        assert request(url, '/api/learning/storage/jobs', bob)[1]['jobs'] == []
        assert request(url, '/api/learning/storage/jobs', bob, body, bob_token)[0] == 403
        assert request(url, prefix + '/pin', bob, {'pinned': True}, bob_token)[0] == 403
        accounts.logout(session)
        assert request(url, '/api/learning/storage/jobs', session)[0] == 401


def test_storage_http_publish_does_not_grant_destructive_manage(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    config = json.loads(accounts.config_path.read_text())
    config['users'][0]['memberships']['one'].remove('manage')
    accounts.config_path.write_text(json.dumps(config))
    # Project connections require their owner's manage grant, so personal ownership is tested separately.
    with running(tmp_path, accounts, inventory, build()) as url:
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        prefix = '/api/learning/storage/jobs/' + 'a' * 32
        assert request(url, prefix + '/reclaim', session, {'confirm': 'a' * 32}, token)[0] == 403
        assert request(url, '/api/learning/storage/cache/reclaim', session, {}, token)[0] == 403


def test_storage_http_unconfigured_pool_preserves_existing_inventory(tmp_path, jobs_setup, accounts):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    inventory.config.pop('pool')
    with running(tmp_path, accounts, inventory, None) as url:
        session, _ = sign_in(accounts, 'alice')
        token = request(url, '/api/accounts/session', session)[1]['token']
        assert request(url, '/api/learning/storage', session)[1]['roots']
        assert request(url, '/api/learning/storage/pool', session)[1]['status'] == 'not_configured'
        assert request(url, '/api/learning/storage/jobs', session, {}, token)[0] == 400


@pytest.mark.parametrize('width', [1440, 320])
def test_storage_browser_capacity_archive_reclaim_restore(tmp_path, jobs_setup, accounts, width):
    from browser_harness import browser_tests_enabled, open_page, save_temp_screenshot
    if not browser_tests_enabled(): pytest.skip('requires explicit Chromium browser run')
    playwright = pytest.importorskip('playwright.sync_api')
    build, actor, remote, artifact, cache, inventory = jobs_setup
    service = build()
    service.pool.config['quotas']['first']['remaining_bytes'] = 0
    with running(tmp_path, accounts, inventory, service) as url:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=url)
            try:
                session, _ = sign_in(accounts, 'alice')
                page.context.add_cookies([dict(name='rosy_learning_session', value=session, url=url)])
                page.goto(url + '/learning', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#storage-targets')).to_contain_text('first')
                expect(page.locator('#storage-targets')).to_contain_text('second')
                page.locator('#storage-source').select_option('raw')
                page.locator('#storage-artifact').fill('run-one')
                page.locator('#storage-profile').select_option('isaac')
                page.get_by_role('button', name='보관 작업 등록', exact=True).click()
                expect(page.locator('#storage-jobs')).to_contain_text('전송 대기')
                page.get_by_role('button', name='전송·검증', exact=True).click()
                expect(page.locator('#storage-jobs')).to_contain_text('원격 검증 완료')
                expect(page.locator('#storage-jobs')).to_contain_text('second/episodes')
                page.get_by_role('button', name='로컬 정리', exact=True).click()
                job_id = service.list(actor)[0]['id']
                expect(page.locator('#storage-confirmation')).to_be_visible()
                page.locator('#storage-confirm-id').fill(job_id)
                page.get_by_role('button', name='확인한 로컬 사본 정리', exact=True).click()
                expect(page.locator('#storage-jobs')).to_contain_text('로컬 사본 없음')
                page.get_by_role('button', name='필요 자료 복원', exact=True).click()
                expect(page.locator('#storage-jobs')).to_contain_text('로컬 사본 있음')
                assert (cache / job_id / 'images/frame.png').read_bytes() == b'frame-bytes'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                save_temp_screenshot(page, f'learning-storage-pool-{width}.png')
                assert not errors
            finally: browser.close()
