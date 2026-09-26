"""BENCH 라이브 표면 게이트 — 같은 법, 실물 주소 (D-201/202/203/214/220).

옵트인: ROSY_LIVE_DASHBOARD_URL(및 선택적으로 ROSY_LIVE_FLEET_URL,
ROSY_LIVE_GAMES_URL)이 가리키는 실물 표면에 계측 센서스를 그대로 돌린다.
픽스처도 오버라이드도 없다 — 법은 어떤 상태에서나 성립해야 하므로,
현재 렌더된 그 상태 그대로를 잔다(D-91: 증거 계층만 다를 뿐 같은 계약).

실행(로봇 AP에 붙은 상태):
    $env:ROSY_RUN_BROWSER_TESTS="1"
    $env:ROSY_LIVE_DASHBOARD_URL="http://192.168.0.7:8080/dashboard"
    python -m pytest test/test_live_surface_gates.py -q

콘솔은 operate/inspect 양 뷰를 모두 잰다(화면 전환은 실물 컨트롤로).
상태를 강제하는 게이트(safe-stop 분쇄 검사 등)는 픽스처 묶음에만 산다 —
실물에서 위험 상태를 인위적으로 만들지 않는다.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from browser_harness import open_page

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
        reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
    ),
    pytest.mark.skipif(
        not os.environ.get("ROSY_LIVE_DASHBOARD_URL"),
        reason="set ROSY_LIVE_DASHBOARD_URL to a live surface (bench)",
    ),
]


CENSUS = """() => {
  const cs = getComputedStyle(document.documentElement);
  const ctx = document.createElement('canvas').getContext('2d');
  const norm = (v) => { ctx.fillStyle = v.trim(); return ctx.fillStyle; };
  const warm = new Set([norm(cs.getPropertyValue('--status-warn')),
                        norm(cs.getPropertyValue('--status-crit'))]);
  const STEPS = new Set(['12px', '14px', '16px', '18px', '20px', '32px']);
  const effBg = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const s = getComputedStyle(node);
      const m = s.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
      if (m && (m[1].split(',').length < 4 || Number(m[1].split(',')[3]) === 1)) {
        return s.backgroundColor;
      }
      node = node.parentElement;
    }
    return cs.getPropertyValue('--ground');
  };
  const lum = (c) => {
    let r, g, b;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.replace(/[^#]/g, (x) => x + x) : c;
      r = parseInt(h.slice(1, 3), 16); g = parseInt(h.slice(3, 5), 16);
      b = parseInt(h.slice(5, 7), 16);
    } else {
      const m = c.match(/rgba?\\(([^)]+)\\)/);
      if (!m) return null;
      [r, g, b] = m[1].split(',').map(Number);
    }
    const f = (v) => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const off = { floor: [], scale: [], warm: [], motion: [] };
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if ((s.transitionDuration !== '0s' && s.transitionProperty !== 'none')
        || s.animationName !== 'none') {
      off.motion.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
        + ` t=${s.transitionDuration}/${s.transitionProperty} a=${s.animationName}`);
    }
    if (!(el.textContent.trim() && el.children.length === 0)) continue;
    const color = norm(s.color);
    const la = lum(color), lb = lum(effBg(el));
    if (la !== null && lb !== null) {
      const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
      const floor = parseFloat(s.fontSize) >= 24 ? 3.0 : 4.5;
      if (ratio < floor) {
        off.floor.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
          + ` ${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 14)}"`);
      }
    }
    if (warm.has(color)) {
      const la = lum(color), lb = lum(effBg(el));
      if (la !== null && lb !== null) {
        const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
        if (ratio < 4.5) {
          off.warm.push(`${el.tagName.toLowerCase()}#${el.id || '-'}`
            + ` ${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 14)}"`);
        }
      }
    }
    if (!STEPS.has(s.fontSize)) {
      off.scale.push(`${s.fontSize} ${el.tagName.toLowerCase()}#${el.id || '-'}`);
    }
  }
  return off;
}"""


def _host_of(url: str) -> str:
    return urlparse(url).netloc


def _censuses(page, label: str, failures: list[str]) -> None:
    off = page.evaluate(CENSUS)
    for kind in ("floor", "warm", "scale", "motion"):
        if off[kind]:
            failures.append(f"[{label}/{kind}] " + "; ".join(off[kind][:4]))


def test_live_dashboard_keeps_the_craft_contracts():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    url = os.environ["ROSY_LIVE_DASHBOARD_URL"]
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1536, 864)
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
        _censuses(page, f"{_host_of(url)} operate", failures)
        switch = page.locator("#view-inspect")
        if switch.count():
            switch.click()
            page.wait_for_timeout(800)
            _censuses(page, f"{_host_of(url)} inspect", failures)
        if errors:
            failures.append(f"[{_host_of(url)} pageerror] " + "; ".join(errors[:3]))
        browser.close()

    assert failures == [], (
        "실물 표면이 공예 계약을 어겼다 (D-201/202/203/214/220): "
        + " | ".join(failures[:8])
    )


@pytest.mark.skipif(
    not os.environ.get("ROSY_LIVE_FLEET_URL"),
    reason="set ROSY_LIVE_FLEET_URL to a live fleet console (bench)",
)
def test_live_fleet_keeps_the_craft_contracts():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    url = os.environ["ROSY_LIVE_FLEET_URL"]
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1920, 1080)
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
        _censuses(page, f"{_host_of(url)} fleet", failures)
        if errors:
            failures.append(f"[{_host_of(url)} pageerror] " + "; ".join(errors[:3]))
        browser.close()

    assert failures == [], (
        "실물 Fleet이 공예 계약을 어겼다: " + " | ".join(failures[:8])
    )


@pytest.mark.skipif(
    not os.environ.get("ROSY_LIVE_GAMES_URL"),
    reason="set ROSY_LIVE_GAMES_URL to a live match board (bench)",
)
def test_live_games_keeps_the_craft_contracts():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    url = os.environ["ROSY_LIVE_GAMES_URL"]
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1280, 800)
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
        _censuses(page, f"{_host_of(url)} games", failures)
        if errors:
            failures.append(f"[{_host_of(url)} pageerror] " + "; ".join(errors[:3]))
        browser.close()

    assert failures == [], (
        "실물 경기 보드가 공예 계약을 어겼다: " + " | ".join(failures[:8])
    )
