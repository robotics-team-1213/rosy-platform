"""Real monitor -> source-authorized API -> database restart -> Cell browser, no hardware."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import ssl
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import uvicorn
from fastapi.testclient import TestClient

from browser_harness import browser_tests_enabled, launch_options, safe_listener
from core_common.protocol.workcell_observations import WorkcellObservationManifest
from deploy.robot.omx.load_report_bridge import publish
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.workcell_observations import WorkcellObservations
from test_device_care import care, monitor_report


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in real Chromium pipeline')
ROOT = Path(__file__).resolve().parents[3]
OPERATOR = 'fixture-profile-operator'
VIEWER = 'fixture-profile-viewer'
SOURCE = 'fixture-profile-observation'


@pytest.fixture
def persisted_cell(tmp_path, request):
    arm = {'source_id': 'source-one', 'arm_id': 'fixture-owner', 'label': '검증용 팔',
           'board_id': 'EXAMPLE-BOARD', 'joint_topic': '/omx_commissioning/fixture_owner/joint_states',
           'joint_names': ['joint2', 'joint3'], 'token_env': 'EXAMPLE_PROFILE_SOURCE',
           'credential_sha256': sha256(SOURCE.encode()).hexdigest()}
    camera = {'source_id': 'fixture-top', 'label': '미연결 검증 카메라', 'role': 'overhead', 'arm_id': None,
              'image_topic': '/fixture_top/image_raw', 'device_path': '/dev/v4l/by-id/example-only',
              'token_env': 'EXAMPLE_PROFILE_CAMERA', 'credential_sha256': sha256(b'fixture-camera').hexdigest()}
    manifest = WorkcellObservationManifest.model_validate({
        'schema': 'rosy.workcell-observations/1', 'workcells': [{
            'workcell_id': 'fixture-cell', 'label': '검증용 셀', 'arms': [arm], 'cameras': [camera]}]})
    path = tmp_path / 'tasks.sqlite3'

    def application():
        users = {sha256(token.encode()).hexdigest(): {'principal_id': f'fixture-{role}', 'role': role}
                 for token, role in ((OPERATOR, 'operator'), (VIEWER, 'viewer'))}
        observations = WorkcellObservations(manifest, {'source-one': SOURCE})
        return create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(path), robot_ids=()),
                          site_users=users, workcell_observations=observations,
                          web_common=ROOT / 'shared/web')

    document, report = monitor_report(stamp=time.time(), attention=True)
    with TestClient(application()) as writer:
        headers = {'Authorization': f'Bearer {OPERATOR}'}
        base = '/api/fleet/device-profiles/arm-one'
        assert writer.put(base, headers=headers,
                          json={'display_name': '검증용 팔', 'device_kind': 'manipulator'}).status_code == 200
        assert writer.put(base + '/care', headers=headers,
                          json=care() | {'characteristics': document}).status_code == 200

        class Transport:
            @contextmanager
            def open(self, request, timeout):
                response = writer.post(urlsplit(request.full_url).path, content=request.data,
                                       headers=dict(request.headers))
                assert response.status_code == 202, response.text
                yield SimpleNamespace(status=response.status_code)

        publish(json.dumps(report).encode(), fleet_url='https://fleet.example', device_id='arm-one',
                source_id='source-one', token=SOURCE, context=ssl.create_default_context(), opener=Transport())

    if getattr(request, 'param', False):
        changed = manifest.model_dump(by_alias=True)
        changed['workcells'][0]['arms'][0]['arm_id'] = 'replacement-owner'
        manifest = WorkcellObservationManifest.model_validate(changed)
    # A new app and store reopen the database before any browser requests.
    listener = safe_listener()
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(application(), log_level='error', timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(.02)
        assert server.started
        yield origin, report
    finally:
        server.should_exit = True
        worker.join(20)
        listener.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_persisted_analysis_origin_and_diagnosis_order_in_cell(persisted_cell, width):
    from playwright.sync_api import expect, sync_playwright
    origin, report = persisted_cell
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors, writes = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append(request.url) if request.method in ('POST', 'PUT', 'DELETE')
                    and ('/api/fleet/robots/' in request.url or '/api/fleet/device-profiles/' in request.url) else None)
            page.add_init_script(f"sessionStorage.setItem('rosy-console-token', '{VIEWER}')")
            page.goto(origin + '/console/cell')
            info = page.locator('[data-arm-source="source-one"] [data-robot-profile]')
            expect(info).to_contain_text('2·3번 관절 하중 주의')
            expect(info).to_contain_text('feedback_gap')
            expect(info).to_contain_text('fixture-v1')
            info.locator('summary').click()
            expect(info.locator('[data-profile-origin]')).to_contain_text('source-one')
            expect(info.locator('[data-profile-origin]')).to_contain_text('fixture-owner')
            expect(info.locator('[data-profile-origin]')).to_contain_text(report['characteristics_sha256'])
            assert info.evaluate("""el => (el.querySelector('[data-profile-diagnosis]')
                .compareDocumentPosition(el.querySelector('[data-profile-characteristics]'))
                & Node.DOCUMENT_POSITION_FOLLOWING) !== 0""")
            result = page.request.get(origin + '/api/fleet/device-profile-sources/arm/source-one',
                                      headers={'Authorization': f'Bearer {VIEWER}'}).json()['profile']
            assert result['latest_analysis']['assessed_at'] == report['assessed_at']
            assert result['latest_analysis']['fresh'] is False
            assert result['motion_admitted'] is False
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if output := os.environ.get('ROSY_SHOT_DIR'):
                target = Path(output) / f'persisted-load-profile-{width}.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target), full_page=True)
            assert not errors and not writes
        finally:
            browser.close()


@pytest.mark.parametrize('persisted_cell', [True], indirect=True)
def test_restarted_cell_does_not_attach_old_owner_profile_or_accept_old_report(persisted_cell):
    from playwright.sync_api import expect, sync_playwright
    origin, report = persisted_cell
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 1000})
            page.add_init_script(f"sessionStorage.setItem('rosy-console-token', '{VIEWER}')")
            page.goto(origin + '/console/cell')
            info = page.locator('[data-arm-source="source-one"] [data-robot-profile]')
            expect(info).to_contain_text('프로필 연결을 다시 확인하세요')
            expect(info).not_to_contain_text('2·3번 관절 하중 주의')
            expect(info.locator('a')).to_have_attribute('href', '/console/install?profile=arm-one#device-profiles')
            old = page.request.get(origin + '/api/fleet/device-profiles/arm-one/care',
                                   headers={'Authorization': f'Bearer {VIEWER}'}).json()
            assert old['source_binding_status'] == 'owner_changed'
            assert old['caution'] == care()['caution']
            assert old['latest_analysis']['fresh'] is False
            assert old['latest_analysis']['assessed_at'] == report['assessed_at']
            rejected = page.request.post(origin + '/api/fleet/device-profiles/arm-one/load-reports/source-one',
                                         headers={'X-Workcell-Observation-Token': SOURCE}, data=report)
            assert rejected.status == 422
        finally:
            browser.close()
