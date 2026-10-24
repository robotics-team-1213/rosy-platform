"""Integrated Work reads and explicit stop requests in real Chromium; HTTP evidence is synthetic."""
import json

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
PREFIX = "/api/fleet/control-unit"


def unit(identity, parent, **changes):
    return {"unit_id": identity, "parent": parent, "availability": "AVAILABLE", "sampled_at": "2026-10-24T00:00:00Z",
            "age_s": 0.0, "robots_total": 0, "robots_online": 0, "tasks_active": 0, "map": None,
            "dispatch": {"authority_epoch": 3, "generation": 7}, "error": None, "stop_pending": 0, **changes}


def integrated_api(role="operator"):
    map_ref = {"map_id": "_site", "version": 2, "frame": "unit_local"}
    overview = {"unit_id": "R", "config_revision": "v1", "units": [
        unit("R", None), unit("A", "R"), unit("A1", "A", robots_total=1, robots_online=1, tasks_active=1, map=map_ref),
        unit("B", "R", availability="UNAVAILABLE", age_s=None, dispatch=None, error="UNAVAILABLE")]}
    detail = {"unit_id": "A1", "config_revision": "v1", "availability": "AVAILABLE",
              "sampled_at": "2026-10-24T00:00:00Z", "age_s": 0.0, "robots": [
                  {"robot_id": "a1", "online": True, "state_age_s": 0.0, "mode": None, "battery_percent": 72.0,
                   "estop": False, "pose": None, "evidence": {"battery": "fresh", "safety": "fresh", "pose": "unavailable"}}],
              "tasks": [{"task_id": "owned-task", "robot_id": "a1", "status": "QUEUED", "updated_at": "2026-10-24T00:00:00Z"}],
              "tasks_truncated": True, "map": map_ref, "dispatch": {"authority_epoch": 3, "generation": 7}}
    api = {**API, "/api/fleet/session": {"principal_id": "bob", "role": role},
           PREFIX: {"unit_id": "R", "config_revision": "v1", "parent": None, "children": ["A", "B"], "resources": []},
           PREFIX + "/delegations": {"delegations": []}, PREFIX + "/overview": overview,
           PREFIX + "/stops": {"unit_id": "R", "config_revision": "v1", "stops": []},
           "/api/fleet/work": {"rows": [], "kinds": [], "observed_at": "2026-10-24T00:00:00Z",
                               "tasks_available": True, "missions_available": False, "truncated_sources": []}}
    for identity in ["R", "A", "B"]:
        api[PREFIX + "/units/" + identity] = {**detail, "unit_id": identity, "robots": [], "tasks": [], "map": None}
    api[PREFIX + "/units/A1"] = detail
    api[PREFIX + "/units/A1/map"] = {"unit_id": "A1", "config_revision": "v1", "map": map_ref,
        "places": [{"id": "safe", "label": "<img src=x onerror=alert(1)>", "x": 0.0, "y": 0.0}],
        "lanes": [{"id": "lane", "points": [{"x": 0.0, "y": 0.0}, {"x": 2.0, "y": 1.0}]}]}
    return api


def stop_snapshot(body, local=False):
    return {"unit_id": "R", "origin_id": "R", "stop_id": body["stop_id"], "target_unit": body["target_unit"],
            "config_revision": "v1", "revision": 1, "results": [
                {"unit_id": "R" if local else "A", "state": "UNKNOWN" if local else "ACKNOWLEDGED",
                 "dispatch": {"authority_epoch": 3, "generation": 7}, "acknowledged_robots": 0,
                 "unknown_robots": 1 if local else 0, "omx_state": "UNKNOWN" if local else "LOCAL_LATCHED",
                 "physical_stop": "UNVERIFIED", "error": None}]}


