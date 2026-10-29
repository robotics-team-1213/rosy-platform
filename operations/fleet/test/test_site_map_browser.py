"""D-488 M1 site map page in real Chromium (opt-in, ROSY_BROWSER_TESTS=1). No robot moves."""

import os
import json
import re
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from browser_harness import BODY_FIT, browser_tests_enabled, open_token_access, safe_listener

from test_site_map_trip import _app, _on_ring_s

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="opt-in real Chromium browser scenario")
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_mapless_survey_elements_persist_and_stay_out_of_operations(page_site, width):
    from playwright.sync_api import expect

    page, store, robot = page_site
    page.set_viewport_size({'width': width, 'height': 1000})
    assert page.evaluate('''() => {
        const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
        return ids.length === new Set(ids).size;
    }''')
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#map-status')).to_contain_text('활성 지도 없음')
    page.locator('#survey-setup > summary').click()
    page.locator('#survey-description').fill('Start mark facing east, calibrated wheel odom')
    page.locator('#survey-new').click()
    expect(page.locator('#map-status')).to_contain_text('초안')
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(0)
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(0)
    page.locator('#survey-editor > summary').click()

    def point(x, y):
        page.locator('#element-x').fill(str(x))
        page.locator('#element-y').fill(str(y))
        page.locator('#element-point').click()

    for id_, name, x, y in [('a', 'Start', 0, 0), ('b', 'Destination', 1, 0)]:
        page.locator('#element-id').fill(id_)
        page.locator('#element-name').fill(name)
        page.locator('#element-kind').select_option('park')
        point(x, y)
        page.locator('#element-save').click()
        expect(page.locator('#survey-status')).to_have_text('요소를 초안에 반영했습니다. 저장·검토·활성화는 각각 별도입니다.')
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(2)
    page.locator('#element-id').fill('ab')
    page.locator('#element-name').fill('Road')
    page.locator('#element-kind').select_option('road')
    page.locator('#element-from').select_option('a')
    page.locator('#element-to').select_option('b')
    page.locator('#element-direction').select_option('two_way')
    page.locator('#element-endpoints').click()
    page.locator('#element-save').click()
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(1)
    page.locator('#element-id').fill('sig')
    page.locator('#element-name').fill('Junction signal')
    page.locator('#element-kind').select_option('traffic_signal')
    page.locator('#element-signal-id').fill('sig-ring')
    page.locator('#element-lanes').select_option(['ab'])
    page.locator('#element-stop').fill('.8')
    point(.8, .1)
    page.locator('#element-save').click()
    expect(page.locator('#site-map-svg .facility.traffic_signal')).to_have_count(1)
    page.locator('#save-draft').click()
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    saved = store.draft_view()['map']
    assert saved['survey']['reviewed'] is False
    assert saved['edges'][0]['evidence']['status'] == 'observed'
    assert saved['facilities'][0]['approaches'] == [{'edge_id': 'ab', 'forward': True, 'stop_s_m': .8}]
    assert store.active_view() is None
    page.locator('#element-existing').select_option('facilities:sig')
    page.locator('#element-load').click()
    page.locator('#element-name').fill('Reviewed signal name')
    page.locator('#element-save').click()
    with page.expect_response(lambda response: response.request.method == 'PUT'
                             and response.url.endswith('/api/fleet/site-map/draft')) as saved_response:
        page.locator('#save-draft').click()
    assert saved_response.value.ok
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    assert store.draft_view()['map']['facilities'][0]['name'] == 'Reviewed signal name'
    assert store.draft_view()['map']['facilities'][0]['approaches'][0]['stop_s_m'] == .8
    page.reload()
    open_token_access(page)
    page.locator('#token-save').click()
    page.locator('#map-source').select_option('draft')
    expect(page.locator('#site-map-svg [data-place]')).to_have_count(2)
    expect(page.locator('#site-map-svg .facility.traffic_signal')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not [call for call in robot.calls if call[0] in ('navigation_goal', 'swarm_arm', 'line_follow_start')]


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('page_site', [False], indirect=True)
def test_mapless_driven_survey_records_unknown_robot_and_confirms_only_a_draft(page_site, width):
    import math
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap

    page, store, robot = page_site
    page.set_viewport_size({'width': width, 'height': 1000})
    store.save_draft(SiteMap.model_validate({'schema': 'rosy.site_map/1', 'map_id': 'survey-yard',
        'places': [], 'edges': [], 'survey': {'revision': 'reference-1', 'origin': [10, 20],
        'heading_rad': math.pi / 2, 'scale_source': 'odometry', 'description': 'Start at the marked origin'}}),
        expected_revision=None, principal_id='bob')
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#draft-status')).to_contain_text('초안')
    page.locator('#map-source').select_option('draft')
    page.locator('#teach-frame').select_option('survey')
    expect(page.locator('#teach-start')).to_be_disabled()
    expect(page.locator('#teach-start')).to_have_attribute('reason', re.compile('시작점'))
    expect(page.locator('#teach-reference')).to_contain_text('10.00, 20.00')
    page.locator('#teach-origin-confirm').check()
    robot._state = {'robot_id': 'rosy_60', 'pose': None, 'localization': {'state': 'UNKNOWN', 'pose_frame': 'odom'},
        'odom_pose': {'x': 2, 'y': 3, 'yaw': 0, 'stamp': time.time()}}
    page.locator('#teach-start').click()
    expect(page.locator('#teach-status')).to_contain_text('조사 기록 중')
    robot._state['odom_pose'] = {'x': 2.2, 'y': 3, 'yaw': 0, 'stamp': time.time() + 0.01}
    expect(page.locator('#teach-status')).to_contain_text('2점')
    page.locator('#teach-stop').click()
    expect(page.locator('#teach-form')).to_be_visible()
    expect(page.locator('#site-map-svg polyline.teach')).to_have_count(1)
    page.locator('#teach-from-name').fill('Origin')
    page.locator('#teach-to-name').fill('End')
    page.locator('#teach-confirm').click()
    expect(page.locator('#notice')).to_contain_text('초안에 차로')
    body = store.draft_view()['map']
    assert body['edges'][0]['polyline'] == [[10, 20], [10, 20.2]]
    assert body['edges'][0]['evidence']['source'] == 'odometry'
    assert body['survey']['reviewed'] is False and store.active_view() is None
    assert {call[0] for call in robot.calls} <= {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 390])
