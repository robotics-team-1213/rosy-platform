"""Real Chromium regression checks for filtered selection and safe label undo."""
import os
import threading

from contextlib import contextmanager

import pytest

import class_sets
from test_review_app import fixture_inputs, open_store
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(os.getenv('ROSY_RUN_BROWSER_TESTS') != '1',
                                reason='requires explicit local Chromium browser run')


@contextmanager
def serve(store):
    playwright = pytest.importorskip('playwright.sync_api')
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
        playwright.expect(page.locator('#image-message')).to_be_hidden()
        try:
            yield page, store, playwright.expect
            assert not errors
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.fixture
def browser_workspace(tmp_path):
    with serve(open_store(tmp_path)) as value:
        yield value


@pytest.fixture
def custom_class_workspace(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    record = class_sets.from_data_yaml('names: [car, traffic_light]\ndisplay: {car: 자동차}\n'.encode(), 'detect')
    with serve(ReviewStore(tmp_path / 'state', source, human, images, record)) as value:
        yield value


def test_arrow_keys_move_between_photos(browser_workspace):
    page, store, expect = browser_workspace

    def photo_loaded(title):
        expect(page.locator('#frame-title')).to_have_text(title)
        expect(page.locator('#image-message')).to_be_hidden()
        expect(page.locator('#save-status')).to_contain_text('서버 저장됨')

    photo_loaded('사진 1')
    # Number fields keep their native arrow behaviour and never move between photos.
    page.locator('input[aria-label="박스 1 x0"]').focus()
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 1')
    page.locator('#canvas').focus()
    expect(page.locator('#next-frame')).not_to_have_attribute('disabled', '')
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 2')
    expect(page.locator('#prev-frame')).not_to_have_attribute('disabled', '')
    page.keyboard.press('ArrowLeft')
    photo_loaded('사진 1')
    page.locator('#filter').select_option('excluded')
    photo_loaded('사진 2')
    expect(page.locator('#prev-frame')).to_have_attribute('disabled', '')
    page.locator('#canvas').focus()
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 2')
    assert [row['status'] for row in store.list_frames()] == ['approved', 'excluded']


def test_filter_selection_empty_recovery_and_reload(browser_workspace):
    page, store, expect = browser_workspace
    page.locator('#filter').select_option('excluded')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('#prev-frame')).to_have_attribute('disabled', '')
    expect(page.locator('#next-frame')).to_have_attribute('disabled', '')
    page.reload(wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    page.locator('#filter').select_option('pending')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    page.reload(wait_until='networkidle')
    expect(page.locator('#empty-review')).to_be_visible()
    page.locator('#show-all').click()
    expect(page.locator('#frame-title')).to_have_text('사진 1')
    expect(page.locator('#review-content')).to_be_visible()
    assert [row['status'] for row in store.list_frames()] == ['approved', 'excluded']


def test_approve_advances_to_next_pending_and_keeps_filter(browser_workspace):
    page, store, expect = browser_workspace
    for index in (0, 1):
        store.update(index, {'version': store.get(index)['version'], 'action': 'reopen'})
    page.goto(page.url.split('?')[0] + '?filter=pending', wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 1')
    expect(page.locator('#image-message')).to_be_hidden()
    page.locator('#complete').check()
    page.locator('#approve').click()
    # The reviewer lands on the next pending photo without a third click.
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('#filter')).to_have_value('pending')
    expect(page.locator('#drag-status')).to_contain_text('사진 1 승인')
    expect(page.locator('#complete')).not_to_be_checked()
    expect(page.locator('#image-message')).to_be_hidden()
    page.locator('#exclude').click()
    # Nothing pending is left: stay on the decided photo and say the queue is done.
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('#drag-status')).to_contain_text('검수 대기 사진을 모두 처리했습니다')
    assert [row['status'] for row in store.list_frames()] == ['approved', 'excluded']


def test_decision_while_auditing_approved_does_not_jump_to_pending(browser_workspace):
    page, store, expect = browser_workspace
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    page.goto(page.url.split('?')[0] + '?filter=approved', wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 1')
    expect(page.locator('#image-message')).to_be_hidden()
    page.locator('#exclude').click()
    # The audited photo stays open; the filter widens so it remains listed.
    expect(page.locator('#save-status')).to_contain_text('서버 저장됨')
    expect(page.locator('#frame-title')).to_have_text('사진 1')
    expect(page.locator('#filter')).to_have_value('all')
    assert store.get(0)['status'] == 'excluded'


def test_phone_photo_list_is_one_strip_above_editor(browser_workspace):
    page, _store, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0] + '?frame=1', wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    layout = page.evaluate("""() => {
      const strip = document.getElementById('frames');
      const tops = [...strip.children].map(b => Math.round(b.getBoundingClientRect().top));
      return {pageWidth: document.documentElement.scrollWidth, rows: new Set(tops).size,
              direction: getComputedStyle(strip).flexDirection, overflow: getComputedStyle(strip).overflowX};
    }""")
    # Hundreds of photos must not push the editor below a full-page thumbnail grid.
    assert layout == {'pageWidth': 390, 'rows': 1, 'direction': 'row', 'overflow': 'auto'}


