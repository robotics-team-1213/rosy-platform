"""Real Chromium proves center actions and failure recovery inside the existing app."""
import threading
import base64
import uuid
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_native_review_preview_explicit_confirmation_retry_and_stale_reload(tmp_path):
    import io
    import json
    from PIL import Image
    playwright = pytest.importorskip('playwright.sync_api')
    prepared_id, revision, saved_id = 'a' * 32, 'b' * 64, 'c' * 32
    episodes = [{'episode_index': i, 'frames': 3, 'content_sha256': str(i) * 64,
                 'session_id': f'session-{i}', 'cycle_id': f'cycle-{i}'} for i in range(2)]
    decisions = [dict(episode, outcome='failure', object_result='dropped', split='exclude', reason='original failure')
                 for episode in episodes]
    document = {'prepared_id': prepared_id, 'name': 'Recorded review fixture', 'source_revision': revision,
                'inspection': {'rig_revision': 'rig-sealed', 'calibration_revision': 'cal-sealed',
                    'source_mode': 'fixture', 'camera_keys': ['observation.images.top', 'observation.images.wrist'],
                    'episodes': episodes}, 'decisions': decisions, 'latest_review_id': None,
                'trainable': {'ok': False, 'reason': 'missing independent eval'}, 'fixture_only': True}
    posts, frames = [], []
    image = io.BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(image, format='JPEG')
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
                page.route('**/api/learning/omx', lambda route: route.fulfill(json={'sets': [{
                    'id': prepared_id, 'name': document['name'], 'trainable': document['trainable'], 'episodes': []}]}))
                page.route('**/center/review/' + prepared_id, lambda route: route.fulfill(json=document))

                def preview(route):
                    frames.append(route.request.url)
                    route.fulfill(body=image.getvalue(), content_type='image/jpeg')

                def save(route):
                    body = route.request.post_data_json
                    posts.append(body)
                    if len(posts) == 1:
                        route.fulfill(status=503, json={'error': 'reply lost; retry same request'})
                    elif len(posts) == 3:
                        route.fulfill(status=409, json={'error': 'stale source revision; reload required'})
                    else:
                        document.update(decisions=[dict(episodes[i], **row) for i, row in enumerate(body['decisions'])],
                            latest_review_id=saved_id, reviewer_identity={'kind': 'local_unverified', 'id': body['reviewer']})
                        route.fulfill(json=dict(document, saved_review_id=saved_id))

                page.route('**/center/review-frame/**', preview)
                page.route('**/center/review', save)
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                page.locator('#review-open').click()
                expect = playwright.expect
                expect(page.locator('#review-meta')).to_contain_text('rig-sealed')
                expect(page.locator('#review-meta')).to_contain_text('session-0')
                expect(page.locator('#review-status')).to_contain_text('fixture')
                expect(page.locator('#review-image')).to_have_attribute('src',
                    f'/api/learning/omx/center/review-frame/{prepared_id}/{revision}/0/0/0')
                expect(page.locator('#review-image')).to_be_visible()
                assert page.locator('#review-image').evaluate('(image)=>image.naturalWidth') == 8
                page.locator('#review-camera').select_option('1')
                page.locator('#review-last').click()
                expect(page.locator('#review-image')).to_have_attribute('src',
                    f'/api/learning/omx/center/review-frame/{prepared_id}/{revision}/0/2/1')
                expect(page.locator('#review-save')).to_be_disabled()
                page.locator('[data-episode="0"] [data-field="outcome"]').select_option('success')
                page.locator('[data-episode="0"] [data-field="split"]').select_option('train')
                page.locator('[data-episode="0"] [data-field="reason"]').fill('observed first attempt')
                page.locator('#reviewer').fill('Local Reviewer')
                page.locator('#review-confirmed').check()
                page.locator('#review-save').click()
                expect(page.locator('#review-status')).to_contain_text('reply lost')
                page.locator('#review-save').click()
                expect(page.locator('#review-status')).to_contain_text(saved_id)
                assert posts[0] == posts[1]
                assert set(posts[0]) == {'prepared_id', 'source_revision', 'decisions', 'reviewer', 'confirmed', 'request_id'}
                assert posts[0]['decisions'][1]['outcome'] == 'failure'
                assert posts[0]['decisions'][1]['split'] == 'exclude'
                uuid.UUID(posts[0]['request_id'])
                expect(page.locator('#review-identity')).to_contain_text('local_unverified')
                page.locator('[data-episode="0"] [data-field="reason"]').fill('new unsaved reason')
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(page.locator('[data-episode="0"] [data-field="reason"]')).to_have_value('new unsaved reason')
                page.locator('#review-confirmed').check()
                page.locator('#review-save').click()
                expect(page.locator('#review-status')).to_contain_text('stale source revision')
                expect(page.locator('#review-save')).to_be_disabled()
                page.reload(wait_until='networkidle')
                page.locator('#review-open').click()
                expect(page.locator('[data-episode="0"] [data-field="reason"]')).to_have_value('observed first attempt')
                expect(page.locator('#export-saved-review')).not_to_be_checked()
                expect(page.locator('#export-saved-review')).to_be_enabled()
                page.locator('#export-saved-review').check()
                expect(page.locator('#export-review-status')).to_contain_text(saved_id)
                assert frames
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_learning_center_offline_and_continuous_experience_actions(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    class Center:
        def bind_workspace(self, project):
            self.project = project

        def __init__(self):
            self.profiles = SimpleNamespace(list=lambda: [])
            self.runs = []
            self.requests = []
            self.uploads = []
            self.online_requests = []
            self.experiences = []
            self.datasets = []

        def upload(self, body):
            self.uploads.append(body)
            return {'offset': body['offset'] + len(base64.b64decode(body['data']))}

        def publish(self, body):
            row = {'id': str(uuid.uuid4()), 'name': body['name'], 'profile': {
                'schema': 'rosy.omx.learning-profile/2', 'arms': [
                    {'id': 'left', 'joint_names': ['joint'], 'action_limits': [[-1, 1]]}]}}
            self.datasets.append(row)
            return row

        def snapshot(self):
            return {'datasets': [{'id': 'dataset', 'name': 'Two arms and three cameras',
                'source': 'synthetic_smoke', 'revision': 'sealed',
                'profile': {'schema': 'rosy.omx.learning-profile/1',
                            'mode': 'cooperative', 'arms': [{'id': 'left'}, {'id': 'right'}],
                            'cameras': [{'id': 'top', 'placement': 'overhead'},
                                        {'id': 'wrist_left'}, {'id': 'wrist_right'}]}}] + self.datasets,
                'runs': self.runs, 'methods': {m: {'available': True} for m in ('act', 'hilserl')}}

        def start(self, body):
            self.requests.append(body)
            row = dict(id='run', status='running', progress={'step': 1}, **body)
            self.runs.append(row)
            return row

        def stop(self, body):
            row = next(row for row in self.runs if row['id'] == body['id'])
            row['status'] = 'cancelled'
            return row

        def start_online(self, body):
            self.online_requests.append(body)
            row = dict(id=str(uuid.uuid4()), status='running', execution_mode='online_experience',
                       inputs=[],
                       progress={'phase': 'waiting_for_experience', 'total_steps': 2,
                                 'consumed_inputs': ['initial'], 'latest_version': '000001',
                                 'input_errors': []}, **body)
            self.runs.append(row)
            return row

        def experience(self, body):
            self.experiences.append(body)
            rejected = len(self.experiences) > 1
            self.runs[-1]['inputs'].append({'id': body['request_id'], 'dataset_id': body['dataset_id'],
                                           'sequence': len(self.experiences),
                                           'status': 'rejected' if rejected else 'queued'})
            if rejected:
                self.runs[-1]['progress']['input_errors'] = [{'id': body['request_id'], 'error': 'profile mismatch'}]
            return {'id': body['request_id']}

    center = Center()
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                expect = playwright.expect
                expect(page.locator('#dataset-profile')).to_contain_text('wrist_right')
                expect(page.locator('#dataset-profile')).to_contain_text('합성 스모크')
                expect(page.locator('#method')).to_contain_text('오프라인 경험 재학습')
                folder = tmp_path / 'upload'
                folder.mkdir()
                for name in ('dataset.json', 'episode.npz', 'conversion-receipt.json', 'native-split-receipt.json'):
                    (folder / name).write_bytes(b'fixture')
                page.locator('#dataset-folder').set_input_files(str(folder))
                page.locator('#dataset-name').fill('Native conversion fixture')
                page.locator('#upload').click()
                expect(page.locator('#upload-status')).to_contain_text('데이터 검증을 마쳤습니다')
                assert {row['name'] for row in center.uploads} == {p.name for p in folder.iterdir()}
                page.locator('#method').select_option('hilserl')
                page.locator('#steps').fill('2')
                page.locator('#start').click()
                expect(page.locator('#runs')).to_contain_text('학습 중')
                assert center.requests[0]['method'] == 'hilserl'
                page.get_by_role('button', name='이 학습 중지').click()
                expect(page.locator('#runs')).to_contain_text('취소됨')
                page.reload(wait_until='networkidle')
                expect(page.locator('#runs')).to_contain_text('취소됨')
                assert len(center.requests) == 1
                page.locator('#execution-mode').select_option('online_experience')
                expect(page.locator('#method')).to_have_value('hilserl')
                expect(page.locator('#method option[value="act"]')).to_have_attribute('disabled', '')
                page.locator('#dataset').select_option('dataset')
                expect(page.locator('#start')).to_be_disabled()
                expect(page.locator('#method-status')).to_contain_text('action_limits')
                page.locator('#dataset').select_option(center.datasets[0]['id'])
                expect(page.locator('#start')).to_be_enabled()
                expect(page.locator('main')).to_contain_text('현장 actor 미연결')
                page.locator('#steps').fill('2')
                page.locator('#start').click()
                expect(page.locator('#runs')).to_contain_text('경험 대기 중')
                expect(page.locator('#runs')).to_contain_text('정책 버전 000001')
                online = center.runs[-1]
                assert center.online_requests[0] == {
                    'dataset_id': center.datasets[0]['id'], 'method': 'hilserl', 'steps': 2,
                    'batch_size': 8, 'device': 'cpu', 'seed': 0,
                    'request_id': center.online_requests[0]['request_id']}
                uuid.UUID(center.online_requests[0]['request_id'])
                link = page.get_by_role('link', name='최신 저장 정책·입력·평가 내려받기')
                expect(link).to_have_attribute('href', '/api/learning/omx/center/artifact/' + online['id'])
                page.locator('#dataset-folder').set_input_files(str(folder))
                page.locator('#dataset-name').fill('New recovery experience')
                page.locator('#upload').click()
                expect(page.get_by_role('option', name='New recovery experience')).to_be_attached()
                expect(page.locator('#dataset')).to_have_value(center.datasets[1]['id'])
                page.locator('#experience-run').select_option(online['id'])
                page.locator('#add-experience').click()
                expect(page.locator('#experience-status')).to_contain_text('입력 대기열에 추가')
                assert center.experiences[0]['id'] == online['id']
                assert center.experiences[0]['dataset_id'] == center.datasets[1]['id']
                assert set(center.experiences[0]) == {'id', 'dataset_id', 'request_id'}
                uuid.UUID(center.experiences[0]['request_id'])
                expect(page.locator('#runs')).to_contain_text('접수된 입력 1개 · 입력 대기 1개 · 소비 0개 · 거절 0개')
                online['inputs'][0]['status'] = 'consumed'
                online['progress'].update(total_steps=4, latest_version='000002',
                    consumed_inputs=['initial', center.experiences[0]['request_id']])
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(page.locator('#runs')).to_contain_text('정책 버전 000002')
                expect(page.locator('#runs')).to_contain_text('입력 대기 0개 · 소비 1개 · 거절 0개')
                page.locator('#add-experience').click()
                expect(page.locator('#runs')).to_contain_text('거절된 입력 1개')
                expect(page.locator('#runs')).to_contain_text('접수된 입력 2개 · 입력 대기 0개 · 소비 1개 · 거절 1개')
                expect(page.locator('#runs')).to_contain_text('profile mismatch')
                page.reload(wait_until='networkidle')
                expect(page.locator('#runs')).to_contain_text('경험 대기 중')
                expect(page.locator('#runs')).to_contain_text('profile mismatch')
                assert len(center.online_requests) == 1 and len(center.experiences) == 2
                page.get_by_role('button', name='이 학습 중지').click()
                expect(page.locator('#experience-run')).to_be_disabled()
                expect(page.locator('#add-experience')).to_be_disabled()
                page.locator('#execution-mode').select_option('offline')
                expect(page.locator('#method option[value="act"]')).not_to_have_attribute('disabled', '')
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_native_export_validates_file_retries_same_request_and_tracks_jobs(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    prepared_id = None
    profile = {'schema': 'rosy.omx.learning-profile/2', 'name': 'Declared native mapping'}

    class Center:
        def __init__(self):
            self.profiles = SimpleNamespace(list=lambda: [])
            self.runs, self.requests, self.datasets = [], [], []

        def bind_workspace(self, project):
            pass

        def snapshot(self):
            return {'datasets': self.datasets, 'runs': self.runs, 'methods': {}}

        def start_export(self, body, prepared_row=None):
            assert prepared_row['id'] == prepared_id and prepared_row['kind'] == 'omx'
            self.requests.append(body)
            existing = next((run for run in self.runs if run['request_id'] == body['request_id']), None)
            if existing:
                return existing
            run = dict(body, id=str(uuid.uuid4()), method='act', execution_mode='native_export',
                       status='running', progress={'phase': 'verifying'})
            self.runs.append(run)
            if len(self.runs) == 1:
                raise ValueError('reply lost after recording request; retry safely')
            return run

        export = start_export

        def stop(self, body):
            run = next(run for run in self.runs if run['id'] == body['id'])
            run['status'] = 'cancelled'
            return run

    center = Center()
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    prepared = tmp_path / 'prepared'
    prepared.mkdir()
    (prepared / 'intake-receipt.json').write_text('{"schema":"rosy.omx.intake/1"}')
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                origin = f'http://127.0.0.1:{server.server_port}'
                token = page.request.get(origin + '/api/learning').json()['token']
                registered = page.request.post(origin + '/api/learning/register',
                    headers={'X-Pinky-Token': token, 'Origin': origin},
                    data={'kind': 'omx', 'name': 'Registered reviewed native set', 'path': str(prepared)})
                assert registered.ok, registered.text()
                prepared_id = registered.json()['id']
                page.route('**/api/learning/omx', lambda route: route.fulfill(json={'sets': [{
                    'id': prepared_id, 'name': 'Registered reviewed native set',
                    'trainable': {'ok': True, 'counts': {'train': 2, 'eval': 1}}, 'episodes': []}]}))
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                expect = playwright.expect
                expect(page.locator('#native-export')).to_be_disabled()
                page.locator('#export-name').fill('Native ACT data')
                page.locator('#export-profile').set_input_files({'name': 'large.json', 'mimeType': 'application/json',
                                                               'buffer': b' ' * (1024 * 1024 + 1)})
                expect(page.locator('#export-status')).to_contain_text('1 MiB')
                expect(page.locator('#native-export')).to_be_disabled()
                page.locator('#export-profile').set_input_files({'name': 'bad.json', 'mimeType': 'application/json',
                                                               'buffer': b'[]'})
                expect(page.locator('#export-status')).to_contain_text('JSON 객체')
                expect(page.locator('#native-export')).to_be_disabled()
                import json
                page.locator('#export-profile').set_input_files({'name': 'profile.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(profile).encode()})
                expect(page.locator('#native-export')).to_be_enabled()
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(page.locator('#export-name')).to_have_value('Native ACT data')
                expect(page.locator('#export-profile')).to_have_value('C:\\fakepath\\profile.json')
                page.locator('#native-export').click()
                expect(page.locator('#center-error')).to_contain_text('reply lost')
                page.locator('#native-export').click()
                expect(page.locator('#runs')).to_contain_text('시연 자료 검증 중')
                assert len(center.runs) == 1 and len(center.requests) == 2
                assert center.requests[0] == center.requests[1]
                assert center.requests[0] == {'prepared_id': prepared_id, 'name': 'Native ACT data',
                    'profile': profile, 'request_id': center.requests[0]['request_id']}
                uuid.UUID(center.requests[0]['request_id'])
                page.reload(wait_until='networkidle')
                expect(page.locator('#runs')).to_contain_text(center.runs[0]['id'])
                expect(page.locator('#runs')).to_contain_text('시연 자료 검증 중')
                page.get_by_role('button', name='이 변환 중지').click()
                expect(page.locator('#runs')).to_contain_text('취소됨')
                page.locator('#export-name').fill('Second native data')
                page.locator('#export-profile').set_input_files({'name': 'profile.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(profile).encode()})
                page.locator('#native-export').click()
                expect(page.locator('#runs').get_by_role('button', name='이 변환 중지')).to_have_count(1)
                run = center.runs[-1]
                run.update(status='succeeded', progress={'phase': 'completed'},
                    result={'dataset_id': 'native-data', 'dataset_revision': 'sealed-native-revision', 'act_only': True})
                center.datasets.append({'id': 'native-data', 'name': 'Converted native ACT data', 'profile': profile})
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(page.locator('#runs')).to_contain_text('데이터 등록 완료')
                expect(page.locator('#runs')).to_contain_text('sealed-native-revision')
                expect(page.locator('#runs')).to_contain_text('ACT 전용')
                expect(page.locator('#dataset option[value="native-data"]')).to_be_attached()
                expect(page.locator('#runs a[download]')).to_have_count(0)
                expect(page.locator('#comparison tbody tr')).to_have_count(0)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_comparison_only_uses_selected_initial_dataset_and_actual_evaluations(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')

    datasets = [{'id': 'initial', 'name': 'Initial collection', 'source': 'synthetic_smoke', 'profile': {}},
                {'id': 'other', 'name': 'Other collection', 'source': 'recorded_fixture', 'profile': {}}]

    def result(mae, steps):
        return {'source': 'synthetic_smoke', 'steps': steps,
                'evaluation': {'frames': 7, 'action_mae': mae, 'constant_train_mean_mae': 0.75},
                'replay': {'demonstration_frames': 11, 'rollout_frames': 13}}

    runs = [dict(id='act-result', dataset_id='initial', method='act', status='succeeded',
                 steps=2, result=result(0.25, 2)),
            dict(id='sac-result', dataset_id='initial', method='hilserl', status='succeeded',
                 steps=3, result=result(0.5, 3)),
            dict(id='online-result', dataset_id='initial', method='hilserl', status='running',
                 execution_mode='online_experience', steps=2, inputs=[],
                 progress={'latest_version': '000002'},
                 result=dict(result(0.125, 2), total_steps=4, version='000002', inputs=[{}, {}])),
            dict(id='no-evaluation', dataset_id='initial', method='act', status='queued', steps=9),
            dict(id='different-initial', dataset_id='other', method='act', status='succeeded',
                 steps=99, result=result(0.99, 99))]
    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
        snapshot=lambda: {'datasets': datasets, 'runs': runs,
        'methods': {method: {'available': True} for method in ('act', 'hilserl')}})
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
                comparison = page.locator('#comparison')
                expect(comparison.locator('tbody tr')).to_have_count(3)
                expect(comparison).to_contain_text('동일 초기 데이터')
                expect(comparison).to_contain_text('000002')
                expect(comparison).to_contain_text('0.125')
                expect(comparison).to_contain_text('초기 포함 2개')
                expect(comparison).to_contain_text('미검증')
                expect(comparison).to_contain_text('미수집')
                expect(comparison).not_to_contain_text('no-evaluation')
                expect(comparison).not_to_contain_text('different-initial')
                expect(comparison.locator('tbody tr').filter(has_text='online-result')).to_contain_text('4')
                page.locator('#dataset').select_option('other')
                expect(comparison.locator('tbody tr')).to_have_count(1)
                expect(comparison).to_contain_text('different-initial')
                expect(comparison).not_to_contain_text('act-result')
                runs[-1]['result']['evaluation']['action_mae'] = 0.875
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(comparison).to_contain_text('0.875')
                runs[-1].pop('result')
                page.get_by_role('button', name='다시 확인', exact=True).click()
                expect(comparison).to_contain_text('저장된 평가 결과가 없습니다')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