@pytest.mark.parametrize("size", [(1366, 768), (390, 844), (320, 568)])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_integrated_units_owned_evidence_and_readonly_map_keep_local_stop_visible(site, size, theme):
    from playwright.sync_api import expect, sync_playwright
    api = integrated_api()
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], size=size)
        try:
            page.goto(site + "/console?view=work")
            page.evaluate("theme => window.RosyTheme.set(theme)", theme)
            page.clock.run_for(1500)
            panel = page.locator("#integrated-control")
            expect(panel).to_be_visible()
            expect(panel).to_contain_text("직접 상위 A")
            expect(panel).to_contain_text("상단 비상 정지는 이 관제의 직접 장치")
            expect(panel).to_contain_text("정보 없음")
            choose = panel.get_by_role("button", name="A1 · 직접 상위 A", exact=True)
            choose.click()
            expect(page.locator("#integrated-control-detail")).to_contain_text("a1")
            expect(page.locator("#integrated-control-detail")).to_contain_text("배터리 72% (최신)")
            expect(page.locator("#integrated-control-detail")).to_contain_text("위치 미확인 (정보 없음)")
            expect(page.locator("#integrated-control-detail")).to_contain_text("owned-task")
            expect(page.locator("#integrated-control-detail")).to_contain_text("이전 작업 더 있음")
            panel.get_by_role("button", name="선택 관제 지도 보기", exact=True).click()
            expect(panel.locator("svg[role=img]")).to_have_attribute("aria-label", "A1 관제 활성 지도 · 읽기 전용")
            expect(panel.locator("svg text")).to_have_text("<img src=x onerror=alert(1)>")
            expect(panel.locator("svg img")).to_have_count(0)
            expect(panel).to_contain_text("A1 · 지도 _site · 버전 2 · 관제 고유 좌표")
            choose.focus()
            page.locator("#work-refresh").evaluate("node => node.click()")
            page.clock.run_for(1000)
            expect(panel.get_by_role("button", name="A1 · 직접 상위 A", exact=True)).to_be_focused()
            api[PREFIX + "/units/A1"]["robots"][0]["evidence"]["battery"] = "unavailable"
            page.locator("#work-refresh").evaluate("node => node.click()")
            page.clock.run_for(1000)
            expect(page.locator("#integrated-control-detail")).to_contain_text("배터리 미확인 (정보 없음)")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("window.scrollTo(0, 0)")
            box = page.locator("#estop").bounding_box()
            assert box and box["height"] >= 48 and box["y"] + box["height"] <= size[1]
            _shot(page, f"integrated-control-{size[0]}-{theme}.png", full_page=True)
            api[PREFIX + "/units/A1/map"]["unit_id"] = "B"
            panel.get_by_role("button", name="선택 관제 지도 보기", exact=True).click()
            expect(panel).to_contain_text("활성 지도 조회 실패")
            expect(panel.locator("svg[role=img]")).to_have_count(0)
            assert not errors
        finally:
            browser.close()


def test_selected_subtree_stop_uses_only_its_fresh_fences_and_polling_never_reposts(site):
    from playwright.sync_api import expect, sync_playwright
    api, requests = integrated_api(), []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        def stops(route):
            if route.request.method == "GET":
                route.fulfill(json=api[PREFIX + "/stops"])
                return
            body = route.request.post_data_json
            requests.append(body)
            route.fulfill(json=stop_snapshot(body))
        page.route("**/api/fleet/control-unit/stops", stops)
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            panel = page.locator("#integrated-control")
            panel.get_by_role("button", name="B · 직접 상위 R", exact=True).click()
            expect(page.locator("#integrated-stop")).to_be_disabled()
            panel.get_by_role("button", name="A · 직접 상위 R", exact=True).click()
            page.locator("#integrated-stop").click()
            expect(page.locator("#integrated-stop-results")).to_contain_text("A · 요청 수신")
            expect(page.locator("#integrated-stop-results")).to_contain_text("물리 정지 미확인")
            expect(page.locator("#integrated-stop-results li")).to_have_attribute("data-physical-stop", "UNVERIFIED")
            assert len(requests) == 1
            body = requests[0]
            assert body["target_unit"] == "A" and body["config_revision"] == "v1"
            assert body["expected_controls"] == {"A": {"authority_epoch": 3, "generation": 7},
                                                "A1": {"authority_epoch": 3, "generation": 7}}
            assert "actor" not in body
            page.clock.run_for(12000)
            page.locator("#work-refresh").click()
            page.clock.run_for(1000)
            assert len(requests) == 1
            assert not errors
        finally:
            browser.close()


