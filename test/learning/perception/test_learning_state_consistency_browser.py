"""A verdict belongs to its submitted inputs; failed reads must finish and be retryable."""
import base64
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled
from test_review_app import open_store
from test_review_flow_browser import serve

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium state consistency')
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1cAAAAASUVORK5CYII=')
REF = {'revision': 'a' * 64, 'camera_role': 'front', 'camera_identity': 'fixture-camera',
       'created_at': 'fixture', 'method': 'features', 'width': 1, 'height': 1,
       'intrinsics': {'camera_info_sha256': 'c' * 64}, 'guides': [], 'markers': [],
       'check_pose': {'joint_names': ['joint1'], 'positions_rad': [0]}}
OK = {'check': {'verdict': 'ok', 'method': 'features', 'matches': 40}, 'homography': None}


def capture(page, name):
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / f'consistency-{name}.png'))


@pytest.fixture
def workspace(tmp_path):
    with serve(open_store(tmp_path)) as (page, _, expect):
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(page.url))
        state = {'status': 200, 'hold': False, 'checks': [], 'held': []}
        refs = [REF, dict(REF, revision='b' * 64)]
        def camera(route):
            path = urlsplit(route.request.url).path
            if '/stills/' in path:
                route.fulfill(body=PNG, content_type='image/png'); return
            if path.endswith('/check'):
                state['checks'].append(route.request.post_data_json)
                if state['hold']: state['held'].append(route)
                else: route.fulfill(json=copy.deepcopy(OK))
            else:
                route.fulfill(status=state['status'], json={'references': refs} if state['status'] == 200 else {'error': 'fixture read failed'})
        page.route('**/api/learning/camera/**', camera)
        page.route('**/api/learning', lambda route: route.fulfill(status=state['status'], json={'token': 'fixture', 'domains': []} if state['status'] == 200 else {'error': 'fixture read failed'}))
        page.route('**/api/learning/promotion-requests', lambda route: route.fulfill(json={'candidates': [], 'requests': []}))
        yield page, state, origin, expect


def ready_camera(page, origin, expect):
    page.goto(origin + '/learning/camera')
    expect(page.locator('#reference option')).to_have_count(2)
    page.set_input_files('#check-photo', {'name': 'fixture.png', 'mimeType': 'image/png', 'buffer': PNG})


def change_input(page, key):
    if key == 'photo':
        page.set_input_files('#check-photo', {'name': 'new.png', 'mimeType': 'image/png', 'buffer': PNG})
    elif key == 'reference': page.select_option('#reference', 'b' * 64)
    elif key == 'fingerprint': page.fill('#fingerprint', 'd' * 64)
    else: page.fill('#joints', '{"joint1":0.1}')


@pytest.mark.parametrize('key', ['photo', 'reference', 'fingerprint', 'joints'])
@pytest.mark.parametrize('width', [320, 1440])
def test_input_change_invalidates_the_previous_ready_verdict(workspace, key, width):
    page, _, origin, expect = workspace
    page.set_viewport_size({'width': width, 'height': 900})
    ready_camera(page, origin, expect)
    page.locator('#check-form ui-button[type=submit]').click()
    expect(page.locator('#verdict')).to_have_attribute('state', 'ready')
    change_input(page, key)
    expect(page.locator('#verdict')).not_to_contain_text('녹화할 수 있습니다')
    expect(page.locator('#numbers dt')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture(page, f'invalidated-{key}-{width}')


@pytest.mark.parametrize('key', ['photo', 'reference', 'fingerprint', 'joints'])
def test_late_verdict_cannot_describe_changed_inputs(workspace, key):
    page, state, origin, expect = workspace
    ready_camera(page, origin, expect)
    state['hold'] = True
    page.locator('#check-form ui-button[type=submit]').click()
    page.wait_for_function("document.querySelector('#view').hidden === false")
    expect(page.locator('#check-form ui-button[type=submit]')).to_be_disabled()
    assert len(state['held']) == 1
    change_input(page, key)
    state['held'][0].fulfill(json=copy.deepcopy(OK))
    page.wait_for_timeout(100)
    expect(page.locator('#verdict')).not_to_have_attribute('state', 'ready')
    expect(page.locator('#numbers dt')).to_have_count(0)
    expect(page.locator('#check-form ui-button[type=submit]')).to_be_enabled()


def test_image_decode_cannot_mix_an_old_photo_with_a_new_reference(workspace):
    page, state, origin, expect = workspace
    ready_camera(page, origin, expect)
    page.evaluate("""() => {const decode = window.createImageBitmap;
      window.createImageBitmap = async (...args) => {const image = await decode(...args);
        await new Promise(resolve => window.releaseImage = resolve); return image;};} """)
    page.locator('#check-form ui-button[type=submit]').click()
    page.wait_for_function('window.releaseImage !== undefined')
    page.select_option('#reference', 'b' * 64)
    page.evaluate('window.releaseImage()')
    page.wait_for_timeout(100)
    assert state['checks'] == []
    expect(page.locator('#verdict')).not_to_have_attribute('state', 'ready')


@pytest.mark.parametrize('surface', ['camera', 'evaluate'])
@pytest.mark.parametrize('status', [401, 403, 503])
@pytest.mark.parametrize('width', [390, 1440])
def test_failed_read_finishes_and_recovers_without_losing_input(workspace, surface, status, width):
    page, state, origin, expect = workspace
    state['status'] = status
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(origin + '/learning/' + surface + ('?domain=lane' if surface == 'evaluate' else ''))
    expect(page.locator('#' + surface + '-error')).to_be_visible()
    status_node = page.locator('#verdict' if surface == 'camera' else '#promote-status')
    expect(status_node).to_contain_text('다시 확인')
    if surface == 'camera': page.fill('#camera-identity', 'keep fixture input')
    capture(page, f'read-error-{surface}-{status}-{width}')
    state['status'] = 200
    page.locator('#' + surface + '-refresh').click()
    expect(page.locator('#' + surface + '-error')).to_be_hidden()
    expect(status_node).not_to_contain_text('확인하는 중')
    if surface == 'camera':
        expect(page.locator('#reference option')).to_have_count(2)
        expect(page.locator('#camera-identity')).to_have_value('keep fixture input')
    else:
        expect(page.locator('#promote-status')).to_contain_text('등록된 인식 학습 결과가 없습니다')
        expect(page.locator('#promote-request')).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture(page, f'recovered-{surface}-{status}-{width}')
