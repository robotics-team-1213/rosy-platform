"""Host pytest bootstrap for this suite."""

import sys
from pathlib import Path

import pytest

# Browser tests here import test/browser_harness.py (opt-in flag, Chromium-safe ports).
_HARNESS = str(Path(__file__).resolve().parents[4] / "test")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)


@pytest.fixture(scope="module")
def base_url():
    import threading

    import uvicorn
    from browser_harness import safe_listener

    suite = str(Path(__file__).resolve().parent)
    if suite not in sys.path:
        sys.path.insert(0, suite)
    import dev_server

    listener = safe_listener()
    server = uvicorn.Server(uvicorn.Config(dev_server.app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=5)
    listener.close()


@pytest.fixture
def tablet_page(base_url):
    playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2000, "height": 1200})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(10_000)
        yield base_url, page, errors
        browser.close()