def test_soccer_profile_basic_information_and_template(page_site, width):
    from playwright.sync_api import expect
    page, store, robot = page_site
    page.set_viewport_size({'width': width, 'height': 1000})
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#map-status')).to_contain_text('활성 지도')
    before = store.active_view()
    page.locator('#profile-kind').select_option('soccer')
    page.locator('#profile-description').fill('실측 연습 경기장')
    page.locator('#profile-length').fill('3')
    page.locator('#profile-width').fill('2')
    page.locator('#profile-goal-width').fill('0.5')
    page.locator('#profile-new').click()
    page.locator('#profile-id').fill('pitch')
    page.locator('#profile-save').click()
    expect(page.locator('#map-status')).to_contain_text('새 축구장')
    row = next(r for r in store.profiles() if r['profile_id'] == 'pitch')
    assert row['kind'] == 'soccer' and row['description'] == '실측 연습 경기장'
    assert row['soccer_field'] == {'length_m': 3, 'width_m': 2, 'goal_width_m': 0.5}
    assert row['map']['edges'] == []
    expect(page.locator('[data-pitch-mark]')).to_have_count(4)
    page.locator('#map-profile').select_option('')
    page.locator('#map-profile').select_option('pitch')
    expect(page.locator('#profile-length')).to_have_value('3')
    expect(page.locator('#profile-description')).to_have_value('실측 연습 경기장')
    expect(page.locator('#profile-draft')).to_be_disabled()
    page.locator('#profile-file').set_input_files({'name': 'pitch.json', 'mimeType': 'application/json',
                                                  'buffer': json.dumps(row).encode()})
    expect(page.locator('#profile-kind')).to_have_value('soccer')
    expect(page.locator('#profile-length')).to_have_value('3')
    assert store.active_view() == before
    assert not [call for call in robot.calls if call[0] == 'navigation_goal']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 390])
def test_profiles_rules_import_preview_and_draft_stay_separate(page_site, width):
    from playwright.sync_api import expect
    from test_site_map_trip import _line
    page, store, robot = page_site
    page.set_viewport_size({'width': width, 'height': 1000})
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#map-status')).to_contain_text('활성 지도')
    before = store.active_view()
    page.locator('#profile-new').click()
    page.locator('#profile-id').fill('training')
    page.locator('#profile-name').fill('연습장')
    page.locator('#profile-save').click()
    expect(page.locator('#profile-status')).to_contain_text('지도 설정을 저장했습니다')
    expect(page.locator('#map-status')).to_contain_text('연습장')
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(0)
    assert next(row['map'] for row in store.profiles() if row['profile_id'] == 'training')['places'] == []
    expect(page.locator('#site-map-svg #robot-layer')).to_have_count(0)
    assert store.active_view() == before and store.draft_view()['map'] is None
    body = {'schema': 'rosy.site_map/1', 'map_id': 'imported', **_line()}
    page.locator('#profile-file').set_input_files({'name': 'imported.json',
      'mimeType': 'application/json', 'buffer': json.dumps(body).encode()})
    page.locator('#profile-save').click()
    expect(page.locator('#map-status')).to_contain_text('imported.json')
    expect(page.locator('#map-profile option')).to_have_count(3)
    page.locator('#map-profile').select_option('training')
    expect(page.locator('#map-status')).to_contain_text('연습장')
    page.locator('#profile-draft').click()
    expect(page.locator('#map-source')).to_have_value('draft')
    assert store.draft_view()['map']['map_id'] == next(row['map']['map_id'] for row in store.profiles() if row['profile_id'] == 'training')
    assert store.active_view() == before
    assert not [call for call in robot.calls if call[0] == 'navigation_goal']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_rectangular_camera_coordinates_are_display_only(page_site):
    import cv2
    import numpy as np
    from playwright.sync_api import expect

    page, store, robot = page_site
    writes = []
    page.on("request", lambda request: writes.append(request.url) if request.method in {"POST", "PUT", "DELETE"} else None)
    record = {"source_id": "camera-test", "map_id": store.active_view()["map"]["map_id"],
              "map_to_image": [50, 0, 100, 0, -50, 100, 0, 0, 1],
              "track_bounds_m": {"min_x": -1, "max_x": 3, "min_y": -1, "max_y": 1},
              "image": {"width": 300, "height": 200}, "lens": None}
    image = np.zeros((200, 300, 3), np.uint8)
    image[:, :150] = [0, 255, 0]
    encoded = cv2.imencode(".png", image)[1].tobytes()
    other = {**record, "source_id": "camera-other"}
    page.route("**/api/fleet/calibrations", lambda route: route.fulfill(json={"calibrations": [record, other]}))
    page.route("**/api/fleet/vision/lease", lambda route: route.fulfill(json={"lease": "preview-test", "frame_path": "/test-camera-frame"}))
    headers = {"X-Frame-Age-Ms": "10", "X-Frame-Rectified": "false"}
    page.route("**/test-camera-frame", lambda route: route.fulfill(body=encoded, content_type="image/png", headers=headers))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "bob · operator")
    plane_tools = page.locator(".plane-tools")
    expect(plane_tools).not_to_have_attribute("open", "")
    plane_tools.locator("summary").focus()
    page.keyboard.press("Enter")
    expect(plane_tools).to_have_attribute("open", "")
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("불러온 평면 영상")
    expect(page.locator("#site-map-svg image")).to_be_visible()
    page.locator("#trip-pick").check()
    page.locator("#plane-pick").check()
    expect(page.locator("#trip-pick")).not_to_be_checked()
    writes.clear()
    page.locator("#map-viewport").scroll_into_view_if_needed()
    point = page.locator("#site-map-svg").evaluate("svg => { const p = new DOMPoint(400, 240).matrixTransform(svg.getScreenCTM()); return {x: p.x, y: p.y}; }")
    page.mouse.click(point["x"], point["y"])
    expect(page.locator("#plane-point")).to_contain_text("확인한 좌표 x")
    x, y = map(float, re.search(r"x ([\d.-]+) m, y ([\d.-]+) m", page.locator("#plane-point").inner_text()).groups())
    # Native mouse events round screen pixels; one map pixel is about 5.3 mm here.
    assert abs(x - 1) <= 0.006 and abs(y) <= 0.006
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 없음")
    assert not writes
    page.locator("#plane-source").select_option("camera-other")
    expect(page.locator("#site-map-svg image")).to_have_count(0)
    expect(page.locator("#plane-point")).to_contain_text("확인한 좌표 없음")
    assert page.locator("#plane-source").input_value() == "camera-other"
    headers["X-Source-Lens"] = "kind=standard;focal_mm=5.4;hfov_deg=67.8"
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("렌즈와 보정이 다릅니다")
    expect(page.locator("#site-map-svg image")).to_have_count(0)
    expect(page.locator("#plane-pick")).not_to_be_checked()
    expect(page.locator("#plane-pick")).to_be_disabled()
    headers.pop("X-Source-Lens")
    headers["X-Frame-Age-Ms"] = "4000"
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("신선한 원본 영상을 확인할 수 없습니다")


