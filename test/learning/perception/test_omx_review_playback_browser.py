"""Recording frames verify atomic galleries and sequential playback in Chromium."""
import base64
import io
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def capture(page, name):
    if root := os.environ.get('ROSY_SCREENSHOT_DIR'):
        target = Path(root).expanduser() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
        print(f'screenshot: {target}')


@pytest.fixture
def playback_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    prepared_id, revision = 'a' * 32, 'b' * 64
    keys = ['observation.images.cam' + str(index) for index in range(10)]
    image = io.BytesIO()
    Image.new('RGB', (8, 6), 'blue').save(image, format='JPEG')
    jpeg = image.getvalue()
    state = SimpleNamespace(requests=[], pending=[], delay=None, fail=None, damaged=None, review_fail=False,
                            hold=False, inflight=0, max_inflight=0)

    def release():
        route, data = state.pending.pop(0)
        state.inflight -= 1  # The simulated server read finishes before its response is delivered.
        route.fulfill(json=data)

    state.release = release

    def packet(episode, frame, cameras):
        return {'prepared_id': prepared_id, 'source_revision': revision, 'episode_index': episode,
            'frame_index': frame, 'index': (0 if episode == 0 else 4) + frame,
            'timestamp_seconds': frame / 10, 'fps': 10,
            'frames': [{'camera_index': camera, 'camera_key': keys[camera], 'jpeg_base64': base64.b64encode(jpeg).decode(),
                        'width': 8, 'height': 6} for camera in cameras]}

    document = {'prepared_id': prepared_id, 'name': 'Playback fixture', 'source_revision': revision,
        'inspection': {'rig_revision': 'fixture-rig', 'calibration_revision': 'fixture-cal', 'source_mode': 'fixture',
            'camera_keys': keys, 'episodes': [{'episode_index': index, 'frames': frames,
                'content_sha256': str(index) * 64, 'session_id': str(index), 'cycle_id': str(index)}
                for index, frames in [(0, 4), (1, 3)]]},
        'decisions': [{'episode_index': index, 'outcome': 'failure', 'split': 'exclude',
                       'object_result': 'unknown', 'reason': 'original'} for index in (0, 1)],
        'latest_review_id': None, 'fixture_only': True, 'trainable': {'ok': False, 'reason': 'fixture draft'}}
    state.document = document
    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
                             snapshot=lambda: {'datasets': [], 'runs': [], 'methods': {}})
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.add_init_script("""const originalFetch=window.fetch;
                  window.fetch=(url,options)=>originalFetch(url,String(url).includes('/review-frame-set/')?
                    {...options,signal:undefined}:options);""")
                page.route('**/api/learning/omx', lambda route: route.fulfill(json={'sets': [{
                    'id': identifier, 'name': title, 'trainable': document['trainable'], 'episodes': []}
                    for identifier, title in [(prepared_id, 'Playback fixture'), ('c' * 32, 'Other recording')]]}))
                page.route('**/center/review/' + prepared_id, lambda route: route.fulfill(
                    status=400 if state.review_fail else 200,
                    json={'error': 'source hash changed'} if state.review_fail else document))
                page.route('**/center/review-frame/**', lambda route: route.fulfill(body=jpeg, content_type='image/jpeg'))

                def grouped(route):
                    parts = route.request.url.split('/')
                    episode, frame, cameras = int(parts[-3]), int(parts[-2]), tuple(map(int, parts[-1].split(',')))
                    target = (episode, frame, cameras)
                    state.requests.append(target)
                    state.inflight += 1
                    state.max_inflight = max(state.max_inflight, state.inflight)
                    data = packet(episode, frame, cameras)
                    if state.hold or target == state.delay:
                        state.pending.append((route, data))
                    elif target == state.fail:
                        state.inflight -= 1
                        route.fulfill(status=400, json={'error': 'source hash changed'})
                    else:
                        if target == state.damaged:
                            data['frames'].pop()
                        state.inflight -= 1
                        route.fulfill(json=data)

                page.route('**/center/review-frame-set/**', grouped)
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                page.locator('#review-open').click()
                yield page, state, playwright.expect
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_group_binding_subset_and_delayed_reply_do_not_replace_new_view(playback_page):
    page, state, expect = playback_page
    expect(page.locator('#review-view')).to_have_value('single')
    page.locator('#review-view').select_option('group')
    expect(page.locator('#review-gallery img')).to_have_count(8)
    expect(page.locator('#review-frame-status')).to_contain_text('시각 0')
    expect(page.locator('#review-frame-status')).to_contain_text('1–8 / 10')
    assert page.locator('#review-gallery img').evaluate_all('(images)=>images.every(image=>image.naturalWidth===8)')
    state.delay = (0, 1, tuple(range(8)))
    with page.expect_request('**/review-frame-set/**/0/1/0,1,2,3,4,5,6,7'):
        page.locator('#review-frame').evaluate("input=>{input.value='1';input.dispatchEvent(new Event('input',{bubbles:true}));}")
    page.locator('#review-camera').select_option('8')
    expect(page.locator('#review-gallery img')).to_have_count(2)
    expect(page.locator('#review-frame-status')).to_contain_text('9–10 / 10')
    expect(page.locator('#review-frame-status')).to_contain_text('시각 0.1')
    state.release()
    page.wait_for_timeout(80)  # Let an ignored-abort response reach the generation check.
    expect(page.locator('#review-gallery img')).to_have_count(2)
    expect(page.locator('#review-gallery')).to_contain_text('observation.images.cam8')
    expect(page.locator('#review-gallery')).not_to_contain_text('observation.images.cam0')
    page.locator('#review-episode').select_option('1')
    expect(page.locator('#review-frame')).to_have_value('0')
    expect(page.locator('#review-frame-status')).to_contain_text('기록 행 4')
    page.locator('#review-view').select_option('single')
    expect(page.locator('#review-gallery img')).to_have_count(0)
    expect(page.locator('#review-image')).to_be_visible()
    state.review_fail = True
    page.locator('#review-open').click()
    expect(page.locator('#review-status')).to_contain_text('source hash changed')
    expect(page.locator('#review-image')).to_be_hidden()
    expect(page.locator('#review-gallery img')).to_have_count(0)


