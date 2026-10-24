"""D-857 §3: the five loop stages in the Learning rail; every page is at most two clicks away."""
from urllib.parse import urlsplit

import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')

# (rail link name, sub-menu name or None, sub-menu link or None, address)
STAGE_PAGES = [('홈', None, None, '/learning'), ('자료 등록', '자료 하위 메뉴', '자료 등록', '/catalog'),
               ('자료 등록', '자료 하위 메뉴', '카메라 맞춤', '/learning/camera'), ('정답 달기', '정답 하위 메뉴', '객체 검수', '/'),
               ('정답 달기', '정답 하위 메뉴', '픽셀 검수', '/pixels'), ('정답 달기', '정답 하위 메뉴', '로봇암 시범 검수', '/learning/omx'),
               ('정답 달기', '정답 하위 메뉴', 'VLM 판단', '/learning/vlm'), ('학습 실행', '학습 하위 메뉴', '학습 과제', '/learning/tasks'),
               ('학습 실행', '학습 하위 메뉴', '인식 학습', '/learning'), ('학습 실행', '학습 하위 메뉴', 'SIM 실험', '/learning/sim'),
               ('평가·승격', None, None, '/learning/evaluate')]


@pytest.mark.parametrize('width', [1280, 390])
def test_five_stage_menu_reaches_every_page_in_two_clicks(browser_workspace, width):
    page, _, expect = browser_workspace
    origin = urlsplit(page.url)
    base = f'{origin.scheme}://{origin.netloc}'
    page.set_viewport_size({'width': width, 'height': 844})
    rail = page.locator('.ui-rail-nav')
    for stage, menu, sub, target in STAGE_PAGES:
        page.goto(base + '/learning/evaluate', wait_until='networkidle')
        with page.expect_navigation(wait_until='load'):
            rail.get_by_role('link', name=stage, exact=True).click()
        if sub:
            subnav = page.get_by_role('navigation', name=menu, exact=True)
            with page.expect_navigation(wait_until='load'):
                subnav.get_by_role('link', name=sub, exact=True).click()
        assert urlsplit(page.url).path == target, page.url  # editors add their own frame/filter keys
        assert page.title().startswith('Rosy Learning — '), (target, page.title())
        link = rail.locator('[aria-current]')
        # "page" only when the rail link is this very page; a stage that holds it is "true".
        entries = ('/learning', '/catalog', '/', '/learning/tasks', '/learning/evaluate')
        assert link.get_attribute('aria-current') == ('page' if target in entries else 'true'), target
        assert link.bounding_box()['height'] >= 44
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), target
    page.goto(base + '/learning', wait_until='networkidle')
    expect(page.locator('.domain-row')).to_have_count(6)
    expect(page.locator('.domain-row[data-domain="object"] .domain-stage')).to_have_count(6)
    expect(page.locator('.domain-row[data-domain="vlm"] .domain-blocked')).to_have_text('VLM 질문 자료가 없습니다.')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.goto(base + '/learning/evaluate?domain=vlm', wait_until='networkidle')
    expect(page.locator('#evaluate-filter')).to_contain_text('VLM 판단만')
    expect(page.locator('.evaluate-source[data-domain="vlm"]')).to_contain_text('VLM 질문 자료가 없습니다.')
    assert page.locator('.evaluate-source[data-domain="lane"]').count() == 0
    expect(page.locator('#promote-request')).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
