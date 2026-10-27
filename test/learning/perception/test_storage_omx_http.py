"""Real HTTP/Chromium handoff; only HF transport is replaced with test-owned bytes."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_storage_omx import registered
from test_storage_setup_http import setup_server, session_for, idle
from test_learning_accounts import accounts  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401
from test_learning_collaboration import request


@pytest.fixture
def archive_server(setup_server, registered, accounts):
    running, settings, remote, folder, now = setup_server
    center, row, source = registered
    def bind(project):
        with center.catalog.connect() as db: center.catalog._archive_project(db, project)
    center.bind_workspace = bind
    center.profiles = SimpleNamespace(list=lambda: [])
    center.snapshot = lambda: dict(datasets=[row], methods={}, runs=[dict(
        id=row['id'], name='Converted fixture', execution_mode='native_export', status='succeeded',
        prepared_id='fixture-preparation', progress=dict(phase='completed'),
        result=dict(dataset_id=row['id'], dataset_revision=row['revision'], act_only=True))])
    with running(omx_center=center) as url:
        session, token = session_for(url, accounts)
        assert request(url, '/api/learning/storage/settings', session, settings, token)[0] == 200
        assert request(url, '/api/learning/storage/settings/verify', session, dict(revision=1, confirm=True), token)[0] == 202
        assert idle(url, session)['result']['status'] == 'verified'
        assert request(url, '/api/learning/storage/settings/activate', session, dict(revision=1), token)[0] == 200
        yield url, session, token, row, source, remote, folder


def test_registered_source_http_preserves_authority_and_requires_explicit_post(archive_server, accounts):
    url, session, token, row, source, remote, folder = archive_server
    commits = remote.commits
    status, listing = request(url, '/api/learning/storage/sources', session)
    assert status == 200 and listing['datasets'][0]['revision'] == row['revision']
    assert str(source) not in json.dumps(listing)
    assert remote.commits == commits and not list((folder / 'storage-data/exports').glob('omx-*'))
    body = dict(kind='omx', dataset_id=row['id'], revision=row['revision'], confirm_completed=True, archive=True)
    assert request(url, '/api/learning/storage/sources/prepare', session, body)[0] == 403
    assert request(url, '/api/learning/storage/sources/prepare', session, dict(body, confirm_completed=False), token)[0] == 400
    bob, bob_token = session_for(url, accounts, 'bob')
    assert request(url, '/api/learning/storage/sources', bob)[0] == 403
    assert request(url, '/api/learning/storage/sources/prepare', bob, body, bob_token)[0] == 403
    assert remote.commits == commits
    assert request(url, '/api/learning/storage/sources/prepare', session, dict(body, revision='0' * 64), token)[0] == 202
    assert idle(url, session)['error'] and remote.commits == commits
    assert request(url, '/api/learning/storage/sources/prepare', session, body, token)[0] == 202
    result = idle(url, session)['result']
    assert result['bytes_verified'] and result['provenance']['dataset_id'] == row['id']
    assert result['provenance']['source_revision'] == row['revision']


@pytest.mark.parametrize('width,theme', [(320, 'light'), (1440, 'dark')])
def test_conversion_card_to_exact_confirmed_archive_in_chromium(archive_server, width, theme):
    from browser_harness import browser_tests_enabled, open_page
    if not browser_tests_enabled(): pytest.skip('requires explicit Chromium browser run')
    playwright = pytest.importorskip('playwright.sync_api')
    url, session, token, row, source, remote, folder = archive_server
    commits = remote.commits
    with playwright.sync_playwright() as runtime:
        browser, page, errors = open_page(runtime, width, 1000, url=url)
        try:
            page.context.add_cookies([dict(name='rosy_learning_session', value=session, url=url)])
            page.goto(url + '/learning/omx#dataset-section', wait_until='networkidle')
            expect = playwright.expect
            expect(page.locator('#export-runs')).to_be_visible()
            page.get_by_role('link', name='이 데이터 HF 보관 준비', exact=True).click()
            expect(page.locator('#storage-prepare-kind')).to_have_value('omx')
            expect(page.locator('#storage-prepare-dataset')).to_have_value(row['id'])
            expect(page.locator('#storage-omx-revision')).to_contain_text(row['revision'])
            expect(page.locator('#storage-preparation')).to_be_visible()
            expect(page.locator('#storage-completed-consent')).not_to_be_checked()
            expect(page.locator('#storage-prepare-submit')).to_be_disabled()
            assert remote.commits == commits
            if theme == 'light': page.locator('[data-theme-cycle]').click()
            expect(page.locator('html')).to_have_attribute('data-theme', theme)
            page.locator('#storage-completed-consent').check()
            expect(page.locator('#storage-prepare-submit')).to_be_enabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if os.environ.get('ROSY_SCREENSHOT_DIR'):
                capture = Path(os.environ['ROSY_SCREENSHOT_DIR']).expanduser()
                capture.mkdir(parents=True, exist_ok=True)
                page.locator('#storage-preparation').scroll_into_view_if_needed()
                page.screenshot(path=str(capture / f'omx-archive-{width}-{theme}.png'))
            page.locator('#storage-prepare-submit').click()
            expect(page.locator('#storage-setup-result')).to_contain_text('원격 검증 완료', timeout=15000)
            result = idle(url, session)['result']
            assert result['provenance']['dataset_id'] == row['id']
            assert result['provenance']['source_revision'] == row['revision']
            assert remote.commits == commits + 1 and not errors
            assert not (source / 'storage-source.json').exists()
        finally: browser.close()


def test_missing_handoff_revision_cannot_silently_select_other_data(archive_server):
    from browser_harness import browser_tests_enabled, open_page
    if not browser_tests_enabled(): pytest.skip('requires explicit Chromium browser run')
    playwright = pytest.importorskip('playwright.sync_api')
    url, session, token, row, source, remote, folder = archive_server
    commits = remote.commits
    with playwright.sync_playwright() as runtime:
        browser, page, errors = open_page(runtime, 1100, 900, url=url)
        try:
            page.context.add_cookies([dict(name='rosy_learning_session', value=session, url=url)])
            page.goto(url + f'/learning?archive=omx&dataset={row["id"]}&revision={"0" * 64}#storage-preparation', wait_until='networkidle')
            expect = playwright.expect
            expect(page.locator('#storage-prepare-kind')).to_have_value('omx')
            expect(page.locator('#storage-prepare-dataset')).to_have_value('')
            expect(page.locator('#storage-source-help')).to_contain_text('버전')
            page.locator('#storage-completed-consent').check()
            expect(page.locator('#storage-prepare-submit')).to_be_disabled()
            assert remote.commits == commits
            page.locator('#storage-prepare-dataset').select_option(row['id'])
            expect(page.locator('#storage-omx-revision')).to_contain_text(row['revision'])
            expect(page.locator('#storage-prepare-submit')).to_be_disabled()
            expect(page.locator('#storage-completed-consent')).not_to_be_checked()
            page.locator('#storage-completed-consent').check()
            expect(page.locator('#storage-prepare-submit')).to_be_enabled()
            assert not errors
        finally: browser.close()
