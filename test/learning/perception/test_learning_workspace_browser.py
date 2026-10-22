"""The next real task stays above the fold and training has its own app view."""
import re

import pytest
from urllib.parse import urlsplit

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 320])
def test_workspace_next_action_and_training_navigation(browser_workspace, width):
    page, _store, expect = browser_workspace
    address = urlsplit(page.url)
    origin = f'{address.scheme}://{address.netloc}'
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(origin + '/learning', wait_until='networkidle')
    expect(page.get_by_role('heading', name='작업', exact=True)).to_be_visible()
    action = page.locator('#pipeline-link')
    expect(action).to_have_text('픽셀 검수 시작')
    expect(action).to_be_visible()
    box = action.bounding_box()
    assert box['y'] + box['height'] <= 844
    expect(page.locator('#workspace-review')).to_be_visible()
    page.get_by_role('navigation', name='Learning 주 메뉴').get_by_role('link', name='학습·결과', exact=True).click()
    expect(page.get_by_role('heading', name='학습·결과', exact=True)).to_be_visible()
    expect(page.locator('#workspace-review')).to_be_hidden()
    expect(page.locator('#workspace-results')).to_be_visible()
    expect(page.get_by_role('button', name='학습 시작', exact=True)).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width == 1440:
        expect(page.locator('#work-preview')).to_be_visible()
    page.route('**/api/learning', lambda route: route.fulfill(
        status=503, content_type='application/json', body='{}'))
    page.locator('#refresh').click()
    expect(page.locator('#pipeline-title')).to_have_text('작업 상태를 확인하지 못했습니다')
    expect(page.locator('#pipeline-status')).to_contain_text('서비스를 사용할 수 없습니다')
    expect(page.locator('#work-preview')).to_be_hidden()
    expect(page.locator('#work-summary')).to_be_empty()


def test_learning_summary_separates_review_from_training(browser_workspace):
    page, store, expect = browser_workspace
    store.update(0, {'version': store.get(0)['version'], 'action': 'reopen'})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    expect(page.locator('#review-stage-summary')).to_contain_text('등록 2장')
    expect(page.locator('#training-data-state')).to_contain_text('픽셀 승인 0장')
    expect(page.locator('[data-stage="training"]')).to_have_attribute('data-state', 'waiting')
    expect(page.locator('[data-stage="evaluation"]')).to_have_attribute('data-state', 'waiting')
    expect(page.locator('#pipeline-link')).to_have_attribute('href', re.compile(r'/pixels\?filter=pending'))
    expect(page.locator('#object-review-link')).to_contain_text(re.compile('객체 (검수 열기|초안 확인)'))
    expect(page.locator('#pixel-review-link')).to_contain_text(re.compile('픽셀 (검수 열기|초안 확인)'))
    page.locator('#object-review-link').click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('#approve')).to_be_visible()
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    page.locator('#pixel-review-link').click()
    expect(page.locator('#pixel-approve')).to_be_visible()
