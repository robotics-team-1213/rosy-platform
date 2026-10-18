"""D-540 3 / 7 queue decisions, one scroll and folded cards in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves the console and its asset allowlist; every /api call is a fake answer: rosy_01 is
stuck and asks, rosy_02's trip waits at a place for a changed route, rosy_03 is nominal, rosy_04 is offline.
No robot moves. ROSY_SHOT_DIR keeps the screenshots.
"""

import base64
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, launch_options, safe_listener

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
WIDE = [(1920, 1080), (1440, 900), (1024, 768)]
DECISIONS = ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


def _robot(robot_id, online=True, safety=None, **extra):
    battery = {"evidence": "fresh", "sample_age_s": 0.2, "stale_after_s": 5, "percent": 80, "level": "ok",
               "charging_state": "unknown"}
    row = {"robot_id": robot_id, "online": online, "goal": None, "queued": None, "yielding": None, "error": None,
           "power_health_age_s": 0.3, "power_health": {"battery": battery},
           "state": {"robot_id": robot_id, "mode": "LINE_FOLLOW", "navigation": "IDLE",
                     "pose": {"x": 1.0, "y": 1.0, "yaw": 0.0}, "battery": {"percent": 80},
                     "safety": {"estop": False} if safety is None else safety}}
    row.update(extra)
    return row


STUCK = {"robot_id": "rosy_01", "stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING",
         "held_s": 4.0, "attempts": 0, "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 11.0,
         "front_clearance_m": 0.12, "rear_clearance_m": 0.31, "turn_clearance_m": 0.09, "preview_seq": 812,
         "robot_online": True, "observed_age_s": 0.0, "fleet_answer": None}
HELD = {"trip_id": "t-rosy_02", "plan_id": "t-rosy_02", "robot_id": "rosy_02", "state": "running", "reason": None,
        "detail": {}, "map_version": None, "segment_index": 0, "lap": 1,
        "plan": {"segments": [], "places": [], "actions": []},
        "hold": {"reason": "replan", "map_version": 4, "length_m": 3.2, "eta_s": 40,
                 "plan": {"segments": [], "places": ["a", "b"], "actions": []}}}
OFFLINE = _robot("rosy_04", online=False, error={"reachable": False, "code": "ConnectError"})
OFFLINE["state"] = None
API = {
    "/api/fleet/session": {"principal_id": "bob", "role": "operator"},
    "/api/fleet/incidents": {"reports": []},
    "/api/fleet/state": {"fleet": {"name": "site", "online": 3, "total": 4}, "ts": 0.0,
                         "robots": [_robot("rosy_01", line_stuck=STUCK), _robot("rosy_02"), _robot("rosy_03"),
                                    OFFLINE]},
    "/api/fleet/traffic": {"map_version": None, "block_length_m": {}, "units": [], "loop_capacity": [],
                           "wait_cycle": None, "robots": [{"robot_id": "rosy_02", "authority_end_m": 0.5,
                                                           "waiting_for": [], "lap": 1, "trip_state": "running"}]},
    "/api/fleet/trips": {"running": HELD, "trips": [HELD], "open": [HELD]},
    "/api/fleet/formation": {"active": False, "state": "IDLE", "leader": None, "formation": None, "spacing": None,
                             "assignment": {}, "reason": None, "pending_triggers": [], "stream_evidence": {},
                             "relay": None},
}


