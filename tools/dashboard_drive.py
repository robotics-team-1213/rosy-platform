"""Drive and read the CORE dashboard in headless Chromium (Python Playwright).

Examples (the token file holds one API or paired token; keep it outside the repo):

    python tools/dashboard_drive.py --base-url http://<robot-ip>:8080 --token-file X:/DevTemp/rosy.token status
    python tools/dashboard_drive.py ... mode MANUAL
    python tools/dashboard_drive.py ... teleop --direction forward --seconds 1.0
    python tools/dashboard_drive.py ... screenshot --view inspect --out X:/DevTemp/inspect.png

`teleop` moves a real robot. Lift the wheels first; the command ticks `#bench-safety-confirmed`
for you only because you asked for motion. It prints the measured stop latency: the time
from releasing the button until `/api/v1/robot/state` reports zero velocity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

TOKEN_KEY = "rosy.dashboard.token"
MODES = ("IDLE", "MANUAL", "NAVIGATION")
DIRECTIONS = ("forward", "backward", "left", "right")
READ_APIS = ("/api/v1/robot/state", "/api/v1/safety/state", "/api/v1/host/commissioning",
             "/api/v1/host/hardware")

#: Calls the robot's API from inside the page, with the token the page itself uses.
API_GET = """async (path) => {
    const token = sessionStorage.getItem('rosy.dashboard.token') || '';
    const response = await fetch(path, {headers: {Authorization: 'Bearer ' + token}});
    let body = null;
    try { body = await response.json(); } catch (_error) { body = null; }
    return {status: response.status, body};
}"""


def token_init_script(token: str) -> str:
    return f"sessionStorage.setItem({json.dumps(TOKEN_KEY)}, {json.dumps(token)});"


def open_dashboard(playwright, base_url: str, token: str, width: int = 1366, height: int = 900):
    """Launch Chromium with the token injected before any dashboard script runs."""
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(15_000)
    page.add_init_script(script=token_init_script(token))
    # Mode changes and other irreversible actions go through window.confirm; an
    # unhandled dialog is dismissed and the action silently does not happen.
    page.on("dialog", lambda dialog: dialog.accept())
    # "load", never "networkidle": the dashboard polls and streams, so the
    # network is never idle and networkidle waits until the timeout.
    page.goto(base_url.rstrip("/") + "/dashboard", wait_until="load")
    page.wait_for_function("document.getElementById('robot-mode')?.textContent?.trim()")
    return browser, page


def api_get(page, path: str) -> dict:
    return page.evaluate(API_GET, path)


def status(page) -> dict:
    result = {"robot_mode_shown": page.locator("#robot-mode").inner_text().strip()}
    for path in READ_APIS:
        result[path] = api_get(page, path)
    return result


def _robot_state(page) -> dict:
    reply = api_get(page, "/api/v1/robot/state")
    return reply["body"] if reply["status"] == 200 and isinstance(reply["body"], dict) else {}


def set_mode(page, mode: str, timeout_s: float = 5.0) -> dict:
    page.locator(f'.mode-control [data-mode="{mode}"]').click()
    deadline = time.monotonic() + timeout_s
    current = None
    while time.monotonic() < deadline:
        current = _robot_state(page).get("mode")
        if current == mode:
            break
        page.wait_for_timeout(100)
    return {"requested": mode, "mode": current, "reached": current == mode}


def _moving(state: dict) -> bool:
    velocity = state.get("velocity") or {}
    return any(abs(float(velocity.get(axis) or 0.0)) > 1e-3 for axis in ("linear", "angular"))


def teleop(page, direction: str, seconds: float, stop_timeout_s: float = 3.0) -> dict:
    """Hold a teleop button like a person does, then measure how fast the robot stops."""
    page.locator("#bench-safety-confirmed").check()
    button = page.locator(f'[data-teleop="{direction}"]')
    page.wait_for_function(
        f"!document.querySelector('[data-teleop=\"{direction}\"]')?.disabled", timeout=5_000)
    button.hover()
    samples = []
    started = time.monotonic()
    page.mouse.down()
    try:
        while time.monotonic() - started < seconds:
            state = _robot_state(page)
            samples.append({"t": round(time.monotonic() - started, 3), "velocity": state.get("velocity")})
    finally:
        page.mouse.up()
    released = time.monotonic()
    stopped_after = None
    while time.monotonic() - released < stop_timeout_s:
        if not _moving(_robot_state(page)):
            stopped_after = round(time.monotonic() - released, 3)
            break
        page.wait_for_timeout(20)
    return {"direction": direction, "held_s": round(released - started, 3), "samples": samples,
            "moved": any(_moving({"velocity": s["velocity"]}) for s in samples),
            "stop_latency_s": stopped_after}


def screenshot(page, out: Path, view: str = "operate") -> Path:
    page.locator(f"#view-{view}").click()
    page.wait_for_timeout(300)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), full_page=True)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="e.g. http://<robot-ip>:8080")
    parser.add_argument("--token-file", required=True, type=Path, help="file holding one API token")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="print robot/safety/commissioning/hardware APIs")
    mode = actions.add_parser("mode", help="click a mode button (confirm is accepted)")
    mode.add_argument("mode", choices=MODES)
    mode.add_argument("--timeout", type=float, default=5.0)
    drive = actions.add_parser("teleop", help="hold a teleop button; wheels must be lifted")
    drive.add_argument("--direction", choices=DIRECTIONS, required=True)
    drive.add_argument("--seconds", type=float, required=True)
    shot = actions.add_parser("screenshot", help="save a full-page screenshot")
    shot.add_argument("--out", type=Path, required=True)
    shot.add_argument("--view", choices=("operate", "inspect"), default="operate")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "teleop" and not 0 < args.seconds <= 5:
        print("--seconds must be in (0, 5]", file=sys.stderr)
        return 2
    token = args.token_file.read_text(encoding="utf-8").strip()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page = open_dashboard(playwright, args.base_url, token)
        try:
            if args.action == "status":
                result = status(page)
            elif args.action == "mode":
                result = set_mode(page, args.mode, args.timeout)
            elif args.action == "teleop":
                result = teleop(page, args.direction, args.seconds)
            else:
                result = {"screenshot": str(screenshot(page, args.out, args.view))}
        finally:
            browser.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == "mode" and not result["reached"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
