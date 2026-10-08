"""Real Chromium regression checks for filtered selection and safe label undo."""
import os
import re
import threading
import json

from contextlib import contextmanager

import pytest
from browser_harness import browser_tests_enabled, free_port

import class_sets
from test_review_app import fixture_inputs, open_store
from test_review_cycle import CLASSES, catalog
from review_app import ReviewStore, Conflict, make_server
import review_masks
import review_ingest

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='requires explicit local Chromium browser run')


@contextmanager
def serve(store):
    playwright = pytest.importorskip('playwright.sync_api')
    # make_server takes only a port number, so this one keeps free_port().
    server = make_server(store, free_port())
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


def test_imported_approval_and_recheck_history_are_visible(browser_workspace):
    page, store, expect = browser_workspace
    expect(page.locator('#review-history-summary')).to_contain_text('객체 승인 · 픽셀 대기')
    expect(page.locator('#review-history-events')).to_contain_text('검수자 식별 불가')
    page.locator('#filter').select_option('approved')
    page.locator('#reopen').click()
    expect(page.locator('#review-history-events')).to_contain_text('재검수 시작')
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#review-history-summary')).to_contain_text('객체 대기 · 픽셀 대기')
    expect(page.locator('#review-history-events')).to_contain_text('전체 채우기')


