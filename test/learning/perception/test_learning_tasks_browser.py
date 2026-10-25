"""Chromium exercises real task registration; only learner execution is a fixture."""
import hashlib
import json
import threading
import uuid
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_robot_task_launch_and_reconnect(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    profile = {'schema': 'rosy.omx.learning-profile/2', 'name': 'Fixture profile',
        'task': 'Pick fixture', 'mode': 'independent', 'arms': [
            {'id': 'arm', 'joint_names': ['joint'], 'units': 'rad', 'action_limits': [[-1, 1]]}],
        'cameras': [{'id': 'top', 'input_key': 'observation.images.top', 'arm_id': None,
            'role': 'top', 'source_identity': 'fixture:top', 'placement': 'overhead',
            'shape': [3, 8, 8], 'purposes': ['policy']}]}
    revision = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False).encode()).hexdigest()
    record = {'id': str(uuid.uuid4()), 'revision': revision, 'profile': profile}

    class Center:
        host_id = 'model'

        def __init__(self):
            self.runs, self.requests = [], []
            self.experience_requests, self.stops = [], []
            self.profiles = SimpleNamespace(list=lambda: [record], get=lambda key: record)

        def bind_workspace(self, project):
            pass

        def snapshot(self):
            return {'datasets': [{'id': 'fixture-data', 'name': 'Synthetic fixture data',
                'revision': 'c' * 64, 'source': 'synthetic_smoke', 'profile': profile},
                {'id': 'extra-data', 'name': 'Additional synthetic experience',
                    'revision': 'd' * 64, 'source': 'synthetic_smoke', 'profile': profile}],
                'runs': self.runs, 'methods': {m: {'available': True} for m in ('act', 'hilserl')}}

        def start(self, body):
            self.requests.append(body)
            row = {'id': str(uuid.uuid4()), 'status': 'succeeded', 'method': body['method'],
                'dataset_id': body['dataset_id'], 'learning_task': {'task_id': body['task_id']},
                'result': {'evaluation': {'action_mae': 0.25, 'frames': 4}, 'source': 'synthetic_smoke'}}
            self.runs.append(row)
            return row

        def start_online(self, body):
            row = self.start(body)
            row.update(status='running', execution_mode='online_experience',
                inputs=[{'dataset_id': body['dataset_id']}], progress={'phase': 'waiting_for_experience'})
            return row

        def experience(self, body):
            self.experience_requests.append(body)
            row = next(run for run in self.runs if run['id'] == body['id'])
            if not any(item.get('id') == body['request_id'] for item in row['inputs']):
                row['inputs'].append({'id': body['request_id'], 'dataset_id': body['dataset_id']})
                raise ValueError('reply lost after enqueue')
            return row['inputs'][-1]

        def stop(self, body):
            self.stops.append(body)
            row = next(run for run in self.runs if run['id'] == body['id'])
            row['status'] = 'cancelled'
            return row

    center = Center()
    store = ReviewStore(tmp_path / 'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/tasks', wait_until='networkidle')
                expect = playwright.expect

                def robot(name, kind, device):
                    for key, value in [('robot-name', name), ('robot-kind', kind),
                                       ('robot-model', 'fixture-v1'), ('robot-device', device)]:
                        page.locator('#' + key).fill(value)
                    page.locator('#robot-save').click()
                    expect(page.locator('#robots')).to_contain_text(name)

                def task(name):
                    for key, value in [('task-name', name), ('task-objective', 'Move fixture'),
                        ('task-success', 'At target'), ('task-failure', 'Dropped'), ('task-reset', 'Return fixture')]:
                        page.locator('#' + key).fill(value)
                    page.locator('#task-save').click()
                    expect(page.locator('#selected-task')).to_contain_text(name)

                robot('Mobile fixture', 'mobile', 'mobile-1')
                page.locator('#task-adapter').fill('mobile')
                page.locator('[data-component]').fill('base')
                task('Mobile task')
                expect(page.locator('#run-readiness')).to_contain_text('어댑터')
                expect(page.locator('#run-start')).to_be_disabled()
                robot('OMX fixture', 'omx', 'omx-1')
                page.locator('#task-adapter').fill('omx')
                page.locator('#task-profile').select_option(record['id'])
                page.locator('[data-robot] option').filter(has_text='OMX fixture').evaluate(
                    'option => {option.parentElement.value=option.value;option.parentElement.dispatchEvent(new Event("change",{bubbles:true}));}')
                task('Pick fixture')
                page.locator('#run-dataset').select_option('fixture-data')
                page.locator('#run-start').click()
                expect(page.locator('#task-runs')).to_contain_text('0.25')
                assert len(center.requests) == 1
                assert center.requests[0]['compute_host'] == 'model'
                task_id = center.requests[0]['task_id']
                page.reload(wait_until='networkidle')
                page.locator('#task-select').select_option(task_id)
                expect(page.locator('#task-runs')).to_contain_text(center.runs[0]['id'])
                expect(page.locator('#task-runs')).to_contain_text('0.25')
                page.locator('#run-dataset').select_option('fixture-data')
                page.locator('#run-execution').select_option('online')
                page.locator('#run-start').click()
                expect(page.locator('[data-continuous-run]')).to_have_count(1)
                online_id = center.runs[-1]['id']
                page.reload(wait_until='networkidle')
                page.locator('#task-select').select_option(task_id)
                controls = page.locator(f'[data-continuous-run="{online_id}"]')
                expect(controls).to_be_visible()
                expect(controls.locator('option[value="fixture-data"]')).to_have_count(0)
                controls.locator('select').select_option('extra-data')
                controls.get_by_role('button', name='추가 경험 입력').click()
                expect(page.locator('#tasks-error')).to_contain_text('reply lost after enqueue')
                page.locator('#tasks-refresh').click()
                expect(controls.locator('select')).to_have_value('extra-data')
                controls.get_by_role('button', name='추가 경험 입력').click()
                expect(controls).to_contain_text('입력 대기열에 추가했습니다')
                assert len(center.experience_requests) == 2
                assert center.experience_requests[0] == center.experience_requests[1]
                assert center.experience_requests[0]['id'] == online_id
                assert len(center.runs[-1]['inputs']) == 2
                controls.get_by_role('button', name='이 지속 학습 중지').click()
                expect(page.locator('[data-continuous-run]')).to_have_count(0)
                assert center.stops == [{'id': online_id}]
                expect(page.locator('#task-runs')).to_contain_text('취소됨')
                expect(page.locator('#task-runs')).to_contain_text('0.25')
                page.get_by_text('다른 호스트로 과제 메타데이터 전달', exact=True).click()
                with page.expect_download() as downloaded:
                    page.locator('#task-export').click()
                transfer = tmp_path / 'task-transfer.json'
                downloaded.value.save_as(transfer)
                package = json.loads(transfer.read_text())
                assert package['task']['request_id'] == task_id
                assert 'token' not in package
                page.locator('#task-import-file').set_input_files(transfer)
                with page.expect_response('**/api/learning/tasks/import') as imported:
                    page.locator('#task-import').click()
                assert imported.value.ok
                expect(page.locator('#task-select')).to_have_value(task_id)
                expect(page.locator('#selected-task')).to_contain_text(task_id)
                page.locator('#task-name').fill('Unsaved next task')
                page.locator('#tasks-refresh').click()
                expect(page.locator('#task-name')).to_have_value('Unsaved next task')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
