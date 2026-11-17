"""Shared helpers for the optional Chromium regressions (D-153 G2 캡처 훅).

렌더는 표면마다 다르지만 실행기·오류 수집·confirm 스텁·스크린샷 저장의 배관은
그렇지 않다. `robot_contracts.py` 의 공유 헬퍼 관례를 따른다 — D-92 는 제품
표면의 컴포넌트 공유를 금지할 뿐, 시험 도구의 공유는 다른 문제다.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

# Chromium net/base/port_util.cc kRestrictedPorts: page loads to these fail with
# net::ERR_UNSAFE_PORT. Windows hosts whose dynamic port range starts at 1024
# (`netsh int ipv4 show dynamicport tcp`) hand them out for port 0 (2049 seen 2026-10-07).
CHROMIUM_RESTRICTED_PORTS = frozenset({
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
    101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
    179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
    587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060,
    5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080,
})


def browser_tests_enabled() -> bool:
    """Opt-in for real-Chromium tests. `ROSY_RUN_BROWSER_TESTS=1` is canonical;
    `ROSY_BROWSER_TESTS=1` (the older Fleet name) is accepted too."""
    return "1" in (os.environ.get("ROSY_RUN_BROWSER_TESTS"), os.environ.get("ROSY_BROWSER_TESTS"))


def goto_with_network_change_retry(page, url):
    """Retry initial navigation once when Chromium aborts a document/script on network change."""
    changes = []

    def failed(request):
        if request.resource_type in ('document', 'script') and request.failure == 'net::ERR_NETWORK_CHANGED':
            changes.append(request.failure)

    page.on('requestfailed', failed)
    try:
        for attempt in range(2):
            changes.clear()
            try:
                response = page.goto(url)
            except Exception as error:
                if 'net::ERR_NETWORK_CHANGED' not in str(error):
                    raise
                changes.append(str(error))
            if not changes:
                return response
            if attempt:
                raise RuntimeError('net::ERR_NETWORK_CHANGED persisted across initial navigation retry')
            print('Chromium ERR_NETWORK_CHANGED: retrying initial navigation once')
    finally:
        page.remove_listener('requestfailed', failed)


def open_token_access(page) -> None:
    """Open the paired console's token fallback before using its controls."""
    try:  # a polling console may never go idle; the wait only covers the auth refresh
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception as error:  # playwright TimeoutError, imported lazily like the rest of the harness
        if type(error).__name__ != "TimeoutError":
            raise
    # Reconnect publishes selections before finishing; open after its controls settle.
    page.wait_for_function("() => !document.getElementById('token-save')?.disabled")
    # D-540 2: below 90rem the token sits in the header fold behind 설정.
    toggle = page.locator("#topbar-more")
    if toggle.is_visible() and toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    details = page.locator("#token-access")
    if details.get_attribute("open") is None:
        details.locator("summary").click()


def safe_listener(host: str = "127.0.0.1") -> socket.socket:
    """A socket bound to a free port Chromium will load (never a restricted one)."""
    for _ in range(64):
        listener = socket.socket()
        listener.bind((host, 0))
        if listener.getsockname()[1] not in CHROMIUM_RESTRICTED_PORTS:
            return listener
        listener.close()
    raise RuntimeError("could not allocate a browser-safe local port")


def safe_http_server(handler_cls, *, server_cls=ThreadingHTTPServer, host: str = "127.0.0.1"):
    """`server_cls` serving on an already-bound `safe_listener()` socket (no bind race)."""
    listener = safe_listener(host)
    server = server_cls(listener.getsockname(), handler_cls, bind_and_activate=False)
    server.socket.close()
    server.socket = listener
    # What HTTPServer.server_bind() would have set (handlers read server_port).
    server.server_address = listener.getsockname()
    server.server_name, server.server_port = host, server.server_address[1]
    server.server_activate()
    return server


def free_port(host: str = "127.0.0.1") -> int:
    """A browser-safe free port, closed before return, so another bind can take it first.
    Use only for a server API that accepts nothing but a port number."""
    with safe_listener(host) as listener:
        return listener.getsockname()[1]


