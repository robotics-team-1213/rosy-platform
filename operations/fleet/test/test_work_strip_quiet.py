"""작업 집계 띠(#work-strip)의 조용한 모름 표기 — 초기 마크업과 조회 갱신이 같은 규칙을 쓴다.

조회 전에는 띠가 "정보 없음"을 세 번 반복하지 않고 한 번만 말한다(D-280 병합,
blankRepeatedUnknown). 한쪽만 고치면 첫 페인트나 재조회에서 다시 반복이 돌아오므로
양쪽을 함께 고정한다. 병합 규칙 자체는 shared/web/test/quiet-row.test.mjs가 지킨다.
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / 'applications/fleet/web'
WORK_VIEW = WEB / 'work' / 'work-view.js'


def strip_markup() -> str:
    page = (WEB / 'index.html').read_text(encoding='utf-8')
    return page.split('id="work-strip"', 1)[1].split('</dl>', 1)[0]


def paint_counts_source() -> str:
    source = WORK_VIEW.read_text(encoding='utf-8')
    return source.split('function paintCounts', 1)[1].split('\n  }', 1)[0]


def test_initial_markup_says_unknown_once():
    strip = strip_markup()
    assert strip.count('정보 없음') == 1, strip


def test_refill_paints_counts_through_the_row_merge():
    body = paint_counts_source()
    assert 'blankRepeatedUnknown(' in body, body
    # 세 칸(승인 대기·진행·막힘)이 같은 병합 줄을 지나야 재조회에서도 반복이 돌아오지 않는다.
    assert body.count('valueText(count(state)).text') == 1, body
