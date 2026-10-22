"""Actual Fleet UI over the connected dev host, real APIs and a temporary task ledger."""
import ssl
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port
from test_app_connected_integration import connected_fleet

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def test_connected_ui_login_goal_cancel_readback_and_logout(connected_fleet):
    from connected import ConnectedAPI
    from http_host import make_server
    from playwright.sync_api import sync_playwright, expect
    from test_password_session import TYPED

    upstream, certificate, key, robot = connected_fleet
    origin = f'https://localhost:{free_port()}'
    provider = ConnectedAPI(upstream, ssl.create_default_context(cafile=str(certificate)), origin)
    with make_server(provider, origin) as server:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(certificate, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    # Only the browser trusts the disposable self-signed fixture; upstream TLS stays verified.
                    page = browser.new_page(ignore_https_errors=True, viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/console/login?return=/console/profile')
                    page.locator('[data-login=login]').fill('alice')
                    page.locator('[data-login=password]').fill(TYPED)
                    page.locator('[data-login=submit]').click()
                    expect(page.locator('#profile-id')).to_have_text('alice')
                    page.locator('#profile-name').fill('Connected UI operator')
                    page.locator('#profile-name-save').click()
                    expect(page.locator('#profile-status')).to_contain_text('저장하고 다시 확인')
                    page.reload()
                    expect(page.locator('#profile-name')).to_have_value('Connected UI operator')

                    page.goto(origin + '/console')
                    page.locator('[data-context-tab=status]').click()
                    expect(page.locator('#robot-choice')).to_contain_text('rosy_01')
                    page.locator('#robot-choice').select_option('rosy_01')
                    aim = page.locator('#robot-workspace [data-goal-robot-id=rosy_01]')
                    expect(aim).to_be_enabled()
                    aim.click()
                    page.locator('#map-canvas').press('Enter')
                    with page.expect_response(lambda response: response.url.endswith('/robots/rosy_01/goal')
                                              and response.request.method == 'POST') as submitted:
                        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
                    assert submitted.value.status == 200
                    task = submitted.value.json()['task']
                    assert task['status'] == 'QUEUED'
                    identifier = task['task_id']
                    expect(page.locator('#log')).to_contain_text(identifier)
                    with page.expect_response(lambda response: response.url.endswith(f'/tasks/{identifier}/cancel')
                                              and response.request.method == 'POST') as canceled:
                        page.locator('#robot-workspace [data-cancel-scope]').click()
                    assert canceled.value.status == 200
                    expect(page.locator('#log')).to_contain_text('QUEUED 취소')
                    readback = page.request.get(origin + '/api/fleet/tasks/' + identifier)
                    assert readback.status == 200 and readback.json()['task']['status'] == 'CANCELED'
                    assert not any(call[0] == 'navigation_goal' for call in robot.calls)

                    toggle = page.locator('#topbar-more')
                    if toggle.get_attribute('aria-expanded') != 'true':
                        toggle.click()
                    with page.expect_response(lambda response: response.url.endswith('/auth/logout')) as logged_out:
                        page.locator('[data-login=logout]').click()
                    assert logged_out.value.status == 204
                    page.get_by_role('link', name='로그인', exact=True).click()
                    expect(page.locator('[data-login=login]')).to_be_visible()
                    assert page.request.get(origin + '/api/fleet/auth/session').status == 401
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            server.shutdown()
            worker.join(5)
            assert not worker.is_alive()