def launch_options() -> dict:
    options = {"headless": True, "timeout": 10_000}
    if channel := os.environ.get("ROSY_BROWSER_CHANNEL"):
        options["channel"] = channel
    return options


def open_page(playwright, width: int, height: int, *, url: str | None = None):
    """Chromium 실행 + 페이지 오류 수집. 호출자이 browser.close() 한다."""
    options = launch_options()
    if url and (port := urlsplit(url).port):
        options["args"] = [f"--explicitly-allowed-ports={port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # 기본 대기 예산은 15초다(2026-09-25). 5초는 경합 중인 호스트에서
    # goto(networkidle)·wait_for_function 을 계약과 무관하게 쓰러뜨렸다 —
    # 플레이크 사후 처리 3건이 같은 원인이었다. 계약 자체의 타임아웃은
    # 호출처에서 이미 명시적으로 지정한다.
    page.set_default_timeout(15_000)
    return browser, page, errors


# D-741 — what a Fleet document's body still offers once the rail and the sub-nav took their seats: sideways overflow,
# sub-nav entries that are off screen or under something, grids whose cells got narrow, buttons and selects whose own
# text is cut (a text input scrolls its value, so it is not counted), controls that reach past the window, and the
# stop. A grid with nothing visible in it is left out. The caller decides what is too narrow.
BODY_FIT = """() => {
  const seen = (node) => node.checkVisibility({visibilityProperty: true}) && node.getClientRects().length > 0;
  const onTop = (node) => { const r = node.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth
      && node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); };
  const ctx = document.createElement('canvas').getContext('2d');
  const cut = [];
  for (const node of document.querySelectorAll('main :is(ui-button, select)')) {
    if (!seen(node)) continue;
    const style = getComputedStyle(node);
    let need = node.scrollWidth;
    if (node.matches('select')) {
      ctx.font = style.font;
      need = ctx.measureText(node.selectedOptions[0]?.textContent ?? '').width
        + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    }
    if (need > node.clientWidth + 1) cut.push(`${node.id || node.tagName} needs ${Math.round(need)} has ${node.clientWidth}`);
  }
  const cells = (node) => [...node.children].filter(seen).map((child) => child.getBoundingClientRect().width);
  const grids = [...document.querySelectorAll('main :is(.form, .scope, .draft-actions, .documents, .map-workflow)')]
    .filter((node) => seen(node) && cells(node).length).map((node) => ({
      name: node.id || node.className, columns: getComputedStyle(node).gridTemplateColumns.split(' ').length,
      width: Math.round(node.getBoundingClientRect().width), narrowest: Math.round(Math.min(...cells(node))),
    }));
  const outside = [...document.querySelectorAll('main :is(ui-button, select, input, textarea)')].filter((node) => {
    const r = node.getBoundingClientRect();
    return seen(node) && (r.left < -1 || r.right > innerWidth + 1);
  }).map((node) => node.id || node.tagName);
  const nav = document.querySelector('.fleet-body > .ui-subnav > nav'), box = nav.getBoundingClientRect();
  const stop = document.getElementById('estop');
  return {
    overflow: document.documentElement.scrollWidth - innerWidth,
    body: Math.round(document.querySelector('main').getBoundingClientRect().width),
    nav: {column: getComputedStyle(nav).flexDirection === 'column', top: Math.round(box.top), bottom: Math.round(box.bottom)},
    unreachable: [...nav.querySelectorAll('a')].filter((link) => !onTop(link)).map((link) => link.textContent),
    grids, cut, outside, stop: onTop(stop),
  };
}"""


DECLINE_CONFIRM = """
    window.__confirms = [];
    window.confirm = (message) => { window.__confirms.push(String(message)); return false; };
"""


def accept_confirm(page) -> None:
    """이후 confirm 을 수락한다. 표현식을 `; null` 로 닫는다 — Playwright
    evaluate 의 완료값이 함수면 그 함수를 무인자 호출하기 때문이다(D-153 회차 3
    발견)."""
    page.evaluate(
        "window.confirm = (message) => { window.__confirms.push(String(message));"
        " return true; }; null"
    )


def save_temp_screenshot(page, name: str, **options) -> Path:
    root = os.environ.get("ROSY_UIUX_SCREENSHOT_DIR") or os.environ.get("TEMP", "/tmp")
    shot = Path(root) / name
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), **options)
    print(f"\nscreenshot: {shot}")
    return shot


