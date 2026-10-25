"""Recording API plus real Chromium verifies guided immutable profile versions."""
import copy
import json
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_saved_profile_training_requires_semantic_dataset_match_and_can_be_cleared(tmp_path):
    import uuid
    playwright = pytest.importorskip('playwright.sync_api')
    profile = {'schema': 'rosy.omx.learning-profile/2', 'name': 'Dataset profile', 'task': 'Fixture task',
        'mode': 'independent', 'arms': [{'id': 'arm', 'joint_names': ['joint'], 'units': 'rad', 'action_limits': [[-1, 1]]}],
        'cameras': [{'id': 'top', 'input_key': 'observation.images.top', 'arm_id': None, 'role': 'top',
            'source_identity': 'fixture:top', 'placement': 'overhead', 'shape': [3, 8, 8], 'purposes': ['policy']}]}
    stored = json.loads(json.dumps(profile, sort_keys=True))
    mismatch = copy.deepcopy(stored)
    mismatch['cameras'][0]['placement'] = 'side'
    parent_id, mismatch_id, saved_id = [str(uuid.uuid4()) for _ in range(3)]
    records = [{'id': parent_id, 'revision': 'a' * 64, 'profile': stored, 'created_by': 'fixture'},
               {'id': mismatch_id, 'revision': 'b' * 64, 'profile': mismatch, 'created_by': 'fixture'}]
    offline, online, runs, saves = [], [], [], []
    save_release = threading.Event()

    def save(body, actor=None):
        assert save_release.wait(10), 'release the delayed save before continuing'
        saves.append(body)
        result = {'id': saved_id, 'revision': 'c' * 64,
                  'profile': json.loads(json.dumps(body['profile'], sort_keys=True)), 'created_by': 'fixture'}
        records.append(result)
        return result

    def start(body, *, continuous=False):
        (online if continuous else offline).append(body)
        run = dict(body, id=str(uuid.uuid4()), status='queued',
                   execution_mode='online_experience' if continuous else 'offline_replay')
        runs.append(run)
        return run

    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: records, get=lambda identity: next(row for row in records if row['id'] == identity), save=save),
        snapshot=lambda: {'datasets': [{'id': 'original', 'name': 'Original dataset', 'profile': profile},
                                       {'id': 'other', 'name': 'Other dataset', 'profile': mismatch}], 'runs': runs,
                          'methods': {method: {'available': True} for method in ('act', 'hilserl')}},
        start=start, start_online=lambda body: start(body, continuous=True))
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                expect = playwright.expect
                page.locator('#profile-panel > summary').click()
                page.locator('#profile-record').select_option(parent_id)
                page.locator('#profile-clone').click()
                expect(page.locator('#profile-diff')).to_contain_text('변경 없음')
                page.locator('#profile-import-dataset').click()
                page.locator('#profile-save').click()
                try:
                    expect(page.locator('#profile-name')).to_be_disabled()
                    for control in ['profile-add-arm', 'profile-add-camera']:
                        page.locator('#'+control).evaluate('node=>node.click()')
                    expect(page.locator('#profile-arms > fieldset')).to_have_count(1)
                    expect(page.locator('#profile-cameras > fieldset')).to_have_count(1)
                finally:
                    save_release.set()
                expect(page.locator('#profiles-status')).to_contain_text(saved_id)
                assert 'parent_id' not in saves[0]
                expect(page.locator('#profile-diff')).to_contain_text('변경 없음')
                page.locator('#profile-use').click()
                expect(page.locator('#selected-profile-status')).to_contain_text('일치')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(1)
                assert offline[0]['profile_id'] == saved_id
                page.locator('#execution-mode').select_option('online_experience')
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(2)
                assert online[0]['profile_id'] == saved_id
                page.locator('#profile-record').select_option(mismatch_id)
                page.locator('#profile-use').click()
                expect(page.locator('#start')).to_be_disabled()
                expect(page.locator('#selected-profile-status')).to_contain_text('다릅니다')
                page.locator('#dataset').select_option('other')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#dataset').select_option('original')
                expect(page.locator('#start')).to_be_disabled()
                page.locator('#profile-clear').click()
                page.locator('#execution-mode').select_option('offline')
                page.locator('#method').select_option('act')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#start').click()
                expect(page.locator('#runs > section')).to_have_count(3)
                assert len(offline) == 2 and 'profile_id' not in offline[-1]
                assert profile['cameras'][0]['placement'] == 'overhead'
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_guided_profiles_preserve_order_bounds_lineage_and_explicit_export_selection(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    original_id = '11111111-1111-4111-8111-111111111111'
    saved_id = '22222222-2222-4222-8222-222222222222'
    original = {'schema': 'rosy.omx.learning-profile/1', 'name': 'Two arm fixture', 'task': 'Declared fixture task',
        'mode': 'cooperative', 'arms': [{'id': identity, 'joint_names': ['joint'], 'units': 'rad'}
                                     for identity in ('left', 'right')],
        'cameras': [{'id': identity, 'input_key': 'observation.images.' + identity,
            'arm_id': arm, 'role': 'wrist' if arm else 'top', 'source_identity': 'fixture:' + identity,
            'placement': 'attached' if arm else 'overhead', 'shape': [3, 8, 8], 'purposes': ['policy', 'record']}
            for identity, arm in [('top', None), ('left_wrist', 'left'), ('right_wrist', 'right')]]}
    untouched = copy.deepcopy(original)
    records = [{'id': original_id, 'revision': 'a' * 64, 'profile': original, 'parent_id': None,
                'created_by': 'recording-user', 'physical_setup_verified': False, 'policy_activation': False}]
    requests, exports = [], []
    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: records, get=lambda identity: next(row for row in records if row['id'] == identity)),
        snapshot=lambda: {
        'datasets': [{'id': 'dataset', 'name': 'Existing dataset', 'profile': original}], 'runs': [], 'methods': {}})
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/center/profiles', lambda route: route.fulfill(json={'profiles': records}))

                def save(route):
                    body = route.request.post_data_json
                    requests.append(body)
                    if len(records) == 1:
                        records.append(dict(records[0], id=saved_id, revision='b' * 64,
                                            profile=body['profile'], parent_id=body['parent_id']))
                        route.fulfill(status=503, json={'error': 'reply lost; retry same request'})
                    else:
                        route.fulfill(json=records[-1])

                def exported(route):
                    exports.append(route.request.post_data_json)
                    route.fulfill(json={'id': 'acknowledged-export'})

                page.route('**/center/profile', save)
                page.route('**/center/export', exported)
                page.route('**/api/learning/omx', lambda route: route.fulfill(json={'sets': [{
                    'id': '3' * 32, 'name': 'Registered ready fixture', 'episodes': [],
                    'trainable': {'ok': True, 'counts': {'train': 1, 'eval': 1}}}]}))
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                expect = playwright.expect
                page.locator('#profile-panel > summary').click()
                page.locator('#profile-record').select_option(records[0]['id'])
                page.locator('#profile-clone').click()
                expect(page.locator('#profile-arms [data-arm]')).to_have_count(2)
                expect(page.locator('#profile-cameras [data-camera]')).to_have_count(3)
                page.locator('[data-arm="1"] [data-action="up"]').click()
                expect(page.locator('[data-arm="0"] [data-field="id"]')).to_have_value('right')
                page.locator('[data-camera="2"] [data-action="up"]').click()
                expect(page.locator('[data-camera="2"] [data-field="arm_id"]')).to_have_value('left')
                page.locator('[data-camera="0"] [data-field="placement"]').fill('above_shifted')
                page.locator('#profile-name').fill('Moved top camera fixture')
                page.locator('#profile-bounds').check()
                page.locator('#profile-save').click()
                expect(page.locator('#profiles-status')).to_contain_text('하한·상한')
                assert requests == []
                for index in range(2):
                    page.locator(f'[data-arm="{index}"] [data-field="lower-0"]').fill('-1')
                    page.locator(f'[data-arm="{index}"] [data-field="upper-0"]').fill('1')
                expect(page.locator('#profile-diff')).to_contain_text('above_shifted')
                expect(page.locator('#profile-diff')).to_contain_text('overhead')
                page.locator('#profile-save').click()
                expect(page.locator('#profiles-status')).to_contain_text('reply lost')
                page.locator('#profile-save').click()
                expect(page.locator('#profiles-status')).to_contain_text(saved_id)
                assert requests[0] == requests[1]
                assert set(requests[0]) == {'profile', 'parent_id', 'request_id'}
                assert requests[0]['parent_id'] == records[0]['id']
                assert original == untouched
                page.locator('#profile-task').fill('Unsaved task edit')
                page.locator('#profiles-refresh').click()
                expect(page.locator('#profile-task')).to_have_value('Unsaved task edit')
                page.reload(wait_until='networkidle')
                page.locator('#profile-panel > summary').click()
                page.locator('#profile-record').select_option(records[-1]['id'])
                page.locator('#profile-clone').click()
                expect(page.locator('[data-camera="0"] [data-field="placement"]')).to_have_value('above_shifted')
                page.locator('[data-arm="1"] [data-action="remove"]').click()
                expect(page.locator('[data-camera="2"] [data-field="arm_id"]')).to_have_value('left')
                page.locator('#profile-save').click()
                expect(page.locator('#profiles-status')).to_contain_text('알 수 없는 팔')
                assert len(requests) == 2
                page.locator('#profile-clone').click()
                with page.expect_download() as download:
                    page.locator('#profile-download').click()
                assert download.value.suggested_filename == 'omx-profile-' + records[-1]['id'] + '.json'
                assert json.loads(open(download.value.path(), encoding='utf-8').read()) == records[-1]['profile']
                page.locator('#profile-use').click()
                expect(page.locator('#export-profile')).not_to_have_attribute('required', '')
                page.locator('#export-name').fill('Selected saved profile export')
                page.locator('#native-export').click()
                expect(page.locator('#export-status')).to_contain_text('접수')
                assert exports[0]['profile_id'] == records[-1]['id']
                assert exports[0]['profile'] == records[-1]['profile']
                page.locator('#export-profile').set_input_files({'name': 'alternative.json',
                    'mimeType': 'application/json', 'buffer': json.dumps(original).encode()})
                expect(page.locator('#export-profile')).to_have_attribute('required', '')
                expect(page.locator('#export-status')).to_contain_text('파일을 읽었습니다')
                page.locator('#native-export').click()
                expect(page.locator('#export-status')).to_contain_text('접수')
                assert 'profile_id' not in exports[-1]
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
