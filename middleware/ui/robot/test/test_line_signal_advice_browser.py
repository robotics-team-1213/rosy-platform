"""D-551 J3 — the robot line-follow panel shows Fleet's D-525 signal advice, display only.

The chip says lamp, time and stop-line distance in words (never colour alone), wears the
orange dashed "가상" frame, says passage is the Fleet authority's call, and falls back to
"신호 정보 없음" when the advice expires or the status read fails — never a stale green.
"""

import os
from pathlib import Path

from test_panel_copy_evidence_browser import panel, pytestmark  # noqa: F401

ADVICE = """(signal, expiresIn) => window.__callbacks['/api/v1/line-follow'].onData({mode:'CAMERA_LINE', state:'FOLLOWING',
  advice: {advice_id:'a1', leg_id:'leg-1', seq:1, fleet_epoch:'e1', pose_stamp:1.0, ttl_s:2.0,
           expires_in_s: expiresIn, signal}})"""


def _chip(page):
    return page.locator("section.line-signal")


def _signal(**over):
    signal = {"signal_id": "S1", "approach": "north", "stop_m": 0.42, "lamp": "green",
              "left_s": 3.2, "green_in_s": None, "exact": True, "may_enter": True}
    signal.update(over)
    return signal


def test_chip_reads_lamp_time_and_stop_line_in_words(panel):
    page = panel("console/line-follow.js")
    chip = _chip(page)
    assert chip.get_attribute("data-lamp") == "unknown"
    assert "신호 정보 없음" in chip.inner_text()
    page.evaluate(ADVICE, [_signal(), 2.0])
    text = chip.inner_text()
    assert chip.get_attribute("data-lamp") == "green"
    assert "가상" in text and "가상 신호 S1 · north" in text
    assert "녹색 · 4초 남음" in text and "정지선까지 0.42 m" in text
    assert "통과 허가는 관제 authority" in text
    # The frame is the Fleet T-map pill's: orange (--status-warn) dashed border.
    border = chip.evaluate("""e => { const s = getComputedStyle(e);
      const probe = document.createElement('i'); probe.style.color = 'var(--status-warn)';
      document.body.append(probe); const warn = getComputedStyle(probe).color; probe.remove();
      return [s.borderTopStyle, s.borderTopColor === warn]; }""")
    assert border == ["dashed", True]
    if shot_dir := os.environ.get("ROSY_SHOT_DIR"):
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        chip.screenshot(path=str(Path(shot_dir) / "robot-signal-chip-green.png"))
    page.evaluate(ADVICE, [_signal(lamp="red", left_s=None, green_in_s=6.4, exact=False, stop_m=-0.05), 2.0])
    text = chip.inner_text()
    assert chip.get_attribute("data-lamp") == "red"
    assert "적색 · 녹색까지 ≥7초" in text and "정지선 안쪽" in text
    if shot_dir:
        chip.screenshot(path=str(Path(shot_dir) / "robot-signal-chip-red.png"))
        page.screenshot(path=str(Path(shot_dir) / "robot-line-follow-panel.png"), full_page=True)


def test_expiry_and_read_failure_show_unknown_not_green(panel):
    page = panel("console/line-follow.js")
    chip = _chip(page)
    page.evaluate(ADVICE, [_signal(), 0.3])
    assert chip.get_attribute("data-lamp") == "green"
    # No newer poll arrives: the CORE-given remaining life runs out on the panel's clock.
    page.wait_for_function("document.querySelector('section.line-signal').dataset.lamp === 'unknown'", timeout=3000)
    assert "신호 정보 없음" in chip.inner_text() and "녹색" not in chip.inner_text()
    page.evaluate(ADVICE, [_signal(), 2.0])
    assert chip.get_attribute("data-lamp") == "green"
    page.evaluate("() => window.__callbacks['/api/v1/line-follow'].onData({mode:'OFF', state:'OFF'})")
    assert chip.get_attribute("data-lamp") == "unknown"
    page.evaluate(ADVICE, [_signal(), 2.0])
    page.evaluate("() => window.__callbacks['/api/v1/line-follow'].onError(new Error('fixture'))")
    assert chip.get_attribute("data-lamp") == "unknown" and "신호 정보 없음" in chip.inner_text()
    page.evaluate(ADVICE, [_signal(lamp="blue"), 2.0])
    assert chip.get_attribute("data-lamp") == "unknown"