@pytest.fixture
def custom_class_workspace(request, tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    data = getattr(request, 'param', 'names: [car, traffic_light]\ndisplay: {car: 자동차}\n')
    record = class_sets.from_data_yaml(data.encode(), 'detect')
    with serve(ReviewStore(tmp_path / 'state', source, human, images, record)) as value:
        yield value


def test_pixel_points_preview_before_explicit_apply(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-flood')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#pixel-class')).to_have_value(
        str(next(row['index'] for row in review_masks.classes(store)['classes']
                 if row['name'] == 'lane_line')))
    canvas = page.locator('#pixel-canvas')
    expect(canvas).to_be_visible()
    canvas.click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('1점 선택')
    expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
    assert review_masks.get(store, 0)['version'] == 0
    canvas.click(position={'x': 16, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('2점 선택')
    page.locator('#pixel-sample-apply').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    assert review_masks.get(store, 0)['status'] == 'pending'
    assert review_masks.get(store, 0)['version'] == 1


def test_pixel_review_shows_unclassified_coverage(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    unknown = int((review_masks.pixels(store, review_masks.get(store, 0)) == 255).sum())
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-coverage')).to_contain_text(f'미검수 {unknown:,}픽셀')
    assert page.locator('#pixel-coverage').bounding_box()['y'] < page.locator('#pixel-class').bounding_box()['y']
    page.locator('#pixel-class').select_option('0')
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-coverage')).to_contain_text('미검수 0픽셀')


def test_pixel_number_key_recalculates_current_selection(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    page.locator('#pixel-canvas').click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
    with page.expect_request(lambda request: request.url.endswith('/api/mask-preview/0')
                             and request.post_data_json['label'] == 1):
        page.keyboard.press('2')
    expect(page.locator('#pixel-class')).to_have_value('1')


def test_pixel_multiple_lane_classes_require_explicit_choice(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES.replace(b'name: lane_line', b'name: left_lane'))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-class')).to_have_value('')
    expect(page.locator('#pixel-fill')).to_be_disabled()
    page.locator('#pixel-canvas').click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('클래스를 선택')
    page.locator('#pixel-class').select_option('1')
    expect(page.locator('#pixel-fill')).to_be_enabled()
    page.locator('#pixel-canvas').click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')


def test_object_candidate_is_findable_and_empty_review_is_neutral(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    rows[0]['boxes'] = [{'label': 'traffic_light', 'bbox_xyxy': [1, 2, 12, 14],
                         'signal_state': 'unknown'}]
    source.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    reviews = [json.loads(line) for line in human.read_text().splitlines()]
    reviews[0].update(boxes=[], review_status='pending_human', complete_frame_review=False)
    human.write_text('\n'.join(json.dumps(row) for row in reviews), encoding='utf-8')
    with serve(ReviewStore(tmp_path / 'state', source, human, images)) as (page, store, expect):
        expect(page.locator('#candidate-details')).to_be_visible()
        expect(page.locator('#candidate-source')).to_contain_text('원본 후보 1개')
        expect(page.locator('#source-preview')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#candidates')).to_be_visible()
        page.on('dialog', lambda dialog: dialog.accept())
        page.locator('#candidates').click()
        expect(page.locator('#boxes summary')).to_contain_text('박스 1')
        page.get_by_role('button', name='박스 1 삭제').click()
        expect(page.locator('#empty')).to_contain_text('객체가 없으면 전체 확인 후 승인하세요')
        page.reload(wait_until='networkidle')
        expect(page.locator('#candidate-details')).to_be_visible()


def test_model_object_draft_is_visible_before_apply(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    rows[0]['objects'] = [{'bbox_xyxy': [2, 3, 12, 14], 'label': 'cone'}]
    rows[0]['annotation_source'] = 'qwen3-vl:8b-instruct'
    (folder / 'verified-inputs.jsonl').write_text(json.dumps(rows[0]) + '\n', encoding='utf-8')
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    with serve(store) as (page, store, expect):
        page.goto(page.url.split('?')[0] + '?frame=2', wait_until='networkidle')
        expect(page.locator('#candidate-source')).to_contain_text('미적용 모델 초안 1개')
        expect(page.locator('#model-preview')).to_have_attribute('aria-pressed', 'true')
        assert page.locator('#candidate-details').bounding_box()['y'] < page.locator('#canvas').bounding_box()['y']
        assert store.get(2)['review']['boxes'] == []
        page.on('dialog', lambda dialog: dialog.accept())
        page.locator('#model-candidates').click()
        expect(page.locator('#candidate-source')).to_contain_text('모델 초안 적용됨 · 검수 대기')
        expect(page.locator('#model-preview')).to_have_attribute('aria-pressed', 'false')
        assert store.get(2)['review']['boxes'] == rows[0]['objects']
        assert store.get(2)['status'] == 'pending'

@pytest.mark.parametrize('width', [390, 320])
def test_catalog_import_reaches_pending_review_on_phone(browser_workspace, tmp_path, width):
    page, store, expect = browser_workspace
    folder, _, _ = catalog(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/catalog', wait_until='networkidle')
    for form, field, action in [('import-form', 'catalog-path', 'import'),
                                ('cad-form', 'cad-path', 'cad')]:
        widths = page.evaluate("""selectors => selectors.map(selector =>
          document.querySelector(selector).getBoundingClientRect().width)""",
          [f'#{form}', f'#{form} label', f'#{field}', f'#{action}'])
        if width == 320:
            assert max(widths) - min(widths) <= 1, widths
        else:
            assert max(widths[1:]) - min(widths[1:]) <= 1, widths
        assert 44 <= page.locator(f'#{action}').bounding_box()['height'] <= 72
    page.locator('#catalog-path').fill(str(folder))
    page.locator('#import').click()
    expect(page.locator('#result')).to_contain_text('새 사진 1장 · 중복 표현 1개 · 새 픽셀 검수 대기 1장')
    assert len(store.list_frames()) == 3 and store.get(2)['status'] == 'pending'
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-import-result-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('a[href="/?filter=pending"]').click()
    expect(page.locator('#counts')).to_contain_text('대기 1')
    expect(page.locator('#status')).to_contain_text('검수 대기')
    if width == 320:
        assert page.locator('#frames').evaluate('(node) => getComputedStyle(node).flexDirection') == 'row'
        assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output:
        target = Path(output) / f'learning-import-pending-{width}.png'
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('route,left,right', [('/', '.review-stage', '.label-inspector'),
                                                   ('/pixels', '.pixel-layout > section', '.pixel-layout > aside')])
@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_review_editor_peer_widths(browser_workspace, route, left, right, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    if route == '/pixels':
        assert page.locator('#pixel-flood').get_attribute('disabled') is not None
    boxes = [page.locator(selector).bounding_box() for selector in (left, right)]
    assert all(box and box['width'] > 0 for box in boxes)
    assert abs(boxes[0]['width'] - boxes[1]['width']) <= 1
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    for pane in (left, right):
        actions = page.locator(f'{pane} ui-actions').first
        buttons = actions.locator('ui-button').all()
        if buttons:
            widths = [button.bounding_box()['width'] for button in buttons]
            assert max(widths) - min(widths) <= 1, widths
    if width <= 390:
        if route == '/pixels':
            previous = page.locator('#pixel-prev').bounding_box()
            following = page.locator('#pixel-next').bounding_box()
            reload = page.locator('#pixel-reload').bounding_box()
            bar = page.locator('.ui-workspace-bar').first.bounding_box()
            for action in (previous, following, reload):
                assert abs(action['x'] - bar['x']) <= 1 and abs(action['width'] - bar['width']) <= 1
            assert previous['y'] + previous['height'] <= following['y']
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/") or "objects"}-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [390, 320])
def test_object_filter_uses_photo_strip_width_on_phone(browser_workspace, width):
    from pathlib import Path

    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/', wait_until='networkidle')
    filter_box = page.locator('.photo-sidebar > label').bounding_box()
    strip = page.locator('#frames').bounding_box()
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        page.screenshot(path=str(Path(output) / f'learning-filter-{width}.png'), full_page=True)
    assert filter_box and strip
    assert abs(filter_box['x'] - strip['x']) <= 1
    assert abs(filter_box['width'] - strip['width']) <= 1, (filter_box, strip)
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_empty_review_can_recover_at_declared_widths(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    assert page.locator('.workspace').bounding_box()['width'] == width
    topbar = page.locator('ui-topbar').bounding_box()
    assert page.locator('.workspace').bounding_box()['y'] == topbar['y'] + topbar['height']
    page.locator('#filter').select_option('pending')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    action = page.locator('#show-all')
    assert action.bounding_box()['width'] > 0
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-objects-empty-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    action.click()
    expect(page.locator('#frame-title')).to_have_text('사진 1')


@pytest.mark.parametrize('route,main', [('/learning', '#learning-main'), ('/catalog', '#catalog-main')])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_learning_pages_start_below_topbar(browser_workspace, route, main, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert page.locator(main).bounding_box()['y'] == topbar['y'] + topbar['height']
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/")}-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [390, 320])
def test_catalog_compact_forms_use_the_same_full_width(browser_workspace, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/catalog', wait_until='networkidle')
    for form, field, action in [('#import-form', '#catalog-path', '#import'),
                                ('#cad-form', '#cad-path', '#cad')]:
        bounds = [page.locator(selector).bounding_box() for selector in (form, field, action)]
        assert all(abs(box['x'] - bounds[0]['x']) <= 1 for box in bounds), bounds
        assert all(abs(box['width'] - bounds[0]['width']) <= 1 for box in bounds), bounds
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-catalog-form-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [390, 320])
def test_learning_compact_actions_and_connection_form_use_full_width(browser_workspace, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    main = page.locator('.workspace-heading').bounding_box()
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
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
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
        search = page.locator('#search').bounding_box()
        assert abs(card['x'] - search['x']) <= 1 and abs(card['width'] - search['width']) <= 1
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-report-age-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(target), full_page=True)
    page.locator('#refresh').click()
    expect(age).to_contain_text('방금 확인')


@pytest.mark.parametrize('width', [1440, 390])
def test_learning_filter_shows_visible_count(browser_workspace, tmp_path, width):
    page, _, expect = browser_workspace
    report = tmp_path / 'learning-result'
    report.mkdir()
    (report / 'state.json').write_text('{"status":"done"}', encoding='utf-8')
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    expect(page.locator('.workspace-heading h2')).to_have_text('연결한 학습 결과')
    page.locator('#new-task').click()
    page.locator('#name').fill('검수할 결과')
    page.locator('#path').fill(str(report))
    page.locator('#connect').click()
    expect(page.locator('#updated')).to_contain_text('1개 작업')
    page.locator('#search').fill('없는 작업')
    expect(page.locator('#updated')).to_contain_text('1개 중 0개 표시')
    expect(page.locator('#empty-title')).to_have_text('조건에 맞는 작업이 없습니다')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(output) / f'learning-results-filter-{width}.png'), full_page=True)
    page.locator('#reset-filters').click()
    expect(page.locator('#updated')).to_contain_text('1개 작업')


@pytest.mark.parametrize('width', [1440, 390])
def test_object_to_pixel_review_keeps_photo_and_shows_decision(browser_workspace, width):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0] + '?frame=1', wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('a[href="/pixels?frame=1"]')).to_have_count(2)
    page.locator('.workspace-tabs a[href^="/pixels"]').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 검수 대기')
    page.locator('#pixel-class').select_option('0')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-complete').check()
    page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    expect(page.locator('#pixel-decision')).to_contain_text('사진 2 픽셀 승인 · 다음 검수 대기 사진 1')
    assert not page.locator('#pixel-decision').is_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(output) / f'learning-pixel-decision-{width}.png'), full_page=True)
    page.locator('.workspace-tabs a[href="/learning"]').click()
    expect(page.locator('#review-counts')).to_contain_text('검수 대기 1장')
    expect(page.locator('#pixel-counts')).to_contain_text('승인 1장 · 검수 대기 1장')
    page.locator('a[href="/pixels?filter=pending"]').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')


@pytest.mark.parametrize('route', ['/learning', '/catalog', '/', '/pixels'])
@pytest.mark.parametrize('width,height', [(390, 844), (320, 568)])
def test_learning_compact_header_stays_within_first_view_budget(browser_workspace, route, width, height):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert topbar['height'] <= height * 0.2, (route, topbar, height)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        name = route.strip('/') or 'objects'
        target = Path(output) / f'learning-header-{name}-{width}x{height}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))


@pytest.mark.parametrize('route,action', [('/', '#prepare'), ('/pixels', '#pixel-export')])
@pytest.mark.parametrize('width,height', [(390, 844), (320, 568)])
def test_review_preparation_action_uses_compact_panel_width(browser_workspace, route, action, width, height):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    panel = page.locator('.preparation').bounding_box()
    button = page.locator(action).bounding_box()
    assert abs(panel['x'] - button['x']) <= 1 and abs(panel['width'] - button['width']) <= 1, (panel, button)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-prepare-{"objects" if route == "/" else "pixels"}-{width}x{height}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.locator(action).scroll_into_view_if_needed()
        page.screenshot(path=str(target))


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_empty_pixel_review_can_recover_at_declared_widths(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    page.locator('#pixel-filter').select_option('approved')
    expect(page.locator('#pixel-empty')).to_be_visible()
    expect(page.locator('#pixel-content')).to_be_hidden()
    expect(page.locator('#pixel-title')).to_have_text('픽셀 검수')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인 0장')
    expect(page.locator('#pixel-frame').locator('..')).to_be_hidden()
    expect(page.locator('#pixel-prev')).to_be_hidden()
    expect(page.locator('#pixel-next')).to_be_hidden()
    action = page.locator('#pixel-all')
    assert action.bounding_box()['x'] + action.bounding_box()['width'] <= width
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-pixels-empty-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    action.click()
    expect(page.locator('#pixel-content')).to_be_visible()
    expect(page.locator('#pixel-frame').locator('..')).to_be_visible()
    expect(page.locator('#pixel-next')).to_be_visible()


def test_pixel_review_first_use_leads_to_data_registration(browser_workspace):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    with store.connect() as db:
        db.execute('DELETE FROM frames')
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-empty')).to_be_visible()
    expect(page.locator('#pixel-status')).to_contain_text('등록된 사진 0장')
    expect(page.locator('#pixel-filter').locator('..')).to_be_hidden()
    expect(page.locator('#pixel-all')).to_have_text('자료 등록 열기')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / 'learning-pixels-first-use-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#pixel-all').click()
    assert page.url.endswith('/catalog')


def test_object_review_first_use_leads_to_data_registration(browser_workspace):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    with store.connect() as db:
        db.execute('DELETE FROM frames')
    page.reload(wait_until='networkidle')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    expect(page.locator('#filter').locator('..')).to_be_hidden()
    expect(page.locator('#show-all')).to_have_text('자료 등록 열기')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / 'learning-objects-first-use-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#show-all').click()
    assert page.url.endswith('/catalog')


@pytest.mark.parametrize('route,empty,retry,content', [('/', '#empty-review', '#show-all', '#review-content'),
                                                       ('/pixels', '#pixel-empty', '#pixel-reload', '#pixel-content')])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_workspace_disconnect_shows_reachable_retry(browser_workspace, route, empty, retry, content, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.route('**/api/workspace', lambda request: request.abort())
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(retry)).to_be_visible()
    if route == '/':
        expect(page.locator('#empty-review h2')).to_have_text('검수 내용을 불러오지 못했습니다')
    else:
        expect(page.locator('#pixel-status')).to_contain_text('검수 내용을 불러오지 못했습니다')
        expect(page.locator('#pixel-frame').locator('..')).to_be_hidden()
    assert page.locator(retry).bounding_box()['y'] < 844
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-disconnect-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.unroute('**/api/workspace')
    page.locator(retry).click()
    expect(page.locator(content)).to_be_visible()


@pytest.mark.parametrize('route,reload,content', [('/', '#reload', '#review-content'),
                                                 ('/pixels', '#pixel-reload', '#pixel-content')])
def test_workspace_disconnect_hides_stale_review(browser_workspace, route, reload, content):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(content)).to_be_visible()
    page.route('**/api/workspace', lambda request: request.abort())
    page.locator(reload).click()
    expect(page.locator(content)).to_be_hidden()
    page.unroute('**/api/workspace')
    page.locator('#show-all' if route == '/' else '#pixel-reload').click()
    expect(page.locator(content)).to_be_visible()


@pytest.mark.parametrize('route,reload,content,empty,prepare,result,error', [
    ('/', '#reload', '#review-content', '#empty-review', '#prepare', '#export-result', '#error'),
    ('/pixels', '#pixel-reload', '#pixel-content', '#pixel-empty', '#pixel-export', '#pixel-export-result', '#pixel-error'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_permission_denial_blocks_work_until_reload(
    browser_workspace, route, reload, content, empty, prepare, result, error, width
):
    page, _, expect = browser_workspace
    output = os.getenv('ROSY_UIUX_SCREENSHOT_DIR')
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    page.route('**/api/workspace', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local host required"}'))
    page.locator(reload).click()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(empty)).to_be_visible()
    denied = '#empty-review p' if route == '/' else '#pixel-status'
    expect(page.locator(denied)).to_contain_text('권한')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output:
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-workspace-denied-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute('**/api/workspace')
    page.locator('#show-all' if route == '/' else reload).click()
    expect(page.locator(content)).to_be_visible()

    page.route('**/api/prepare', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local workspace authorization required"}'))
    page.locator(prepare).click()
    expect(page.locator(result)).to_contain_text('권한')
    box = page.locator(result).bounding_box()
    assert box and box['y'] >= 0 and box['y'] + box['height'] <= 844
    expect(page.locator(error)).to_contain_text('권한')
    expect(page.locator(prepare)).to_be_disabled()
    expect(page.locator(reload)).to_be_enabled()
    if output:
        page.locator(result).scroll_into_view_if_needed()
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-prepare-denied-{width}.png'
        page.screenshot(path=str(target))
    page.unroute('**/api/prepare')
    page.locator(reload).click()
    expect(page.locator(prepare)).to_be_enabled()


@pytest.mark.parametrize('route,reload,content,empty,prepare,pending_text', [
    ('/', '#reload', '#review-content', '#empty-review', '#prepare', '검수 내용을 확인하는 중'),
    ('/pixels', '#pixel-reload', '#pixel-content', '#pixel-empty', '#pixel-export', '검수 내용을 확인하는 중'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_waiting_workspace_hides_stale_editing(
    browser_workspace, route, reload, content, empty, prepare, pending_text, width
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    pending = []
    page.route('**/api/workspace', lambda request: pending.append(request))
    with page.expect_request('**/api/workspace'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    if route == '/pixels':
        expect(page.locator(empty)).to_be_hidden()
    else:
        expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(empty if route == '/' else '#pixel-status')).to_contain_text(pending_text)
    expect(page.locator(prepare)).to_be_disabled()
    assert pending
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    expect(page.locator(prepare)).to_be_enabled()
    page.locator(reload).click()
    if route == '/pixels':
        expect(page.locator(empty)).to_be_hidden()
    else:
        expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(prepare)).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    assert pending
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-waiting-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    expect(page.locator(prepare)).to_be_enabled()


@pytest.mark.parametrize('route,status,content', [
    ('/', '#empty-review p', '#review-content'),
    ('/pixels', '#pixel-status', '#pixel-content'),
])
def test_review_delayed_workspace_shows_wait_age(browser_workspace, route, status, content):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    pending = []
    page.route('**/api/workspace', lambda request: pending.append(request))
    with page.expect_request('**/api/workspace'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    expect(page.locator(status)).to_contain_text('서버 응답 대기 3초', timeout=5000)
    expect(page.locator(content)).to_be_hidden()
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-delayed-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    if route == '/pixels':
        expect(page.locator(status)).not_to_contain_text('서버 응답 대기')
    else:
        expect(page.locator('#empty-review')).to_be_hidden()


@pytest.mark.parametrize('route,api,status,action', [
    ('/learning', 'learning', '#learning-status', '#new-task'),
    ('/catalog', 'catalog', '#catalog-load', '#import'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_learning_list_and_catalog_show_delayed_response_age(browser_workspace, route, api, status, action, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    pending = []
    page.route(f'**/api/{api}', lambda request: pending.append(request))
    with page.expect_request(f'**/api/{api}'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    expect(page.locator(status)).to_contain_text(re.compile(r'서버 응답 대기 [3-9]\d*초'), timeout=15000)
    expect(page.locator(action)).to_be_disabled()
    if route == '/learning':
        expect(page.locator('#empty-jobs')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{api}-delayed-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    pending.pop().continue_()
    expect(page.locator(action)).to_be_enabled()
    if route == '/catalog':
        expect(page.locator(status)).to_be_hidden()
    else:
        expect(page.locator(status)).not_to_contain_text('서버 응답 대기')


@pytest.mark.parametrize('route,api,actions,status,retry', [
    ('/learning', 'learning', ('#new-task', '#connect'), '#learning-status', '#refresh'),
    ('/catalog', 'catalog', ('#import', '#cad'), '#catalog-load', '#catalog-retry'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_learning_list_and_catalog_wait_denial_and_retry(
    browser_workspace, route, api, actions, status, retry, width
):
    page, _, expect = browser_workspace
    output = os.getenv('ROSY_UIUX_SCREENSHOT_DIR')
    page.set_viewport_size({'width': width, 'height': 844})
    pending = []
    page.route(f'**/api/{api}', lambda request: pending.append(request))
    with page.expect_request(f'**/api/{api}'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    expect(page.locator(status)).to_contain_text('확인하는 중')
    for action in actions:
        expect(page.locator(action)).to_be_disabled()
    if route == '/learning':
        expect(page.locator('#jobs')).to_be_hidden()
    if output:
        from pathlib import Path
        target = Path(output) / f'learning-{api}-waiting-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    assert pending
    pending.pop().fulfill(status=403, content_type='application/json', body='{"error":"local host required"}')
    expect(page.locator(status)).to_contain_text('권한')
    for action in actions:
        expect(page.locator(action)).to_be_disabled()
    if route == '/learning':
        expect(page.locator('#review-counts')).to_contain_text('확인 불가')
        expect(page.locator('#pixel-counts')).to_contain_text('확인 불가')
        expect(page.locator('#search')).to_be_disabled()
    else:
        expect(page.locator('#catalog-path')).to_be_disabled()
    expect(page.locator(retry)).to_be_enabled()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output:
        target = Path(output) / f'learning-{api}-denied-{width}.png'
        page.screenshot(path=str(target))
    page.locator(retry).click()
    assert pending
    pending.pop().continue_()
    for action in actions:
        expect(page.locator(action)).to_be_enabled()
    expect(page.locator('#search' if route == '/learning' else '#catalog-path')).to_be_enabled()
    if route == '/learning':
        expect(page.locator('#pixel-counts')).to_contain_text('검수 대기')


@pytest.mark.parametrize('route,api,status,retry,recovered', [
    ('/', 'workspace', '#empty-review h2', '#show-all', '#review-content'),
    ('/pixels', 'workspace', '#pixel-status', '#pixel-reload', '#pixel-content'),
    ('/learning', 'learning', '#learning-status', '#refresh', '#connect'),
    ('/catalog', 'catalog', '#catalog-load', '#catalog-retry', '#import'),
])
@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_review_service_unavailable_is_distinct_from_connection_failure(
    browser_workspace, route, api, status, retry, recovered, width
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.route(f'**/api/{api}', lambda request: request.fulfill(
        status=503, content_type='text/html', body='Service Unavailable'))
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(status)).to_contain_text('사용할 수 없습니다')
    expect(page.locator(retry)).to_be_visible()
    if route == '/pixels':
        expect(page.locator('#pixel-empty h3')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if route == '/learning':
        expect(page.locator('#learning-error')).to_be_hidden()
    if route in ('/', '/catalog') and width <= 390:
        assert page.locator(retry).bounding_box()['width'] >= width * .8
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        name = 'objects' if route == '/' else route.lstrip('/')
        target = Path(output) / f'learning-{name}-unavailable-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute(f'**/api/{api}')
    page.locator(retry).click()
    if route in ('/learning', '/catalog'):
        expect(page.locator(recovered)).to_be_enabled()
    else:
        expect(page.locator(recovered)).to_be_visible()


@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_object_decision_and_preparation_result_are_visible(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    expect(page.locator('#object-approval-hint')).to_contain_text('사진 전체 확인')
    assert page.locator('.review-actions').bounding_box()['y'] < page.locator('.inspector-heading').bounding_box()['y']
    def shot(state):
        if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            from pathlib import Path
            target = Path(output) / f'learning-objects-{state}-{width}.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(target), full_page=True)
    page.locator('#exclude').click()
    expect(page.locator('#status')).to_have_text('제외')
    assert store.get(0)['status'] == 'excluded'
    shot('excluded')
    page.locator('#reopen').click()
    expect(page.locator('#status')).to_have_text('검수 대기')
    page.locator('#complete').check()
    page.locator('#approve').click()
    expect(page.locator('#status')).to_have_text('승인')
    assert store.get(0)['status'] == 'approved'
    shot('approved')
    page.locator('#prepare').click()
    expect(page.locator('#export-result')).to_contain_text('승인 1장 준비 완료')
    expect(page.locator('#export-result')).to_contain_text('이번 준비 결과')
    page.reload()
    expect(page.locator('#export-result')).to_contain_text('이전 준비 결과')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if width <= 390:
        navigation = page.locator('.frame-navigation').bounding_box()
        buttons = [page.locator(f'#{name}').bounding_box() for name in ('prev-frame', 'next-frame', 'next-pending')]
        assert all(abs(button['width'] - navigation['width']) <= 1 for button in buttons)
        assert buttons[0]['y'] < buttons[1]['y'] < buttons[2]['y']
    shot('decision-result')


@pytest.mark.parametrize('route,post,action,status,retry', [
    ('/learning', 'learning/register', '#connect', '#learning-status', '#refresh'),
    ('/catalog', 'import', '#import', '#catalog-load', '#catalog-retry'),
])
def test_learning_registration_denial_blocks_repeat_until_retry(
    browser_workspace, route, post, action, status, retry
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    page.route(f'**/api/{post}', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local workspace authorization required"}'))
    if route == '/learning':
        page.locator('#new-task').click()
        page.locator('#name').fill('권한 확인')
        page.locator('#path').fill('X:/DevTemp/permission-check')
    else:
        page.locator('#catalog-path').fill('X:/DevTemp/permission-check')
    page.locator(action).click()
    expect(page.locator(status)).to_contain_text('권한')
    result = page.locator('#learning-error' if route == '/learning' else '#catalog-error')
    expect(result).to_contain_text('권한')
    box = result.bounding_box()
    assert box and box['y'] >= 0 and box['y'] + box['height'] <= 844
    expect(page.locator(action)).to_be_disabled()
    expect(page.locator(retry)).to_be_enabled()
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/")}-submit-denied-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute(f'**/api/{post}')
    page.locator(retry).click()
    expect(page.locator(action)).to_be_enabled()


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


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_stale_undo_never_overwrites_other_tab(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    row=store.get(0)
    newer=store.update(0, {'version':row['version'], 'action':'save',
                          'boxes':[{'label':'traffic_light','signal_state':'red',
                                    'bbox_xyxy':[2,3,13,15]}]})
    page.locator('#undo').click()
    expect(page.locator('#save-status')).to_contain_text('저장 실패')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    expect(page.locator('#approve')).to_have_attribute('disabled', '')
    assert store.get(0) == newer
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width == 390:
        reload = page.locator('#reload').bounding_box()
        assert reload and reload['width'] >= width * .8 and reload['x'] + reload['width'] <= width
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-objects-conflict-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#reload').click()
    expect(page.get_by_label('박스 1 x0',exact=True)).to_have_value('2')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')


def test_class_select_lists_the_workspace_class_set(browser_workspace):
    page, store, expect = browser_workspace
    options = page.locator('#boxes .box-top select').first.locator('option')
    expect(options).to_have_text(['클래스 선택 필요', '로봇', '장애물 상자', '콘', '신호등', '표지판', '사람 발'])


def test_object_ribbon_class_click_saves_selected_box_only(browser_workspace):
    page, store, expect = browser_workspace
    chip = page.locator('#object-quick-classes button[value="obstacle_box"]')
    expect(chip).to_be_disabled()
    expect(page.locator('#object-quick-classes .ui-icon')).to_have_count(
        page.locator('#object-quick-classes button').count())
    assert page.locator('.review-editor-tools').bounding_box()['x'] < page.locator('#canvas').bounding_box()['x']
    assert page.locator('.review-editor-tools').bounding_box()['y'] < page.locator('#canvas').bounding_box()['y'] + 1
    expect(page.locator('#view-original .ui-icon')).to_have_count(1)
    expect(page.locator('#view-detail .ui-icon')).to_have_count(1)
    page.get_by_role('button', name='박스 1 선택', exact=True).click()
    expect(chip).to_be_enabled()
    chip.click()
    expect(page.locator('#save-status')).to_contain_text('서버 저장됨')
    expect(chip).to_have_attribute('aria-pressed', 'true')
    assert store.get(0)['review']['boxes'][0]['label'] == 'obstacle_box'
    assert store.get(0)['status'] == 'pending'
    expect(page.locator('#approve')).to_be_disabled()


def test_object_zoom_pan_and_draw_keep_source_coordinates(browser_workspace):
    page, store, expect = browser_workspace
    stage = page.locator('.image-stage')
    canvas = page.locator('#canvas')
    original_width = canvas.bounding_box()['width']
    page.locator('.review-viewport-controls [aria-label^="확대"]').click()
    assert canvas.bounding_box()['width'] > original_width
    page.locator('.review-viewport-controls [aria-label^="이동"]').click()
    stage.scroll_into_view_if_needed()
    box = stage.bounding_box()
    cx, cy = box['x']+box['width']/2, box['y']+box['height']/2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx-80, cy-30, steps=4)
    page.mouse.up()
    assert stage.evaluate('(node) => node.scrollLeft') > 0
    assert len(store.get(0)['review']['boxes']) == 1
    page.locator('.review-viewport-controls [aria-label^="이동"]').click()
    page.locator('#draw').click()
    image = canvas.bounding_box()
    box = stage.bounding_box()
    x0, y0 = box['x']+box['width']/2-35, box['y']+box['height']/2-20
    x1, y1 = x0+90, y0+90
    expected = [round((x0-image['x'])*32/image['width'], 1), round((y0-image['y'])*24/image['height'], 1),
                round((x1-image['x'])*32/image['width'], 1), round((y1-image['y'])*24/image['height'], 1)]
    assert not stage.evaluate('(node) => node.classList.contains("review-pan")')
    assert 0 < expected[0] < expected[2] < 32 and 0 < expected[1] < expected[3] < 24, (image, box, expected)
    assert page.evaluate('([x,y]) => document.elementFromPoint(x,y)?.id', [x0,y0]) == 'canvas', (image,box,x0,y0)
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=4)
    page.mouse.up()
    expect(page.locator('#boxes .box-row')).to_have_count(2)
    actual = store.get(0)['review']['boxes'][-1]['bbox_xyxy']
    assert all(abs(a-b) < 1 for a, b in zip(actual, expected)), (actual, expected)
    page.keyboard.press('0')
    expect(page.locator('.review-zoom-level')).to_have_text('100%')


def test_custom_class_set_names_and_saves(custom_class_workspace):
    page, store, expect = custom_class_workspace
    select = page.locator('#boxes .box-top select').first
    expect(select.locator('option')).to_have_text(['클래스 선택 필요', '자동차', '신호등'])
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
    # Right after ticking the checkbox, without moving focus back to the canvas.
    page.locator('#complete').check()
    page.keyboard.press('a')
    expect(page.locator('#status')).to_have_text('승인')
    assert store.get(0)['status'] == 'approved'
    # X only excludes a pending photo; an approved one stays approved.
    page.keyboard.press('x')
    page.wait_for_timeout(300)
    assert store.get(0)['status'] == 'approved'
    page.locator('#reopen').click()
    expect(page.locator('#status')).to_have_text('검수 대기')
    # Korean IME: key is 'ㅁ' but the physical key is still KeyA.
    page.locator('#complete').check()
    page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ㅁ', code: 'KeyA', bubbles: true}))")
    expect(page.locator('#status')).to_have_text('승인')
    page.locator('#reopen').click()
    expect(page.locator('#status')).to_have_text('검수 대기')
    page.keyboard.press('x')
    expect(page.locator('#status')).to_have_text('제외')
    assert store.get(0)['status'] == 'excluded'


def test_review_shortcuts_confirm_then_move_without_approving(browser_workspace):
    page, store, expect = browser_workspace
    for index in (0, 1):
        row = store.get(index)
        store.update(index, {'version': row['version'], 'action': 'reopen'})
    page.reload(wait_until='networkidle')
    expect(page.locator('#complete')).not_to_be_checked()
    page.locator('#canvas').focus()
    page.keyboard.press('c')
    expect(page.locator('#complete')).to_be_checked()
    assert store.get(0)['status'] == 'pending'
    page.keyboard.press('n')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    assert store.get(0)['status'] == 'pending'


def test_learning_summary_separates_review_from_training(browser_workspace):
    page, _, expect = browser_workspace
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    expect(page.locator('#review-stage-summary')).to_contain_text('등록 2장')
    expect(page.locator('#training-data-state')).to_contain_text('픽셀 승인 0장')
    expect(page.get_by_text('현재 검수 중인 사진의 학습 완료를 뜻하지 않습니다.')).to_be_visible()
    expect(page.locator('#object-review-link')).to_contain_text('검수·승인')
    expect(page.locator('#pixel-review-link')).to_contain_text('검수·승인')
    page.locator('#object-review-link').click()
    expect(page.locator('#approve')).to_be_visible()
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    page.locator('#pixel-review-link').click()
    expect(page.locator('#pixel-approve')).to_be_visible()


def test_learning_shows_prepared_export_and_stale_decision(browser_workspace):
    page, store, expect = browser_workspace
    page.goto(page.url.split('?')[0].rstrip('/') + '/learning', wait_until='networkidle')
    expect(page.locator('#preparation-status')).to_contain_text('준비본 없음')
    store.prepare()
    page.reload(wait_until='networkidle')
    expect(page.locator('#preparation-status')).to_contain_text('픽셀 승인 0장 · 학습 입력 없음')
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    review_masks.update(store, 0, {'version': 1, 'action': 'approve',
                                   'complete_frame_review': True, 'background_reviewed': True}, Conflict)
    store.prepare()
    page.reload(wait_until='networkidle')
    expect(page.locator('#preparation-status')).to_contain_text('객체 1장 · 픽셀 1장 · 현재 결정 일치')
    row = store.get(0)
    store.update(0, {'version': row['version'], 'action': 'reopen'})
    page.reload(wait_until='networkidle')
    expect(page.locator('#preparation-status')).to_contain_text('현재 결정과 다름')


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


@pytest.mark.parametrize('custom_class_workspace', ["names: ['10', car, traffic_light]\n"], indirect=True)
def test_class_options_keep_class_index_order(custom_class_workspace):
    page, store, expect = custom_class_workspace
    expect(page.locator('#boxes .box-top select').first.locator('option')).to_have_text(
        ['클래스 선택 필요', '10', 'car', '신호등'])
