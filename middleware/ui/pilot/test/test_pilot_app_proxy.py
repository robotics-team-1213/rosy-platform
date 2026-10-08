"""The bundled Pilot page loaded through the app proxy, not a rewritten dev server page."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")

ROOT = Path(__file__).resolve().parents[4]
ANDROID = ROOT / "middleware" / "ui" / "pilot" / "android"
GRADLEW = ROOT / "operations" / "ui" / "cam" / "gradlew.bat"
PROBE = Path(r"X:\DevTemp\pilot-app-connect\page-probe")


def _gradle(probe: Path, log: Path) -> tuple[subprocess.Popen[str], object]:
    env = os.environ.copy()
    env["JAVA_HOME"] = r"X:\java\jdk-21.0.8"
    env["GRADLE_USER_HOME"] = r"X:\DevCaches\gradle"
    command = [
        str(GRADLEW), "-p", ".",
        "--project-cache-dir", r"X:\DevTemp\pilot-app-connect\project-cache",
        "-Prosy.buildRoot=X:/DevTemp/pilot-app-connect/build",
        "-Prosy.pilot.page.probe=1",
        f"-Prosy.pilot.page.dir={probe.as_posix()}",
        ":app:testDebugUnitTest",
        "--tests", "io.github.livsbittt.rosy.pilot.ShellPageProbe",
        "--offline",
    ]
    handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command, cwd=ANDROID, env=env, text=True,
        stdout=handle, stderr=subprocess.STDOUT,
    )
    return process, handle


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_bundled_page_uses_the_app_proxy():
    """Chromium loads the assets and session the Pilot app proxy actually serves."""
    if PROBE.exists():
        for child in PROBE.iterdir():
            child.unlink()
    else:
        PROBE.mkdir(parents=True)
    gradle_log = PROBE / "gradle.txt"
    gradle, gradle_handle = _gradle(PROBE, gradle_log)
    origin = capability = ""
    try:
        deadline = time.monotonic() + 180
        address = PROBE / "address.txt"
        while time.monotonic() < deadline:
            if gradle.poll() is not None:
                raise AssertionError(
                    f"proxy exited {gradle.returncode} before the page was ready\n{gradle_log.read_text(encoding='utf-8')}")
            if address.is_file() and len(address.read_text(encoding="utf-8").splitlines()) >= 2:
                origin, capability = address.read_text(encoding="utf-8").splitlines()[:2]
                break
            time.sleep(0.2)
        else:
            raise AssertionError("proxy address was not published")
        with playwright_sync.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1200, "height": 800})
                context.add_cookies([{
                    "name": "rosy-shell", "value": capability, "domain": "127.0.0.1",
                    "path": "/", "httpOnly": True, "sameSite": "Strict",
                }])
                page = context.new_page()
                errors: list[str] = []
                failed: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: failed.append(f"{response.status} {response.url}")
                        if response.status >= 400 and not urlsplit(response.url).path.startswith(("/api/", "/ws/")) else None)
                page.goto(f"{origin}/pilot", wait_until="domcontentloaded")
                try:
                    page.locator("[data-drive-enter]").wait_for(timeout=8000)
                except Exception:
                    upstream = (PROBE / "upstream.log").read_text(encoding="utf-8") if (PROBE / "upstream.log").is_file() else ""
                    raise AssertionError(
                        f"shell={page.evaluate('document.documentElement.dataset.pilotShell')!r} "
                        f"text={page.locator('body').inner_text()!r} errors={errors!r} "
                        f"failed={failed!r} upstream={upstream!r}") from None
                assert page.locator("[data-dev-connect]").count() == 0
                assert page.locator("[data-lobby-list]").count() == 0
                assert page.locator("form[data-pilot-token-form]").count() == 0
                assert page.locator("ui-topbar [data-goto]").is_hidden()
                page.click("[data-drive-enter]")
                page.locator("[data-drive-stick]").wait_for()
                assert page.locator("[data-drive-goal]").count() == 0
                assert page.locator("ui-topbar [data-goto]").is_hidden()
                page.locator("ui-topbar [data-goto]").evaluate("node => node.click()")
                page.wait_for_timeout(200)
                assert "/console" not in page.url
                assert errors == [], errors
                assert failed == [], failed
            finally:
                browser.close()
    finally:
        (PROBE / "done").write_text("done", encoding="utf-8")
        try:
            code = gradle.wait(timeout=60)
        except subprocess.TimeoutExpired:
            gradle.kill()
            gradle.wait(timeout=10)
            gradle_handle.close()
            raise AssertionError(f"proxy did not finish\n{gradle_log.read_text(encoding='utf-8')}") from None
        gradle_handle.close()
        if code != 0:
            raise AssertionError(f"proxy test failed\n{gradle_log.read_text(encoding='utf-8')}")
