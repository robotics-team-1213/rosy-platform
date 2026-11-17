"""Shared fixture for the choice-part browser tests: the served gallery at the two reference widths."""

import json
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"


@pytest.fixture(params=[1440, 390], ids=["w1440", "w390"])
def gallery(request):
    from playwright.sync_api import sync_playwright, expect

    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]

    def serve(route):
        name = route.request.url.split("/common/", 1)[-1].split("?", 1)[0]
        if name not in assets:
            return route.fulfill(status=404, body="not registered")
        route.fulfill(path=str(WEB / name), content_type=assets[name])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": request.param, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(HOST + "/**", serve)
        assert page.goto(HOST + "/common/component-gallery.html").status == 200
        expect(page.locator("#kit-ready")).to_have_text("견본 준비 완료")
        page.wide = request.param >= 1024
        yield page
        assert not errors, errors
        browser.close()


def selection_color(page):
    """The resolved --selection colour, as the browser prints it (rgb(...))."""
    return page.evaluate("""() => { const probe = document.createElement('span'); probe.style.color = 'var(--selection)';
      document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; }""")
