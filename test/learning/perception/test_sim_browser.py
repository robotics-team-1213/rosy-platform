"""Existing authenticated Learning shell controls a shared run backend."""
import copy
import threading
import uuid

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import make_server
from test_learning_collaboration import Accounts
from test_review_app import open_store
from test_sim_web import Runs

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


class SharedRuns(Runs):
    def __init__(self):
        super().__init__()
        self.row['status'] = 'SUCCEEDED'
        self.row['result'] = {'task_success': None, 'import_verified': True,
                              'video_unavailable_reason': 'model_import_does_not_record_video'}
        self.rows = {self.row['run_id']: copy.deepcopy(self.row)}
        self.requests = {}
        self.start_requests = []
        self.ready = True

    def call(self, payload):
        action = payload['action']
        if action == 'catalog':
            return [*super().call(payload), {'id': 'pinky-conveyor-roundtrip', 'implemented': True}]
        if action == 'check' and not self.ready:
            return {'ready': False, 'reason': '다른 GPU 작업이 실행 중입니다.', 'input_sha256': 'c' * 64}
        if action == 'list':
            return list(self.rows.values())
        if action == 'status':
            return self.rows[payload['run_id']]
        if action == 'start':
            request = payload['request']
            self.start_requests.append(copy.deepcopy(request))
            run_id = self.requests.setdefault(request['request_id'], uuid.uuid4().hex)
            if run_id not in self.rows:
                self.rows[run_id] = dict(copy.deepcopy(self.row), run_id=run_id,
                    status='RUNNING', parent_run_id=request.get('parent_run_id'))
                self.rows[run_id].pop('result', None)
            return self.rows[run_id]
        if action == 'stop':
            row = self.rows[payload['run_id']]
            row.update(status='STOPPED', revision=row['revision'] + 1, result={'task_success': None})
            return row
        return super().call(payload)