def test_vision_map_plane_is_drawn_and_picked_by_its_scale_then_falls_back_on_409(page_site):
    """D-560 S2: the site-map tab asks for mode map, draws the plane as received and picks
    x = min_x + u/ppm, y = max_y - v/ppm; only 409 plane-unavailable falls back to the browser warp."""
    import cv2
    import numpy as np
    from playwright.sync_api import expect

    page, store, robot = page_site
    record = {"source_id": "camera-test", "map_id": store.active_view()["map"]["map_id"],
              "calibration_revision": "paint-test",
              "map_to_image": [50, 0, 100, 0, -50, 100, 0, 0, 1],
              "track_bounds_m": {"min_x": -1, "max_x": 3, "min_y": -1, "max_y": 1},
              "image": {"width": 300, "height": 200}, "lens": None}
    plane_image = np.zeros((100, 200, 3), np.uint8)  # 4 x 2 m at 50 px/m
    plane_image[:, :100] = [0, 255, 0]
    plane_png = cv2.imencode(".png", plane_image)[1].tobytes()
    raw_png = cv2.imencode(".png", np.zeros((200, 300, 3), np.uint8))[1].tobytes()
    leases, plane = [], {"status": 200, "revision": "paint-test"}

    def serve_lease(route):
        body = route.request.post_data_json
        leases.append(body)
        mode = (body.get("rectification") or {}).get("mode")
        route.fulfill(json={"lease": "plane-test" if mode == "map" else "raw-test", "frame_path": "/test-camera-frame"})

    def serve_frame(route):
        if route.request.headers.get("authorization") != "Bearer plane-test":
            route.fulfill(body=raw_png, content_type="image/png",
                          headers={"X-Frame-Age-Ms": "10", "X-Frame-Rectified": "false"})
        elif plane["status"] == 409:
            route.fulfill(status=409, json={"detail": "plane unavailable"},
                          headers={"X-Frame-State": "plane-unavailable"})
        else:
            route.fulfill(body=plane_png, content_type="image/png",
                          headers={"X-Frame-Age-Ms": "10", "X-Frame-Rectified": "map",
                                   "X-Frame-Plane": "-1,-1,3,1,50", "X-Frame-Calibration": plane["revision"],
                                   "X-Frame-Observed-Fraction": "0.75"})

    page.route("**/api/fleet/calibrations", lambda route: route.fulfill(json={"calibrations": [record]}))
    page.route("**/api/fleet/vision/lease", serve_lease)
    page.route("**/test-camera-frame", serve_frame)
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "bob · operator")
    page.locator(".plane-tools summary").click()
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("Rosy Cam 평면 영상")
    expect(page.locator("#plane-status")).to_contain_text("영상 유효 영역 75%")
    expect(page.locator("#plane-status")).to_contain_text("paint-test")
    assert leases == [{"source_id": "camera-test", "rectification": {"mode": "map"}}]
    image = page.locator("#site-map-svg image")
    expect(image).to_be_visible()
    assert image.get_attribute("href").startswith("blob:")
    page.locator("#plane-pick").check()
    page.locator("#map-viewport").scroll_into_view_if_needed()
    box = image.bounding_box()
    assert abs(box["width"] / box["height"] - 2) < 0.02, box  # drawn as received: 200 x 100 px
    # Pixel (50, 25) of the plane is map (-1 + 50/50, 1 - 25/50) = (0, 0.5).
    page.mouse.click(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.25)
    expect(page.locator("#plane-point")).to_contain_text("확인한 좌표 x")
    x, y = map(float, re.search(r"x ([\d.-]+) m, y ([\d.-]+) m", page.locator("#plane-point").inner_text()).groups())
    assert abs(x) <= 0.01 and abs(y - 0.5) <= 0.01, (x, y)
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 없음")

    # A plane made with another calibration revision is neither drawn nor picked.
    plane["revision"] = "paint-old"
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("보정 revision이 다릅니다")
    expect(page.locator("#site-map-svg image")).to_have_count(0)
    expect(page.locator("#plane-pick")).to_be_disabled()
    plane["revision"] = "paint-test"

    plane["status"] = 409
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("브라우저 보정(대체)")
    expect(page.locator("#site-map-svg image")).to_be_visible()
    assert page.locator("#site-map-svg image").get_attribute("href").startswith("data:image/png")
    assert [body.get("rectification") for body in leases[1:]] == [{"mode": "map"}, {"mode": "map"}, None]


def test_import_camera_map_draft_never_activates(page_site):
    from playwright.sync_api import expect
    from test_site_map_trip import _line

    page, store, robot = page_site
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "bob · operator")
    previous = store.active_view()
    camera_fixture = os.environ.get("ROSY_CAMERA_MAP_FIXTURE")
    draft = json.loads(Path(camera_fixture).read_text(encoding="utf-8")) if camera_fixture \
        else {"schema": "rosy.site_map/1", **_line()}
    page.locator("#camera-map-file").set_input_files({
        "name": "camera-draft.json", "mimeType": "application/json",
        "buffer": json.dumps(draft).encode()})
    page.locator("#import-camera-map").click()
    expect(page.locator("#notice")).to_contain_text("카메라 지도 초안")
    expect(page.locator("#site-map-svg [data-edge]")).to_have_count(len(draft["edges"]))
    assert store.active_view() == previous
    assert store.draft_view()["map"]["edges"]
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    if output := os.environ.get("ROSY_SHOT_DIR"):
        for width, height in ((1440, 1000), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=str(Path(output) / f"camera-map-import-{width}x{height}.png"), full_page=True)
    page.locator("#camera-map-file").set_input_files({
        "name": "invalid.json", "mimeType": "application/json", "buffer": b'{"schema":"wrong"}'})
    page.locator("#import-camera-map").click()
    expect(page.locator("#notice")).to_contain_text("rosy.site_map/1")
    assert store.active_view() == previous


@pytest.fixture
def page_site(tmp_path, request):
    from playwright.sync_api import sync_playwright

    client, tasks, store, robot = _app(tmp_path, imported=getattr(request, 'param', True))
    if store.active() is not None:
        robot._state = _on_ring_s(store)
    client.app.state.web_common = ROOT / "shared" / "web"
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as toolkit:
            browser = toolkit.chromium.launch(headless=True,
                                              args=[f"--explicitly-allowed-ports={listener.getsockname()[1]}"])
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(origin + "/console/site-map")
                yield page, store, robot
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def test_requested_recording_robot_never_falls_back_to_another_robot(page_site):
    from playwright.sync_api import expect

    page, store, robot = page_site
    page.goto(page.url + '?robot=not-in-roster#teach-heading')
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'bob · operator')
    expect(page.locator('#teach-target')).to_contain_text('not-in-roster')
    expect(page.locator('#teach-robot')).to_have_value('')
    expect(page.locator('#teach-start')).to_be_disabled()
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]


