"""Real Chromium checks for readout evidence notes and learning review summary."""
import pytest
from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='requires explicit local Chromium browser run')


def test_learning_summary_separates_review_from_training(browser_workspace):
    page, store, expect = browser_workspace
    store.update(0, {'version': store.get(0)['version'], 'action': 'reopen'})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning#review-section', wait_until='networkidle')
    expect(page.locator('#review-stage-summary')).to_contain_text('등록 2장')
    expect(page.locator('#training-data-state')).to_contain_text('픽셀 승인 0장')
    page.locator('.learning-home-nav a[href="#learning-results"]').click()
    expect(page.get_by_text('현재 검수 중인 사진의 학습 완료를 뜻하지 않습니다.')).to_be_visible()
    page.locator('.learning-home-nav a[href="#review-section"]').click()
    expect(page.locator('#object-review-link')).to_contain_text('검수·승인')
    expect(page.locator('#pixel-review-link')).to_contain_text('검수·승인')
    page.locator('#object-review-link').click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('#approve')).to_be_visible()
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning#review-section', wait_until='networkidle')
    page.locator('#pixel-review-link').click()
    expect(page.locator('#pixel-approve')).to_be_visible()


@pytest.mark.parametrize('route,strip', [('/', '#counts'), ('/pixels', '#pixel-counts')])
def test_readout_strip_carries_non_empty_data_note_after_load(browser_workspace, route, strip):
    page, _, expect = browser_workspace
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    notes = page.locator(f'{strip} dd[data-note]')
    expect(notes).to_have_count(3)
    for idx in range(3):
        expect(notes.nth(idx)).to_contain_text('검수 원장')
