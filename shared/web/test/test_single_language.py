"""D-396 G1: 단일 디자인 언어 — 공유 자산 밖의 정의를 붉게 만든다.

공용화의 압력은 두 계약으로 만든다(ADR D-396 1):

1. **커스텀 엘리먼트는 web_common 만 정의한다.** 서피스 JS에서
   `customElements.define` 을 찾으면 위반 — 공유 컴포넌트가 필요하면
   `web_common/ui.js` 에 넣고 소비만 한다.
2. **토큰 변수는 web_common 만 선언한다.** 서피스 CSS가 `:root` 또는
   `[data-theme…]` 블록에서 `--이름: 값` 을 선언하면 위반 — 지역 변수는
   컴포넌트 스코프 셀렉터 안에서만 쓴다. `color-scheme` 같은 비토큰 선언은
   허용한다(pilot 의 예).

승격 판단(무엇을 web_common 으로 올릴지)은 사람이 한다. 이 시험은 미루는
순간 붉어질 뿐이다.

변이 증명: 서피스 CSS에 `:root { --paper: red; }` 를 넣거나 JS에
`customElements.define('x-thing', …)` 을 넣으면 이 시험이 빨갛진다.
"""

from __future__ import annotations

import re
from pathlib import Path

from surface_registry import REPO, load

SHARED = REPO / "shared/web"

_DEFINE = re.compile(r"customElements\s*\.\s*define\s*\(")
#: `:root` 또는 테마 어트리뷰트 블록에서 시작해 `}` 까지 — 그 안의 `--name:` 선언.
_ROOT_BLOCK = re.compile(
    r"(?:^|\})\s*((?::root|;?\s*\[[^\]]*data-theme[^\]]*\])[^{}]*)\{([^{}]*)\}", re.M)
_TOKEN_DECL = re.compile(r"^\s*(--[\w-]+)\s*:", re.M)


def _root_token_exceptions(row: dict) -> set[str]:
    """`raw_colours` 로 선언된 `:root` 예외 파일명 (이유는 등록부에 있다)."""
    return {
        str(entry.get("file"))
        for entry in (row.get("raw_colours") or [])
        if isinstance(entry, dict) and ":root" in str(entry.get("block") or "")
    }


def _surface_directories() -> list[tuple[str, Path, set[str]]]:
    """등록된 웹 서피스 (web_common 자신은 제외 — 단일 출처이므로).

    세 번째 원소는 `raw_colours` 로 선언된 :root 예외 파일명이다 — 예외는
    조용한 허용이 아니라 등록부의 한 줄이다(게시판 피치 색이 그 선례).
    """
    out = []
    for row in load(REPO):
        if row.get("medium") != "web":
            continue
        path = REPO / row["path"]
        if path == SHARED or SHARED in path.parents:
            continue
        out.append((row["id"], path, _root_token_exceptions(row)))
    return out


def _files(base: Path, suffix: str) -> list[Path]:
    if base.is_file():
        return [base] if base.suffix == suffix else []
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob(f"*{suffix}") if p.is_file())


def test_no_surface_defines_custom_elements():
    violations = []
    for surface_id, base, _exceptions in _surface_directories():
        sources = [*(js for js in _files(base, ".js")), *(html for html in _files(base, ".html"))]
        for source in sources:
            text = source.read_text(encoding="utf-8", errors="replace")
            if _DEFINE.search(text):
                violations.append(f"{surface_id}: {source.relative_to(REPO)}")
    assert not violations, (
        "커스텀 엘리먼트 정의는 web_common/ui.js 만 한다 (D-396 G1): "
        + ", ".join(violations)
    )


def test_no_surface_redeclares_tokens_at_root():
    violations = []
    for surface_id, base, exceptions in _surface_directories():
        for css in _files(base, ".css"):
            if css.name in exceptions:
                continue  # raw_colours 의 :root 예외 — 이유는 등록부에 있다
            text = css.read_text(encoding="utf-8", errors="replace")
            for _match in _ROOT_BLOCK.finditer(text):
                declared = _TOKEN_DECL.findall(_match.group(2))
                if declared:
                    rel = css.relative_to(REPO)
                    violations.append(f"{surface_id}: {rel} 재선언 {declared}")
    assert not violations, (
        ":root/[data-theme] 의 --토큰 선언은 web_common/tokens.css 만 한다 "
        "(지역 변수는 컴포넌트 스코프 안; 예외는 raw_colours 로 선언; D-396 G1): "
        + "; ".join(violations)
    )
