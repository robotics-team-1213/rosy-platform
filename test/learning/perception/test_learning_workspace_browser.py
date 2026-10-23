"""The next real task stays above the fold and training has its own app view."""
import re

import json
import os
from pathlib import Path

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
    expect(page.get_by_role('heading', name='홈', exact=True)).to_be_visible()
    action = page.locator('#pipeline-link')
    expect(action).to_have_text('픽셀 검수 시작')
    expect(action).to_be_visible()
    box = action.bounding_box()
    assert box['y'] + box['height'] <= 844
    expect(page.locator('#workspace-review')).to_be_visible()
    page.get_by_role('navigation', name='Learning 주 메뉴').get_by_role('link', name='학습', exact=True).click()
    expect(page.get_by_role('heading', name='학습', exact=True)).to_be_attached()
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


@pytest.mark.parametrize('width', [390, 320])
def test_learning_compact_actions_and_connection_form_use_full_width(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning?view=training', wait_until='networkidle')
    main = page.locator('#learning-main').evaluate('(node) => {const r=node.getBoundingClientRect(),s=getComputedStyle(node); return {x:r.x+parseFloat(s.paddingLeft),width:r.width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)};}')
    for selector in ('#new-task', '#refresh'):
        box = page.locator(selector).bounding_box()
        assert abs(box['x'] - main['x']) <= 1 and abs(box['width'] - main['width']) <= 1, (selector, box, main)
    page.locator('#connection-panel summary').click()
    form = page.locator('#register').bounding_box()
    for selector in ('#kind', '#name', '#path', '#connect'):
        box = page.locator(selector).bounding_box()
        assert abs(box['x'] - form['x']) <= 1 and abs(box['width'] - form['width']) <= 1, (selector, box, form)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-work-form-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_learning_report_age_advances_and_refreshes(browser_workspace, tmp_path, width):
    page, _, expect = browser_workspace
    report = tmp_path / 'learning-result'
    report.mkdir()
    (report / 'state.json').write_text('{"status":"done"}', encoding='utf-8')
    page.clock.install()
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning?view=training', wait_until='networkidle')
    page.locator('#new-task').click()
    page.locator('#name').fill('검수할 결과')
    page.locator('#path').fill(str(report))
    page.locator('#connect').click()
    age = page.locator('[data-report-age]')
    expect(age).to_contain_text('방금 확인')
    expect(page.locator('#jobs')).to_contain_text('보고서 상태와 단계별 근거를 확인')
    expect(page.locator('#jobs')).not_to_contain_text('실패·거절 이유')
    page.clock.fast_forward(121_000)
    expect(age).to_contain_text('2분 전 확인')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width <= 390:
        card = page.locator('#jobs .ui-task-row').bounding_box()
        content = page.locator('#jobs').bounding_box()
        assert abs(card['x'] - content['x']) <= 1 and abs(card['width'] - content['width']) <= 1
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-report-age-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(target), full_page=True)
    page.locator('#refresh').click()
    expect(age).to_contain_text('방금 확인')


def test_owner_hold_stays_visible_after_timer_report_changes(browser_workspace, tmp_path):
    page, _, expect = browser_workspace
    report = tmp_path / 'owner-result'; report.mkdir()
    held = {'review_autobuild': {'status': 'held', 'blockers': ['no_approved_masks']}}
    for name in ['state.json', 'summary.json']:
        (report / name).write_text(json.dumps(held))
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning?view=training', wait_until='networkidle')
    page.locator('#new-task').click()
    page.locator('#name').fill('자동 학습')
    page.locator('#path').fill(str(report))
    page.locator('#connect').click()
    expect(page.locator('#jobs')).to_contain_text('승인·입력 조건 대기')
    held['timer_cycle'] = 2
    (report / 'summary.json').write_text(json.dumps(held))
    page.locator('#refresh').click()
    expect(page.locator('#jobs ui-tag')).to_contain_text('승인·입력 조건 대기')
    expect(page.locator('#jobs .job-reason')).to_have_count(1)


@pytest.mark.parametrize('width', [1440, 390])
def test_learning_filter_shows_visible_count(browser_workspace, tmp_path, width):
    page, _, expect = browser_workspace
    report = tmp_path / 'learning-result'
    report.mkdir()
    (report / 'state.json').write_text('{"status":"done"}', encoding='utf-8')
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning?view=training', wait_until='networkidle')
    expect(page.get_by_role('heading', name='학습', exact=True)).to_be_attached()
    page.locator('#new-task').click()
    page.locator('#name').fill('검수할 결과')
    page.locator('#path').fill(str(report))
    page.locator('#connect').click()
    # A single job hides redundant filters; exercise the actual multiple-job workflow.
    other = tmp_path / 'other-learning-result'
    other.mkdir()
    (other / 'state.json').write_text('{"status":"done"}', encoding='utf-8')
    page.locator('#new-task').click()
    page.locator('#name').fill('다른 결과')
    page.locator('#path').fill(str(other))
    page.locator('#connect').click()
    expect(page.locator('#updated')).to_contain_text('2개 작업')
    page.locator('#search').fill('검수할 결과')
    expect(page.locator('#updated')).to_contain_text('2개 중 1개 표시')
    page.locator('#search').fill('없는 작업')
    expect(page.locator('#updated')).to_contain_text('2개 중 0개 표시')
    expect(page.locator('#empty-title')).to_have_text('조건에 맞는 결과가 없습니다')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(output) / f'learning-results-filter-{width}.png'), full_page=True)
    page.locator('#reset-filters').click()
    expect(page.locator('#updated')).to_contain_text('2개 작업')

