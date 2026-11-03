"""Manager revisions are explicit and new classes reach the ordinary editor."""
import json
import pytest
from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


def test_class_manager_addition_requires_confirmation_and_reloads_binding(browser_workspace):
    page, store, expect = browser_workspace
    with store.connect() as db:
        db.execute('INSERT INTO metadata VALUES (?,?)', ('image_folders', json.dumps([
            {'id': 'selected', 'label': '선택 자료', 'path': '/private/selected'}])))
        db.execute("UPDATE frames SET source=json_set(source,'$.source_session','folder:selected:run')")
    base = page.url.rstrip('/')
    page.goto(base + '/classes?kind=object&folder_id=selected', wait_until='networkidle')
    expect(page.locator('#workspace')).to_contain_text('프로젝트')
    expect(page.locator('#apply')).to_be_disabled()
    count = page.locator('#rows fieldset').count()
    page.locator('#add').click()
    last = page.locator('#rows fieldset').last
    last.get_by_label('정본 이름').fill('new_object')
    last.get_by_label('표시 이름').fill('새 물체')
    expect(page.locator('#apply')).to_be_disabled()
    page.locator('#confirm').check()
    page.locator('#apply').click()
    expect(page.locator('#result')).to_contain_text('저장했습니다')
    expect(page.locator('#rows fieldset')).to_have_count(count + 1)
    page.locator('#back').click()
    expect(page.locator('#image-message')).to_be_hidden()
    assert page.locator('#review-folder').input_value() == 'selected'
    assert page.locator('#review-workspace').input_value() == ''
