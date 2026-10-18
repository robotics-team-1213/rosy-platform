"""Headless Chromium captures of the LIVE SIM Fleet console (real API answers, no fixtures)."""
import os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['MAP_DRIVE_SOURCE']) / 'test'))
from browser_harness import launch_options, open_token_access  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path(os.environ['D763_OUT']) / 'shots-live'
OUT.mkdir(exist_ok=True)
TOKEN = os.environ['MAP_DRIVE_FLEET_TOKEN']
SITE = 'http://127.0.0.1:31353'
PAGES_ALL = [('control', '/console'), ('work', '/console?view=work'), ('records', '/console?view=records'),
         ('map', '/console/site-map'), ('install', '/console/install')]
TAG = os.environ.get('D763_SHOT_TAG', '')
PAGES = [p for p in PAGES_ALL if p[0] in os.environ.get('D763_SHOT_PAGES', 'control,work,records,map,install').split(',')]
with sync_playwright() as pw:
    browser = pw.chromium.launch(**launch_options())
    for width, height in ((1440, 900), (390, 844)):
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.goto(SITE + '/console')
        try:
            open_token_access(page)
            page.locator('#console-token').fill(TOKEN)
            page.locator('#token-save').click()
            time.sleep(3)
        except Exception as error:
            print('token entry failed', width, repr(error)[:200], flush=True)
        for name, path in PAGES:
            try:
                page.goto(SITE + path)
                time.sleep(5)
                page.screenshot(path=str(OUT / f'live{TAG}-{name}-{width}.png'))
                if name == 'work':
                    page.screenshot(path=str(OUT / f'live{TAG}-{name}-{width}-full.png'), full_page=True)
            except Exception as error:
                print('shot failed', name, width, repr(error)[:200], flush=True)
        page.close()
    browser.close()
print('live shots done', sorted(p.name for p in OUT.iterdir()), flush=True)
