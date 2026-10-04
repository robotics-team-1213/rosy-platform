"""D-398 — 2026-10-01 전 레이어 감사가 남긴 정적 게이트 네 개.

규칙 자체는 각기 ADR·DESIGN.md 에 이미 있다. 이 파일은 그중 "규칙은 있었으나
지키는 자가 없던" 네 간극에 검사자를 단다(감사 원문: docs/adr/D-398).

1. 정지(D-220) — 제품 웹 표면의 CSS 에 `transition:`·`animation:`·`@keyframes` 가 없다.
2. 장미색 부정 범위(D-277) — `--brand-rose*` 참조는 워드마크·위치 표식 파일에서만.
3. 역할 우선(D-359 §1.3, DESIGN.md Do) — 역할 토큰이 있는 바탕색은 팔레트 이름 대신
   역할 이름을 쓴다. 지금은 `--ground-soft`→`--surface-flat`, `--ground-card`→
   `--surface-raised` 두 쌍만 기계로 가릴 수 있다(나머지는 역할이 아직 없다).
4. 온뷰포트 높이(D-359 §6.5) — `100vh` 프레임은 `100dvh` 다. 비례 값(clamp 의 45vh
   등)은 프레임이 아니므로 가리지 않는다.

제품이 아닌 등록 표면은 `NON_PRODUCT` 에 사유와 함께 뺀다. 게이트가 빨개지면
사유를 다시 읽고 — 위반이면 고치고, 표면 사정이면 사유를 갱신한다.
"""

from __future__ import annotations

import re

import surface_registry as registry

#: 제품 웹 표면이 아닌 등록 표면 — 모든 게이트에서 뺀다(사유 필수).
NON_PRODUCT = {
    "control-diagnostic": "PARKED D-266 — 타이포·확인 계약과 같이 재개 때 합의한다",
    "lane-live-view": "제품 표면이 아니다(contracts: []) — Gazebo 개발 도구",
}

#: D-277 — 장미색이 살아도 좋은 파일. 워드마크(ui-brand·레거시 .brand b)와
#: 현재 위치 표식(역할 메뉴·표면 링크) 가족, 그리고 팔레트 원본.
ROSE_FILES = {
    "shared/web/tokens.css",                 # 팔레트 원본(정의)
    "shared/web/components.css",             # ui-brand 워드마크
    "middleware/ui/robot/styles.css",                  # 레거시 셸 워드마크(.brand b)
    "middleware/ui/robot/shell/shell.css",             # 역할 메뉴 위치 표식(팔레트 게이트 핀)
    "middleware/ui/robot/panels/surface-panels.css",   # 표면 링크(위치 표식 가족)
}

#: D-359 §1.3 — 역할 토큰이 이미 존재하는 팔레트 이름. 이 표를 늘리는 것은
#: tokens.css 에 역할을 더하는 ADR 과 같은 커밋에서만 한다.
ROLE_FOR_GROUND = {
    "--ground-soft": "--surface-flat",
    "--ground-card": "--surface-raised",
}

_MOTION = re.compile(r"(?:^|[;{\s])(?:transition|animation)\s*:|@keyframes\b")
_ROSE = re.compile(r"--brand-rose(?:-wash)?\b")
_GROUND = re.compile(r"var\((--ground-soft|--ground-card)\)")
_FULL_VIEWPORT_VH = re.compile(r"(?<![\da-z])100vh\b")


def _web_rows() -> list[dict]:
    return [row for row in registry.load()
            if row.get("medium") == "web" and row.get("id") not in NON_PRODUCT]


def motion_problems(css: str) -> list[str]:
    """D-220 — 한 시트에서 장식 움직임 규칙을 걷어 낸 목록."""
    return [m.group(0).strip() for m in _MOTION.finditer(css)]


def test_product_web_surfaces_hold_still():
    """D-220 — 제품 웹 표면에 장식 움직임이 없다. 상태 변화는 점프 컷."""
    problems = []
    for row in _web_rows():
        for page, css in registry._style_sources(registry.REPO, row["path"]):
            for text in motion_problems(css):
                where = page.relative_to(registry.REPO).as_posix()
                problems.append(f"still: {row['id']} {where} 움직임 규칙 {text!r}")
    assert problems == [], "D-220 정지 계약 위반:\n" + "\n".join(problems)


def test_rose_stays_on_the_wordmark_and_position_markers():
    """D-277 — `--brand-rose*` 는 이름 식별에만 쓴다. 허용 파일 밖 참조는 실패."""
    problems = []
    for row in _web_rows():
        for page, text in registry.colour_sources(registry.REPO, row):
            if _ROSE.search(text):
                here = page.relative_to(registry.REPO).as_posix()
                if here not in ROSE_FILES:
                    problems.append(
                        f"rose: {here} 가 --brand-rose 를 참조한다 — 워드마크·위치 표식이 아니면 쓰지 않는다")
    assert problems == [], "D-277 장미색 범위 위반:\n" + "\n".join(problems)


def test_ground_fills_use_their_role_tokens():
    """D-359 §1.3 — 역할이 있는 바탕색은 역할 이름으로 읽는다(표면이 팔레트를 직접 쓰지 않는다)."""
    problems = []
    for row in _web_rows():
        if row["id"] == "web-common":
            continue  # 라이브러리 — 역할 토큰을 정의·소비하는 주체다
        for page, css in registry._style_sources(registry.REPO, row["path"]):
            for found in _GROUND.finditer(css):
                here = page.relative_to(registry.REPO).as_posix()
                role = ROLE_FOR_GROUND[found.group(1)]
                problems.append(f"role: {here} {found.group(1)} 대신 {role} 역할 토큰을 쓴다")
    assert problems == [], "역할 우선 규칙 위반:\n" + "\n".join(problems)


def test_full_viewport_heights_use_dvh():
    """D-359 §6.5 — 온뷰포트 높이는 dvh 다(모바일 주소 창에도 프레임이 정확하다)."""
    problems = []
    for row in _web_rows():
        for page, css in registry._style_sources(registry.REPO, row["path"]):
            for found in _FULL_VIEWPORT_VH.finditer(css):
                here = page.relative_to(registry.REPO).as_posix()
                problems.append(f"dvh: {here} 100vh 대신 100dvh 를 쓴다")
    assert problems == [], "온뷰포트 높이 규칙 위반:\n" + "\n".join(problems)


def test_the_patterns_catch_a_planted_violation_and_pass_the_real_ones():
    """돌연변이 증명 — 게이트가 진짜로 빨개지는지 가진 규칙으로 보인다."""
    assert motion_problems("b { transition: opacity .2s; }") != []
    assert motion_problems("@keyframes pulse { from { opacity: .3; } }") != []
    assert motion_problems("b { animation: pulse 1s infinite; }") != []
    assert motion_problems("b { color: var(--ink); }") == []
    # reduced-motion 조건문 자체는 움직임 규칙이 아니다.
    assert motion_problems("@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto; } }") == []

    assert _ROSE.search("color: var(--brand-rose)") is not None
    assert _ROSE.search("background: var(--brand-rose-wash)") is not None
    assert _ROSE.search("color: var(--ink)") is None

    assert _GROUND.search("background: var(--ground-soft)") is not None
    assert _GROUND.search("background: var(--ground-raise)") is None  # 아직 역할이 없다

    assert _FULL_VIEWPORT_VH.search("height: 100vh") is not None
    assert _FULL_VIEWPORT_VH.search("height: 100dvh") is None
    assert _FULL_VIEWPORT_VH.search("height: clamp(16rem, 45vh, 32rem)") is None  # 비례 값