def test_incident_report_shows_source_evidence_and_records_review(site):
    from playwright.sync_api import expect, sync_playwright

    report = {"schema": "rosy.incident.v1", "id": "line_stuck:rosy_01:stuck-abc",
              "stuck_id": "stuck-abc", "classification": "line_stuck", "robot_ids": ["rosy_01"],
              "opened_at": "2026-10-10T05:00:00+00:00", "closed_at": None,
              "evidence": {"core": {"cause": "obstacle_ahead", "phase_at_open": "ASKING",
                                    "held_s_max": 12, "attempts_max": 1},
                           "fleet": {"close_reason": None, "pose_state": "LOCALIZED", "pose_age_s": 0.4,
                                     "resolved_by": None},
                           "rosy_cam": {"source_id": "ceiling_north", "seq": 21,
                                        "captured_at": 1791608400},
                           "ai_facts": [{"kind": "stalled", "stage": "shadow", "confidence": 0.8},
                                        {"kind": "incident_context", "stage": "shadow", "confidence": 0.45,
                                         "value": {"cause_draft": "obstacle", "missing": ["interpreted_front_image"],
                                                   "support": [{"source": "core_sensor", "field": "front_clearance_m",
                                                                "value": 0.12}]}}],
                           "front_image": {"status": "not_retained"}},
              "actions": [], "reviews": []}
    posts = []
    traffic = {"schema": "rosy.incident.v1", "id": "ai_fact:17", "classification": "wait_cycle_confirmed",
               "robot_ids": ["rosy_01", "rosy_02"], "opened_at": "2026-10-10T05:00:00+00:00",
               "evidence": {"ai_fact": {"fact_row": 17, "kind": "wait_cycle_confirmed",
                                        "source": "analyzer:traffic_watch@1", "stage": "shadow",
                                        "confidence": 0.7, "value": {"fleet_agrees": False},
                                        "evidence": {"fleet_wait_cycle": None}}},
               "actions": [], "reviews": []}
    traffic2 = {**traffic, "id": "ai_fact:18",
                "evidence": {"ai_fact": {**traffic["evidence"]["ai_fact"], "fact_row": 18}}}
    api = {**API, "/api/fleet/incidents": {"reports": [report], "traffic_reports": [traffic, traffic2]},
           "/api/fleet/enrollment/robots": {"robots": [{"robot_id": "rosy_01", "hostname": "rosy-pinky-demo"}]},
           "/api/fleet/discovery": {"scanner_online": True, "devices": []}}
    answers = {"/api/fleet/incidents/rosy_01/stuck-abc/review": (200, {"reviewed": True}),
               "/api/fleet/incidents/facts/17/review": (200, {"reviewed": True})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        item = page.locator("#incident-list li")
        expect(item).to_have_count(1)
        records = page.locator(".incident-panel")
        expect(records).not_to_be_visible()
        page.get_by_role("tab", name="기록·근거").click()
        expect(page.locator("#incident-status")).to_contain_text("최근 라인 정지 1건")
        expect(records).to_be_visible()
        expect(item.locator(":scope > details > summary")).to_contain_text("rosy-pinky-demo (rosy_01)")
        expect(item.locator(":scope > details > summary")).to_contain_text("앞 물체로 멈춤")
        expect(item.locator("time")).to_have_attribute("datetime", "2026-10-10T05:00:00.000Z")
        assert item.evaluate("node => getComputedStyle(node).borderLeftWidth") == "0px"
        assert records.evaluate("node => node.closest('[role=tabpanel]').id") == "context-evidence"
        item.locator(":scope > details > summary").click()
        assert "interpreted_front_image" not in item.inner_text()
        expect(item.locator("details details")).not_to_have_attribute("open", "")
        item.locator("details details > summary").click()
        expect(item).to_contain_text("Rosy Cam: ceiling_north")
        expect(item).to_contain_text("AI PC 원인 초안: 전방 장애물")
        expect(item).to_contain_text("interpreted_front_image")
        expect(item).to_contain_text("AI 참고: stalled (shadow, 80%)")
        expect(item).to_contain_text("이미지는 보존되지 않음")
        item.locator("select").select_option("obstacle")
        item.locator("input").fill("현장 상자 확인")
        item.locator("ui-button[type=submit]").click()
        assert posts[-1][0] == "/api/fleet/incidents/rosy_01/stuck-abc/review"
        assert json.loads(posts[-1][1]) == {"root_cause": "obstacle", "note": "현장 상자 확인"}
        expect(page.locator("#incident-traffic-list li")).to_have_count(2)
        fact = page.locator("#incident-traffic-list li").first
        fact.locator(":scope > details > summary").click()
        assert "fleet_wait_cycle" not in fact.inner_text()
        expect(fact).to_contain_text("AI 단독 대기 순환 판단")
        fact.locator("select").select_option("traffic_wait")
        fact.locator("ui-button[type=submit]").click()
        assert posts[-1][0] == "/api/fleet/incidents/facts/17/review"
        with page.expect_download() as download_info:
            page.locator("#incident-export").click()
        download = download_info.value
        assert download.suggested_filename == "rosy-incidents.json"
        assert json.loads(Path(download.path()).read_text(encoding="utf-8"))["traffic_reports"][0]["id"] == "ai_fact:17"
        assert not errors
        browser.close()

@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
def test_records_area_raises_incidents_into_the_body_and_the_judgment_to_the_side(site, size):
    """D-741 8 — /console?view=records: 사건은 본문, 연 사건의 원인과 조치는 오른쪽 칸, 하위 탐색이 화면을 고른다."""
    from playwright.sync_api import expect, sync_playwright

    def report(stuck, closed, reviews):
        return {"id": f"line_stuck:rosy_01:{stuck}", "classification": "line_stuck", "robot_ids": ["rosy_01"],
                "stuck_id": stuck, "opened_at": "2026-10-10T05:00:00+00:00", "closed_at": closed,
                "actions": [], "reviews": reviews,
                "evidence": {"core": {}, "fleet": {}, "rosy_cam": None, "ai_facts": [],
                             "front_image": {"status": "not_retained"}}}
    fact = {"id": "ai_fact:17", "classification": "stalled", "robot_ids": ["rosy_01"],
            "opened_at": "2026-10-10T05:00:00+00:00", "actions": [], "reviews": [],
            "evidence": {"ai_fact": {"fact_row": 17, "kind": "stalled", "source": "analyzer:traffic_watch@1",
                                     "stage": "shadow", "confidence": 0.7, "value": {}, "evidence": {}}}}
    done = [{"root_cause": "obstacle", "note": "상자", "principal_id": "bob"}]
    reports = [report("open-new", None, []), report("closed-new", "2026-10-10T05:10:00+00:00", []),
               report("closed-done", "2026-10-10T05:10:00+00:00", done)]
    # Enough unreviewed rows on the one robot that, below 64rem, the judgment seat starts off-screen.
    reports += [report(f"more-{index}", "2026-10-10T05:10:00+00:00", []) for index in range(12)]
    api = {**API, "/api/fleet/incidents": {"reports": reports, "traffic_reports": [fact]}}
    answers = {f"/api/fleet/incidents/rosy_01/{stuck}/review": (200, {"reviewed": True}) for stuck in ("open-new", "closed-new")}
    posts = []

    def screen(show):
        page.goto(site + "/console?view=records" + (f"&show={show}" if show else ""))
        page.clock.run_for(2000)
        return page.get_by_role("navigation", name="기록 화면", exact=True)

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers, size=size)
        try:
            nav = screen("")
            rows = page.locator("#incident-list > li")
            expect(rows).to_have_count(14)  # 검토할 사건: 검토 기록이 없는 것만
            expect(page.locator("#incident-status")).to_contain_text("최근 라인 정지 14건")
            assert nav.locator("a").all_inner_texts() == ["검토할 사건", "열린 사건", "닫힌 사건", "AI 상황 사실", "관제 기록"]
            assert nav.locator('a[aria-current="page"]').all_inner_texts() == ["검토할 사건"]
            assert [text.strip() for text in page.locator('.doc-tabs a[aria-current="page"]').all_inner_texts()] == ["기록"]
            expect(page.locator('.ui-subnav[data-area="work"]')).to_be_hidden()
            panel, side = page.locator(".incident-panel"), page.locator("#incident-side")
            expect(panel).to_be_visible()
            expect(side).to_be_visible()
            expect(side.locator(".hint")).to_be_visible()
            expect(page.locator(".queues-panel")).to_be_visible()
            expect(page.locator('[aria-labelledby="map-heading"]')).to_be_hidden()
            expect(page.locator("#incident-traffic-list")).to_be_hidden()
            assert panel.evaluate("node => !node.closest('[role=tabpanel]')")
            assert side.evaluate("node => node.closest('[role=tabpanel]').id") == "context-evidence"
            if size[0] >= 1024:
                body, right = panel.bounding_box(), side.bounding_box()
                assert body["x"] + body["width"] <= right["x"], (body, right)
            first = rows.first
            first.locator(":scope > details > summary").click()
            expect(first).to_contain_text("해소 확인")
            expect(side).to_contain_text("담당 인수: 아직 없음")
            expect(side).to_contain_text("사람 검토: 아직 없음")
            expect(side.locator(".hint")).to_be_hidden()
            assert first.locator("form").count() == 0 and "사람 검토" not in first.inner_text()
            heading = page.locator("#incident-judgment h3")
            expect(heading).to_contain_text("rosy_01")
            expect(heading).to_contain_text("사건 기록 · 종료 미확인")  # A: the open incident
            expect(heading).to_contain_text("시작 ")
            seat = page.locator("#incident-judgment")
            if size[0] < 1024:  # the form sits under the whole list: opening a fold brings it into view
                expect(seat).to_be_in_viewport()
            # ArrowDown on the fold's summary is not roster navigation: the review form stays in front.
            first.locator(":scope > details > summary").press("ArrowDown")
            expect(page.locator("#context-evidence")).to_be_visible()
            expect(page.get_by_role("tab", name="기록·근거")).to_have_attribute("aria-selected", "true")
            # Two incidents of one robot, without <details name>: script closes A, the seat names B, the review posts B.
            assert page.locator("details[name]").count() == 0
            rows.nth(1).locator(":scope > details > summary").click()
            expect(first.locator(":scope > details")).not_to_have_attribute("open", "")
            expect(page.locator(".incident-row > details[open]")).to_have_count(1)
            expect(page.locator('#incident-judgment > [data-report-key="rosy_01|closed-new"]')).to_have_count(1)
            expect(heading).to_have_count(1)
            expect(heading).to_contain_text("과거 · 종료 기록 있음")  # B: the closed incident
            if size[0] < 1024:
                expect(seat).to_be_in_viewport()
            # A repaint keeps the seat on B and returns focus to B's control: both incidents' controls share one label.
            side.locator("select").focus()
            page.evaluate("""() => { window.oldSeat = document.querySelector('#incident-judgment > div');
                document.getElementById('incident-refresh').dispatchEvent(new Event('click')); }""")
            page.wait_for_function("""() => document.querySelector('#incident-judgment > div') !== window.oldSeat
                && document.activeElement.matches('#incident-judgment > [data-report-key="rosy_01|closed-new"] select')""")
            side.locator("select").select_option("obstacle")
            side.locator("input").fill("현장 상자 확인")
            side.locator("ui-button[type=submit]").click()
            assert posts[-1][0] == "/api/fleet/incidents/rosy_01/closed-new/review"
            assert json.loads(posts[-1][1]) == {"root_cause": "obstacle", "note": "현장 상자 확인"}
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["height"] >= 48 and stop["y"] + stop["height"] <= size[1]
            _shot(page, f"records-review-{size[0]}.png", full_page=True)
            for show, count in (("open", 1), ("closed", 14)):
                nav = screen(show)
                expect(page.locator("#incident-list > li")).to_have_count(count)
                assert len(nav.locator('a[aria-current="page"]').all_inner_texts()) == 1
            nav = screen("nonsense")  # an unknown screen falls back to the default list and marks it
            expect(page.locator("#incident-list > li")).to_have_count(14)
            assert nav.locator('a[aria-current="page"]').all_inner_texts() == ["검토할 사건"]
            # The filter runs over a capped fetch: a full answer says so in the count line.
            api["/api/fleet/incidents"] = {"reports": [report(f"cap-{index}", None, done if index else []) for index in range(100)],
                                           "traffic_reports": []}
            screen("")
            expect(page.locator("#incident-status")).to_contain_text("최근 라인 정지 100건 중 1건")
            api["/api/fleet/incidents"] = {"reports": reports, "traffic_reports": [fact]}
            nav = screen("facts")
            expect(page.locator("#incident-traffic-list > li")).to_have_count(1)
            expect(page.locator("#incident-list")).to_be_hidden()
            assert nav.locator('a[aria-current="page"]').all_inner_texts() == ["AI 상황 사실"]
            screen("log")
            expect(page.locator("#log-panel")).to_be_visible()
            assert page.locator("#log-panel").evaluate("node => !node.closest('[role=tabpanel]')")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()