def test_undo_restores_boxes_without_restoring_approval(browser_workspace):
    page, store, expect = browser_workspace
    original = store.get(0)['review']['boxes']
    page.locator('#filter').select_option('approved')
    expect(page.locator('#image-message')).to_be_hidden()
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#boxes details')).to_have_count(0)
    expect(page.locator('#filter')).to_have_value('all')
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    page.locator('#undo').focus(); page.keyboard.press('Enter')
    expect(page.locator('#boxes details')).to_have_count(1)
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    assert store.get(0)['review']['boxes'] == original
    assert store.get(0)['status'] == 'pending'
    assert not store.get(0)['review']['complete_frame_review']
    assert store.get(0)['version'] == 3
    page.reload(wait_until='networkidle')
    expect(page.locator('#status')).to_have_text('검수 대기')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')


def test_stale_undo_never_overwrites_other_tab(browser_workspace):
    page, store, expect = browser_workspace
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    row=store.get(0)
    newer=store.update(0, {'version':row['version'], 'action':'save',
                          'boxes':[{'label':'traffic_light','signal_state':'red',
                                    'bbox_xyxy':[2,3,13,15]}]})
    page.locator('#undo').click()
    expect(page.locator('#save-status')).to_contain_text('저장 실패')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    assert store.get(0) == newer
    page.locator('#reload').click()
    expect(page.get_by_label('박스 1 x0',exact=True)).to_have_value('2')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')


def test_class_select_lists_the_workspace_class_set(browser_workspace):
    page, store, expect = browser_workspace
    options = page.locator('#boxes .box-top select').first.locator('option')
    expect(options).to_have_text(['클래스 선택 필요', '로봇', '장애물 상자', '콘', '신호등', '표지판', '사람 발'])


def test_custom_class_set_names_and_saves(custom_class_workspace):
    page, store, expect = custom_class_workspace
    select = page.locator('#boxes .box-top select').first
    expect(select.locator('option')).to_have_text(['클래스 선택 필요', '자동차', 'traffic_light'])
    select.select_option('car')
    expect(page.locator('#save-status')).to_contain_text('v2')
    expect(page.locator('#boxes summary').first).to_contain_text('자동차')
    assert store.get(0)['review']['boxes'][0]['label'] == 'car'


def test_number_keys_pick_classes_and_a_x_decide(browser_workspace):
    page, store, expect = browser_workspace
    page.get_by_role('button', name='박스 1 선택', exact=True).click()
    page.locator('#canvas').focus()
    page.keyboard.press('2')
    expect(page.locator('#boxes .box-top select').first).to_have_value('obstacle_box')
    expect(page.locator('#status')).to_have_text('검수 대기')
    assert store.get(0)['review']['boxes'][0]['label'] == 'obstacle_box'
    # Approval stays explicit (D-461): A never ticks the whole-photo check.
    page.locator('#canvas').focus()
    page.keyboard.press('a')
    page.wait_for_timeout(300)
    expect(page.locator('#complete')).not_to_be_checked()
    assert store.get(0)['status'] == 'pending'
    page.locator('#complete').check()
    page.locator('#canvas').focus()
    page.keyboard.press('a')
    expect(page.locator('#status')).to_have_text('승인')
    assert store.get(0)['status'] == 'approved'
    page.locator('#canvas').focus()
    page.keyboard.press('x')
    expect(page.locator('#status')).to_have_text('제외')
    assert store.get(0)['status'] == 'excluded'


def test_number_key_in_a_number_field_stays_typing(browser_workspace):
    page, store, expect = browser_workspace
    field = page.get_by_label('박스 1 x0', exact=True)
    field.focus()
    page.keyboard.press('2')
    expect(page.locator('#boxes .box-top select').first).to_have_value('traffic_light')
    page.keyboard.press('Control+a')
    page.wait_for_timeout(300)
    assert store.get(0)['review']['boxes'][0]['label'] == 'traffic_light'
    assert store.get(0)['status'] == 'approved'
