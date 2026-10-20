"""Run representative stateful contracts over browser fetch against the real sample host.

These check browser transport and subsequent document rendering. Form interactions
are covered separately in test_sample_browser; these are not device acceptance.
"""
import json
from types import SimpleNamespace

import pytest

from test_sample_browser import sample_site, pytestmark
import test_sample_flows as flows
import test_sample_collaboration as collaboration


CASES = {
    'policy': (flows.test_policy_window_approval_closure_and_expiry, '/console/policy'),
    'stop': (flows.test_unauthorized_and_stale_changes_do_not_mutate_state, '/console'),
    'work': (flows.test_flow_ids_revisions_and_reset_are_consistent, '/console'),
    'monitoring': (flows.test_goal_idempotency_progress_and_terminal_read, '/console'),
    'assistant': (flows.test_assistant_idempotency_and_explicit_terminal_result, '/console'),
    'vision': (flows.test_media_grant_renewal_revoke_and_viewer_read_permission, '/console'),
    'cell_documents': (flows.test_cell_documents_revision_preview_and_job_recovery, '/console/cell'),
    'cell_jobs': (flows.test_cell_documents_revision_preview_and_job_recovery, '/console/cell'),
    'installation': (flows.test_enrollment_pairing_and_calibration_readbacks, '/console/install'),
    'pairing': (flows.test_enrollment_pairing_and_calibration_readbacks, '/console/install'),
    'calibration': (flows.test_enrollment_pairing_and_calibration_readbacks, '/console/install'),
    'mission': (collaboration.test_channel_review_creates_one_task_and_tracks_its_result, '/console'),
    'traffic': (collaboration.test_formation_hold_resume_stop_and_incident_review, '/console'),
    'incidents': (collaboration.test_formation_hold_resume_stop_and_incident_review, '/console'),
    'profile': (flows.test_profile_change_survives_logout_and_login, '/console/profile'),
}


class BrowserEngine:
    def __init__(self, page):
        self.page = page

    def handle(self, method, path, headers, body):
        value = self.page.evaluate('''async ({method,path,headers,body}) => {
            const response = await fetch(path, {method,headers,body:['GET','HEAD'].includes(method)?undefined:body});
            return {status:response.status,body:await response.text(),headers:[...response.headers]};
        }''', {'method': method, 'path': path, 'headers': {k:v for k,v in headers.items() if k.lower() != 'cookie'},
              'body': body.decode()})
        return SimpleNamespace(status=value['status'], body=value['body'].encode(), headers=value['headers'])

    def advance(self, flow_id, event):
        response = self.handle('POST', '/__dev/advance', {'Content-Type':'application/json'},
                               json.dumps({'flow_id':flow_id, 'event':event}).encode())
        assert response.status == 200

    def reset(self, scenario_id):
        response = self.handle('POST', '/__dev/reset', {'Content-Type':'application/json'},
                               json.dumps({'scenario_id':scenario_id}).encode())
        assert response.status == 200


@pytest.mark.parametrize('feature', sorted(CASES))
def test_representative_contract_in_browser(sample_site, monkeypatch, feature):
    from playwright.sync_api import sync_playwright, expect
    engine, origin = sample_site
    check, document = CASES[feature]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external.append(req.url)
                    if req.url.startswith('http') and not req.url.startswith(origin + '/') else None)
            # Login document has no background Fleet polling to race explicit scenario steps.
            page.goto(origin + '/console/login')
            adapter = BrowserEngine(page)
            owner = flows if check.__module__ == flows.__name__ else collaboration
            monkeypatch.setattr(owner, 'load_engine', lambda: adapter)
            check()
            page.goto(origin + document)
            expect(page.locator('body')).to_be_visible()
            page.wait_for_timeout(300)
            assert not errors, errors
            assert not external, external
            assert not engine.unhandled, engine.unhandled
        finally:
            browser.close()
