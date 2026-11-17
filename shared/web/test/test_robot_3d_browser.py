"""C15 robot 3D view on the served gallery: a real WebGL canvas per view, the selected state in the accent colour, the
keyboard orbit, theme repaint, no render loop, lazy loading of three.js, and the quiet fallback without WebGL.

ROSY_ROBOT3D_SHOTS=<dir> also saves the gallery section (dark and light, 1440 and 390 wide) for visual review."""

import io
import json
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"
SHOTS = os.environ.get("ROSY_ROBOT3D_SHOTS")
GL_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
COUNT_RAF = "(() => { window.__raf = 0; const raf = window.requestAnimationFrame.bind(window); window.requestAnimationFrame = cb => {window.__raf += 1; return raf(cb);}; })();"
ACCENT = """() => { const probe = document.createElement('canvas').getContext('2d'); probe.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--selection').trim();
  probe.fillRect(0, 0, 1, 1); return Array.from(probe.getImageData(0, 0, 1, 1).data).slice(0, 3); }"""


def _open(pw, width=1440, args=GL_ARGS, theme=None):
    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    requested = []

    def serve(route):
        name = route.request.url.split("/common/", 1)[-1].split("?", 1)[0]
        requested.append(name)
        if name not in assets:
            return route.fulfill(status=404, body="not registered")
        route.fulfill(path=str(WEB / name), content_type=assets[name])

    browser = pw.chromium.launch(args=args)
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(COUNT_RAF)
    if theme:
        page.add_init_script(f"localStorage.setItem('rosy.theme', '{theme}')")
    page.route(HOST + "/**", serve)
    assert page.goto(HOST + "/common/component-gallery.html").status == 200
    return browser, page, requested, errors


def _pixels(locator):
    from PIL import Image
    image = Image.open(io.BytesIO(locator.screenshot())).convert("RGB")
    return image, image.getpixel((2, 2))


def _count(image, predicate):
    raw = image.tobytes()  # RGB triples; getdata is deprecated and get_flattened_data is not on older Pillow
    return sum(1 for i in range(0, len(raw), 3) if predicate(tuple(raw[i:i + 3])))


def _drawn(page):
    page.locator("#robot-3d").scroll_into_view_if_needed()
    page.wait_for_function("document.getElementById('robot-3d-mount').dataset.drawn", timeout=60000)
    assert page.locator("#robot-3d-mount").get_attribute("data-drawn") == "all"
    page.wait_for_timeout(400)


@pytest.fixture
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        yield playwright


def test_every_view_draws_real_pixels_and_says_the_same_facts_in_text(pw):
    browser, page, requested, errors = _open(pw)
    assert not any(name.startswith("vendor/") for name in requested), "three.js must not load before a view is near"
    _drawn(page)
    assert "vendor/three.module.min.js" in requested and "meshes/omx-f.urdf" in requested
    views = page.locator("#robot-3d-mount .robot-view")
    assert views.count() == 5
    for index in range(5):
        view = views.nth(index)
        image, background = _pixels(view.locator("canvas"))
        assert _count(image, lambda p: max(abs(p[i] - background[i]) for i in range(3)) > 24) > 800, f"view {index} is empty"
        assert view.locator("canvas").get_attribute("role") == "img"
        labelled = view.locator("canvas").get_attribute("aria-labelledby")
        assert view.locator("figcaption").inner_text().startswith(page.locator(f"#{labelled}").inner_text())
        described = view.locator("canvas").get_attribute("aria-describedby")
        assert page.locator(f"#{described}").text_content().strip(), "the joint or pose list is the accessible description"
        assert "°" not in view.locator(".robot-view-summary").inner_text(), "joint values are not visible text"
    detail = lambda i: views.nth(i).locator(".sr-only").text_content()
    assert views.nth(0).locator(".robot-view-summary").inner_text().startswith("로봇암 OMX-AI A · 선택 안 됨 · 최신")
    assert detail(0).startswith("관절 1 29° · 관절 2 26°") and "그리퍼 11°" in detail(0)
    assert "선택됨" in views.nth(1).locator(".robot-view-summary").inner_text() and views.nth(1).get_attribute("data-selected") is not None
    assert views.nth(2).locator(".robot-view-summary").inner_text().startswith("이동로봇 rosy_40 · 선택 안 됨")
    assert detail(2) == "위치 x 0.50 · y -0.25 m · 방향 52°"
    assert views.nth(4).locator(".robot-view-summary").inner_text().endswith("지연 · 14초 전")
    assert detail(4).startswith("마지막 보고 기준 · 관절 1")
    views.nth(0).get_by_role("button", name="OMX-AI A 관절 값").click()
    assert "관절 1 29°" in views.nth(0).locator(".ui-toggletip-note").inner_text(), "the toggletip shows the joint list on demand"
    browser.close()
    assert not errors, errors


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_selected_is_the_accent_and_unselected_has_none(pw, theme):
    browser, page, _, errors = _open(pw, theme=theme)
    _drawn(page)
    accent = page.evaluate(ACCENT)
    near = lambda p: sum(abs(p[i] - accent[i]) for i in range(3)) < 60
    views = page.locator("#robot-3d-mount .robot-view")
    for plain, chosen in ((0, 1), (2, 3)):
        assert _count(_pixels(views.nth(chosen).locator("canvas"))[0], near) > 250, "selected view needs the accent ring and outline"
        assert _count(_pixels(views.nth(plain).locator("canvas"))[0], near) < 10, "unselected view must not use the accent"
    frame = views.nth(1).locator(".robot-view-stage").evaluate("node => getComputedStyle(node).borderTopColor")
    assert frame != views.nth(0).locator(".robot-view-stage").evaluate("node => getComputedStyle(node).borderTopColor")
    browser.close()
    assert not errors, errors


