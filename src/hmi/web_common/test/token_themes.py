"""D-359 §7.1 — tokens.css를 테마별 팔레트와 파생 블록으로 읽는다 (test-support).

파일 전체를 `--x: #hex` 정규식으로 훑으면 두 번째 테마 블록의 값이 앞 값을 덮어
앞 테마가 검사되지 않는다. 여기서는 선택자 블록 단위로 나눈다.

  팔레트  선택자에 `[data-theme="이름"]`이 있는 블록 — 이름마다 값 사전 하나.
  파생    선택자가 정확히 `:root`인 블록 — 팔레트만 참조하고 원시 색이 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[1] / "tokens.css"

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_THEME = re.compile(r'\[data-theme="([a-z0-9-]+)"\]')
_HEX_DECL = re.compile(r"^\s*--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", re.M)
_SCHEME = re.compile(r"^\s*color-scheme\s*:\s*([a-z ]+?)\s*;", re.M)

#: 원시 색 리터럴 — hex, 함수형 색, 이름 있는 색. `transparent`와 `color-mix(`는 아니다.
RAW_COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:rgba?|hsla?|hwb|oklch|oklab|lab|lch)\("
    r"|\bcolor\("
    r"|\b(?:black|white|red|green|blue|gray|grey)\b"
)


def read(path: Path = TOKENS) -> str:
    return path.read_text(encoding="utf-8")


def blocks(text: str) -> list[tuple[str, str]]:
    """(선택자, 본문) — 주석을 걷어낸 최상위 규칙들."""
    return [(sel.strip(), body) for sel, body in _BLOCK.findall(_COMMENT.sub("", text))]


def palettes(text: str) -> dict[str, dict[str, str]]:
    """테마 이름 → {토큰 이름(`--` 없음): #rrggbb 소문자}."""
    found: dict[str, dict[str, str]] = {}
    for selector, body in blocks(text):
        for theme in _THEME.findall(selector):
            found.setdefault(theme, {}).update(
                {name: value.lower() for name, value in _HEX_DECL.findall(body)}
            )
    return found


def colour_schemes(text: str) -> dict[str, list[str]]:
    """테마 이름 → 그 블록이 선언한 `color-scheme` 값들."""
    found: dict[str, list[str]] = {}
    for selector, body in blocks(text):
        for theme in _THEME.findall(selector):
            found.setdefault(theme, []).extend(_SCHEME.findall(body))
    return found


def derived_body(text: str) -> str:
    """선택자가 `:root` 하나뿐인 블록들 — 파생·역할·척도 층."""
    return "\n".join(body for selector, body in blocks(text) if selector == ":root")
