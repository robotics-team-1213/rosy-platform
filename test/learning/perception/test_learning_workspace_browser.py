"""The next real task stays above the fold and training has its own app view."""
import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 320])
def test_workspace_next_action_and_training_navigation(browser_workspace, width):
    page, _store, expect = browser_workspace
    origin = page.url.rstrip('/')
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
