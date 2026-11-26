"""Site map overlays and selection in real Chromium. No robot motion."""

import re

import pytest

from browser_harness import browser_tests_enabled, open_token_access
from fleet.site_map import with_floor_surveys
from test_site_map_browser import page_site, show_screen


pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="opt-in real Chromium browser scenario")


def test_world_road_overlay_separates_surveyed_paint_and_stored_maneuver(page_site):
    from playwright.sync_api import expect

    page, store, _ = page_site
    active = store.active_view()
    map_body = {
        "schema": "rosy.site_map/1", "map_id": "world_261026", "turn_bans": [],
        "places": [
            {"id": "P1", "name": "P1", "kind": "junction", "x": -.43002, "y": .04266},
            {"id": "C1", "name": "C1", "kind": "charge", "x": -.41816, "y": .47},
            {"id": "S5", "name": "S5", "kind": "stop", "x": .89822, "y": -.48152},
            {"id": "S3", "name": "S3", "kind": "stop", "x": .745, "y": -.207},
            {"id": "J_in", "name": "J_in", "kind": "junction", "x": .31418, "y": -.25008},
        ],
        "edges": [
            {"id": eid, "from": source, "to": target, "direction": "two_way",
             "drive_mode": "lane", "speed_cap_mps": .02, "polyline": points}
            for eid, source, target, points in [
                ("bay_1", "P1", "C1", [[-.43002, .04266], [-.4354, .3294], [-.41816, .47]]),
                ("loop_right", "S5", "S3", [[.89822, -.48152], [.9756, -.4676],
                     [1.0593, -.3424], [.9756, -.2173], [.9238, -.207], [.745, -.207]]),
                ("upper_east", "S3", "J_in", [[.745, -.207], [.56, -.207], [.31418, -.25008]]),
            ]
        ],
    }
    # The survey line comes from the server's map record (2026-11-26), not a console constant.
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(json={**active, "map": with_floor_surveys(map_body)}))
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()

    svg = page.locator("#site-map-svg")
    bay = svg.locator('[data-edge="bay_1"]')
    loop = svg.locator('[data-edge="loop_right"]')
    upper = svg.locator('[data-edge="upper_east"]')
    for paint in (bay, loop, upper):
        expect(paint).to_have_class(re.compile(r"\bsurveyed\b"))
        expect(paint).to_have_css("stroke-dasharray", "none")
        assert len(paint.get_attribute("points").split()) == 2
    expect(upper.locator("title")).to_have_text("upper_east · 측량 2026-11-26 · ceiling_north · 영상에서 읽은 차선 양쪽 경계의 중점")
    evidence = page.locator("#map-evidence")
    expect(evidence).to_have_text(re.compile(rf"^지도 v{active['version']} · 활성 \d\d:\d\d:\d\d · 출처 Fleet 활성 지도 · 측량 2026-11-26 ceiling_north$"))
    expect(evidence).to_have_attribute("title", re.compile(r"^world_261026 · 활성 .+Z \(UTC\)$"))
    expect(svg.locator(".arrow")).to_have_count(0)

    prefix = svg.locator('[data-road-prefix="loop_right"]')
    expect(prefix).to_have_css("stroke-dasharray", "5px, 4px")
    prefix_points = prefix.get_attribute("points").split()
    assert len(prefix_points) == 5
    expect(svg.locator("[data-stored-road]")).to_have_count(0)

    prefix.dispatch_event("click")
    stored_loop = svg.locator('[data-stored-road="loop_right"]')
    expect(stored_loop.locator("title")).to_contain_text("저장 주행 경로")
    expect(stored_loop).to_have_css("stroke-dasharray", "5px, 4px")
    expect(prefix).to_have_count(0)
    actual = stored_loop.get_attribute("points").split()
    assert actual[:-1] == prefix_points and len(actual) == 6
    expect(svg.locator(".stored-road-arrow")).not_to_have_count(0)

    page.locator("#map-source").select_option("draft")
    expect(loop).to_have_attribute("points", " ".join(actual))
    expect(svg.locator(".surveyed, .stored-road")).to_have_count(0)
    expect(evidence).to_have_text(re.compile(r"^초안 표시 · 기준 지도 v"))
    assert store.active_view() == active