def test_keyboard_orbit_presets_and_theme_repaint(pw):
    browser, page, _, errors = _open(pw)
    _drawn(page)
    stage = page.locator("#view-arm .robot-view-stage")
    stage.focus()  # the focus ring is part of the picture, so the baseline is taken focused
    page.wait_for_timeout(300)
    before = stage.locator("canvas").screenshot()
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    page.keyboard.press("+")
    page.wait_for_timeout(300)
    rotated = stage.locator("canvas").screenshot()
    assert rotated != before, "arrow keys must rotate the view"
    page.keyboard.press("Home")
    page.wait_for_timeout(300)
    assert stage.locator("canvas").screenshot() == before, "Home returns to the preset view"
    page.locator("#view-arm [data-preset='top']").click()
    page.wait_for_timeout(300)
    assert stage.locator("canvas").screenshot() != before
    assert page.locator("#view-arm [data-preset='top']").get_attribute("aria-pressed") == "true"
    page.locator("#view-arm [data-preset='iso']").click()
    page.wait_for_timeout(300)
    dark = stage.locator("canvas").screenshot()
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    page.wait_for_timeout(500)
    assert stage.locator("canvas").screenshot() != dark, "a theme change repaints without reload"
    browser.close()
    assert not errors, errors


def test_no_render_loop_when_idle(pw):
    browser, page, _, errors = _open(pw)
    _drawn(page)
    page.wait_for_timeout(300)
    first = page.evaluate("window.__raf")
    page.wait_for_timeout(1200)
    assert page.evaluate("window.__raf") == first, "an idle 3D view draws no frames (render on change, D-220)"
    browser.close()
    assert not errors, errors


def test_without_webgl_the_facts_stay_and_the_box_goes(pw):
    browser, page, _, errors = _open(pw, args=["--disable-3d-apis", "--disable-gpu"])
    page.locator("#robot-3d").scroll_into_view_if_needed()
    page.wait_for_function("document.getElementById('robot-3d-mount').dataset.drawn", timeout=60000)
    assert page.locator("#robot-3d-mount").get_attribute("data-drawn") == "fallback"
    view = page.locator("#view-arm-selected")
    assert view.locator(".robot-view").get_attribute("data-state") == "fallback"
    assert not view.locator(".robot-view-stage").is_visible() and not view.locator(".robot-view-presets").is_visible()
    assert "관절 1 29°" in view.locator(".sr-only").text_content() and "선택됨" in view.locator(".robot-view-summary").inner_text()
    assert "3D 보기를 쓸 수 없어" in view.locator(".robot-view-note").inner_text()
    browser.close()
    assert not errors, errors


@pytest.mark.parametrize("width", [1440, 390])
def test_robot_fills_about_three_quarters_of_the_shorter_side(pw, width):
    browser, page, _, errors = _open(pw, width=width)
    _drawn(page)
    for name in ("view-arm", "view-pinky"):
        image, background = _pixels(page.locator(f"#{name} canvas"))
        w, h = image.size
        raw = image.tobytes()
        xs, ys = [], []
        for i in range(0, len(raw), 3):
            if max(abs(raw[i + k] - background[k]) for k in range(3)) > 24:
                xs.append((i // 3) % w); ys.append((i // 3) // w)
        fill = max((max(xs) - min(xs)) / w, (max(ys) - min(ys)) / h)
        assert 0.55 <= fill <= 0.95, f"{name} fills {fill:.2f} of the canvas at {width}px"
    browser.close()
    assert not errors, errors


@pytest.mark.parametrize("width", [1440, 390])
def test_gallery_section_fits_and_can_be_photographed(pw, width):
    for theme in ("dark", "light"):
        browser, page, _, errors = _open(pw, width=width, theme=theme)
        _drawn(page)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "no horizontal overflow"
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.locator("#robot-3d").screenshot(path=str(Path(SHOTS) / f"robot-3d-{theme}-{width}.png"))
        browser.close()
        assert not errors, errors
