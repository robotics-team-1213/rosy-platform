#!/usr/bin/env python3
"""Capture the real dashboard markup with deterministic simulated line state."""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/index.html")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.goto(args.url)
        page.wait_for_load_state("networkidle")
        repo = Path(__file__).resolve().parents[4]
        web = repo / "src/hmi/dashboard"
        page.add_style_tag(path=str(web / "tokens.css"))
        page.add_style_tag(path=str(web / "styles.css"))
        page.locator('[data-line-mode="CAMERA_LINE"]').wait_for()
        page.evaluate("""
          () => {
            document.querySelectorAll('[data-line-mode]').forEach((button) => {
              button.classList.toggle('active', button.dataset.lineMode === 'CAMERA_LINE');
              button.disabled = false;
            });
            document.getElementById('line-follow-state').textContent = 'TRACKING';
            document.getElementById('line-follow-source').textContent = 'CAMERA_LINE';
            document.getElementById('line-follow-error').textContent = '-0.214';
            document.getElementById('line-follow-confidence').textContent = '82%';
            document.getElementById('line-follow-linear').textContent = '0.047 m/s';
            document.getElementById('line-follow-angular').textContent = '0.171 rad/s';
            document.getElementById('line-follow-reason').textContent = 'tracking · host simulation';
          }
        """)
        page.locator(".control-panel").screenshot(path=str(args.output))
        browser.close()


if __name__ == "__main__":
    main()
