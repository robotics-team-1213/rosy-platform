"""Shared helpers for the optional Chromium regressions (D-153 G2 캡처 훅).

렌더는 표면마다 다르지만 실행기·오류 수집·confirm 스텁·스크린샷 저장의 배관은
그렇지 않다. `robot_contracts.py` 의 공유 헬퍼 관례를 따른다 — D-92 는 제품
표면의 컴포넌트 공유를 금지할 뿐, 시험 도구의 공유는 다른 문제다.
"""

from __future__ import annotations

import os
from pathlib import Path


def launch_options() -> dict:
    options = {"headless": True, "timeout": 10_000}
    if channel := os.environ.get("ROSY_BROWSER_CHANNEL"):
        options["channel"] = channel
    return options


def open_page(playwright, width: int, height: int):
    """Chromium 실행 + 페이지 오류 수집. 호출자이 browser.close() 한다."""
    browser = playwright.chromium.launch(**launch_options())
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # 기본 대기 예산은 15초다(2026-09-25). 5초는 경합 중인 호스트에서
    # goto(networkidle)·wait_for_function 을 계약과 무관하게 쓰러뜨렸다 —
    # 플레이크 사후 처리 3건이 같은 원인이었다. 계약 자체의 타임아웃은
    # 호출처에서 이미 명시적으로 지정한다.
    page.set_default_timeout(15_000)
    return browser, page, errors


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


def save_temp_screenshot(page, name: str) -> Path:
    shot = Path(os.environ.get("TEMP", "/tmp")) / name
    page.screenshot(path=str(shot))
    print(f"\nscreenshot: {shot}")
    return shot