def confirm_irreversible(page, accept=True):
    """공용 확인 창(dialog.ui-confirm)을 실행 또는 취소로 닫는다."""
    dialog = page.locator('dialog.ui-confirm')
    dialog.wait_for(state='visible')
    dialog.locator('ui-button[kind="irreversible"]' if accept else 'ui-button:has-text("취소")').click()
    dialog.wait_for(state='hidden')


LAYOUT_GEOMETRY_PROBE = """() => {
  const seen = (node) => Boolean(
    node && node.nodeType === 1
    && node.checkVisibility?.({visibilityProperty: true})
    && node.getClientRects().length > 0
  );
  const violations = [];
  const labelOf = (node) => {
    if (!node) return 'null';
    const id = node.id ? `#${node.id}` : '';
    const cls = typeof node.className === 'string' && node.className.trim()
      ? '.' + node.className.trim().split(/\\s+/).slice(0, 2).join('.')
      : '';
    return `${node.tagName.toLowerCase()}${id}${cls}`;
  };
  const allowed = (node, rule) => {
    const attr = node?.closest?.(`[data-geometry-allow*="${rule}"]`);
    return Boolean(attr);
  };

  // G1: Under-fill in vertical stack containers (e.g. #robot-overview-list trapped in column 1 of .roster-block)
  for (const stack of document.querySelectorAll('.roster-block, .console-secondary, .context-panel, .robot-overview-list, .robot-overview-group')) {
    if (!seen(stack)) continue;
    const sStyle = getComputedStyle(stack);
    const padX = (parseFloat(sStyle.paddingLeft) || 0) + (parseFloat(sStyle.paddingRight) || 0);
    const innerW = stack.clientWidth - padX;
    if (innerW < 120) continue;
    const kids = [...stack.children].filter((k) => seen(k) && ![' absolute', ' fixed'].includes(' ' + getComputedStyle(k).position));
    for (const child of kids) {
      if (allowed(child, 'G1')) continue;
      if (!child.matches('section, ul, ol, dl, details, .robot-overview-list, .robot-overview-group, .robot-overview-items, .queues-panel, .console-context')) continue;
      const r = child.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const hasRowPeer = kids.some((peer) => {
        if (peer === child) return false;
        const pr = peer.getBoundingClientRect();
        return Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top) > 2;
      });
      if (hasRowPeer) continue;
      if (r.width < innerW * 0.92 && (innerW - r.width) > 12) {
        violations.push(`G1 underfill: ${labelOf(child)} width ${Math.round(r.width)}px < 92% of ${labelOf(stack)} innerWidth ${Math.round(innerW)}px`);
      }
    }
  }

  // G2: Sibling overlap & right-edge overflow in header/item rows (roster rows and the app topbar too)
  for (const row of document.querySelectorAll('.robot-overview-head, .robot-head, .map-head, .omx-cell-top, .robot-row, ui-topbar')) {
    if (!seen(row) || allowed(row, 'G2')) continue;
    const rowRect = row.getBoundingClientRect();
    // Only an explicit horizontal-scroll component (data-scroll-x) skips the right-edge check.
    const scrollsX = row.hasAttribute('data-scroll-x');
    const kids = [...row.children].filter((k) => {
      if (!seen(k) || k.classList.contains('sr-only') || k.classList.contains('spacer')) return false;
      const ks = getComputedStyle(k);
      return ks.position !== 'absolute' && ks.position !== 'fixed' && ks.pointerEvents !== 'none';
    });
    for (let i = 0; i < kids.length; i += 1) {
      const a = kids[i], ar = a.getBoundingClientRect();
      if (!scrollsX && ar.right > rowRect.right + 2) {
        violations.push(`G2 overflow: ${labelOf(a)} right ${Math.round(ar.right)} > ${labelOf(row)} right ${Math.round(rowRect.right)}`);
      }
      for (let j = i + 1; j < kids.length; j += 1) {
        const b = kids[j], br = b.getBoundingClientRect();
        const ox = Math.min(ar.right, br.right) - Math.max(ar.left, br.left);
        const oy = Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top);
        if (ox > 2 && oy > 2 && ox * oy > 4) {
          violations.push(`G2 overlap: ${labelOf(a)} and ${labelOf(b)} in ${labelOf(row)} overlap by ${Math.round(ox)}x${Math.round(oy)}px`);
        }
      }
    }
  }

  // G3: Crushed robot names / badges (> 2.2 lines, or nowrap clipping below 10 visible chars)
  for (const node of document.querySelectorAll('.robot-overview-name > strong, .robot-name > b')) {
    if (!seen(node) || allowed(node, 'G3')) continue;
    const r = node.getBoundingClientRect();
    const s = getComputedStyle(node);
    const padY = (parseFloat(s.paddingTop) || 0) + (parseFloat(s.paddingBottom) || 0) + (parseFloat(s.borderTopWidth) || 0) + (parseFloat(s.borderBottomWidth) || 0);
    const lh = parseFloat(s.lineHeight) || ((parseFloat(s.fontSize) || 14) * 1.25);
    const lines = (r.height - padY) / lh;
    if (lines > 2.2) {
      violations.push(`G3 crushed-text: ${labelOf(node)} ("${node.textContent.trim().slice(0, 24)}") wrapped into ${lines.toFixed(1)} lines`);
    }
    const text = (node.textContent || '').trim();
    const shown = text.length * node.clientWidth / node.scrollWidth;
    if (text && node.scrollWidth > node.clientWidth + 1 && shown < 10) {
      violations.push(`G3 clipped-text: ${labelOf(node)} ("${text.slice(0, 24)}") clipped to ~${Math.max(0, Math.round(shown))} of ${text.length} chars`);
    }
  }

  // G4: Box-in-box nesting depth <= 2 for 4-sided bordered layout containers
  const isBorderedBox = (node) => {
    if (!seen(node) || allowed(node, 'G4')) return false;
    if (node.matches('button, ui-button, input, select, textarea, label, ui-tag, table, th, td, canvas, svg, .map-stage, .vision-frame')) return false;
    const r = node.getBoundingClientRect();
    if (r.width < 48 || r.height < 36 || r.width * r.height < 3600) return false;
    const s = getComputedStyle(node);
    const sides = [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth].map((v) => parseFloat(v) || 0);
    if (Math.min(...sides) < 1) return false;
    const colors = [s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor];
    return colors.every((c) => c && c !== 'transparent' && !/rgba?\\([^)]*,\\s*0(?:\\.0+)?\\)/.test(c));
  };
  for (const node of document.querySelectorAll('main div, main section, main article, main aside, main details, main ul, main li')) {
    if (!isBorderedBox(node)) continue;
    const chain = [labelOf(node)];
    let cur = node.parentElement;
    while (cur && cur !== document.body) {
      if (isBorderedBox(cur)) chain.unshift(labelOf(cur));
      cur = cur.parentElement;
    }
    if (chain.length > 2) {
      violations.push(`G4 box-in-box (${chain.length} levels): ${chain.join(' > ')}`);
    }
  }

  // G5: Floating launcher (#assistant-fab) vs #robot-dock-mount / #estop / open robot sheet (#robot-panel-mount) collision.
  // 모바일 시트가 열리면 CSS가 실행기를 visibility:hidden으로 물러나게 하므로 seen()이 잡고,
  // 단추가 시트 바닥의 비상 정지·주행 취소 단추를 덮으면 이 검사가 위반으로 돌린다.
  const openDialog = document.querySelector('dialog[open], [role="dialog"]:not([hidden])');
  if (!openDialog) {
    const fab = document.getElementById('assistant-fab');
    if (seen(fab) && !allowed(fab, 'G5')) {
      const fr = fab.getBoundingClientRect();
      for (const id of ['robot-dock-mount', 'estop', 'robot-panel-mount']) {
        const target = document.getElementById(id);
        if (!seen(target)) continue;
        const tr = target.getBoundingClientRect();
        const ox = Math.min(fr.right, tr.right) - Math.max(fr.left, tr.left);
        const oy = Math.min(fr.bottom, tr.bottom) - Math.max(fr.top, tr.top);
        if (ox > 2 && oy > 2) {
          violations.push(`G5 floating-dock-collision: #assistant-fab overlaps #${id} by ${Math.round(ox)}x${Math.round(oy)}px`);
        }
      }
    }
  }

  // G6-fn-begin
  // Full phrases (label + age) repeated 2+ times; same number under different labels is fine.
  const repeatedFreshness = (raw) => {
    const re = /\\d+(?:\\.\\d+)?\\s*(?:초|분|시간)\\s*전/g;
    const text = raw.replace(/\\s+/g, ' ');
    const stamps = text.match(re) || [];
    const gaps = text.split(re);
    const counts = new Map();
    stamps.forEach((stamp, i) => {
      const label = (gaps[i].match(/(?:[가-힣A-Za-z]+ )?[가-힣A-Za-z]+ ?: ?$|[가-힣A-Za-z]+ ?$|· ?$/) || [''])[0];
      const phrase = (label + stamp).trim();
      counts.set(phrase, (counts.get(phrase) || 0) + 1);
    });
    return [...counts].filter(([, n]) => n > 1).map(([phrase, count]) => ({ phrase, count }));
  };
  // G6-fn-end

  // G6: Duplicate freshness timestamp inside a single robot overview/roster row (visible text only)
  for (const item of document.querySelectorAll('.robot-overview-item, .robot-row')) {
    if (!seen(item) || allowed(item, 'G6')) continue;
    const visible = item.cloneNode(true);
    visible.querySelectorAll('.sr-only, [aria-hidden="true"]').forEach((hidden) => hidden.remove());
    const hits = repeatedFreshness(visible.textContent || '');
    if (hits.length) {
      violations.push(`G6 duplicate-freshness: ${labelOf(item)} (${item.dataset.robotId || ''}) repeats freshness ${hits.reduce((n, h) => n + h.count, 0)} times: ${hits.map((h) => `${h.phrase} x${h.count}`).join(', ')}`);
    }
  }

  // G7: Alert toast region must never overlap right-column, drawer, popover, or stage-head surfaces
  const region = document.getElementById('alert-popup-region');
  if (region && region.childElementCount > 0 && !allowed(region, 'G7')) {
    const rr = region.getBoundingClientRect();
    if (rr.width > 0 && rr.height > 0) {
      for (const sel of ['.queues-panel', '#robot-panel-mount', '#topbar-extra[data-open="true"]', '#assistant-panel:not([hidden])', '.map-head']) {
        for (const node of document.querySelectorAll(sel)) {
          if (!seen(node)) continue;
          const tr = node.getBoundingClientRect();
          const ox = Math.min(rr.right, tr.right) - Math.max(rr.left, tr.left);
          const oy = Math.min(rr.bottom, tr.bottom) - Math.max(rr.top, tr.top);
          if (ox > 2 && oy > 2) {
            violations.push(`G7 alert-overlap: #alert-popup-region overlaps ${labelOf(node)} by ${Math.round(ox)}x${Math.round(oy)}px`);
          }
        }
      }
    }
  }

  return violations;
}"""


def assert_layout_geometry(page) -> None:
    """Assert G1-G7 rendered geometry invariants (underfill, sibling overlap/overflow, crushed text, box-in-box, assistant-fab collision, duplicate freshness age, alert-region overlap)."""
    page.evaluate("() => document.fonts ? document.fonts.ready.then(() => null) : null")
    violations = page.evaluate(LAYOUT_GEOMETRY_PROBE)
    assert violations == [], "Layout geometry violations:\n  - " + "\n  - ".join(violations)