def test_recording_target_survives_refresh_and_names_offline_or_removed_robots(page_site):
    from playwright.sync_api import expect

    page, store, robot = page_site
    roster = {'robots': [{'robot_id': 'alpha', 'online': True}, {'robot_id': 'beta', 'online': True}]}
    recording = {'recording': None, 'pending': []}
    page.route('**/api/fleet/state', lambda route: route.fulfill(content_type='application/json', body=json.dumps(roster)))
    page.route('**/api/fleet/teach', lambda route: route.fulfill(content_type='application/json', body=json.dumps(recording)))
    page.goto(page.url + '?robot=beta#teach-heading')
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#teach-robot')).to_have_value('beta')
    page.locator('#teach-robot').select_option('alpha')
    open_token_access(page)
    page.locator('#token-save').click()
    expect(page.locator('#teach-robot')).to_have_value('alpha')
    roster['robots'][0]['online'] = False
    open_token_access(page)
    page.locator('#token-save').click()
    expect(page.locator('#teach-target')).to_contain_text('연결 끊김')
    recording['recording'] = {'teach_id': 'running', 'robot_id': 'beta', 'map_id': store.active_view()['map']['map_id'],
        'points': [], 'started_at': time.time()}
    expect(page.locator('#teach-target')).to_contain_text('기록 중인 로봇 beta')
    expect(page.locator('#teach-robot')).to_have_value('beta')
    expect(page.locator('#teach-robot')).to_be_disabled()
    roster['robots'] = roster['robots'][:1]
    open_token_access(page)
    page.locator('#token-save').click()
    expect(page.locator('#teach-target')).to_contain_text('기록 중인 로봇 beta')
    expect(page.locator('#teach-robot')).to_have_value('')
    expect(page.locator('#teach-stop')).to_be_enabled()
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_view_edit_activate_and_preview_a_trip(page_site, width, height):
    from playwright.sync_api import expect

    page, store, robot = page_site
    page.set_viewport_size({"width": width, "height": height})
    expect(page).to_have_title("Rosy Fleet — 현장 지도")
    expect(page.locator("ui-brand")).to_contain_text("Fleet")
    expect(page.locator("ui-brand a")).to_have_attribute("aria-label", "Rosy Fleet 관제 홈")
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "bob · operator")
    expect(page.locator("#token-access")).not_to_have_attribute("open", "")
    # D-540 2: below 90rem the reconnect summary sits in the header fold behind 설정.
    expect(page.locator("#topbar-more")).to_be_visible()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(4)
    expect(page.locator("#site-map-svg .arrow")).to_have_count(8)  # 4 one-way + 2 two-way edges
    positions = page.evaluate("""() => ({
      map: document.querySelector('#map-viewport').getBoundingClientRect().top,
      trip: document.querySelector('[aria-labelledby=trip-heading]').getBoundingClientRect().top,
      run: document.querySelector('[aria-labelledby=run-heading]').getBoundingClientRect().top,
      edit: document.querySelector('[aria-labelledby=edit-heading]').getBoundingClientRect().top,
      plane: document.querySelector('.plane-tools summary').getBoundingClientRect().top,
    })""")
    assert positions["map"] < positions["plane"] < positions["trip"] and positions["map"] < height + 1, positions
    expect(page.locator(".plane-tools")).not_to_have_attribute("open", "")
    expect(page.locator("#plane-source")).to_be_hidden()
    if width < 1024:
        assert positions["trip"] < positions["run"] < positions["edit"], positions
    else:
        assert abs(positions["trip"] - positions["edit"]) <= 1 and positions["trip"] < positions["run"], positions
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-fresh-{width}x{height}.png"), full_page=True)

    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("3개 차로")
    expect(page.locator("#site-map-svg .plan")).to_have_count(3)
    expect(page.locator("#trip-actions li").last).to_contain_text("정지")
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-preview-{width}x{height}.png"), full_page=True)

    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator("#place-name").fill("A동 입구")
    page.select_option("#place-kind", "stop")
    page.locator("#apply-edit").click()
    page.locator('#site-map-svg [data-edge="ring_n"]').dispatch_event("click")  # a thin arc stroke
    page.select_option("#edge-direction", "two_way")
    page.locator("#apply-edit").click()
    page.locator("#save-draft").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")
    page.locator("#activate").click()
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-confirm-{width}x{height}.png"), full_page=True)
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    expect(page.locator("#notice")).to_contain_text("활성 지도 v2")
    active = store.active()[1]
    assert next(p for p in active.places if p.id == "NW").name == "A동 입구"
    assert next(e for e in active.edges if e.id == "ring_n").direction == "two_way"

    page.locator("#trip-pick").check()
    page.locator(".map-viewport").evaluate("element => element.scrollLeft = 0")
    page.locator(".map-viewport").click(position={"x": 5, "y": 5})
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 x")
    page.locator("#trip-plan").click()
    if width >= 1024:
        expect(page.locator("#trip-summary")).to_contain_text("차로 폭 두 배 안에 차로가 없습니다")
    else:
        expect(page.locator("#trip-summary")).to_contain_text("실행하지 않음")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_site_map_fits_declared_widths(page_site, width, height):
    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    from playwright.sync_api import expect

    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    sizes = page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      map: document.querySelector('#site-map-svg').getBoundingClientRect().width,
      label: document.querySelector('#site-map-svg .label').getBoundingClientRect().height,
      mapWindow: document.querySelector('.map-viewport').clientWidth,
      mapContent: document.querySelector('.map-viewport').scrollWidth,
      header: document.querySelector('ui-topbar').getBoundingClientRect().height,
      edit: document.querySelector('[aria-labelledby=edit-heading]').getBoundingClientRect().width,
      trip: document.querySelector('[aria-labelledby=trip-heading]').getBoundingClientRect().width,
      stop: document.querySelector('#estop').getBoundingClientRect().right,
      // A select's own width with its chosen words and the native arrow, measured on an unsqueezed copy.
      selects: [...document.querySelectorAll('ui-head select')].map((node) => {
        const copy = node.cloneNode(true);
        copy.style.cssText = 'width:auto;min-width:0;max-width:none;position:absolute';
        copy.replaceChildren(new Option(node.selectedOptions[0].textContent));
        document.body.append(copy);
        const need = copy.offsetWidth;
        copy.remove();
        return [node.id, need, node.offsetWidth];
      })
    })""")
    assert sizes["overflow"] <= 0, sizes
    assert all(need <= has + 1 for _id, need, has in sizes["selects"]), sizes
    assert sizes["label"] >= 12, sizes
    if width < 1024:
        assert sizes["mapWindow"] <= width and sizes["mapContent"] > sizes["mapWindow"], sizes
    if width < 480:
        assert sizes["header"] <= height * 0.2, sizes  # D-540 2: identity folds behind 설정
    assert abs(sizes["edit"] - sizes["trip"]) <= 1, sizes
    assert sizes["stop"] <= width, sizes


# The wide layout stands from a 60rem body: a 1296px shell. 1349 is a 1366 laptop window with a classic scrollbar.
@pytest.mark.parametrize("width,height,panels,fields", [(360, 740, 1, 1), (1024, 768, 1, 1), (1100, 800, 1, 1),
                                                       (1349, 768, 2, 3), (1366, 768, 2, 3)])
def test_site_map_body_keeps_usable_columns_beside_the_sub_nav(page_site, width, height, panels, fields):
    """D-741 2: the rail and the sub-nav take 304px. The body picks its columns from its own width: one panel column
    and one-column forms until the body has 60rem, then two and three. There is no sideways overflow, no control
    past the window or with cut text, no multi-column cell under 9rem (what these forms had at the sheet's own
    64rem break before the seats), and the sticky sub-nav shows every entry at the top and at the end of the page."""
    from playwright.sync_api import expect

    page, _, _ = page_site
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.locator('#site-map-svg [data-place="NW"]').click()
    expect(page.locator("#place-form")).to_be_visible()
    page.set_viewport_size({"width": width, "height": height})
    top = page.evaluate(BODY_FIT)
    page.evaluate("scrollTo(0, document.documentElement.scrollHeight)")
    end = page.evaluate(BODY_FIT)
    label = page.locator("#site-map-svg .label").first.evaluate("node => node.getBoundingClientRect().height")
    print(json.dumps({"size": [width, height], "top": top, "end": end, "label": label}, ensure_ascii=False))
    assert top["nav"]["column"] == (width >= 1024), top
    assert top["overflow"] <= 0 and end["overflow"] <= 0, (top, end)
    assert top["stop"] and end["stop"], (top, end)
    if width >= 1024:  # below it the sub-nav is a row that scrolls sideways
        assert top["unreachable"] == [] and end["unreachable"] == [], (top, end)
    assert top["cut"] == [] and top["outside"] == [] and end["outside"] == [], (top, end)
    columns = {grid["name"]: grid["columns"] for grid in top["grids"]}
    assert columns == {"map-workflow": panels, "place-form": fields, "form": fields,
                       "actions draft-actions": 1 if width < 480 else 3}, top["grids"]
    assert all(grid["narrowest"] >= 144 for grid in top["grids"] if grid["columns"] > 1), top["grids"]
    assert label >= 12, label


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_first_boot_explains_access_before_any_map_evidence(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-first-boot-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
@pytest.mark.parametrize("safety,label", [(True, "비상 정지"), (None, "정지 상태 미확인")])
def test_robot_safety_is_named_during_plan_only_preview(page_site, width, height, safety, label):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_60","online":true,"state":{"safety":'
             + ('{"estop":true}' if safety else 'null') + '}}]}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-robot option")).to_contain_text(label)
    expect(page.locator("#trip-summary")).to_contain_text("실행은 하지 않습니다")
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-safety-{'stopped' if safety else 'unknown'}-{width}x{height}.png"), full_page=True)


def test_changing_trip_target_clears_old_plan_evidence(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("3개 차로")
    expect(page.locator("#site-map-svg .plan")).to_have_count(3)
    page.select_option("#trip-place", "SE")
    expect(page.locator("#trip-summary")).to_contain_text("계산 전")
    expect(page.locator("#site-map-svg .plan")).to_have_count(0)
    expect(page.locator("#trip-actions li")).to_have_count(0)


def test_late_trip_response_cannot_restore_old_target(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    pending = []
    page.route("**/api/fleet/robots/rosy_60/trip", lambda route: pending.append(route))
    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    page.wait_for_timeout(200)
    assert pending
    page.select_option("#trip-place", "SE")
    with page.expect_response("**/api/fleet/robots/rosy_60/trip"):
        pending[0].continue_()
    expect(page.locator("#trip-summary")).to_contain_text("계산 전")
    expect(page.locator("#site-map-svg .plan")).to_have_count(0)
    expect(page.locator("#trip-actions li")).to_have_count(0)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_viewer_cannot_be_offered_operator_actions(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    open_token_access(page)
    page.locator("#console-token").fill("viewer-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "vic · viewer")
    expect(page.locator("#user-role")).to_have_text("보기 전용")
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#map-viewport")).to_be_visible()
    page.locator('#site-map-svg [data-place="NW"]').click()
    for selector in ("#apply-edit", "#save-draft", "#activate", "#trip-plan", "#estop"):
        expect(page.locator(selector)).to_be_disabled()
        expect(page.locator(selector)).to_have_attribute("reason", "운영자 권한이 필요합니다")
    expect(page.locator("#place-form")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('#estop').getBoundingClientRect().right <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-viewer-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_failed_reconnect_clears_old_map_and_actions(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    open_token_access(page)
    page.locator("#console-token").fill("invalid-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_text("인증 필요")
    expect(page.locator("#notice")).to_contain_text("토큰을 확인하고 다시 접속")
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(0)
    expect(page.locator("#estop")).to_be_disabled()
    layout = page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      stop: document.querySelector('#estop').getBoundingClientRect().right,
      actions: ['apply-edit', 'save-draft', 'activate'].map(id => document.getElementById(id).getBoundingClientRect().width)
    })""")
    assert layout["overflow"] <= 0 and layout["stop"] <= width, layout
    assert max(layout["actions"]) - min(layout["actions"]) <= 1, layout
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-auth-rejected-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_site_map_server_error_has_recovery_and_no_stale_controls(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"detail":{"code":"SITE_MAP_UNAVAILABLE"}}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#notice")).to_contain_text("잠시 뒤 다시 접속")
    expect(page.locator("#map-status")).to_contain_text("지도 조회 실패")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("초안 확인 불가")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#apply-edit")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('#estop').getBoundingClientRect().right <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-map-error-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_slow_site_map_load_shows_elapsed_wait(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})

    pending = []
    page.route("**/api/fleet/site-map/active", lambda route: pending.append(route))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#notice")).to_contain_text("접속 중")
    expect(page.locator("#notice")).to_contain_text(re.compile(r"[1-9]초 경과"), timeout=4000)
    expect(page.locator("#token-save")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert pending
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-delayed-{width}x{height}.png"), full_page=True)
    pending[0].continue_()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1", timeout=8000)
    expect(page.locator("#token-save")).to_be_enabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_pending_map_read_then_disconnect(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    pending = []
    page.route("**/api/fleet/site-map/active", lambda route: pending.append(route))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("지도 조회 중")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("초안 조회 중")
    expect(page.locator("#notice")).to_contain_text(re.compile(r"[1-9]초 경과"), timeout=4000)
    expect(page.locator("#token-save")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert pending
    pending[0].abort()
    expect(page.locator("#notice")).to_contain_text("관제 연결을 확인하지 못했습니다")
    expect(page.locator("#notice")).to_contain_text("현재 상태를 다시 조회하세요")
    expect(page.locator("#map-status")).to_contain_text("지도 조회 실패")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-disconnected-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_empty_site_map_names_the_next_step(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(
        status=404, content_type="application/json", body='{"detail":{"code":"SITE_MAP_NOT_ACTIVE"}}'))
    page.route("**/api/fleet/site-map/draft", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"map":null,"revision":null}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 없음")
    expect(page.locator("#notice")).to_contain_text("지도 만들기에서 기준을 정하거나")
    expect(page.locator("#survey-new")).to_be_enabled()
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#save-draft")).to_be_disabled()
    expect(page.locator("#activate")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-empty-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_offline_robot_cannot_be_offered_for_trip_preview(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_60","online":false}]}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-robot option")).to_have_text("rosy_60 · 연결 끊김")
    expect(page.locator("#trip-robot")).to_have_value("rosy_60")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_have_attribute("reason", "연결된 로봇이 없습니다 · 로봇 연결을 확인하세요")
    expect(page.locator("#trip-summary")).to_contain_text("연결된 로봇이 없습니다")
    stop = page.locator("#estop").bounding_box()
    assert stop and 0 <= stop["y"] < height
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-offline-{width}x{height}.png"), full_page=True)


def test_connected_robot_can_be_selected_after_offline_robot(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_99","online":false},{"robot_id":"rosy_60","online":true}]}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_have_attribute("reason", "선택한 로봇의 연결을 확인하세요")
    page.select_option("#trip-robot", "rosy_60")
    expect(page.locator("#trip-plan")).to_be_enabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_no_robot_explains_why_trip_preview_is_unavailable(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"robots":[]}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-summary")).to_contain_text("등록된 로봇이 없습니다")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-no-robot-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_robot_state_failure_keeps_loaded_map_and_names_missing_evidence(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"detail":"state unavailable"}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#map-viewport")).to_be_visible()
    expect(page.locator("#trip-summary")).to_contain_text("로봇 상태 확인 불가")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-robot-state-error-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("status", [401, 403])
def test_robot_state_auth_failure_removes_operator_controls(page_site, status):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=status, content_type="application/json", body='{"detail":"unauthorized"}'))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요" if status == 401 else "지도 조회 실패")
    expect(page.locator("#estop")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_be_disabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_changed_draft_keeps_local_edits_and_conflict_after_reconnect(page_site, width, height):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap

    page, store, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator("#place-name").fill("북서 정차")
    page.locator("#apply-edit").click()
    store.save_draft(SiteMap.model_validate(store.active_view()["map"]), expected_revision=None, principal_id="alice")
    page.locator("#save-draft").click()
    expect(page.locator("#notice")).to_contain_text("화면을 새로고침해 최신 초안")
    expect(page.locator("#draft-status")).to_contain_text("저장 안 된 초안")
    expect(page.locator("#activate")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-conflict-{width}x{height}.png"), full_page=True)
    open_token_access(page)
    page.locator("#token-save").click()
    expect(page.locator("#notice")).to_contain_text("보존")
    expect(page.locator("#draft-status")).to_contain_text("저장 안 된 초안")
    page.locator('#site-map-svg [data-place="NW"]').click()
    expect(page.locator("#place-name")).to_have_value("북서 정차")
    page.locator("#save-draft").click()
    expect(page.locator("#notice")).to_contain_text("화면을 새로고침해 최신 초안")
    assert store.draft_view()["map"]["places"] == store.active_view()["map"]["places"]
    page.reload()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.locator('#site-map-svg [data-place="NW"]').click()
    expect(page.locator("#place-name")).not_to_have_value("북서 정차")
    expect(page.locator("#draft-status")).not_to_contain_text("저장 안 된 초안")


def test_crosswalk_waiting_band_is_drawn_saved_and_deleted_on_the_draft(page_site):
    """D-573 1/7: crosswalk polygons are read-only on the map; the operator draws a waiting band
    on the draft, the named save keeps it, and deleting it saves an empty band list."""
    from playwright.sync_api import expect

    page, store, _robot = page_site
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "bob · operator")
    expect(page.locator("#site-map-svg [data-crosswalk]")).to_have_count(2)  # active map, read-only
    page.select_option("#map-source", "draft")
    page.locator("#map-viewport").scroll_into_view_if_needed()
    zone = page.locator('#site-map-svg [data-crosswalk="cw2"]')
    zone.dispatch_event("click")  # the east lane line runs over the polygon's centre
    expect(page.locator("#selection")).to_contain_text("횡단보도 cw2")
    expect(page.locator("#crosswalk-form")).to_be_visible()
    expect(page.locator("#crosswalk-lanes")).to_contain_text("east")
    page.locator("#band-draw").click()
    zone.evaluate("e => e.scrollIntoView({block: 'center'})")  # the button sits below the map, the topbar above
    box = zone.bounding_box()
    # North of cw2: the lane runs along x; screen up is map +y at view turn 0.
    for fx, fy in ((0.1, 0.05), (0.9, 0.05), (0.9, -0.45), (0.1, -0.45)):
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
    expect(page.locator("#site-map-svg .band-draft")).to_have_count(1)
    page.locator("#band-finish").click()
    expect(page.locator("#crosswalk-band option")).to_have_count(1)
    expect(page.locator("#site-map-svg .crosswalk-approach")).to_have_count(1)
    page.locator("#save-draft").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")
    saved = store.draft_view()
    assert saved["saved_by"] == "bob" and len(saved["map"]["crosswalks"][1]["approach"]) == 1
    assert len(saved["map"]["crosswalks"][1]["approach"][0]) == 4
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / "site-map-crosswalk-band.png"), full_page=True)
    page.locator("#band-delete").click()
    expect(page.locator("#crosswalk-band option")).to_have_count(0)
    page.locator("#save-draft").click()
    expect(page.locator("#notice")).to_contain_text("초안을 저장했습니다")
    assert store.draft_view()["map"]["crosswalks"][1]["approach"] == []
    assert store.active()[0] == 1  # the draft only; activation stays a separate named step