def test_playback_is_sequential_stops_on_error_and_keeps_human_edits(playback_page):
    page, state, expect = playback_page
    page.locator('#review-view').select_option('group')
    expect(page.locator('#review-gallery img')).to_have_count(8)
    reason = page.locator('[data-episode="0"] [data-field="reason"]')
    reason.fill('unsaved human decision')
    page.locator('#reviewer').fill('Local Reviewer')
    page.locator('#review-confirmed').check()
    page.locator('#review-rate').fill('10')
    state.delay = (0, 1, tuple(range(8)))
    page.locator('#review-viewer').focus()
    with page.expect_request('**/review-frame-set/**/0/1/0,1,2,3,4,5,6,7'):
        page.locator('#review-viewer').press('Space')
    page.wait_for_timeout(220)  # Two requested intervals must not enqueue frames while one is pending.
    assert [row[1] for row in state.requests] == [0, 1]
    state.delay = None
    state.release()
    expect(page.locator('#review-frame')).to_have_value('3')
    expect(page.locator('#review-frame-status')).to_contain_text('마지막 프레임')
    expect(page.locator('#review-play')).to_have_text('자동 넘김 시작')
    assert [row[1] for row in state.requests] == [0, 1, 2, 3]
    page.locator('#review-viewer').press('ArrowLeft')
    expect(page.locator('#review-frame')).to_have_value('2')
    reason.focus()
    reason.press('ArrowRight')
    page.locator('#reviewer').press('ArrowRight')
    expect(page.locator('#review-frame')).to_have_value('2')
    expect(reason).to_have_value('unsaved human decision')
    expect(page.locator('#review-confirmed')).to_be_checked()

    page.locator('#review-first').click()
    expect(page.locator('#review-gallery img')).to_have_count(8)
    state.fail = (0, 1, tuple(range(8)))
    page.locator('#review-play').click()
    expect(page.locator('#review-frame-status')).to_contain_text('source hash changed')
    expect(page.locator('#review-play')).to_have_text('자동 넘김 시작')
    expect(page.locator('#review-gallery img')).to_have_count(0)
    count = len(state.requests)
    page.wait_for_timeout(220)
    assert len(state.requests) == count
    state.fail = None
    state.damaged = (0, 2, tuple(range(8)))
    page.locator('#review-frame').evaluate("input=>{input.value='2';input.dispatchEvent(new Event('input',{bubbles:true}));}")
    expect(page.locator('#review-frame-status')).to_contain_text('카메라')
    expect(page.locator('#review-gallery img')).to_have_count(0)
    expect(reason).to_have_value('unsaved human decision')
    expect(page.locator('#review-confirmed')).to_be_checked()


