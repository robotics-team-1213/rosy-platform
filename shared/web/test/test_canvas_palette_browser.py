"""D-359 §4 — 캔버스 색이 토큰에서 오고, 테마를 바꾸면 새로 고침 없이 다시 칠한다.

로봇 지도(dashboard map.js)와 Fleet 지도(map-view.js)를 가짜 호스트
(`http://rosy.test`)에 띄우고 빈 칸(free)의 픽셀을 dark → light로 잰다.
color-mix 토큰이 검정으로 풀리지 않는지도 여기서 본다(hex 전용 파서가 그랬다).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

import token_themes

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

SRC = (Path(__file__).resolve().parents[3] / "src")
COMMON = SRC.parent / "shared" / "web"
DASHBOARD = SRC.parent / "middleware" / "ui" / "robot"
FLEET = SRC.parent / "operations" / "fleet" / "fleet" / "server" / "web"
HOST = "http://rosy.test"
PALETTES = token_themes.palettes(token_themes.read())
TYPES = {".css": "text/css", ".js": "application/javascript", ".html": "text/html"}
SHOTS = os.environ.get("ROSY_D359_SHOTS")

ROBOT_MAP_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="/common/tokens.css">
<script src="/common/theme.js"></script>
<link rel="stylesheet" href="/common/components.css">
<script type="module" src="/common/ui.js"></script>
<style>body { margin: 0; background: var(--ground); } canvas { display: block; width: 640px; height: 480px; }</style>
</head><body><canvas id="map" width="640" height="480"></canvas>
<script type="module">
  import { createFieldMap } from "/assets/map.js";
  // 가운데는 빈 칸(0), 가장자리 네 줄은 벽(100), 한 줄은 불확실(40), 한 구역은 미지(-1).
  const width = 40, height = 30;
  const data = [];
  for (let row = 0; row < height; row += 1) for (let col = 0; col < width; col += 1) {
    const edge = row < 2 || col < 2 || row >= height - 2 || col >= width - 2;
    data.push(edge ? 100 : col < 8 ? -1 : row === 15 ? 40 : 0);
  }
  const grid = { width, height, resolution: 0.05, origin: { x: 0, y: 0 }, data, map_id: "palette" };
  window.__map = createFieldMap({
    canvas: document.getElementById("map"), canGoal: () => false,
    getPose: () => ({ x: 1.4, y: 0.4, yaw: 0.6 }), getNavigation: () => null,
    api: async () => ({}),
    apiMaybe: async (path) => path === "/api/v1/map" ? grid
      : path === "/api/v1/navigation/path" ? { poses: [{ x: 0.6, y: 0.3 }, { x: 1.4, y: 1.2 }] } : null,
  });
  await window.__map.refresh();
  window.__ready = true;
</script></body></html>"""

FLEET_GRID = {
    "width": 40, "height": 30, "resolution": 0.05, "origin": {"x": 0.0, "y": 0.0},
    "map_id": "palette",
    "data": [100 if (r < 2 or c < 2 or r >= 28 or c >= 38) else (-1 if c < 8 else (40 if r == 15 else 0))
             for r in range(30) for c in range(40)],
}
FLEET_ROBOT = {
    "robot_id": "rosy_01", "online": True, "goal": None, "queued": None, "yielding": None, "error": None,
    "state": {"robot_id": "rosy_01", "mode": "NAVIGATION", "navigation": "IDLE",
              "pose": {"x": 1.5, "y": 0.4, "yaw": 0.5}, "battery": {"percent": 90},
              "safety": {"estop": False}},
}
FLEET_API = {
    "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1},
                         "robots": [FLEET_ROBOT], "ts": 0.0},
    "/api/fleet/map": FLEET_GRID,
    "/api/fleet/formation": {"active": False, "state": "IDLE"},
    "/api/fleet/session": {"principal_id": "test-operator", "role": "operator"},
}

# 빈 칸 하나의 월드 좌표 — 로봇·경로·오버레이와 떨어진 곳.
FREE_WORLD = (1.6, 1.15)


def _serve(route):
    path = route.request.url.removeprefix(HOST).split("?", 1)[0]
    if path.startswith("/api/"):
        body = FLEET_API.get(path)
        if body is None:
            return route.fulfill(status=404, json={"detail": "no such api"})
        return route.fulfill(status=200, json=body)
    if path.startswith("/common/"):
        target = COMMON / path.removeprefix("/common/")
    elif path.startswith("/console/assets/"):
        target = FLEET / path.removeprefix("/console/assets/")
    elif path.startswith("/assets/"):
        target = DASHBOARD / path.removeprefix("/assets/")
    elif path == "/console":
        target = FLEET / "index.html"
    elif path == "/robot-map":
        return route.fulfill(status=200, content_type="text/html", body=ROBOT_MAP_PAGE)
    else:
        return route.fulfill(status=404, body="")
    if not target.is_file():
        return route.fulfill(status=404, body="")
    return route.fulfill(status=200, content_type=TYPES.get(target.suffix, "text/plain"),
                         body=target.read_text(encoding="utf-8"))