# Is the element itself what a pointer meets at its centre (not a sticky bar or a neighbour laid over it)?
ON_TOP = """node => { const r = node.getBoundingClientRect();
  return node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }"""
# Text below 4.5:1 (3:1 from 24px) against the surfaces painted under it. A 1px canvas resolves any CSS colour
# (rgb, color(srgb ...), alpha) the way the page composites it.
LOW_CONTRAST = """selector => {
  const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const paint = colours => { ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 1, 1);
    for (const colour of colours) { ctx.fillStyle = colour; ctx.fillRect(0, 0, 1, 1); }
    return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map(v => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); };
  const lum = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const low = [];
  let read = 0;
  for (const node of document.querySelectorAll(selector)) {
    if (!node.checkVisibility({visibilityProperty: true}) || node.closest('[disabled]')) continue;
    if (![...node.childNodes].some(child => child.nodeType === 3 && child.textContent.trim())) continue;
    const under = [];
    read += 1;
    for (let at = node; at; at = at.parentElement) under.unshift(getComputedStyle(at).backgroundColor);
    const style = getComputedStyle(node), ground = lum(paint(under)), ink = lum(paint([...under, style.color]));
    const ratio = (Math.max(ground, ink) + 0.05) / (Math.min(ground, ink) + 0.05);
    if (ratio < (parseFloat(style.fontSize) >= 24 ? 3 : 4.5))
      low.push(`${node.tagName.toLowerCase()}#${node.id}.${node.className} ${ratio.toFixed(2)} "${node.textContent.trim().slice(0, 16)}"`);
  }
  return {read, low};
}"""


