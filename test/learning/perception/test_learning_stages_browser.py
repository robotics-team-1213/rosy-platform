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


@pytest.mark.parametrize('route', ['/', '/pixels'])
def test_answer_links_never_cover_the_title_at_768(browser_workspace, route):
    page, _, _ = browser_workspace
    origin = urlsplit(page.url)
    page.set_viewport_size({'width': 768, 'height': 900})
    page.goto(f'{origin.scheme}://{origin.netloc}{route}', wait_until='networkidle')
    title, nav = page.locator('.ui-pathbar h1').bounding_box(), page.locator('.review-kinds').bounding_box()
    apart = (title['x'] + title['width'] <= nav['x'] or nav['x'] + nav['width'] <= title['x']
             or title['y'] + title['height'] <= nav['y'] or nav['y'] + nav['height'] <= title['y'])
    assert apart, (route, title, nav)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), route


@pytest.mark.parametrize('route', ['/', '/pixels'])
def test_answer_links_come_right_after_the_title_in_focus_order(browser_workspace, route):
    """WCAG 2.4.3: Tab from the title row reaches the 정답 links before the editor and canvas controls."""
    page, _, _ = browser_workspace
    origin = urlsplit(page.url)
    page.goto(f'{origin.scheme}://{origin.netloc}{route}', wait_until='networkidle')
    links = page.locator('.review-kinds a').evaluate_all('links => links.map(link => link.pathname)')  # / adds ?frame=
    page.locator('.ui-pathbar h1').evaluate('title => { title.tabIndex = -1; title.focus(); }')
    focused = []
    for _ in links:
        page.keyboard.press('Tab')
        focused.append(page.evaluate('document.activeElement.closest(".review-kinds") && document.activeElement.pathname'))
    assert focused == links == ['/', '/pixels', '/learning/omx', '/learning/vlm'], (route, focused)
    page.keyboard.press('Tab')
    assert page.evaluate('!document.activeElement.closest(".review-kinds") && !!document.activeElement.closest(".ui-app-main")'), route
