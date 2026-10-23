"""VLM 판단 labels one photo by keyboard and one by mouse on a phone without sideways scroll."""
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port

import vlm_judge
from review_app import make_server
from test_review_app import open_store
from test_vlm_judge import QUESTIONS, wrist

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_label_by_keyboard_and_mouse_at_phone_width(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    cv2 = pytest.importorskip('cv2')
    import json
    import numpy as np
    store = open_store(tmp_path)
    for name, shade in (('a.jpg', 60), ('b.jpg', 200)):
        (tmp_path / name).write_bytes(cv2.imencode('.jpg', np.full((240, 320, 3), shade, np.uint8))[1].tobytes())
    rows = tmp_path / 'rows.jsonl'
    rows.write_text(''.join(json.dumps(row) + '\n' for row in [wrist('a.jpg', 'yes', 'yes'), wrist('b.jpg', 'no', 'no')]))
    vlm_judge.import_rows(store, {'rows_path': str(rows), 'question_set': 'v2', 'questions': QUESTIONS, 'model': 'qwen3-vl-8b'})
    server = make_server(store, free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 720})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                expect = playwright.expect
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/vlm', wait_until='networkidle')
                expect(page.locator('#vlm-progress')).to_contain_text('목록 1 / 2')
                expect(page.locator('#vlm-image-message')).to_be_hidden()
                in_view = '''id => { const r = document.getElementById(id).getBoundingClientRect();
                                     return r.top >= 0 && r.bottom <= innerHeight && r.height > 0; }'''
                option = page.locator('.vlm-question').first.locator('ui-button').first
                for width, height in ((1280, 720), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate(in_view, 'vlm-save') and page.evaluate(in_view, 'vlm-exclude'), width
                    assert option.bounding_box()['height'] >= 44 and option.get_attribute('kind') == 'toggle'
                expect(option).to_contain_text('키 1')
                assert page.evaluate('document.getElementById("vlm-image").getBoundingClientRect().top < innerHeight')
                assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
                assert 'qwen' not in page.content()
                expect(page.locator('#vlm-save')).to_be_disabled()
                page.keyboard.press('1')
                page.keyboard.press('ArrowDown')
                page.keyboard.press('2')
                expect(page.locator('.vlm-question').nth(1).locator('ui-button[data-option="no"]')).to_have_attribute('aria-pressed', 'true')
                page.keyboard.press('Enter')
                expect(page.locator('#vlm-progress')).to_contain_text('목록 1 / 1')
                expect(page.locator('#vlm-image-message')).to_be_hidden()
                page.locator('.vlm-question').nth(0).locator('ui-button[data-option="no"]').click()
                page.locator('.vlm-question').nth(1).locator('ui-button[data-option="unclear"]').click()
                page.locator('#vlm-save').click()
                expect(page.locator('#vlm-image-message')).to_contain_text('이 조건의 사진이 없습니다')
                assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
                page.locator('#tab-eval').click()
                expect(page.locator('#vlm-eval')).to_contain_text('정답 있는 사진 2장')
                assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
    first, second = vlm_judge.item(store, 1), vlm_judge.item(store, 2)
    assert first['answers'] == {'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': 'no'}
    assert second['answers'] == {'wrist.object_in_gripper': 'no', 'wrist.gripper_empty': 'unclear'}
    assert (first['status'], second['status'], first['actor']) == ('labelled', 'labelled', None)
