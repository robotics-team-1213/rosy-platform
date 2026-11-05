"""Both review screens expose and retain their configured data scope."""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace
from test_review_cycle import CLASSES
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('path,title', [('/', '#frame-title'), ('/pixels', '#pixel-title')])
def test_folder_selection_reloads_scoped_frames_and_clears_stale_navigation(browser_workspace, path, title):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    with store.connect() as db:
        db.execute('INSERT INTO metadata VALUES (?,?)', ('image_folders', json.dumps([
            {'id': 'first', 'label': '첫 자료', 'path': '/private/first'},
            {'id': 'second', 'label': '다음 자료', 'path': '/private/second'}])))
        db.execute("UPDATE frames SET status='pending',source=json_set(source,'$.source_session',CASE WHEN id=0 THEN 'folder:first:run' ELSE 'folder:second:run' END)")
        db.execute('INSERT INTO frames SELECT 2,source,review,status,version FROM frames WHERE id=0')
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('review_source_prefix',?)", (json.dumps('folder:first:'),))
    base = page.url.split('?')[0].rstrip('/')
    page.goto(base + path + '?frame=2', wait_until='networkidle')
    expect(page.locator(title)).to_contain_text('사진 2')
    expect(page.locator('[aria-label="검수 작업 범위"]')).to_contain_text('첫 자료 · 2장')
    page.locator('#review-folder').select_option('second')
    expect(page.locator(title)).to_contain_text('사진 1')
    expect(page.locator('[aria-label="검수 작업 범위"]')).to_contain_text('다음 자료 · 1장')
    assert parse_qs(urlparse(page.url).query)['folder_id'] == ['second']
    assert page.locator('#review-folder option').all_text_contents() == ['첫 자료', '다음 자료', '전체 자료']
    assert '/private/' not in page.locator('[aria-label="검수 작업 범위"]').inner_html()
    if path == '/pixels':
        page.locator('#pixel-class').select_option('3')
        page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
        expect(page.locator('#review-folder')).to_be_disabled()
        page.keyboard.press('Escape')
        expect(page.locator('#review-folder')).to_be_enabled()
    page.goto(page.url + '&source_session=folder%3Asecond%3Arun', wait_until='networkidle')
    other = '/' if path == '/pixels' else '/pixels'
    page.locator('.review-kinds a').filter(has_text='객체 검수' if other == '/' else '픽셀 검수').click()
    expect(page.locator('#frame-title' if other == '/' else '#pixel-title')).to_contain_text('사진 1')
    expect(page.locator('#review-folder')).to_have_value('second')
    query = parse_qs(urlparse(page.url).query)
    assert query['frame'] == ['1']
    assert query['source_session'] == ['folder:second:run']
