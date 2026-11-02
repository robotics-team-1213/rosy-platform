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
    'auth': (flows.test_auth_login_logout_and_rejected_credentials, '/console/login'),
    'map': (flows.test_map_draft_conflict_activation_and_readback, '/console/site-map'),
    'policy': (flows.test_policy_window_approval_closure_and_expiry, '/console/policy'),
    'stop': (flows.test_stop_requires_current_generation_to_rearm, '/console'),
    'work': (flows.test_flow_ids_revisions_and_reset_are_consistent, '/console'),
    'monitoring': (flows.test_goal_idempotency_progress_and_terminal_read, '/console'),
    'control_units': (flows.test_control_unit_review_keeps_identity_task_and_terminal_readbacks, '/console?view=work'),
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
    'accounts': (flows.test_account_changes_control_login_and_sample_authority, '/console/accounts'),
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
        if path == '/api/fleet/auth/login' and value['status'] == 204:
            for cookie in self.page.context.cookies():
                if cookie['name'] == 'rosy_sample_session':
                    value['headers'].append(('Set-Cookie', cookie['name'] + '=' + cookie['value']))
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
            # A text resource keeps the same origin without application navigation racing scenario fetches.
            page.goto(origin + '/console/assets/app-runtime.js')
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


@pytest.mark.parametrize('scenario', ['approve', 'poll', 'changed_poll'])
def test_usb_camera_cookie_operator_keeps_edit_during_poll(sample_site, scenario):
    """Real cookie login and dialogs, controlled USB observations; no device approval."""
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    key = 'a' * 64
    candidate = {'key': key, 'usb_id': '046d:0825', 'roles': ['top'],
                 'suggest': 'top', 'hub_arm': None, 'decision': None}
    workcell = {'workcell_id': 'cell-test', 'roles': ['top', 'side'], 'candidates': [candidate]}
    posts = []
    reads = 0

    def observations(route):
        nonlocal reads
        reads += 1
        if reads > 1 and scenario == 'changed_poll':
            candidate['suggest'] = 'side'
            workcell['candidates'] = [dict(candidate, key='b' * 64, usb_id='1234:5678'), candidate]
        route.fulfill(json={'workcells': [workcell]})

    def approve(route):
        request = route.request
        posts.append(request.post_data_json)
        assert 'authorization' not in request.headers
        assert request.headers['origin'] == origin
        assert 'rosy_sample_session=' in request.all_headers()['cookie']
        candidate['decision'] = {'role': posts[-1]['role'], 'principal_id': 'sample'}
        route.fulfill(json={'decision': candidate['decision']})

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            login = context.request.post(origin + '/api/fleet/auth/login',
                headers={'Origin': origin}, data={'login': 'sample', 'password': 'CHANGE_ME'})
            assert login.status == 204
            page = context.new_page()
            page.route('**/api/fleet/workcell-observations/usb-devices', observations)
            page.route(f'**/usb-devices/{key}/decision', approve)
            page.goto(origin + '/console/install#cameras')
            panel = page.locator('#usb-camera-panel')
            expect(panel).to_be_visible()
            assert page.evaluate("sessionStorage.getItem('rosy-console-token')") in (None, '')
            field = panel.get_by_role('textbox', name='USB 046d:0825의 역할', exact=True)
            field.fill('custom_camera')
            if scenario == 'approve':
                panel.get_by_role('button', name='역할 승인', exact=True).click()
                page.locator('dialog[open]').get_by_role('button', name='역할 승인', exact=True).click()
                expect(panel).to_contain_text('승인됨: custom_camera (sample)')
                assert posts == [{'role': 'custom_camera'}]
            else:
                field.focus()
                field.evaluate('(input) => input.setSelectionRange(2, 8)')
                with page.expect_response('**/api/fleet/workcell-observations/usb-devices', timeout=10000) as reply:
                    pass
                reply.value.finished()
                expect(panel).to_have_attribute('aria-busy', 'false')
                expect(field).to_have_value('custom_camera')
                expect(field).to_be_focused()
                assert field.evaluate('(input) => [input.selectionStart, input.selectionEnd]') == [2, 8]
                assert reads >= 2
                if scenario == 'changed_poll':
                    expect(panel.get_by_role('textbox')).to_have_count(2)
                    expect(panel).to_contain_text('추천: side')
                assert not posts
        finally:
            browser.close()
