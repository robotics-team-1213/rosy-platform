"""D-825 drawing registration and local editing in actual Chromium, no robot motion."""
import re
import json

import pytest
from browser_harness import browser_tests_enabled, open_token_access
from playwright.sync_api import expect

import test_site_map_trip as trip
from test_site_map_browser import page_site
from test_site_map_drawing_api import DATA, asset_module
from fleet.server.site_map_store import SiteMapStore

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in real Chromium')


@pytest.fixture
def drawing_assets(tmp_path, monkeypatch):
    assets = asset_module().SiteMapAssetStore(tmp_path / 'assets')
    monkeypatch.setattr(trip, 'SiteMapStore', lambda path: SiteMapStore(path, drawing_assets=assets))
    return assets


@pytest.fixture
def editor_site(drawing_assets, page_site):
    page, store, robot = page_site
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#map-status')).not_to_contain_text('조회 중')
    page.locator('#drawing-tools > summary').click()
    yield page, store, robot
    assert not [call for call in robot.calls if call[0] in {'navigation_goal', 'estop', 'swarm_arm'}]


def register(page, data=DATA):
    page.locator('#drawing-file').set_input_files({'name': 'drawing.stl', 'mimeType': 'application/octet-stream', 'buffer': data})
    expect(page.locator('#drawing-status')).to_contain_text('원본 확인')
    page.locator('#drawing-description').fill('실측한 1 m 기준선, 동쪽 방향')
    page.locator('#drawing-register').click()
    expect(page.locator('#drawing-status')).to_contain_text('맞춤 완료')
    expect(page.locator('#site-map-svg [data-drawing]')).to_have_count(1)


def point(page, x, y):
    page.locator('#site-map-svg').evaluate('''(svg, [x, y]) => {
        const p = new DOMPoint(x, y).matrixTransform(svg.getScreenCTM());
        svg.dispatchEvent(new MouseEvent('click', {bubbles: true, clientX: p.x, clientY: p.y}));
    }''', [x, y])


@pytest.mark.parametrize('width', [1366, 320])
@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_import_register_edit_save_reopen(editor_site, width, tmp_path):
    page, store, robot = editor_site
    page.set_viewport_size({'width': width, 'height': 1000})
    register(page)
    page.locator('#editor-tools > summary').click()
    page.locator('#editor-enabled').check()
    page.locator('#editor-kind').select_option('park')
    page.locator('#editor-name').fill('입구')
    point(page, 300, 200)
    page.locator('#editor-name').fill('목적지')
    point(page, 500, 200)
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(2)
    page.locator('#editor-kind').select_option('road')
    page.locator('#editor-from').select_option(index=0)
    page.locator('#editor-to').select_option(index=1)
    page.locator('#editor-name').fill('연결 도로')
    point(page, 300, 200)
    point(page, 400, 250)
    point(page, 500, 200)
    page.locator('#editor-finish').click()
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(1)
    page.locator('#editor-kind').select_option('exclusion')
    for x, y in ((250, 300), (300, 300), (300, 350)):
        point(page, x, y)
    page.locator('#editor-finish').click()
    expect(page.locator('#site-map-svg [data-facility]')).to_have_count(1)
    page.locator('#editor-undo').click()
    expect(page.locator('#site-map-svg [data-facility]')).to_have_count(0)
    page.locator('#editor-redo').click()
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    saved = store.draft_view()['map']
    assert len(saved['places']) == 2 and len(saved['edges']) == 1 and len(saved['facilities']) == 1
    assert saved['edges'][0]['name'] == '연결 도로' and saved['survey']['reviewed'] is False
    page.reload()
    page.locator('#map-source').select_option('draft')
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(1)
    expect(page.locator('#site-map-svg [data-drawing]')).to_have_count(1)
    layout = page.evaluate('''() => ({overflow: document.documentElement.scrollWidth - innerWidth,
      outside: [...document.querySelectorAll('body *')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.right > innerWidth + 1 && !e.closest('.map-viewport');
      }).slice(-15).map(e => ({tag: e.tagName, id: e.id, cls: e.className,
        width: e.getBoundingClientRect().width, minWidth: getComputedStyle(e).minWidth}))})''')
    if layout['overflow'] > 0:
        print('LAYOUT=' + json.dumps(layout, ensure_ascii=False))
        capture = tmp_path / f'map-editor-{width}.png'
        page.screenshot(path=str(capture), full_page=True)
        print('SCREENSHOT=' + str(capture))
    assert layout['overflow'] <= 0, layout


@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_zoom_rotation_and_drag_never_dispatch(editor_site):
    page, store, robot = editor_site
    requests = []
    page.on('request', lambda req: requests.append(req.url) if req.method == 'POST'
            and re.search(r'/(trip|formation|navigation)(/|$)', req.url) else None)
    register(page)
    page.locator('#editor-tools > summary').click()
    page.locator('#editor-enabled').check()
    page.locator('#editor-kind').select_option('park')
    point(page, 400, 240)
    page.locator('#editor-kind').select_option('select')
    page.locator('#site-map-svg [data-place]').dispatch_event('click')
    expect(page.locator('#site-map-svg [data-editor-vertex]')).to_have_count(1)
    page.locator('#editor-x').fill('0.25')
    page.locator('#editor-y').fill('0.5')
    page.locator('#editor-apply').click()
    page.locator('#map-view-turn').select_option('90')
    page.locator('#editor-zoom').select_option('2')
    expect(page.locator('#editor-pan-right')).to_have_count(1)
    before = page.locator('#site-map-svg').get_attribute('viewBox').split()
    page.locator('#editor-pan-right').click()
    after = page.locator('#site-map-svg').get_attribute('viewBox').split()
    assert float(after[0]) > float(before[0]) and after[2:] == before[2:]
    page.locator('#editor-pan-left').click()
    vertex = page.locator('#site-map-svg [data-editor-vertex]')
    vertex.scroll_into_view_if_needed()
    bounds = vertex.bounding_box()
    assert bounds and 0 <= bounds['y'] < page.viewport_size['height'], bounds
    page.mouse.move(bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2)
    page.mouse.down()
    page.mouse.move(bounds['x'] + 25, bounds['y'] + 20)
    page.mouse.up()
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    assert store.draft_view()['map']['places'][0]['x'] != .25
    page.locator('#site-map-svg').focus()
    page.keyboard.press('Delete')
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(0)
    page.keyboard.press('Control+z')
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(1)
    assert requests == []


