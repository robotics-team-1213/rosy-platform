"""Bench recording page at phone width (390/320): reason button, wrist-camera badges, 12px floor, in real Chromium (opt-in)."""
import re

import pytest
from browser_harness import browser_tests_enabled, open_shared_page

from test_omx_bench_record import ROOT

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")

OMX = ROOT / 'deploy/robot/omx'
# Same markup bench_record_cam.js builds for a wrist picture-in-picture box.
PIP = ('<div class="cam-grid" style="height:420px"><div class="cam-box"></div><div class="cam-pip-stack">'
       '<div class="cam-box cam-pip" style="height:150px"><span class="cam-title-pill">arm_s_wrist (NORMAL)</span>'
       '<span class="cam-rec-badge armed">녹화 대상</span></div></div></div>')


def _page_html():
    html = (OMX / 'bench_record.html').read_text(encoding='utf-8')
    footer = re.search(r'<footer.*?</footer>', html, re.S).group(0)
    footer = footer.replace('class="reason-strip" role="status" hidden', 'class="reason-strip crit" role="status"')
    footer = re.sub(r'(id="reason-(?:action|more|expand|close)-btn"[^>]*?) hidden', r'\1', footer)
    footer = footer.replace('id="reason-action-btn" class="btn-primary btn-xs">', 'id="reason-action-btn" class="btn-primary btn-xs">연결 재확인')
    footer = footer.replace('id="reason-more-btn" class="btn-tool btn-xs">', 'id="reason-more-btn" class="btn-tool btn-xs">(+1건)')
    footer = footer.replace('id="hdr-start-reasons" class="reason-text quiet">', 'id="hdr-start-reasons" class="reason-text quiet">arm_s 리더 USB 미연결 — 리더 USB를 연결하세요')
    css = (OMX / 'bench_record.css').read_text(encoding='utf-8')
    return f'<!doctype html><html><head><style>{css}</style></head><body>{PIP}{footer}</body></html>'


def _overlap(a, b):
    return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


@pytest.mark.parametrize('width', [390, 320])
def test_narrow_bench_controls_stay_readable(width):
    owner, page, _errors = open_shared_page(width, 800)
    try:
        page.set_content(_page_html())
        btn = page.locator('#reason-action-btn')
        box = btn.bounding_box()
        assert box['height'] <= 40, box  # one line, not a vertical stack of syllables
        assert page.evaluate("b => b.scrollWidth <= b.clientWidth + 1", btn.element_handle())
        pill, badge = page.locator('.cam-pip .cam-title-pill').bounding_box(), page.locator('.cam-pip .cam-rec-badge').bounding_box()
        assert not _overlap(pill, badge), (pill, badge)
        for sel in ('#activity-log-bar .status-label', '#reason-action-btn', '.cam-pip .cam-rec-badge'):
            size = page.evaluate("s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize)", sel)
            assert size >= 12, (sel, size)
    finally:
        owner.close()