@pytest.fixture()
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - host without Chromium
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        yield launched
        launched.close()


def _open(browser, path: str):
    context = browser.new_context(viewport={"width": 1366, "height": 768}, color_scheme="dark")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(f"{HOST}/**", _serve)
    page.goto(f"{HOST}{path}", wait_until="load")
    return page, errors


def _rgb(hex_colour: str) -> list[int]:
    raw = hex_colour.lstrip("#")
    return [int(raw[i:i + 2], 16) for i in (0, 2, 4)]


def _close(actual, expected, tolerance=3) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def _shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"us003-{name}.png"))


# 그리드 좌표 → 캔버스 백킹 픽셀. 두 지도 모두 격자 행 0 이 아래다.
SAMPLE = """([canvasId, wx, wy, gw, gh, res]) => {
  const canvas = document.getElementById(canvasId);
  const px = Math.floor((wx / res / gw) * canvas.width);
  const py = Math.floor((1 - wy / res / gh) * canvas.height);
  return Array.from(canvas.getContext('2d').getImageData(px, py, 1, 1).data.slice(0, 3));
}"""


def _sample(page, canvas_id: str) -> list[int]:
    return page.evaluate(SAMPLE, [canvas_id, *FREE_WORLD, 40, 30, 0.05])


@pytest.mark.parametrize("path, canvas_id", [("/robot-map", "map"), ("/console", "map-canvas")],
                         ids=["robot-map", "fleet-map"])
def test_free_space_follows_the_theme_without_reload(browser, path, canvas_id):
    page, errors = _open(browser, path)
    if canvas_id == "map":
        page.wait_for_function("window.__ready === true")
    else:
        page.wait_for_function("document.getElementById('map-stage')?.dataset.mapState === 'ready'")
    dark = _sample(page, canvas_id)
    assert _close(dark, _rgb(PALETTES["dark"]["raster-free"])), dark
    _shot(page, f"{'robot' if canvas_id == 'map' else 'fleet'}-dark")

    page.evaluate("window.RosyTheme.set('light')")
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    light = _sample(page, canvas_id)
    expected = _rgb(PALETTES["light"]["raster-free"])
    assert light != [0, 0, 0]
    assert not _close(light, dark, 10)
    assert _close(light, expected), (light, expected)
    _shot(page, f"{'robot' if canvas_id == 'map' else 'fleet'}-light")
    assert errors == []


def test_read_palette_resolves_color_mix_tokens_and_clears_on_theme(browser):
    page, errors = _open(browser, "/robot-map")
    page.wait_for_function("window.__ready === true")
    read = """() => ({
      quiet: window.RosyPalette.readColour('--line-quiet'),
      grad: window.RosyPalette.readColour('--ground-grad-1'),
      table: window.RosyPalette.readPalette({free: '--raster-free', hex: '#102030'}),
      font: window.RosyPalette.canvasFont(10, 'mono'),
      css: window.RosyPalette.cssColor('--raster-free'),
    })"""
    for theme in ("dark", "light"):
        if theme == "light":
            page.evaluate("window.RosyTheme.set('light')")
        got = page.evaluate(read)
        palette = PALETTES[theme]
        # --line-quiet = color-mix(in oklab, var(--ink-quiet) 25%, transparent)
        assert _close(got["quiet"][:3], _rgb(palette["ink-quiet"]), 4), got["quiet"]
        assert abs(got["quiet"][3] - 0.25) <= 0.02
        # --ground-grad-1 = color-mix(in oklab, var(--ground) 71%, var(--ground-deep)) — 불투명
        low, high = sorted([_rgb(palette["ground"]), _rgb(palette["ground-deep"])], key=sum)
        assert got["grad"][3] == 1 and got["grad"][:3] != [0, 0, 0]
        assert all(min(a, b) - 2 <= c <= max(a, b) + 2 for a, b, c in zip(low, high, got["grad"][:3]))
        assert _close(got["table"]["free"][:3], _rgb(palette["raster-free"]), 0)
        assert got["table"]["hex"] == [16, 32, 48, 1]
        assert got["font"].startswith("12px ") and "Consolas" in got["font"]
        assert got["css"] == "rgba({}, {}, {}, 1)".format(*_rgb(palette["raster-free"]))
    assert errors == []