@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_import_failure_and_unsaved_navigation_preserve_draft(editor_site):
    page, store, robot = editor_site
    register(page)
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    before = store.draft_view()
    page.locator('#drawing-file').set_input_files({'name': 'bad.stl', 'mimeType': 'application/octet-stream', 'buffer': b'<svg onload=alert(1)>'})
    expect(page.locator('#drawing-status')).to_contain_text('INVALID')
    assert store.draft_view() == before
    expect(page.locator('#site-map-svg [data-drawing]')).to_have_count(1)
    expect(page.locator('#drawing-register')).to_be_disabled()
    page.locator('#drawing-file').set_input_files({'name': 'valid.stl', 'mimeType': 'application/octet-stream', 'buffer': DATA})
    expect(page.locator('#drawing-status')).to_contain_text('원본 확인')
    page.locator('#drawing-distance').fill('0')
    page.locator('#drawing-register').click()
    expect(page.locator('#drawing-status')).to_contain_text('양수')
    assert store.draft_view() == before
    page.locator('#editor-tools > summary').click()
    page.locator('#editor-enabled').check()
    page.locator('#editor-kind').select_option('park')
    point(page, 400, 240)
    dialogs = []
    def refuse(dialog):
        dialogs.append(dialog.type)
        dialog.dismiss()
    page.on('dialog', refuse)
    page.locator('nav.doc-tabs a[href="/console"]').click()
    expect(page).to_have_url(re.compile(r'/console/site-map$'))
    assert dialogs == ['beforeunload']
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(1)
    assert store.draft_view() == before


@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_copy_template_requires_new_site_review(editor_site):
    page, store, robot = editor_site
    register(page)
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    original = store.draft_view()['map']
    page.locator('#profile-copy').click()
    page.locator('#profile-name').fill('새 현장 템플릿')
    page.locator('#profile-save').click()
    expect(page.locator('#profile-status')).to_contain_text('저장했습니다')
    copied = store.profiles()[0]['map']
    assert copied['map_id'] != original['map_id']
    assert copied['survey']['reviewed'] is False and copied['survey']['review_note'] == ''
    assert copied['drawing'] == original['drawing']
    assert not any(k in copied for k in ('calibration', 'robot_pose', 'teach'))


def test_new_drawing_preserves_geometry_and_resets_frame(editor_site):
    page, store, robot = editor_site
    previous = store.active_view()['map']
    page.route('**/api/fleet/calibrations', lambda route: route.fulfill(json={
        'calibrations': [{'source_id': 'old-camera', 'map_id': previous['map_id'],
                          'calibration_revision': 'old-camera-revision'}]}))
    page.reload()
    expect(page.locator('#plane-source option')).to_have_count(1)
    page.locator('#drawing-tools > summary').click()
    register(page)
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    new = store.draft_view()['map']
    assert new['places'] == previous['places']
    assert [e['polyline'] for e in new['edges']] == [e['polyline'] for e in previous['edges']]
    assert new['map_id'] != previous['map_id']
    assert new['survey']['reviewed'] is False
    expect(page.locator('#plane-source option')).to_have_count(0)
    assert store.active_view()['map'] == previous


def test_drawing_replacement_uses_working_draft_while_viewing_active(editor_site):
    page, store, robot = editor_site
    active = store.active_view()
    register(page)
    page.locator('#editor-tools > summary').click()
    page.locator('#editor-enabled').check()
    page.locator('#editor-kind').select_option('park')
    page.locator('#editor-name').fill('unsaved destination')
    point(page, 400, 240)
    page.locator('#map-source').select_option('active')
    page.locator('#drawing-rotation').fill('30')
    page.locator('#drawing-register').click()
    page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
    expect(page.locator('#map-source')).to_have_value('draft')
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    assert any(p['name'] == 'unsaved destination' for p in store.draft_view()['map']['places'])
    assert store.active_view() == active


def test_draft_click_never_plans_or_starts_trip(editor_site):
    page, store, robot = editor_site
    active = store.active_view()
    requests = []
    page.on('request', lambda req: requests.append(req.url) if req.method == 'POST'
            and re.search(r'/(trip|trips|route|formation|navigation)(/|$)', req.url) else None)
    register(page)
    page.locator('#site-map-svg [data-place]').first.dispatch_event('click')
    page.locator('#editor-tools > summary').click()
    page.locator('#editor-enabled').check()
    page.locator('#editor-kind').select_option('road')
    point(page, 300, 200)
    point(page, 400, 220)
    page.locator('#site-map-svg').focus()
    page.keyboard.press('Escape')
    expect(page.locator('#site-map-svg .editor-preview')).to_have_count(0)
    assert store.plans() == [] and requests == []
    assert store.active_view() == active
