"""Shared Learning navigation works without losing the review editor context."""
from urllib.parse import parse_qs, urlsplit

import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 320])
def test_learning_shell_navigation_and_review_context(browser_workspace, width):
    page, _, expect = browser_workspace
    origin = urlsplit(page.url)
    base = f'{origin.scheme}://{origin.netloc}'
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(base + '/?frame=0&filter=all', wait_until='networkidle')
    nav = page.get_by_role('navigation', name='Learning 주 메뉴', exact=True)
    expect(nav).to_be_visible()
    assert nav.locator('a').all_text_contents() == ['작업', '자료', '검수', '학습·결과']
    expect(nav.locator('[aria-current="page"]')).to_have_text('검수')
    expect(page.locator('#canvas')).to_be_visible()
    selection = parse_qs(urlsplit(page.url).query)
    assert selection.get('frame') == ['0']
    assert selection.get('filter', ['all']) == ['all']
    assert page.locator('learning-connections').count() == 1
    for link in nav.locator('a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
    training = nav.get_by_role('link', name='학습·결과', exact=True)
    training.focus()
    expect(training).to_be_focused()
    page.keyboard.press('Enter')
    expect(page).to_have_url(base + '/learning?view=training')
    expect(page.get_by_role('navigation', name='Learning 주 메뉴').locator('[aria-current="page"]')).to_have_text('학습·결과')
    page.goto(base + '/pixels?frame=0&filter=pending', wait_until='networkidle')
    subnav = page.get_by_role('navigation', name='검수 종류', exact=True)
    expect(subnav.get_by_role('link', name='픽셀 검수', exact=True)).to_have_attribute('aria-current', 'page')
    expect(subnav.get_by_role('link', name='객체 검수', exact=True)).to_have_attribute('href', '/?frame=0&filter=pending')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