def test_unknown_stop_reply_is_read_only_on_manual_check_and_storage_free_reload(site):
    from playwright.sync_api import expect, sync_playwright
    api, requests = integrated_api(), []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        def lost_reply(route):
            body = route.request.post_data_json
            requests.append(body)
            snapshot = stop_snapshot(body, local=True)
            api[PREFIX + "/stops/R/" + body["stop_id"]] = snapshot
            api[PREFIX + "/stops"]["stops"] = [{"origin_id": "R", "stop_id": body["stop_id"], "target_unit": "R",
                "config_revision": "v1", "revision": 1, "incomplete": True,
                "local_reconciliation_required": True, "updated_at": "2026-10-24T00:00:00Z"}]
            route.abort("failed")
        page.route("**/api/fleet/control-unit/stops", lambda route: lost_reply(route)
                   if route.request.method == "POST" else route.fulfill(json=api[PREFIX + "/stops"]))
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            page.locator("#integrated-stop").click()
            panel = page.locator("#integrated-control")
            expect(panel).to_contain_text("정지 요청 결과 미확인")
            page.clock.run_for(10000)
            assert len(requests) == 1
            panel.get_by_role("button", name="같은 정지 기록 확인", exact=True).click()
            expect(page.locator("#integrated-stop-results")).to_contain_text("전달 결과 미확인")
            page.evaluate("sessionStorage.clear(); localStorage.clear()")
            page.reload()
            page.clock.run_for(1500)
            page.locator("#integrated-control summary").filter(has_text="이 관제의 정지 요청 기록").click()
            page.locator("#integrated-stop-history").get_by_role("button").click()
            expect(page.locator("#integrated-stop-results")).to_contain_text("전달 결과 미확인")
            assert len(requests) == 1
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("role", ["operator", "viewer"])
@pytest.mark.parametrize("state", ["UNKNOWN", "PARTIAL"])
def test_local_history_reconciliation_requires_named_operator_and_both_typed_attestations(site, role, state):
    from playwright.sync_api import expect, sync_playwright
    api, posts = integrated_api(role), []
    body = {"stop_id": "existing-stop", "target_unit": "R"}
    result = stop_snapshot(body, local=True)
    result["results"][0]["state"] = state
    api[PREFIX + "/stops/R/existing-stop"] = result
    api[PREFIX + "/stops"]["stops"] = [{"origin_id": "R", "stop_id": "existing-stop", "target_unit": "R",
        "config_revision": "v1", "revision": 1, "incomplete": True,
        "local_reconciliation_required": True, "updated_at": "2026-10-24T00:00:00Z"}]
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers={
            PREFIX + "/stops/R/existing-stop/reconcile": (200, result)})
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            page.locator("#integrated-control summary").filter(has_text="이 관제의 정지 요청 기록").click()
            if role == "viewer":
                panel = page.locator("#integrated-control")
                panel.get_by_role("button", name="A1 · 직접 상위 A", exact=True).click()
                expect(page.locator("#integrated-control-detail")).to_contain_text("a1")
                panel.get_by_role("button", name="선택 관제 지도 보기", exact=True).click()
                expect(panel.locator("svg[role=img]")).to_have_count(1)
            page.locator("#integrated-stop-history").get_by_role("button").click()
            form = page.locator("#integrated-reconcile")
            expect(form).to_be_visible()
            form.locator("summary").click()
            save = form.get_by_role("button", name="이 관제의 재시운전 확인 기록", exact=True)
            if role == "viewer":
                expect(save).to_be_disabled()
                expect(page.locator("#integrated-stop")).to_be_disabled()
                expect(page.locator("#integrated-control").get_by_role("button", name="같은 정지 기록 확인", exact=True)).to_be_enabled()
                assert not posts
                return
            save.click()
            assert not posts
            page.get_by_label("기존 정지 전송 연결을 종료했습니다", exact=True).check()
            page.get_by_label("영향받은 receiver의 재시운전을 확인했습니다", exact=True).check()
            page.get_by_label("전송 종료·재시운전 확인 근거", exact=True).fill("기존 연결 종료 및 영향 receiver 재시운전 현장 확인")
            save.click()
            expect(page.locator("#integrated-control")).to_contain_text("요청 결과를 기록했습니다")
            assert len(posts) == 1
            payload = json.loads(posts[0][1])
            assert posts[0][0] == PREFIX + "/stops/R/existing-stop/reconcile"
            assert payload == {"expected_generation": 7, "receiver_channels_terminated": True,
                               "receivers_recommissioned": True, "affected_units": ["R"],
                               "evidence": "기존 연결 종료 및 영향 receiver 재시운전 현장 확인"}
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("overview_epoch,overview_generation,receipt_epoch,receipt_generation,stale,expected", [
    (3, 7, 3, 8, False, 8), (3, 8, 3, 7, False, 8),
    (4, 8, 3, 9, False, 8), (3, 7, 3, 8, True, None),
])
def test_local_reconciliation_uses_observed_generation_without_crossing_authority(
        site, overview_epoch, overview_generation, receipt_epoch, receipt_generation, stale, expected):
    from playwright.sync_api import expect, sync_playwright
    api, posts = integrated_api(), []
    root = api[PREFIX + "/overview"]["units"][0]
    root["dispatch"] = {"authority_epoch": overview_epoch, "generation": overview_generation}
    if stale:
        root.update(availability="STALE", age_s=6.0)
    result = stop_snapshot({"stop_id": "generation-stop", "target_unit": "R"}, local=True)
    result["results"][0]["dispatch"] = {"authority_epoch": receipt_epoch, "generation": receipt_generation}
    path = PREFIX + "/stops/R/generation-stop"
    api[path] = result
    api[PREFIX + "/stops"]["stops"] = [{"origin_id": "R", "stop_id": "generation-stop", "target_unit": "R",
        "config_revision": "v1", "revision": 1, "incomplete": True,
        "local_reconciliation_required": True, "updated_at": "2026-10-25T00:00:00Z"}]
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers={path + "/reconcile": (200, result)})
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            page.locator("#integrated-control summary").filter(has_text="이 관제의 정지 요청 기록").click()
            page.locator("#integrated-stop-history").get_by_role("button").click()
            form = page.locator("#integrated-reconcile")
            expect(form).to_be_visible()
            form.locator("summary").click()
            save = form.get_by_role("button", name="이 관제의 재시운전 확인 기록", exact=True)
            if expected is None:
                expect(save).to_be_disabled()
                assert not posts
                return
            page.get_by_label("기존 정지 전송 연결을 종료했습니다", exact=True).check()
            page.get_by_label("영향받은 receiver의 재시운전을 확인했습니다", exact=True).check()
            page.get_by_label("전송 종료·재시운전 확인 근거", exact=True).fill("합성 fixture의 전송 종료와 receiver 재시운전 확인")
            save.click()
            expect(page.locator("#integrated-control")).to_contain_text("요청 결과를 기록했습니다")
            assert len(posts) == 1 and json.loads(posts[0][1])["expected_generation"] == expected
            assert posts[0][0] == path + "/reconcile" and not errors
        finally:
            browser.close()


def test_pagehide_clears_owned_details_and_does_not_restart_a_write(site):
    from playwright.sync_api import expect, sync_playwright
    api, posts = integrated_api(), []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            panel = page.locator("#integrated-control")
            panel.get_by_role("button", name="A1 · 직접 상위 A", exact=True).click()
            expect(page.locator("#integrated-control-detail")).to_contain_text("owned-task")
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
            expect(panel).to_be_hidden()
            expect(page.locator("#integrated-control-detail")).to_have_text("")
            expect(page.locator("#integrated-stop-results")).to_be_empty()
            assert not posts
            assert not errors
        finally:
            browser.close()
