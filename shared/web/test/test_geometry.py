"""setGeometry (shared/web/geometry.js, D1): validation unit tests and a real-CSP browser check."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from browser_harness import browser_tests_enabled

WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"
#: What the apps send: style-src 'self' (core_api_web, learning review app, calibration).
CSP = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"

UNIT = """
import {setGeometry} from %(module)s;
const el = {style: {props: {}, setProperty(k, v) { this.props[k] = v; }, removeProperty(k) { delete this.props[k]; }}};
const out = [];
const run = (v) => { const ok = setGeometry(el, v); out.push([ok, {...el.style.props}]); };
run({x: 12.5, width: "40%%", scale: 2, color: "#aabbcc", fill: "var(--ink)"});
run({width: Number.NaN, x: "calc(1px + 2px)", color: "red", left: "1e3px", top: 1e-7});
run({x: null, width: undefined});
try { setGeometry(el, {background: "red"}); out.push("no throw"); } catch (e) { out.push(e.constructor.name); }
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_values_are_validated_and_only_g_properties_are_written():
    code = UNIT % {"module": json.dumps((WEB / "geometry.js").as_uri())}
    result = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=True)
    first, second, third, error = json.loads(result.stdout)
    assert first == [True, {"--g-x": "12.5px", "--g-width": "40%", "--g-scale": "2", "--g-color": "#aabbcc", "--g-fill": "var(--ink)"}]
    # NaN, free text, expressions, exponent notation and a named colour are rejected; 1e-7 rounds to 0px.
    assert second[0] is False
    # Rejected values (NaN, expression, named colour, exponent) remove the property so the sheet default shows;
    # 1e-7 rounds to 0px.
    assert second[1] == {"--g-scale": "2", "--g-fill": "var(--ink)", "--g-top": "0px"}
    assert third[0] is True and "--g-x" not in third[1] and "--g-width" not in third[1]
    assert error == "TypeError"


pytestmark_browser = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")

PAGE = '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/g.css"><div id="box"></div><script type="module" src="/m.js"></script>'
SHEET = "#box { width: var(--g-width, 10px); height: 10px; color: var(--g-color, rgb(0, 0, 0)); }"
SCRIPT = ("import {setGeometry} from '/common/geometry.js';"
          "window.apply = (v) => setGeometry(document.getElementById('box'), v);")


@pytestmark_browser
def test_setgeometry_changes_computed_size_under_the_real_csp_without_violations():
    from playwright.sync_api import sync_playwright

    def serve(route):
        path = route.request.url.removeprefix(HOST).split("?", 1)[0]
        bodies = {"/": (PAGE, "text/html"), "/g.css": (SHEET, "text/css"), "/m.js": (SCRIPT, "text/javascript")}
        if path == "/common/geometry.js":
            return route.fulfill(body=(WEB / "geometry.js").read_text(encoding="utf-8"), content_type="text/javascript",
                                 headers={"Content-Security-Policy": CSP})
        body, kind = bodies[path]
        route.fulfill(body=body, content_type=kind, headers={"Content-Security-Policy": CSP})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.add_init_script("window.__violations = []; document.addEventListener('securitypolicyviolation', e => window.__violations.push(e.violatedDirective + ' ' + e.blockedURI));")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(HOST + "/**", serve)
        page.goto(HOST + "/")
        page.wait_for_function("typeof window.apply === 'function'")
        width = lambda: page.evaluate("getComputedStyle(document.getElementById('box')).width")
        assert width() == "10px"  # stylesheet default
        assert page.evaluate("apply({width: 123, color: '#ff0000'})") is True
        assert width() == "123px"
        assert page.evaluate("getComputedStyle(document.getElementById('box')).color") == "rgb(255, 0, 0)"
        assert page.evaluate("apply({width: NaN})") is False  # rejected -> back to the default
        assert width() == "10px"
        assert page.evaluate("window.__violations") == []
        assert errors == []
        browser.close()