def test_space_on_a_playback_button_has_one_action(playback_page):
    page, state, expect = playback_page
    page.locator('#review-view').select_option('group')
    expect(page.locator('#review-gallery img')).to_have_count(8)
    page.locator('#review-rate').fill('1')
    state.hold = True
    page.locator('#review-play').press('Space')
    expect(page.locator('#review-play')).to_have_attribute('aria-pressed', 'true')
    page.locator('#review-play').press('Space')
    expect(page.locator('#review-play')).to_have_attribute('aria-pressed', 'false')
    state.hold = False
    while state.pending:
        state.release()
    page.locator('#review-first').click()
    expect(page.locator('#review-frame')).to_have_value('0')
    page.locator('#review-next').press('Space')
    expect(page.locator('#review-frame')).to_have_value('1')
    expect(page.locator('#review-play')).to_have_attribute('aria-pressed', 'false')


def test_manual_scrubbing_keeps_one_read_and_only_latest_pending_target(playback_page):
    page, state, expect = playback_page
    page.locator('#review-view').select_option('group')
    expect(page.locator('#review-gallery img')).to_have_count(8)
    baseline = len(state.requests)
    state.hold = True
    with page.expect_request('**/review-frame-set/**/0/1/0,1,2,3,4,5,6,7'):
        page.locator('#review-frame').evaluate("input=>{input.value='1';input.dispatchEvent(new Event('input'));}")
    page.locator('#review-frame').evaluate("""input=>{
        for(let index=0;index<20;index++){
            input.value=String((index+3)%4);input.dispatchEvent(new Event('input'));
        }
    }""")
    page.wait_for_timeout(500)  # Hold the server read while all twenty manual events reach the browser.
    issued = len(state.requests) - baseline
    print(f'MANUAL_SCRUB held issued={issued} inflight={state.inflight} max={state.max_inflight}')
    assert (issued, state.inflight, state.max_inflight) == (1, 1, 1)
    expect(page.locator('#review-frame')).to_have_value('2')
    expect(page.locator('#review-gallery img')).to_have_count(0)
    with page.expect_request('**/review-frame-set/**/0/2/0,1,2,3,4,5,6,7'):
        state.release()
    expect(page.locator('#review-gallery img')).to_have_count(0)
    assert len(state.pending) == 1
    state.hold = False
    state.release()
    expect(page.locator('#review-gallery img')).to_have_count(8)
    expect(page.locator('#review-frame-status')).to_contain_text('시각 0.2')
    assert len(state.requests) - baseline == 2
    assert state.max_inflight == 1
    print('MANUAL_SCRUB complete issued=2 max=1 latest=2')