@pytest.mark.parametrize('width', [1280, 390])
@pytest.mark.parametrize('session', ['reader', 'reviewer'])
def test_contact_run_exposes_report_and_phase_evidence_without_promotion(tmp_path, width, session):
    playwright = pytest.importorskip('playwright.sync_api')
    runs = SharedRuns()
    row = runs.rows['b' * 32]
    row['input']['scenario_id'] = 'pinky-conveyor-roundtrip'
    row['result'].update(stage='contact_roundtrip', task_success=True)
    artifact_ids = ['contact-report', 'pinky_initial', 'out_lift', 'conveyor_settle', 'back_lift', 'pinky_settle']
    row['artifacts'] = {'files': [{'id': name} for name in [*artifact_ids, 'unknown-artifact']]}
    server = make_server(open_store(tmp_path), free_port(), accounts=Accounts(), sim_runs=runs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': session, 'url': base}])
            try:
                page.goto(base + '/learning/sim', wait_until='networkidle')
                page.locator('#sim-runs ui-button').first.click()
                playwright.expect(page.locator('#sim-artifacts a')).to_have_count(6)
                links = page.locator('#sim-artifacts a').evaluate_all('links=>links.map(link=>link.getAttribute("href"))')
                assert links == [f'/api/learning/sim/runs/{row["run_id"]}/artifacts/{name}' for name in artifact_ids]
                playwright.expect(page.locator('#sim-selected')).to_contain_text('실행 완료')
                playwright.expect(page.locator('#sim-start')).to_be_disabled()
                playwright.expect(page.locator('#sim-main')).to_contain_text('학습 정책·실물 수용은 별도')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == [] and not runs.requests
                if session == 'reviewer':
                    assert page.locator('#sim-scenario').input_value() == 'omx-f-import'
                    page.locator('#sim-replay').click()
                    playwright.expect(page.locator('#sim-runs ui-button')).to_have_count(2)
                    assert runs.start_requests[0]['scenario_id'] == 'pinky-conveyor-roundtrip'
                    assert runs.start_requests[0]['parent_run_id'] == row['run_id']
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('width', [1280, 390])
def test_sim_shared_runs_replay_stop_and_disabled_scenarios(tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    runs = SharedRuns()
    original = copy.deepcopy(runs.rows['b' * 32])
    server = make_server(open_store(tmp_path), 0, accounts=Accounts(), sim_runs=runs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': 'reviewer', 'url': base}])
            try:
                page.goto(base + '/learning/sim', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#sim-runs ui-button')).to_have_count(1)
                expect(page.locator('#sim-prerequisites')).to_contain_text('E0 필요')
                assert page.locator('#sim-scenario option[value="port-mixed-stacking"]').evaluate('option=>option.disabled')
                page.locator('#sim-runs ui-button').first.click()
                expect(page.locator('#sim-selected')).to_contain_text('b' * 32)
                page.locator('#sim-check').click()
                expect(page.locator('#sim-start')).to_be_enabled()
                runs.ready = False
                page.locator('#sim-check').click()
                expect(page.locator('#sim-error')).to_contain_text('GPU 작업')
                expect(page.locator('#sim-start')).to_be_disabled()
                assert len(runs.requests) == 0
                runs.ready = True
                page.locator('#sim-check').click()
                expect(page.locator('#sim-start')).to_be_enabled()
                page.locator('#sim-start').click()
                expect(page.locator('#sim-runs ui-button')).to_have_count(2)
                page.locator('#sim-start').click()
                expect(page.locator('#sim-runs ui-button')).to_have_count(2)
                assert len(runs.requests) == 1
                page.locator('#sim-stop').click()
                expect(page.locator('#sim-selected')).to_contain_text('중단')
                parent = next(key for key in runs.rows if key != 'b' * 32)
                page.locator('#sim-replay').click()
                expect(page.locator('#sim-runs ui-button')).to_have_count(3)
                assert any(row.get('parent_run_id') == parent for row in runs.rows.values())
                assert runs.rows['b' * 32] == original
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('width', [1280, 390])
def test_evaluate_lists_sim_runs_and_each_opens_its_run(tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    runs = SharedRuns()
    runs.rows['b' * 32]['result'].update(stage='model_import', status='passed')
    for index, configured in enumerate([runs, None]):
        root = tmp_path / str(index)
        root.mkdir()
        server = make_server(open_store(root), 0, accounts=Accounts(), sim_runs=configured)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': 'reader', 'url': base}])
                try:
                    page.goto(base + '/learning/evaluate?domain=sim', wait_until='networkidle')
                    block = page.locator('.evaluate-source[data-domain="sim"]')
                    expect = playwright.expect
                    expect(block).to_contain_text('승인·승격이 아닙니다')
                    if configured is None:
                        expect(block).to_contain_text('SIM 실행 연결이 설정되지 않았습니다.')
                        assert block.locator('.evaluate-runs').count() == 0
                    else:
                        link = block.locator('.evaluate-runs a')
                        expect(link).to_have_count(1)
                        expect(link).to_contain_text('SUCCEEDED · 단계 model_import · 과제 성공 기록 없음 · 판정 passed')
                        assert link.bounding_box()['height'] >= 44
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        link.click()
                        page.wait_for_url('**/learning/sim?run=' + 'b' * 32)
                        expect(page.locator('#sim-selected')).to_contain_text('b' * 32)
                        expect(page.locator('#sim-result')).to_contain_text('model_import')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert errors == []
                finally:
                    browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()


def test_sim_discards_check_response_after_browser_identity_changes(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    runs = SharedRuns()
    server = make_server(open_store(tmp_path), 0, accounts=Accounts(), sim_runs=runs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    identity = ['first-session']
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            browser.contexts[0].add_cookies([{'name': 'rosy_learning_session', 'value': 'reviewer', 'url': base}])
            page.route('**/api/accounts/options', lambda route: route.fulfill(json={
                'enabled': True, 'rosy_account': True, 'oauth': False, 'project_id': 'alpha'}))
            def session(route):
                value = route.fetch().json()
                route.fulfill(json=dict(value, account_session=identity[0]))
            page.route('**/api/accounts/session', session)
            def check(route):
                value = route.fetch().json()
                identity[0] = 'replacement-session'
                route.fulfill(json=value)
            page.route('**/api/learning/sim/check', check)
            try:
                page.goto(base + '/learning/sim', wait_until='networkidle')
                playwright.expect(page.locator('#sim-check')).to_be_enabled()
                with page.expect_navigation(wait_until='networkidle'):
                    page.locator('#sim-check').click()
                playwright.expect(page.locator('#sim-start')).to_be_disabled()
                assert not any(call['action'] == 'start' for call in runs.calls)
                assert '확인한 입력 지문' not in page.locator('#sim-checked').inner_text()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
