"""Capture a Fleet-console + games-board round (D-359 remainder of §7.8).

Serves the real Fleet app (FastAPI + two fake robots) and the real games
match-board preview through Playwright route interception, with no network
and no ROS. Saves one screenshot per surface × viewport, plus ``report.json``
(data-theme, first responses, page errors).

Declared round: console × {1920×1080, 390×844, 320×568} + games ×
{1280×800, 390×844, 320×568}. Fleet is dark-pinned (themes: [dark] in
surfaces.yaml); games keeps its own pitch palette.

Examples:

    python operations/fleet/tools/capture_console_games_round.py \
        --out-dir docs/validation/fleet-games-capture-2026-10-04
"""

# 배치 규칙(tools/AGENTS.md): 여러 패키지를 엮는 스크립트는 모듈 tools/에 둔다.
# fleet 모듈 tools/가 게임을 엮으므로 이 스크립트는 순수 측정 역할만 한다.

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    "operations/fleet",
    "operations/fleet/test",
    "contracts/foundation",
    "middleware/core/services",
    "operations/apps/games",
):
    _path = str(REPO / _entry)
    if _path not in sys.path:
        sys.path.insert(0, _path)

FLEET_VIEWPORTS = ((1920, 1080), (390, 844), (320, 568))
GAMES_VIEWPORTS = ((1280, 800), (390, 844), (320, 568))
FLEET_TOKEN = "dev-operator"


def build_fleet_client(tmp: Path):
    from fastapi.testclient import TestClient

    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint

    robots = [FakeRobot("rosy_01"), FakeRobot("rosy_02")]
    endpoints = [RobotEndpoint(robot_id=r.robot_id,
                               base_url=f"http://127.0.0.1:808{i}", token="t")
                 for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, list(robots))
    return TestClient(create_app(console, console_token=FLEET_TOKEN))


def _route_from(client):
    def serve(route, _request):
        target = urlsplit(route.request.url).path
        headers = {}
        if target.startswith("/api/") or target.startswith("/console"):
            headers = {"Authorization": f"Bearer {FLEET_TOKEN}"}
            response = client.get(target, headers=headers)
            route.fulfill(status=response.status_code,
                          headers={"content-type": response.headers.get(
                              "content-type", "application/octet-stream"),
                                   "cache-control": "no-store"},
                          body=response.content)
        else:
            route.continue_()
    return serve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed", file=sys.stderr)
        return 2

    import tempfile

    errors: list[str] = []
    rows = []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        client = build_fleet_client(Path(tmp))
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", _route_from(client))
        page.goto("http://fleet.test/console", wait_until="load")
        page.wait_for_timeout(700)
        for width, height in FLEET_VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(400)
            shot = args.out_dir / f"console-{width}x{height}.png"
            page.screenshot(path=str(shot), full_page=True)
            rows.append({"surface": "console", "viewport": f"{width}x{height}"})
        # Games board — 실제 preview 서버(127.0.0.1 임시 포트, D-101 --preview).
        from games.host.preview import PreviewBoard, PreviewServer

        preview = PreviewServer(PreviewBoard(), host="127.0.0.1", port=0)
        games_base = preview.start()
        try:
            for width, height in GAMES_VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                page.goto(f"{games_base}/", wait_until="load")
                page.wait_for_timeout(500)
                shot = args.out_dir / f"games-{width}x{height}.png"
                page.screenshot(path=str(shot), full_page=True)
                rows.append({"surface": "games", "viewport": f"{width}x{height}"})
        finally:
            preview.close()
        page.close()
        browser.close()

    report = {"rows": rows, "pageErrors": errors, "generated": time.strftime("%F %T")}
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"captured {len(rows)} cells into {args.out_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