def test_unsaved_review_guards_switch_reload_and_departure_without_blocking_refresh(playback_page):
    page, state, expect = playback_page
    reason = page.locator('[data-episode="0"] [data-field="reason"]')
    reason.fill('human judgment not saved')
    page.locator('#prepared-set').select_option('c' * 32)
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button', name='취소', exact=True).click()
    expect(page.locator('#prepared-set')).to_have_value('a' * 32)
    expect(reason).to_have_value('human judgment not saved')
    capture(page, 'recording-learning-review-unsaved.png')
    page.locator('#review-open').click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button', name='취소', exact=True).click()
    expect(reason).to_have_value('human judgment not saved')
    page.locator('#refresh').click()
    expect(page.locator('#omx-status')).to_contain_text('세트 2개')
    expect(reason).to_have_value('human judgment not saved')
    assert page.evaluate("""()=>{const event=new Event('beforeunload',{cancelable:true});
        window.dispatchEvent(event);return event.defaultPrevented;}""")
    # Confirmation opened before another edit must not discard that newer judgment.
    page.locator('#review-open').click()
    expect(page.get_by_role('dialog')).to_be_visible()
    reason.evaluate("""field=>{field.value='newer human judgment';
        field.dispatchEvent(new Event('input',{bubbles:true}));}""")
    page.get_by_role('button', name='편집 버리고 다시 불러오기', exact=True).click()
    expect(reason).to_have_value('newer human judgment')
    page.locator('#review-open').click()
    page.get_by_role('button', name='편집 버리고 다시 불러오기', exact=True).click()
    expect(reason).to_have_value('original')
    assert not page.evaluate("""()=>{const event=new Event('beforeunload',{cancelable:true});
        window.dispatchEvent(event);return event.defaultPrevented;}""")
    reason.fill('discard this edit')
    page.locator('#prepared-set').select_option('c' * 32)
    page.get_by_role('button', name='편집 버리고 자료 바꾸기', exact=True).click()
    expect(page.locator('#prepared-set')).to_have_value('c' * 32)
    expect(page.locator('#review-editor')).to_be_hidden()


def test_saved_review_selection_survives_edits_retry_save_and_binds_conversion(playback_page):
    import json
    page, state, expect = playback_page
    saved_id, next_id = 'd' * 32, 'e' * 32
    state.document.update(latest_review_id=saved_id, trainable={'ok': True, 'counts': {'train': 1, 'eval': 1}})
    page.locator('#review-open').click()
    page.locator('#export-saved-review').check()
    page.locator('#export-name').fill('Reviewed conversion')
    page.locator('#export-profile').set_input_files({'name': 'profile.json',
        'mimeType': 'application/json', 'buffer': json.dumps({'fixture': True}).encode()})
    expect(page.locator('#export-status')).to_contain_text('프로필 파일을 읽었습니다')
    page.locator('#refresh').click()
    expect(page.locator('#prepared-status')).to_contain_text('검수 분할 준비됨')
    expect(page.locator('#native-export')).to_be_enabled()
    reason = page.locator('[data-episode="0"] [data-field="reason"]')
    reason.fill('corrected human judgment')
    expect(page.locator('#export-saved-review')).to_be_checked()
    expect(page.locator('#native-export')).to_be_disabled()
    expect(page.locator('#export-review-status')).to_contain_text('미저장')
    page.locator('#export-saved-review').uncheck()
    expect(page.locator('#export-review-status')).to_contain_text('원본 검수')
    expect(page.locator('#native-export')).to_be_enabled()
    page.locator('#export-saved-review').check()
    posts, pending_saves, exports = [], [], []

    def save(route):
        posts.append(route.request.post_data_json)
        if len(posts) == 1:
            route.fulfill(status=503, json={'error': 'reply lost; retry same request'})
        else:
            pending_saves.append(route)

    page.route('**/center/review', save)
    page.locator('#reviewer').fill('Human Reviewer')
    page.locator('#review-confirmed').check()
    page.locator('#review-save').click()
    expect(page.locator('#review-status')).to_contain_text('reply lost')
    expect(reason).to_have_value('corrected human judgment')
    expect(page.locator('#native-export')).to_be_disabled()
    with page.expect_request('**/center/review'):
        page.locator('#review-save').click()
    page.locator('#prepared-set').select_option('c' * 32)
    expect(page.locator('#prepared-set')).to_have_value('a' * 32)
    assert len(pending_saves) == 1 and posts[0] == posts[1]
    state.document.update(latest_review_id=next_id, decisions=posts[1]['decisions'])
    pending_saves.pop().fulfill(json=dict(state.document, saved_review_id=next_id))
    expect(page.locator('#review-status')).to_contain_text(next_id)
    expect(page.locator('#export-saved-review')).to_be_checked()
    expect(page.locator('#export-review-status')).to_contain_text(next_id)
    capture(page, 'recording-learning-review-saved.png')
    expect(page.locator('#native-export')).to_be_enabled()
    state.review_fail = True
    page.locator('#review-open').click()
    expect(page.locator('#review-status')).to_contain_text('source hash changed')
    expect(page.locator('#export-saved-review')).to_be_checked()
    expect(page.locator('#native-export')).to_be_disabled()
    state.review_fail = False
    page.locator('#review-open').click()
    expect(page.locator('#export-review-status')).to_contain_text(next_id)
    expect(page.locator('#native-export')).to_be_enabled()
    page.route('**/center/export', lambda route: (exports.append(route.request.post_data_json),
        route.fulfill(json={'accepted': True})))
    page.locator('#native-export').click()
    expect(page.locator('#export-status')).to_contain_text('접수')
    assert len(exports) == 1 and exports[0]['review_id'] == next_id
    assert not page.evaluate("""()=>{const event=new Event('beforeunload',{cancelable:true});
        window.dispatchEvent(event);return event.defaultPrevented;}""")


