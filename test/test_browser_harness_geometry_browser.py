"""assert_layout_geometry catches the layout faults it names, in real Chromium (opt-in)."""

import pytest
from browser_harness import assert_layout_geometry, browser_tests_enabled, launch_options
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")

BOX = "border:1px solid rgb(0, 0, 0);"
FAULTS = {
    "G2 overlap": '<div class="robot-head" style="display:flex;width:300px"><span style="width:100px">a</span>'
                  '<span style="width:100px;margin-left:-50px">b</span></div>',
    "G4 box-in-box": f'<main><div style="{BOX}width:300px;height:200px"><div style="{BOX}width:250px;height:150px">'
                     f'<div style="{BOX}width:200px;height:100px">x</div></div></div></main>',
    "G5 floating-dock-collision": '<div id="estop" style="position:fixed;left:10px;top:10px;width:100px;height:40px">stop</div>'
                                  '<button id="assistant-toggle" style="position:fixed;left:20px;top:20px;width:60px;height:30px">AI</button>',
}


def _violations(page, html):
    page.set_content(html)
    try:
        assert_layout_geometry(page)
    except AssertionError as error:
        return str(error)
    return ""


def test_the_probe_flags_each_fault_and_passes_a_clean_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            assert _violations(page, "<main><p>clean</p></main>") == ""
            for rule, html in FAULTS.items():
                assert rule in _violations(page, html), rule
        finally:
            browser.close()