def test_without_a_served_survey_no_survey_line_is_drawn_and_the_evidence_line_says_so(page_site):
    from playwright.sync_api import expect

    page, store, _ = page_site
    active = store.active_view()
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(json={**active, "map": {**active["map"], "map_id": "world_261026"}}))
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    expect(page.locator("#site-map-svg [data-edge]").first).to_be_attached()
    expect(page.locator("#site-map-svg .surveyed")).to_have_count(0)
    expect(page.locator("#map-evidence")).to_have_text(re.compile(rf"^지도 v{active['version']} · .* · 측량선 없음$"))


def test_site_points_summary_follows_the_displayed_map_source(page_site):
    from playwright.sync_api import expect

    page, store, _ = page_site
    active = store.active_view()
    site_map_source = {
        "map_id": active["map"]["map_id"],
        "version": active["version"],
        "sha256": active["sha256"],
    }
    site_points = {
        "sources": {"site_map": site_map_source},
        "coordinate_frames": {"cell_s_arm_base": {"world_origin_hint_m": [0.1, 0.2]}},
    }
    page.route("**/api/fleet/site-points", lambda route: route.fulfill(json=site_points))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()

    source = page.locator("#map-source")
    panel = page.locator("#site-points-panel")
    layer = page.locator("#site-points-layer")
    expect(panel).to_be_visible()
    expect(layer).to_be_attached()
    panel.locator("summary").click()

    for value in ("draft", "profile"):
        source.select_option(value)
        expect(panel).to_be_hidden()
        expect(layer).to_have_count(0)
    source.select_option("active")
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("open", "")
    expect(layer).to_be_attached()


@pytest.mark.parametrize("width,key", [(1440, "Enter"), (390, "Space")])
def test_keyboard_place_picks_map_coordinates_on_rotated_map(page_site, width, key):
    from playwright.sync_api import expect

    page, store, _ = page_site
    page.set_viewport_size({"width": width, "height": 844})
    active = store.active_view()
    rotated = {**active["map"], "view_turn_deg": 90}
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(json={**active, "map": rotated}))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#map-view-turn")).to_have_value("90")

    show_screen(page, "trip-heading")
    marker = page.locator('#site-map-svg [data-place="NW"]')
    marker.press(key)
    expect(page.locator("#trip-place")).to_have_value("NW")
    expect(marker).to_be_focused()
    page.locator("#trip-pick").check()
    show_screen(page, "map-heading")  # The map stays visible and coordinate picking remains armed.
    marker.press(key)
    point = next(place for place in rotated["places"] if place["id"] == "NW")
    expect(page.locator("#trip-point")).to_have_text(f"찍은 좌표 x {round(point['x'], 3):g} m, y {round(point['y'], 3):g} m")
    expect(page.locator('.ui-subnav-nav a[href="#map-heading"]')).to_have_attribute("aria-current", "page")
    expect(marker).to_be_focused()


@pytest.mark.parametrize("width", [1440, 390])
def test_map_inspector_selects_roads_and_crosswalks_on_each_source(page_site, width):
    from playwright.sync_api import expect

    page, store, _ = page_site
    page.set_viewport_size({"width": width, "height": 844})
    active = store.active_view()["map"]
    profile = {**active, "crosswalks": [{**active["crosswalks"][0], "id": "profile-cw"}]}
    page.route("**/api/fleet/site-map/profiles", lambda route: route.fulfill(json={"profiles": [
        {"profile_id": "test-profile", "name": "비교 지도", "kind": "general", "map": profile},
    ]}))
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    picker = page.get_by_label("지도에서 검사할 요소")

    picker.press("End")
    expect(picker).to_have_value("crosswalk:cw2")
    expect(page.locator('#site-map-svg [data-crosswalk="cw2"]')).to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#selection")).to_contain_text("횡단보도 cw2")
    expect(picker).to_be_focused()

    page.locator("#map-source").select_option("draft")
    expect(picker).to_have_value("")
    picker.select_option("edge:ring_n")
    expect(page.locator("#edge-form")).to_be_visible()
    expect(page.locator('#site-map-svg [data-edge="ring_n"]')).to_have_class(re.compile(r"\bselected\b"))
    page.locator('#site-map-svg [data-crosswalk="cw1"]').dispatch_event("click")
    expect(picker).to_have_value("crosswalk:cw1")

    show_screen(page, "profile-heading")
    page.locator("#map-profile").select_option("test-profile")
    expect(picker.locator('[value="crosswalk:cw1"]')).to_have_count(0)
    picker.select_option("crosswalk:profile-cw")
    expect(page.locator("#selection")).to_contain_text("횡단보도 profile-cw")
    expect(page.locator("#crosswalk-form")).to_be_hidden()
    expect(page.locator("#apply-edit")).to_be_disabled()
