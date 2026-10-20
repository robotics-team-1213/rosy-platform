"""Existing authenticated Learning shell controls a shared run backend."""
import copy
import threading
import uuid

import pytest
from browser_harness import browser_tests_enabled
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

    def call(self, payload):
        action = payload['action']
        if action == 'list':
            return list(self.rows.values())
        if action == 'status':
            return self.rows[payload['run_id']]
        if action == 'start':
            request = payload['request']
            run_id = self.requests.setdefault(request['request_id'], uuid.uuid4().hex)
            if run_id not in self.rows:
                self.rows[run_id] = dict(copy.deepcopy(self.row), run_id=run_id,
                    status='RUNNING', parent_run_id=request.get('parent_run_id'), result=None)
            return self.rows[run_id]
        if action == 'stop':
            row = self.rows[payload['run_id']]
            row.update(status='STOPPED', revision=row['revision'] + 1, result={'task_success': None})
            return row
        return super().call(payload)


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
                expect(page.locator('#sim-runs button')).to_have_count(1)
                expect(page.locator('#sim-prerequisites')).to_contain_text('E0 필요')
                assert page.locator('#sim-scenario option[value="port-mixed-stacking"]').is_disabled()
                page.locator('#sim-runs button').first.click()
                expect(page.locator('#sim-selected')).to_contain_text('b' * 32)
                page.locator('#sim-check').click()
                expect(page.locator('#sim-start')).to_be_enabled()
                page.locator('#sim-start').click()
                expect(page.locator('#sim-runs button')).to_have_count(2)
                page.locator('#sim-start').click()
                expect(page.locator('#sim-runs button')).to_have_count(2)
                assert len(runs.requests) == 1
                page.locator('#sim-stop').click()
                expect(page.locator('#sim-selected')).to_contain_text('중단')
                parent = next(key for key in runs.rows if key != 'b' * 32)
                page.locator('#sim-replay').click()
                expect(page.locator('#sim-runs button')).to_have_count(3)
                assert any(row.get('parent_run_id') == parent for row in runs.rows.values())
                assert runs.rows['b' * 32] == original
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
