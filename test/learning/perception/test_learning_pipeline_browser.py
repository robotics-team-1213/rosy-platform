"""Unified Learning workflow, isolated from the frozen review editor suite."""
import json
import re

import pytest

from browser_harness import browser_tests_enabled
from review_app import Conflict
from test_review_app import open_store
from test_review_cycle import CLASSES
from test_review_flow_browser import browser_workspace, serve  # noqa: F401
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 390, 320])
def test_learning_pipeline_prepares_current_reviews_in_app(browser_workspace, width):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='domcontentloaded')
    action = page.locator('#pipeline-action')
    expect(action).to_have_text('승인 자료 준비')
    expect(action).to_be_enabled()
    assert action.bounding_box()['y'] + action.bounding_box()['height'] <= 844
    page.route('**/api/prepare', lambda route: route.fulfill(status=400,
               content_type='application/json', body=json.dumps({'error': '자료 준비 실패'})))
    action.click()
    expect(page.locator('#learning-error')).to_contain_text('자료 준비 실패')
    expect(action).to_be_enabled()
    page.unroute('**/api/prepare')
    action.click()
    expect(page.locator('[data-stage="preparation"]')).to_have_attribute('data-state', 'done')
    expect(page.locator('#pipeline-link')).to_have_text('학습 실행기 연결 안내')
    assert store.exports()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_learning_pipeline_automatically_connects_owner_and_invalidates_new_decisions(tmp_path):
    import review_evidence
    from learning_control import Control
    from learning_workspace import Workspace
    from test_learning_control import binding
    from test_learning_pipeline import ledger
    (tmp_path / 'review').mkdir()
    store = open_store(tmp_path / 'review')
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    store.prepare()
    current = review_evidence.decisions(store)
    file, home, out, _, runner = binding(tmp_path / 'owner', current['workspace_id'])
    doc = ledger()
    doc['review_autobuild']['authority'] = {key: current[key] for key in
                                           ('workspace_id', 'generation', 'decision_sha256')}
    (out / 'state.json').write_text(json.dumps(doc))
    target = Control(file, current['workspace_id'], home=home, runner=runner)
    with serve(store, target) as (page, _, expect):
        page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='domcontentloaded')
        expect(page.locator('[data-stage="evaluation"]')).to_have_attribute('data-state', 'done')
        page.locator('#pipeline-evidence summary').click()
        expect(page.locator('#pipeline-evidence')).to_contain_text('current-model')
        expect(page.locator('#pipeline-evidence')).to_contain_text('평가·READY 기록 확인')
        expect(page.locator('#training-data-state')).to_contain_text('현재 검수 자료가 데이터셋에 연결됐습니다')
        expect(page.locator('#owner-control-start')).not_to_have_attribute('reason', re.compile('.+'))
        assert Workspace(store.db).list() == []
        assert page.locator('#owner-control-status').count() == 1
        page.screenshot(path=str(tmp_path / 'learning-pipeline-desktop.png'), full_page=True)
        print('LEARNING_SCREENSHOT=' + str(tmp_path / 'learning-pipeline-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'learning-pipeline-mobile.png'), full_page=True)
        print('LEARNING_SCREENSHOT=' + str(tmp_path / 'learning-pipeline-mobile.png'))
        review_masks.update(store, 0, {'version': 2, 'action': 'reopen'}, Conflict)
        # Polling must read current decisions, even if the owner service has not changed.
        expect(page.locator('[data-stage="evaluation"]')).not_to_have_attribute('data-state', 'done', timeout=12000)
        expect(page.locator('#pipeline-link')).to_have_text('픽셀 검수 시작')
        page.route('**/api/learning', lambda route: route.fulfill(status=503,
                   content_type='application/json', body='{}'))
        expect(page.locator('#pipeline-action')).to_be_disabled(timeout=12000)
        expect(page.locator('#pipeline-stages')).to_be_empty(timeout=12000)
        expect(page.get_by_role('button', name='학습 시작', exact=True)).to_be_disabled()
