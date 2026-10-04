"""Capture a theme×viewport round of the CORE role surfaces (D-359 §7.8).

Serves the real dashboard (FastAPI TestClient + Pinky Pro profile + development
authentication overlay) through Playwright route interception — the same
machinery as ``web_visible_roles.py`` — and saves one screenshot per
surface × theme × viewport, plus ``report.json``.

The declared round (D-359 §7.8): role surfaces × {dark, light} ×
{desktop, 390×844, 320×568}. The theme is chosen before any page script runs
(``localStorage.rosy.theme``, theme.js) so the capture shows the real themed
paint, not a toggle after-effect.

Examples:

    python tools/capture_surface_round.py --out-dir docs/validation/web-theme-tiers-2026-10-04
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
for _entry in (
    "middleware/core/gateway",
    "middleware/core/api_web",
    "contracts/foundation",
    "middleware/core/events",
    "middleware/core/services",
    "shared/web",
    "contracts/ros_idl",
):
    _path = str(ROOT / _entry)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import yaml  # noqa: E402

TOKEN_KEY = "rosy.dashboard.token"
THEME_KEY = "rosy.theme"

#: 관리자 토큰으로 세 표면을 모두 담는다 — 이 회차의 관심은 테마·뷰포트이지 역할 차이가 아니다.
ROLE = ("administrator", "rosy-dev-admin", ("console", "setup", "device"))
THEMES = ("dark", "light")
VIEWPORTS = ((1280, 800), (390, 844), (320, 568))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="round folder, e.g. docs/validation/web-theme-tiers-2026-10-04")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    role, token, surfaces = ROLE
    with tempfile.TemporaryDirectory() as tmp:
        from web_visible_roles import build_client  # 같은 폴더 계측의 부팅을 그대로 쓴다

        client = build_client(Path(tmp))
        errors: list[str] = []
        rows = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": VIEWPORTS[0][0],
                                                    "height": VIEWPORTS[0][1]})
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            for theme in THEMES:
                page.add_init_script(
                    f"localStorage.setItem({THEME_KEY!r}, {theme!r});")
                for surface in surfaces:
                    for width, height in VIEWPORTS:
                        page.set_viewport_size({"width": width, "height": height})
                        responses: list[tuple[str, int]] = []

                        def serve(route, _request):
                            target = urlsplit(route.request.url).path
                            response = client.get(
                                target, headers={"Authorization": f"Bearer {token}"})
                            responses.append((target, response.status_code))
                            route.fulfill(
                                status=response.status_code,
                                headers={
                                    "content-type": response.headers.get(
                                        "content-type", "application/octet-stream"),
                                    "cache-control": "no-store",
                                },
                                body=response.content)

                        page.unroute_all()
                        page.route("**/*", serve)
                        page.goto(f"http://rosy.test/{surface}", wait_until="load")
                        page.wait_for_timeout(700)
                        applied = page.evaluate(
                            "document.documentElement.getAttribute('data-theme')")
                        shot = args.out_dir / f"robot-{surface}-{theme}-{width}x{height}.png"
                        page.screenshot(path=str(shot), full_page=True)
                        rows.append({"surface": surface, "theme": theme,
                                     "viewport": f"{width}x{height}",
                                     "data-theme": applied,
                                     "badResponses": [r for r in responses if r[1] >= 400][:3]})
            context.close()
            browser.close()

    report = {"rows": rows, "pageErrors": errors, "generated": time.strftime("%F %T")}
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = [f"{r['surface']}/{r['theme']}@{r['viewport']}: data-theme={r['data-theme']!r} "
           f"bad={r['badResponses']}" for r in rows
           if r["data-theme"] != r["theme"] or r["badResponses"]]
    for line in bad:
        print(f"PROBLEM {line}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} page error(s): {errors[:3]}", file=sys.stderr)
    print(f"captured {len(rows)} cells into {args.out_dir}")
    return 1 if (bad or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
