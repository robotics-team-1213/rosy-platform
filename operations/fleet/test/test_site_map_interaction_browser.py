"""Site map overlays and selection in real Chromium. No robot motion."""

import re

import pytest

from browser_harness import browser_tests_enabled, open_token_access
from test_site_map_browser import page_site, show_screen


pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="opt-in real Chromium browser scenario")


def test_world_charge_bay_overlay_joins_both_place_markers_with_a_straight_line(page_site):
    from playwright.sync_api import expect

    page, store, _ = page_site
    active = store.active_view()
    map_body = {
        "schema": "rosy.site_map/1", "map_id": "world_261026", "turn_bans": [],
        "places": [
            {"id": "P1", "name": "P1", "kind": "junction", "x": -.43002, "y": .04266},
            {"id": "C1", "name": "C1", "kind": "charge", "x": -.41816, "y": .47},
        ],
        "edges": [{"id": "bay_1", "from": "P1", "to": "C1", "direction": "two_way",
                   "drive_mode": "lane", "speed_cap_mps": .02,
                   "polyline": [[-.43002, .04266], [-.4354, .3294], [-.41816, .47]]}],
    }
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(json={**active, "map": map_body}))
    open_token_access(page)
    page.locator('#console-token').fill('operator-token')
    page.locator('#token-save').click()
    edge = page.locator('#site-map-svg [data-edge="bay_1"]')
    expect(edge).to_be_attached()
    endpoints = []
    for place_id in ("P1", "C1"):
        marker = page.locator(f'#site-map-svg [data-place="{place_id}"] circle.place')
        endpoints.append(f"{marker.get_attribute('cx')},{marker.get_attribute('cy')}")
    expect(edge).to_have_attribute('points', ' '.join(endpoints))
    assert store.active_view() == active


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