@pytest.mark.parametrize("size,theme", [((320, 568), "dark"), ((320, 568), "light"), ((390, 844), "light"),
                                        ((1366, 768), "light"), ((1024, 768), "dark"), ((1100, 800), "light")])
def test_records_area_fits_the_narrowest_phone_and_reads_in_the_light_theme(site, size, theme):
    """D-741 8 at 320x568 and in the light theme: nothing runs off sideways, the stop is in view with nothing over
    it, every records screen can be reached from the sub-nav, and the judgment seat's heading and review form can
    be read and used."""
    from playwright.sync_api import expect, sync_playwright

    width, height = size
    reports = [{"id": f"line_stuck:rosy_01:s-{index}", "classification": "line_stuck", "robot_ids": ["rosy_01"],
                "stuck_id": f"s-{index}", "opened_at": "2026-10-10T05:00:00+00:00", "closed_at": None, "actions": [],
                "reviews": [], "evidence": {"core": {}, "fleet": {}, "rosy_cam": None, "ai_facts": [],
                                             "front_image": {"status": "not_retained"}}} for index in range(8)]
    api = {**API, "/api/fleet/incidents": {"reports": reports, "traffic_reports": []}}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts,
                                      {"/api/fleet/incidents/rosy_01/s-0/review": (200, {"reviewed": True})}, size=size)
        try:
            page.goto(site + "/console?view=records")
            ground = {name: page.evaluate("""theme => { document.documentElement.dataset.theme = theme;
                return getComputedStyle(document.body).backgroundColor; }""", name) for name in ("dark", theme)}
            assert (ground[theme] != ground["dark"]) == (theme == "light"), ground  # the theme is really the one named
            page.clock.run_for(2000)
            links = page.get_by_role("navigation", name="기록 화면", exact=True).locator("a")
            expect(links).to_have_count(5)
            reach = []
            for index in range(5):
                link = links.nth(index)
                link.scroll_into_view_if_needed()
                box = link.bounding_box()
                reach.append((round(box["x"]), round(box["width"]), round(box["height"])))
                # The row scrolls on whole pixels, so an entry brought to its edge may sit a fraction past it.
                assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1 and box["height"] >= 44, (index, box)
                assert link.evaluate(ON_TOP), (index, box)
            page.locator("#incident-list > li").first.locator(":scope > details > summary").click()
            seat = page.locator("#incident-judgment")
            heading = seat.locator("h3")
            expect(heading).to_contain_text("rosy_01")
            if width < 1024:
                expect(seat).to_be_in_viewport()
            controls = {name: seat.locator(selector) for name, selector in
                        (("heading", "h3"), ("cause", "select"), ("note", "input"), ("save", "ui-button[type=submit]"))}
            boxes = {}
            for name, control in controls.items():
                control.scroll_into_view_if_needed()
                box = boxes[name] = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width and box["width"] >= 144, (name, box)
                assert control.evaluate("node => node.scrollWidth <= node.clientWidth + 1"), (name, box)
                assert control.evaluate(ON_TOP), (name, box)
            order = sorted(boxes.values(), key=lambda box: (box["y"], box["x"]))
            for above, below in zip(order, order[1:]):  # no control lies over the next
                assert above["y"] + above["height"] <= below["y"] + 1 or above["x"] + above["width"] <= below["x"] + 1, boxes
            stop = page.locator("#estop")
            box = stop.bounding_box()
            assert box["height"] >= 48 and box["y"] >= 0 and box["y"] + box["height"] <= height, box
            assert box["x"] >= 0 and box["x"] + box["width"] <= width and stop.evaluate(ON_TOP), box
            overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
            seats = ".ui-subnav *, .doc-tabs *, .incident-panel *, #incident-side *"
            contrast = page.evaluate(LOW_CONTRAST, seats)
            print(json.dumps({"size": size, "theme": theme, "subnav": reach, "seat": boxes, "stop": box,
                              "overflow": overflow, "contrast": contrast}, ensure_ascii=False))
            assert overflow <= 0, overflow
            assert contrast["read"] >= 20 and contrast["low"] == [], contrast
            # The measure itself: grey on grey in the seat heading must be reported, in a colour syntax tokens resolve to.
            heading.evaluate("node => { node.style.color = 'color(srgb 0.5 0.5 0.5)'; node.style.backgroundColor = 'rgb(140 140 140)'; }")
            assert any(line.startswith("h3") for line in page.evaluate(LOW_CONTRAST, seats)["low"])
            heading.evaluate("node => { node.style.color = ''; node.style.backgroundColor = ''; }")
            controls["cause"].select_option("obstacle")
            controls["note"].fill("현장 상자 확인")
            controls["save"].click()
            for _ in range(50):  # the request leaves on the real network clock
                page.clock.run_for(100)
                if posts:
                    break
            assert posts and posts[-1][0] == "/api/fleet/incidents/rosy_01/s-0/review", posts
            _shot(page, f"records-{theme}-{width}.png", full_page=True)
            assert not errors
        finally:
            browser.close()