def test_viewer_sees_crosswalks_without_band_tools(page_site):
    from playwright.sync_api import expect

    page, _store, _robot = page_site
    open_token_access(page)
    page.locator("#console-token").fill("viewer-token")
    page.locator("#token-save").click()
    expect(page.locator("#site-map-svg [data-crosswalk]")).to_have_count(2)
    page.locator("#map-viewport").scroll_into_view_if_needed()
    page.locator('#site-map-svg [data-crosswalk="cw1"]').dispatch_event("click")
    expect(page.locator("#selection")).to_contain_text("횡단보도 cw1")
    expect(page.locator("#crosswalk-form")).to_be_hidden()
    expect(page.locator("#import-crosswalks")).to_be_disabled()


@pytest.mark.parametrize('width', [1440, 390])
def test_normal_teach_preview_disappears_on_an_unrelated_profile(page_site, width):
    from playwright.sync_api import expect
    page, store, robot = page_site
    page.set_viewport_size({'width': width, 'height': 1000})
    active = store.active_view()
    pending = {'teach_id': 'old-frame', 'robot_id': 'rosy_60', 'map_id': active['map']['map_id'],
        'polyline': [[0, 0], [0.2, 0]], 'expires_at': time.time() + 600,
        'points': 2, 'from_candidates': [], 'to_candidates': [], 'reason': 'operator'}
    page.route('**/api/fleet/teach', lambda route: route.fulfill(status=200,
        content_type='application/json', body=json.dumps({'recording': None, 'pending': [pending]})))
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#site-map-svg polyline.teach')).to_have_count(1)
    page.locator('#profile-new').click()
    page.locator('#profile-id').fill('other-frame')
    page.locator('#profile-save').click()
    expect(page.locator('#map-profile')).to_have_value('other-frame')
    expect(page.locator('#site-map-svg polyline.teach')).to_have_count(0)
    assert store.active_view() == active and store.draft_view()['map'] is None
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('first', ['idle', 'recording', 'pending'])
def test_teach_poll_keeps_idle_map_labels_and_draws_then_clears_previews(page_site, first):
    from playwright.sync_api import expect

    page, store, robot = page_site
    replies = []
    page.route('**/api/fleet/teach', lambda route: replies.append(route))
    teach_request = re.compile(r'/api/fleet/teach$')
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    with page.expect_request(teach_request):
        page.locator('#token-save').click()
    expect(page.locator('#map-status')).to_contain_text('활성 지도')
    label = page.locator('#site-map-svg .label').first.element_handle()
    assert label is not None and label.evaluate('node => node.isConnected')
    active = {'teach_id': 'preview', 'robot_id': 'rosy_60',
              'map_id': store.active_view()['map']['map_id'],
              'points': [[0, 0], [0.2, 0]], 'started_by': 'bob'}
    pending = {**active, 'polyline': active['points'], 'points': 2,
               'expires_at': time.time() + 600, 'from_candidates': [], 'to_candidates': []}
    idle = {'recording': None, 'pending': []}
    view = {'recording': active if first == 'recording' else None,
            'pending': [pending] if first == 'pending' else []}
    # The next real timer request proves the prior poll finished, without a timing sleep.
    with page.expect_request(teach_request):
        replies.pop(0).fulfill(json=view)
    if first == 'idle':
        assert label.evaluate('node => node.isConnected'), 'an empty teach poll replaced the map labels'
        assert label.evaluate('node => node.getBoundingClientRect().height') >= 12
        expect(page.locator('#site-map-svg polyline.teach')).to_have_count(0)
        with page.expect_request(teach_request):
            replies.pop(0).fulfill(json={'recording': active, 'pending': []})
    else:
        assert not label.evaluate('node => node.isConnected')
    expect(page.locator('#site-map-svg polyline.teach')).to_have_count(1)
    with page.expect_request(teach_request):
        replies.pop(0).fulfill(json=idle)
    expect(page.locator('#site-map-svg polyline.teach')).to_have_count(0)
    expect(page.locator('#teach-status')).to_have_text('기록 없음')
    assert not [call for call in robot.calls if call[0] not in
                {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]


@pytest.mark.parametrize('width', [1440, 390])
def test_camera_observation_accumulates_without_replacing_operator_features(page_site, width):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap
    page, store, robot = page_site
    active = store.active_view()
    reference = {'revision': 'survey-camera', 'origin': [0, 0], 'heading_rad': 0,
        'scale_source': 'measured', 'measured_distance_m': 2, 'description': 'Measured origin'}
    base = SiteMap.model_validate({'schema': 'rosy.site_map/1', 'map_id': 'yard', 'survey': reference,
        'places': [], 'edges': [], 'facilities': [{'id': 'mark', 'name': 'Origin marker',
            'kind': 'landmark', 'geometry': [[0, 0]], 'approaches': []}]})
    draft = store.save_draft(base, expected_revision=None, principal_id='bob')
    observation = SiteMap.model_validate({'schema': 'rosy.site_map/1', 'map_id': 'yard', 'survey': reference,
        'places': [{'id': 'A', 'name': 'A', 'x': 1, 'y': 0}, {'id': 'B', 'name': 'B', 'x': 2, 'y': 0}],
        'edges': [{'id': 'ab', 'from': 'A', 'to': 'B', 'polyline': [[1, 0], [2, 0]], 'width_m': .2, 'speed_cap_mps': .03,
            'evidence': {'source': 'camera', 'status': 'observed', 'reference_revision': 'survey-camera',
                'note': 'Frame sha256 fixture'}}]}).body()
    page.set_viewport_size({'width': width, 'height': 1000})
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#merge-camera-map')).to_be_disabled()
    page.locator('#camera-map-file').set_input_files({'name': 'observation.json',
        'mimeType': 'application/json', 'buffer': json.dumps(observation).encode()})
    page.locator('#merge-camera-map').click()
    expect(page.locator('#map-source')).to_have_value('draft')
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(1)
    saved = store.draft_view()
    assert saved['map']['facilities'] == draft['map']['facilities']
    assert saved['map']['edges'][0]['evidence']['source'] == 'camera'
    assert saved['map']['survey']['reviewed'] is False
    page.locator('#merge-camera-map').click()
    expect(page.locator('#notice')).to_contain_text('관측')
    assert len(store.draft_view()['map']['edges']) == 1
    other = {**observation, 'map_id': 'wrong-frame'}
    page.locator('#camera-map-file').set_input_files({'name': 'wrong.json',
        'mimeType': 'application/json', 'buffer': json.dumps(other).encode()})
    page.locator('#merge-camera-map').click()
    expect(page.locator('#notice')).to_contain_text('지도 ID')
    assert store.draft_view()['map'] == saved['map']
    assert store.active_view() == active
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 390])
def test_camera_road_review_without_survey_keeps_lineage_and_requires_recheck(page_site, width):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap
    from fleet.server.site_map_store import SiteMapError
    page, store, robot = page_site
    body = store.active_view()['map']
    for edge in body['edges']:
        edge['evidence'] = {'source': 'camera', 'status': 'observed', 'reference_revision': 'cal_fixture',
            'note': 'calibration sha256 abc; frame sha256 def'}
    draft = store.save_draft(SiteMap.model_validate(body), expected_revision=None, principal_id='bob')
    active = store.active_view()
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=draft['revision'], principal_id='bob', route_active=False)
    assert error.value.code == 'SITE_MAP_ROAD_UNREVIEWED'
    page.set_viewport_size({'width': width, 'height': 1000})
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    page.locator('#map-source').select_option('draft')
    expect(page.locator('#survey-review')).to_be_enabled()
    page.locator('details').filter(has=page.locator('#survey-review-note')).locator('summary').click()
    page.locator('#survey-review-note').fill('Measured calibration and road directions checked')
    page.locator('#survey-review').click()
    with page.expect_response(lambda response: response.url.endswith('/api/fleet/site-map/draft')
                              and response.request.method == 'PUT') as saved_response:
        page.locator('#save-draft').click()
    assert saved_response.value.ok
    expect(page.locator('#draft-status')).to_contain_text('저장된 초안')
    reviewed = store.draft_view()
    assert 'survey' not in reviewed['map']
    assert all(e['evidence']['status'] == 'reviewed' for e in reviewed['map']['edges'])
    assert all('frame sha256 def' in e['evidence']['note'] for e in reviewed['map']['edges'])
    assert all('Measured calibration' in e['evidence']['note'] for e in reviewed['map']['edges'])
    edge_id = reviewed['map']['edges'][0]['id']
    page.locator(f'#site-map-svg [data-edge="{edge_id}"]').dispatch_event('click')
    page.locator('#edge-speed').fill('0.02')
    page.locator('#apply-edit').click()
    with page.expect_response(lambda response: response.url.endswith('/api/fleet/site-map/draft')
                              and response.request.method == 'PUT'):
        page.locator('#save-draft').click()
    edited = store.draft_view()
    assert edited['map']['edges'][0]['evidence']['status'] == 'observed'
    assert 'frame sha256 def' in edited['map']['edges'][0]['evidence']['note']
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=edited['revision'], principal_id='bob', route_active=False)
    assert error.value.code == 'SITE_MAP_ROAD_UNREVIEWED'
    assert store.active_view() == active
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('race', ['none', 'file', 'choice', 'dirty', 'dialog'])
def test_camera_connections_require_review_before_extending_the_saved_map(page_site, width, race):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap
    from fleet.server.site_map_store import SiteMapError
    page, store, robot = page_site
    active = store.active_view()
    reference = {'revision': 's1', 'origin': [0, 0], 'heading_rad': 0,
        'scale_source': 'measured', 'measured_distance_m': 2, 'description': 'Measured origin'}
    base = SiteMap.model_validate({'map_id': 'yard', 'survey': reference,
        'places': [{'id': 'a', 'name': 'Start', 'x': 0, 'y': 0}, {'id': 'b', 'name': 'Junction', 'x': 2, 'y': 0}],
        'edges': [{'id': 'ab', 'from': 'a', 'to': 'b', 'polyline': [[0, 0], [2, 0]],
            'width_m': .2, 'speed_cap_mps': .03}]})
    draft = store.save_draft(base, expected_revision=None, principal_id='bob')
    observation = SiteMap.model_validate({'map_id': 'yard', 'survey': reference,
        'places': [{'id': 'near', 'name': 'Observed start', 'x': 2.02, 'y': 0}, {'id': 'far', 'name': 'Branch end', 'x': 3, 'y': 1}],
        'edges': [{'id': 'branch', 'from': 'near', 'to': 'far', 'polyline': [[2.02, 0], [3, 1]],
            'width_m': .2, 'speed_cap_mps': .03, 'evidence': {'source': 'camera', 'status': 'observed',
                'reference_revision': 's1', 'note': 'frame sha256 abc'}}]}).body()
    page.set_viewport_size({'width': width, 'height': 1000})
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    page.locator('#camera-map-file').set_input_files({'name': 'branch.json', 'mimeType': 'application/json',
        'buffer': json.dumps(observation).encode()})
    page.locator('#preview-camera-connections').click()
    expect(page.locator('#camera-connections')).to_contain_text('Observed start')
    expect(page.locator('#camera-connections')).to_contain_text('0.020')
    expect(page.locator('#merge-camera-map')).to_be_disabled()
    page.locator('#camera-connections select').select_option('b')
    expect(page.locator('#merge-camera-map')).to_be_disabled()
    page.locator('#camera-connect-confirm').check()
    if race != 'none':
        if race != 'dialog':
            page.evaluate('''() => {
                const file = document.getElementById('camera-map-file').files[0];
                const original = file.text.bind(file);
                file.text = () => new Promise(resolve => { window.finishCameraRead = () => original().then(resolve); });
            }''')
        page.locator('#import-camera-map' if race == 'dialog' else '#merge-camera-map').click()
        if race == 'dialog':
            expect(page.locator('dialog.ui-confirm')).to_be_visible()
        else:
            page.wait_for_function('typeof window.finishCameraRead === "function"')
        if race == 'file':
            page.locator('#camera-map-file').set_input_files([])
        elif race == 'choice':
            page.locator('#camera-connect-confirm').uncheck()
            page.locator('#camera-connect-confirm').check()
        else:
            page.locator('#map-source').select_option('draft')
            page.locator('#site-map-svg [data-edge="ab"]').dispatch_event('click')
            page.locator('#edge-speed').fill('0.02')
            page.locator('#apply-edit').dispatch_event('click')
        if race == 'dialog':
            page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        else:
            page.evaluate('window.finishCameraRead()')
        expect(page.locator('#notice')).to_contain_text('다시 확인')
        assert store.draft_view() == draft
        assert store.active_view() == active
        return
    page.locator('#merge-camera-map').click()
    expect(page.locator('#site-map-svg [data-edge]')).to_have_count(2)
    saved = store.draft_view()
    assert saved['map']['places'][:2] == draft['map']['places']
    assert saved['map']['edges'][1]['from'] == 'b'
    assert saved['map']['edges'][1]['polyline'][0] == [2, 0]
    assert saved['map']['edges'][1]['evidence']['status'] == 'inferred'
    assert 'near -> b' in saved['map']['edges'][1]['evidence']['note']
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved['revision'], principal_id='bob', route_active=False)
    assert error.value.code == 'SITE_MAP_SURVEY_UNREVIEWED'
    assert store.active_view() == active
    assert not [call for call in robot.calls if call[0] not in
        {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}]
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_reconnect_preserves_unapplied_and_applied_map_edits(page_site):
    from playwright.sync_api import expect

    page, store, robot = page_site
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator('#site-map-svg [data-place="NW"]')).to_be_visible()
    page.locator('#map-source').select_option('draft')
    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator('#place-name').fill('Unsaved local name')
    open_token_access(page)
    page.locator('#token-save').click()
    expect(page.locator('#notice')).to_contain_text('보존')
    expect(page.locator('#place-name')).to_have_value('Unsaved local name')
    page.locator('#apply-edit').click()
    open_token_access(page)
    page.locator('#token-save').click()
    expect(page.locator('#notice')).to_contain_text('보존')
    page.locator('#site-map-svg [data-place="NW"]').click()
    expect(page.locator('#place-name')).to_have_value('Unsaved local name')
    assert store.draft_view()['map'] is None or all(
        place['name'] != 'Unsaved local name' for place in store.draft_view()['map']['places'])
    assert not [call for call in robot.calls if call[0] in {'navigation_goal', 'estop'}]
