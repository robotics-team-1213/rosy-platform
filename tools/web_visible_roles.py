"""Measure the role surfaces of the CORE dashboard in headless Chromium.

Stands up a real CORE (FastAPI TestClient + CoreServices with the Pinky Pro
profile and the development authentication overlay), serves the dashboard
through Playwright route interception, and measures what the design-system
contracts care about across roles and viewports:

- every ``ui-button`` names its ``kind`` (``data-kind-missing`` count is 0)
- no page errors while any surface loads
- no positive horizontal overflow at 1366x768 or 390x844
- the first asset/API responses are not failures

Exit status is 0 only when every check passes, so this can be a gate
command. Screenshots and the full JSON report land in ``--out-dir``.

Examples:

    python tools/web_visible_roles.py
    python tools/web_visible_roles.py --out-dir X:/DevTemp/visible-roles
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
    "src/runtime/gateway",
    "src/runtime/api_web",
    "src/contracts/foundation",
    "src/runtime/events",
    "src/runtime/services",
    "src/hmi/web_common",
    "src/contracts/interfaces",
):
    _path = str(ROOT / _entry)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import yaml  # noqa: E402

TOKEN_KEY = "rosy.dashboard.token"

#: (role, dev token, surfaces that role can reach). The dev overlay ships
#: these tokens; a device profile refuses them, which is a different check.
ROLES = (
    ("operator", "rosy-dev-operator", ("console", "setup")),
    ("administrator", "rosy-dev-admin", ("console", "setup", "device")),
)

VIEWPORTS = ((1366, 768), (390, 844))

MEASURE = """() => {
    const q = (s) => document.querySelector(s);
    const r = (n) => {
        if (!n) return null;
        const x = n.getBoundingClientRect();
        return {x: x.x, right: x.right, y: x.y, bottom: x.bottom,
                width: x.width, height: x.height};
    };
    const nav = q('nav a[aria-current]');
    const primary = q('ui-button[kind=primary]');
    const actions = q('ui-actions');
    return {
        scrollWidth: document.documentElement.scrollWidth,
        viewport: innerWidth,
        brand: q('ui-brand b') && getComputedStyle(q('ui-brand b')).color,
        selected: nav && {text: nav.textContent,
                          color: getComputedStyle(nav).color,
                          bg: getComputedStyle(nav).backgroundColor},
        buttonPadding: primary && getComputedStyle(primary).padding,
        actionGap: actions && getComputedStyle(actions).gap,
        estop: r(q('#shell-estop')),
        missingKinds: document.querySelectorAll('ui-button[data-kind-missing]').length,
        body: document.body.innerText.slice(0, 200),
    };
}"""


def build_client(tmp: Path):
    """The real CORE app with the dev overlay — no robot, no network."""
    from fastapi.testclient import TestClient

    from core.services import CoreServices
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir

    cfgdir = ROOT / "src" / "contracts" / "foundation" / "config"
    config = yaml.safe_load((cfgdir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["auth"] = {
        **config["auth"],
        **yaml.safe_load((cfgdir / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))["auth"],
    }
    robot = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot / "profile.yaml")
    caps = yaml.safe_load((robot / "capabilities.yaml").read_text(encoding="utf-8"))
    return TestClient(
        create_app(config, CoreServices.build(config, profile, caps, tmp / "docks.json")))


def problems_in(report: dict) -> list[str]:
    """The failure surface of a report - pure, so a contract test can pin it."""
    problems: list[str] = []
    errors = report.get("pageErrors") or []
    if errors:
        problems.append(f"{len(errors)} page error(s): {errors[:3]}")
    for row in report.get("results") or []:
        label = f"{row['role']}/{row['surface']}@{row['viewport']}"
        measurements = row["measurements"]
        if measurements["missingKinds"]:
            problems.append(f"{label}: {measurements['missingKinds']} button(s) "
                            "without a kind")
        if measurements["scrollWidth"] > measurements["viewport"]:
            problems.append(f"{label}: horizontal overflow "
                            f"({measurements['scrollWidth']} > "
                            f"{measurements['viewport']})")
        for target, status in row["firstResponses"]:
            if status >= 400:
                problems.append(f"{label}: {target} answered {status}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path,
                        default=Path(tempfile.mkdtemp(prefix="rosy-visible-roles-")),
                        help="where the report.json and screenshots land")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        client = build_client(Path(tmp))
        errors: list[str] = []
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for role, token, surfaces in ROLES:
                context = browser.new_context(viewport={"width": VIEWPORTS[0][0],
                                                        "height": VIEWPORTS[0][1]})
                page = context.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script(
                    f"sessionStorage.setItem({TOKEN_KEY!r}, {token!r});")
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
                        page.wait_for_timeout(800)
                        values = page.evaluate(MEASURE)
                        shot = args.out_dir / f"{role}-{surface}-{width}x{height}.png"
                        page.screenshot(path=str(shot), full_page=True)
                        results.append({
                            "role": role, "surface": surface, "viewport": width,
                            "measurements": values,
                            "firstResponses": responses[:4],
                        })
                context.close()
            browser.close()

    report = {"results": results, "pageErrors": errors, "generated": time.strftime("%F %T")}
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    problems = problems_in(report)

    print(f"report: {args.out_dir / 'report.json'}")
    if problems:
        print("VISIBLE-ROLES FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"visible-roles ok: {len(results)} surface visits, "
          f"{len(ROLES)} roles, {len(VIEWPORTS)} viewports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