# Elements that scroll on their own right now (the document is reported separately).
SCROLLERS = """() => [...document.querySelectorAll('body *')].filter((node) => {
  const y = getComputedStyle(node).overflowY;
  return (y === 'auto' || y === 'scroll') && node.scrollHeight > node.clientHeight + 1;
}).map((node) => node.id || node.className)"""


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_context_tabs_keep_map_and_current_intervention_available(site, theme):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        for width, height in [(1920, 1080), (1366, 768), (390, 844), (320, 568)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1100)
            status = page.get_by_role("tab", name="로봇·작업")
            status.click()
            map_before = page.locator("#map-stage").bounding_box()
            expect(page.locator("#context-status")).to_be_visible()
            expect(page.locator("#context-evidence")).not_to_be_visible()
            page.evaluate("scrollTo(0, 0)")
            _shot(page, f"context-status-{theme}-{width}x{height}.png")
            status.focus()
            status.press("ArrowRight")
            expect(page.get_by_role("tab", name="알림", exact=True)).to_be_focused()
            expect(page.locator("#context-inbox")).to_be_visible()
            page.get_by_role("tab", name="알림", exact=True).press("ArrowRight")
            expect(page.get_by_role("tab", name="기록·근거")).to_be_focused()
            expect(page.locator("#context-evidence")).to_be_visible()
            expect(page.locator("#context-status")).not_to_be_visible()
            page.evaluate("scrollTo(0, 0)")
            _shot(page, f"context-evidence-{theme}-{width}x{height}.png")
            page.get_by_role("tab", name="기록·근거").press("End")
            expect(page.locator("#context-tools")).to_be_visible()
            assert page.locator("#context-tools .signals").evaluate("node => getComputedStyle(node).gridColumnStart") == "1"
            page.get_by_role("tab", name="운영 도구").press("Home")
            expect(status).to_be_focused()
            expect(page.locator("#context-status")).to_be_visible()
            map_after = page.locator("#map-stage").bounding_box()
            assert map_after["width"] == pytest.approx(map_before["width"], abs=1)
            assert map_after["height"] == pytest.approx(map_before["height"], abs=1)
            assert page.locator(".queues-panel").evaluate("node => !node.closest('[role=tabpanel]')")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["height"] >= 48 and stop["y"] + stop["height"] <= height
            if width >= 1024:
                left = page.locator(".console-primary").bounding_box()
                right = page.locator(".console-secondary").bounding_box()
                assert left["width"] / right["width"] == pytest.approx(2, abs=0.05)
                assert page.locator("#roster-heading").evaluate("node => getComputedStyle(node).fontSize") == "16px"
                assert page.locator("#map-heading").evaluate("node => getComputedStyle(node).fontSize") == "20px"
        assert not errors
        browser.close()


@pytest.mark.parametrize("width", [320, 390, 1366])
def test_current_evidence_is_folded_and_keeps_keyboard_context_across_poll(site, width):
    from playwright.sync_api import expect, sync_playwright

    stuck = {**STUCK, "ai": {"state": "present"}, "ai_facts": [{"kind": "new_fact_kind", "source": "analyzer:test", "confidence": 0.8,
                                       "evidence": {"wire_marker": "source_preserved"}}]}
    api = {**API, "/api/fleet/state": {**API["/api/fleet/state"], "robots": [_robot("rosy_01", line_stuck=stuck)]}}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        page.set_viewport_size({"width": width, "height": 844 if width < 1000 else 768})
        item = page.locator('.stuck-item[data-robot-id="rosy_01"]')
        expect(item).to_be_visible()
        assert "wire_marker" not in item.inner_text()
        expect(item.locator('ui-button[data-decision="RESUME"]')).to_be_visible()
        title = item.locator('[data-focus-key="evidence-summary"]')
        title.focus()
        title.press("Enter")
        expect(item.locator('[data-focus-key="evidence"]')).to_have_attribute("open", "")
        assert "wire_marker" not in item.inner_text()
        diagnostic = item.locator('[data-focus-key="diagnostics-summary"]')
        diagnostic.focus()
        diagnostic.press("Enter")
        assert "wire_marker" in item.inner_text()
        stuck["attempts"] = 1  # A changed state rebuilds the current row.
        page.clock.run_for(3500)
        expect(item.locator('[data-focus-key="evidence"]')).to_have_attribute("open", "")
        expect(item.locator('[data-focus-key="diagnostics"]')).to_have_attribute("open", "")
        expect(item.locator('[data-focus-key="diagnostics-summary"]')).to_be_focused()
        stuck["stuck_id"] = "replacement-stuck"
        page.clock.run_for(3500)
        expect(item.locator('[data-focus-key="evidence"]')).not_to_have_attribute("open", "")
        expect(item.locator('[data-focus-key="diagnostics"]')).not_to_have_attribute("open", "")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not posts and not errors
        browser.close()


