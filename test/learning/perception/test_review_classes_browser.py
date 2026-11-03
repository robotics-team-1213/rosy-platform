"""Manager revisions are explicit and new classes reach the ordinary editor."""
import json
from urllib.parse import urlsplit
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
    location = urlsplit(page.url)
    base = f'{location.scheme}://{location.netloc}'
    page.goto(base + '/classes?kind=object&folder_id=selected', wait_until='networkidle')
    theme = page.get_by_role('button', name='테마 변경')
    expect(theme).to_be_visible()
    expect(theme).to_have_attribute('tabindex', '0')
    previous_theme = page.locator('html').get_attribute('data-theme')
    theme.focus()
    theme.press('Enter')
    expect(page.locator('html')).not_to_have_attribute('data-theme', previous_theme)
    expect(page.locator('#workspace')).to_contain_text('프로젝트')
    expect(page.locator('#apply')).to_be_disabled()
    count = page.locator('#rows fieldset').count()
    for width in (390, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#rows label').first.evaluate("node => getComputedStyle(node).display") == 'grid'
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
    expect(page.locator('#review-folder')).to_have_value('selected')
    expect(page.locator('#review-workspace')).to_have_value('')
