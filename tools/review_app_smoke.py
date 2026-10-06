"""Open every Pinky review screen in headless Chromium and report what a reviewer would hit.

Read-only: it sends GET requests only, so it never approves, saves or exports.

    python tools/review_app_smoke.py --state X:/DevTemp/pinky-review-run/state
    python tools/review_app_smoke.py --base-url http://127.0.0.1:8767

With --state it starts the app on a free loopback port and stops it afterwards.
Screenshots of each screen at desktop and phone width go to --out. Exit 1 on a page
error, an HTTP error, a failed request, a sideways-scrolling page or an empty workspace.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

APP = Path(__file__).resolve().parents[1] / 'learning/training/perception/dataset/review_app.py'
SCREENS = {'objects': '/', 'objects-pending': '/?filter=pending', 'pixels': '/pixels',
           'catalog': '/catalog', 'learning': '/learning'}
VIEWPORTS = {'desktop': (1440, 900), 'phone': (390, 844)}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_up(base: str, server: subprocess.Popen | None, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if server and server.poll() is not None:
            sys.exit(f'review app exited with {server.returncode}')
        try:
            urllib.request.urlopen(base + '/api/decisions', timeout=2).read()
            return
        except OSError:
            time.sleep(0.3)
    sys.exit(f'review app did not answer at {base}')


def summary(base: str) -> dict:
    decisions = json.load(urllib.request.urlopen(base + '/api/decisions', timeout=30))
    count = lambda key: {s: sum(f[key] == s for f in decisions['frames'])
                         for s in ('pending', 'approved', 'excluded')}
    return {'frames': len(decisions['frames']), 'objects': count('object_decision'),
            'pixels': count('mask_decision')}


def check(base: str, out: Path) -> list[str]:
    from playwright.sync_api import sync_playwright
    problems: list[str] = []
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for view, (width, height) in VIEWPORTS.items():
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.on('pageerror', lambda e, v=view: problems.append(f'{v} page error: {e}'))
            page.on('requestfailed', lambda r, v=view: problems.append(f'{v} request failed: {r.url}'))
            page.on('response', lambda r, v=view: r.status >= 400 and problems.append(
                f'{v} HTTP {r.status}: {r.url}'))
            for name, path in SCREENS.items():
                started = time.time()
                page.goto(base + path, wait_until='networkidle')
                shot = out / f'{view}-{name}.png'
                page.screenshot(path=str(shot))
                wide = page.evaluate('document.documentElement.scrollWidth')
                if wide > width:
                    problems.append(f'{view} {path} scrolls sideways: {wide}px > {width}px')
                print(f'{view:7} {path:18} {time.time() - started:5.2f}s  {shot}')
            page.close()
        browser.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument('--state', type=Path, help='existing review state to serve on a free port')
    where.add_argument('--base-url', help='an already running review app')
    parser.add_argument('--out', type=Path, default=Path('X:/DevTemp/pinky-review-smoke'))
    args = parser.parse_args()
    server = None
    base = (args.base_url or '').rstrip('/')
    if args.state:
        if not (args.state / 'reviews.sqlite3').is_file():
            sys.exit(f'{args.state} has no reviews.sqlite3; first run needs --source/--human/--images')
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        server = subprocess.Popen([sys.executable, str(APP), '--state', str(args.state), '--port', str(port)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up(base, server)
        counts = summary(base)
        print(json.dumps(counts, ensure_ascii=False))
        problems = check(base, args.out)
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
    if not counts['frames']:
        problems.append('workspace has no photos')
    for problem in problems:
        print('PROBLEM', problem)
    print('OK' if not problems else f'{len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