def test_inbox_marks_read_without_resolving_and_shows_message_stages(site):
    from playwright.sync_api import expect, sync_playwright

    stuck = {**STUCK, "inquiry": {"version": "situation-inquiry-v1", "problem_id": STUCK["stuck_id"],
        "observations": {"cause": "obstacle_ahead"}},
        "ai_proposal": {"decision": "WAIT", "class": "accepted", "verdict": "forwarded", "outcome": "hold"},
        "fleet_answer": {"decision": "WAIT", "tier": "ai", "accepted": True, "outcome": "hold"}}
    api = {**API, "/api/fleet/state": {**API["/api/fleet/state"], "robots": [
        _robot("rosy_01", line_stuck=stuck), OFFLINE]}}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        entry = page.locator("#topbar-more")
        unread = entry.get_attribute("aria-label")
        entry.click()
        assert entry.get_attribute("aria-label") == unread
        button = page.locator("#fleet-inbox")
        assert "미확인 메시지 0개" not in button.get_attribute("aria-label")
        button.click()
        expect(page.locator("#context-inbox")).to_be_visible()
        expect(button).to_have_attribute("aria-label", "알림 창 · 미확인 메시지 0개")
        messages = page.locator("#inbox-messages")
        expect(messages).to_contain_text("로봇 문의 (CORE)")
        expect(messages).to_contain_text("AI 제안 대기")
        expect(messages).to_contain_text("CORE 수락 · 복구 완료는 별도 확인")
        expect(messages.locator("pre")).not_to_be_visible()
        assert "situation-inquiry-v1" not in messages.inner_text()
        messages.locator("li > details > summary").click()
        expect(messages.locator("pre")).not_to_be_visible()
        messages.locator("details details > summary").click()
        expect(messages.locator("pre")).to_contain_text("situation-inquiry-v1")
        page.get_by_role("tab", name="로봇·작업").click()
        page.clock.run_for(6000)
        expect(button).to_have_attribute("aria-label", "알림 창 · 미확인 메시지 0개")
        stuck["fleet_answer"] = {"decision": "RESUME", "tier": "ai", "accepted": False, "code": "EMERGENCY_ACTIVE"}
        page.clock.run_for(3000)
        assert "미확인 메시지 0개" not in button.get_attribute("aria-label")
        button.click()
        expect(messages).to_contain_text("CORE 거절 (EMERGENCY_ACTIVE)")
        assert messages.locator("li > details").get_attribute("open") is not None
        assert messages.locator("details details").get_attribute("open") is not None
        assert page.locator("#critical-list").inner_text()
        snapshot = api.pop("/api/fleet/state")
        page.clock.run_for(4000)
        expect(messages).to_contain_text("상태 갱신 실패")
        expect(messages.locator("pre")).to_have_count(0)
        api["/api/fleet/state"] = snapshot
        page.clock.run_for(4000)
        expect(messages).to_contain_text("CORE 거절 (EMERGENCY_ACTIVE)")
        stuck["fleet_answer"] = None
        stuck["ai_proposal"] = {"decision": "RESUME", "class": "held", "verdict": "crosswalk_unknown"}
        page.clock.run_for(4000)
        expect(messages.locator("dd").nth(3)).to_have_text("CORE 전달·응답 기록 없음 · 실행 완료 미확인")
        assert not posts and not errors
        _shot(page, "context-inbox-message-stages.png")
        browser.close()


@pytest.fixture
def site():
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot])
    app = create_app(console, console_token="operator-token", web_common=ROOT / "shared" / "web")
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield origin
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def _open(playwright, origin, api, posts, answers=None, size=(1440, 900)):
    options = launch_options()
    options["args"] = [f"--explicitly-allowed-ports={urlparse(origin).port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method != "GET":
            posts.append((path, request.post_data))
            status, body = (answers or {}).get(path, (404, {"detail": "no such api"}))
            route.fulfill(status=status, json=body)
        elif isinstance(api.get(path), tuple):   # binary evidence (Accept: image/jpeg): (meta, jpeg)
            assert request.headers.get("accept", "").startswith("image/jpeg")
            meta, jpeg = api[path]
            route.fulfill(body=jpeg, content_type="image/jpeg",
                          headers={"X-Stuck-Evidence": json.dumps(meta), "Cache-Control": "no-store"})
        elif path in api:
            route.fulfill(json=api[path])
        else:
            route.fulfill(status=404, json={"detail": "no such api"})

    page.route("**/api/**", serve)
    page.clock.install()
    page.goto(origin + "/console")
    page.clock.run_for(2500)  # state, traffic and trips polls
    return browser, page, errors


def _shot(page, name, *, full_page=False):
    if out := os.environ.get("ROSY_SHOT_DIR"):
        if full_page:
            page.evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)")
            page.evaluate("document.fonts.ready")
            page.clock.run_for(100)
            assert page.evaluate("window.scrollY") == 0
        page.screenshot(path=str(Path(out) / name), full_page=full_page)


