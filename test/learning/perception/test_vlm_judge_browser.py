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


def test_audit_shows_the_consensus_and_records_confirm_and_fix(tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    cv2 = pytest.importorskip('cv2')
    import json
    import numpy as np
    from test_vlm_judge import answer
    monkeypatch.setattr(vlm_judge, 'EVAL_SET_SIZE', 1)  # four photos: one blind evaluation photo, two audits
    monkeypatch.setattr(vlm_judge, 'AUDIT_PER_WEEK', 2)
    store = open_store(tmp_path)
    for name, shade in (('a.jpg', 60), ('b.jpg', 120), ('c.jpg', 200), ('d.jpg', 30)):
        (tmp_path / name).write_bytes(cv2.imencode('.jpg', np.full((240, 320, 3), shade, np.uint8))[1].tobytes())
    sure = lambda value: dict(answer(value), p=[0.9, 0.05, 0.05] if value == 'yes' else [0.05, 0.9, 0.05])
    rows = tmp_path / 'rows.jsonl'
    rows.write_text(''.join(json.dumps(dict(wrist(name, 'yes', 'no'), answers={
        'wrist.object_in_gripper': sure('yes'), 'wrist.gripper_empty': sure('no')})) + '\n' for name in ('a.jpg', 'b.jpg', 'c.jpg', 'd.jpg')))
    for model in ('model-one', 'model-two'):
        vlm_judge.import_rows(store, {'rows_path': str(rows), 'question_set': 'v2', 'questions': QUESTIONS, 'model': model})
    counts = vlm_judge.queue(store)['counts']['wrist']
    assert counts == {'eval': 1, 'disputed': 0, 'audit': 2, 'eval_size': 1, 'eval_done': 0}
    server = make_server(store, free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                expect = playwright.expect
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/vlm', wait_until='networkidle')
                expect(page.locator('#vlm-queue')).to_contain_text('평가셋 0/1 · 의견 갈림 0 · 점검 2')
                expect(page.locator('#vlm-audit-note')).to_be_hidden()  # the evaluation photo comes first and is blind
                assert 'model-one' not in page.content() and page.locator('.vlm-provisional').count() == 0
                page.locator('#vlm-kind').select_option('audit')
                expect(page.locator('#vlm-audit-note')).to_be_visible()
                expect(page.locator('.vlm-provisional').first).to_have_text('임시 정답 yes')
                assert page.locator('.vlm-options').count() == 0
                confirm, fix = page.locator('#vlm-confirm'), page.locator('#vlm-fix')
                for button in (confirm, fix):
                    assert button.bounding_box()['height'] >= 44
                expect(page.locator('#vlm-save')).to_be_hidden()
                confirm.click()  # 맞음: the consensus becomes the confirmed answer
                expect(page.locator('#vlm-progress')).to_contain_text('목록 1 / 1')
                expect(page.locator('#vlm-image-message')).to_be_hidden()
                page.keyboard.press('e')  # 고침 reveals the options with the consensus preselected
                expect(page.locator('.vlm-options')).to_have_count(2)
                expect(page.locator('.vlm-question').nth(0).locator('ui-button[data-option="yes"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('.vlm-question').nth(0).locator('ui-button[data-option="no"]').click()
                page.locator('#vlm-save').click()
                expect(page.locator('#vlm-image-message')).to_contain_text('이 조건의 사진이 없습니다')
                assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
                page.locator('#tab-eval').click()
                expect(page.locator('#panel-eval')).to_contain_text('승인·승격이 아닙니다')
                expect(page.locator('#vlm-eval')).to_contain_text('임시 정답 점검')
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
    audits = {row['question']: row for row in vlm_judge.evaluation(store)['audits']}
    assert audits['wrist.object_in_gripper'] == {'question': 'wrist.object_in_gripper', 'n': 2, 'errors': 1, 'rate': 0.5, 'paused': False}
    assert audits['wrist.gripper_empty']['errors'] == 0