@pytest.mark.parametrize('recovery', ['original', 'new_saved_review'])
def test_changed_recording_without_matching_review_keeps_saved_choice_blocked(playback_page, recovery):
    import json
    page, state, expect = playback_page
    state.document.update(latest_review_id='d' * 32,
                          trainable={'ok': True, 'counts': {'train': 1, 'eval': 1}})
    page.locator('#review-open').click()
    page.locator('#export-saved-review').check()
    page.locator('#export-name').fill('Source revision changed')
    page.locator('#export-profile').set_input_files({'name': 'profile.json',
        'mimeType': 'application/json', 'buffer': json.dumps({'fixture': True}).encode()})
    page.locator('#refresh').click()
    expect(page.locator('#native-export')).to_be_enabled()
    # The owner retains the prepared ID but invalidates older review snapshots for new bytes.
    state.document.update(source_revision='f' * 64, latest_review_id=None)
    page.locator('#review-open').click()
    expect(page.locator('#review-meta')).to_contain_text('f' * 64)
    expect(page.locator('#export-saved-review')).to_be_checked()
    expect(page.locator('#export-saved-review')).to_be_enabled()
    expect(page.locator('#native-export')).to_be_disabled()
    expect(page.locator('#export-review-status')).to_contain_text('저장 검수 사용 대기')
    page.locator('#refresh').click()
    expect(page.locator('#prepared-status')).to_contain_text('검수 분할 준비됨')
    expect(page.locator('#native-export')).to_be_disabled()
    exports = []
    page.route('**/center/export', lambda route: (exports.append(route.request.post_data_json),
        route.fulfill(json={'accepted': True})))
    if recovery == 'original':
        page.locator('#export-saved-review').uncheck()
        expect(page.locator('#export-review-status')).to_contain_text('원본 검수 결정 사용')
    else:
        state.document['latest_review_id'] = 'e' * 32
        page.locator('#review-open').click()
        expect(page.locator('#export-saved-review')).to_be_checked()
        expect(page.locator('#export-review-status')).to_contain_text('e' * 32)
    expect(page.locator('#native-export')).to_be_enabled()
    page.locator('#native-export').click()
    expect(page.locator('#export-status')).to_contain_text('접수')
    assert len(exports) == 1
    assert exports[0].get('review_id') == (None if recovery == 'original' else 'e' * 32)