def test_decision_buttons_show_at_rail_scroll_zero_and_the_rail_is_the_one_scroll(site):
    """D-540 7: at 1920, 1440 and 1024 the open stuck row's five answers are on screen with the rail at
    scroll 0, the document does not scroll and the queue and roster have no scroll of their own. 390 is one
    column: the document scrolls, nothing inside it does. Queue text is never cut (wrapping is fine)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        for width, height in [*WIDE, (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            _shot(page, f"console-{width}x{height}.png")
            slot = page.locator('[data-decision-slot="rosy_01|stuck"]')
            assert slot.is_visible(), width
            if width >= 1024:
                assert page.evaluate("document.querySelector('.console-secondary').scrollTop") == 0
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), width
                for decision in DECISIONS:
                    box = slot.locator(f'ui-button[data-decision="{decision}"]').bounding_box()
                    assert box and box["y"] >= 0 and box["y"] + box["height"] <= height, (width, decision, box)
                assert set(page.evaluate(SCROLLERS)) <= {"console-primary", "console-secondary"}, (width, page.evaluate(SCROLLERS))
            else:
                assert page.evaluate(SCROLLERS) == [], page.evaluate(SCROLLERS)
            assert page.evaluate("""() => [...document.querySelectorAll('.issue-list li, .queue-row')]
              .every((node) => node.scrollWidth <= node.clientWidth + 1)"""), width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
        assert page.locator("#stuck-panel").count() == 0 and page.locator("#roster-toggle").count() == 0
        assert not errors
        browser.close()


def test_one_queue_row_open_at_a_time_and_the_replan_confirm_round_trips(site):
    """D-540 3: the most urgent decision opens first; opening the replan row closes it; `바뀐 경로로 계속`
    posts confirm-replan for that trip and the stuck answers send unchanged values."""
    from playwright.sync_api import sync_playwright

    posts = []
    answers = {"/api/fleet/trips/t-rosy_02/confirm-replan": (200, {**HELD, "hold": None}),
               "/api/fleet/robots/rosy_01/line-stuck/claim": (200, {"ok": True}),
               "/api/fleet/robots/rosy_01/line-stuck/decision": (200, {"result": {"outcome": "hold"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts, answers)
        stuck_row = page.locator('li[data-key="rosy_01|stuck"] > .queue-row')
        replan_row = page.locator('li[data-key="rosy_02|replan"] > .queue-row')
        assert stuck_row.get_attribute("aria-expanded") == "true"
        assert replan_row.get_attribute("aria-expanded") == "false"
        page.locator('[data-decision-slot="rosy_01|stuck"] ui-button[data-decision="WAIT"]').click()
        page.clock.run_for(300)
        assert ("/api/fleet/robots/rosy_01/line-stuck/decision",
                json.dumps({"stuck_id": "stuck-abc", "decision": "WAIT"}, separators=(",", ":"))) in posts

        replan_row.click()
        page.clock.run_for(1500)  # the choice survives a poll
        assert replan_row.get_attribute("aria-expanded") == "true"
        assert stuck_row.get_attribute("aria-expanded") == "false"
        slot = page.locator('[data-decision-slot="rosy_02|replan"]')
        assert "바뀐 경로 3.2 m" in slot.inner_text()
        _shot(page, "console-replan-1440x900.png")
        slot.locator('ui-button[data-replan="confirm"]').click()
        for _ in range(50):  # the answer lands on the real network clock
            page.clock.run_for(100)
            if "바뀐 경로로 계속합니다" in slot.inner_text():
                break
        assert ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts
        assert "바뀐 경로로 계속합니다" in slot.inner_text()
        assert not errors
        browser.close()


def test_compact_robot_list_keeps_all_four_safety_exceptions_visible_beside_the_workspace(site):
    """D-651: selecting another robot never hides offline, E-stop, unknown safety or calibration evidence."""
    from playwright.sync_api import expect, sync_playwright

    api = {**API, "/api/fleet/trips": {"running": None, "trips": [], "open": []},
           "/api/fleet/state": {"fleet": {"name": "site", "online": 4, "total": 5}, "ts": 0.0, "robots": [
               _robot("nominal"), OFFLINE, _robot("latched", safety={"estop": True}),
               _robot("unknown", safety={}), _robot("calib", calibration={"label": "카메라 보정", "holder": "kim"})]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        card = page.locator('#roster article[data-robot-id="nominal"]')
        assert "80%" in card.inner_text()
        for robot_id, evidence in (("rosy_04", "접속 실패"), ("latched", "비상 정지"),
                                   ("unknown", "안전 확인 불가"), ("calib", "보정 진행 중 · 카메라 보정 · kim")):
            must = page.locator(f'#roster article[data-robot-id="{robot_id}"]')
            expect(must).to_contain_text(evidence)
            assert must.locator(".robot-fold").count() == 0, robot_id
        card.locator("[data-select-robot-id]").click()
        page.clock.run_for(1500)
        expect(page.locator('#robot-workspace article[data-robot-id="nominal"]')).to_have_count(1)
        expect(page.locator('#roster article[data-robot-id="calib"]')).to_contain_text("kim")
        _shot(page, "console-cards-1440x900.png")
        assert not errors
        browser.close()


def test_the_open_stuck_row_shows_its_evidence_picture_below_the_answers(site):
    """D-623/D-641: fresh evidence opens below the answers; historical/expired frames disappear."""
    from playwright.sync_api import sync_playwright

    preview = {"robot_id": "rosy_01", "stuck_id": "stuck-abc", "sequence": 812, "source": "front",
               "media_type": "image/jpeg", "age_s": 0.4, "live": True}
    api = {**API}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], size=(1024, 768))
        jpeg = base64.b64decode(page.evaluate("""() => {
          const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 48;
          return canvas.toDataURL('image/jpeg').split(',')[1];
        }"""))
        api["/api/fleet/robots/rosy_01/line-stuck/evidence"] = (preview, jpeg)
        page.reload()
        page.clock.run_for(1500)
        slot = page.locator('[data-decision-slot="rosy_01|stuck"]')
        image = slot.locator(".stuck-evidence img")
        page.wait_for_function("""() => {
          const img = document.querySelector('.stuck-evidence img'); return img?.complete && img.naturalWidth > 0;
        }""")
        assert image.get_attribute("src").startswith("blob:")
        slot.locator('[data-focus-key="evidence-summary"]').click()
        assert "앞 카메라 #812" in slot.locator(".stuck-evidence figcaption").inner_text()
        for decision in DECISIONS:
            box = slot.locator(f'ui-button[data-decision="{decision}"]').bounding_box()
            assert box and box["y"] + box["height"] <= 768, (decision, box)
        _shot(page, "console-stuck-evidence-1024x768.png")
        preview["age_s"] = 4
        page.clock.run_for(3000)
        from playwright.sync_api import expect
        expect(image).to_have_count(0)
        expect(slot.locator(".stuck-evidence figcaption")).to_contain_text("현재 영상 만료")
        preview.update(live=False, age_s=0.4)
        page.clock.run_for(3000)
        expect(image).to_have_count(0)
        assert not errors
        browser.close()


def test_the_deadlock_row_shows_fleet_and_ai_and_acts_only_through_the_trip_routes(site):
    """D-577 (d): a wait-cycle row opens on Fleet's resolver decision and the AI facts (shadow). `바뀐 경로로 계속`
    posts confirm-replan, `운행 취소` posts cancel (no confirm step), `로봇 카드 열기` opens the card and posts
    nothing. No other route is called."""
    from playwright.sync_api import sync_playwright

    running = {**HELD, "trip_id": "t-rosy_03", "plan_id": "t-rosy_03", "robot_id": "rosy_03", "hold": None}
    cycle = ["rosy_02", "rosy_03"]
    api = {**API,
           "/api/fleet/traffic": {**API["/api/fleet/traffic"], "wait_cycle": cycle, "resolver": [
               {"robot_id": "rosy_02", "trigger": "wait_cycle", "decision": "replan", "cycle": cycle,
                "blocked_edges": ["e1"]},
               {"robot_id": "rosy_03", "trigger": "wait_cycle", "decision": "wait", "cycle": cycle}]},
           "/api/fleet/trips": {"running": HELD, "trips": [HELD, running], "open": [HELD, running]},
           "/api/fleet/ai": {"status": {"state": "present"}, "proposals": [], "facts": [
               {"kind": "wait_cycle_confirmed", "robot_ids": cycle, "value": {"held_s": 4.0}, "confidence": 0.9,
                "evidence": {}, "source": "analyzer:traffic_watch@1", "observed_at": 0, "ttl_s": 3,
                "stage": "shadow"}]}}
    posts = []
    answers = {"/api/fleet/trips/t-rosy_02/confirm-replan": (200, {**HELD, "hold": None}),
               "/api/fleet/trips/t-rosy_03/cancel": (200, {**running, "state": "canceled"})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        page.clock.run_for(1500)

        def slot_of(robot_id):
            page.locator(f'li[data-key="{robot_id}|deadlock"] > .queue-row').click()
            page.clock.run_for(300)
            return page.locator(f'[data-decision-slot="{robot_id}|deadlock"]')

        slot = slot_of("rosy_02")
        text = slot.inner_text()
        assert "rosy_02 · 해결기 다른 길 계획" in text and "rosy_03 · 해결기 다른 로봇 대기" in text
        assert "AI 참고 · 교착 확인 (모두 멈춤) · rosy_02, rosy_03 · 신뢰도 90%" in text
        _shot(page, "console-deadlock-1440x900.png")
        slot.locator('ui-button[data-replan="confirm"]').click()
        for _ in range(50):
            page.clock.run_for(100)
            if ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts:
                break
        assert ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts

        assert page.locator('#robot-workspace article[data-robot-id="rosy_03"]').count() == 0
        slot = slot_of("rosy_03")
        assert slot.locator('ui-button[data-replan="confirm"]').get_attribute("reason") == "확인할 바뀐 경로가 없습니다"
        slot.locator('ui-button[data-replan="cancel"]').click()
        for _ in range(50):
            page.clock.run_for(100)
            if ("/api/fleet/trips/t-rosy_03/cancel", None) in posts:
                break
        assert ("/api/fleet/trips/t-rosy_03/cancel", None) in posts
        before = list(posts)
        page.locator('[data-decision-slot="rosy_03|deadlock"] ui-button[data-replan="card"]').click()
        page.clock.run_for(300)
        assert page.locator('#robot-workspace article[data-robot-id="rosy_03"]').count() == 1
        assert posts == before
        assert {path for path, _ in posts} <= {"/api/fleet/trips/t-rosy_02/confirm-replan",
                                                "/api/fleet/trips/t-rosy_03/cancel"}
        assert not errors
        browser.close()
