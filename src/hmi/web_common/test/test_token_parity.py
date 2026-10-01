"""D-345 token_parity — 웹이 아닌 표면이 가진 tokens.css 색 사본의 일치.

tokens.css가 색 값의 유일한 원본이다(D-292). 휴대폰 앱(Kotlin)과 로봇 LCD(Python)는
CSS를 읽을 수 없어 값을 옮겨 적는다. 소비자 모듈의 시험은 자기 코드만 단언하므로(D-73)
사본이 원본과 같은지는 원본의 주인인 web_common이 여기서 지킨다.

사본 줄의 형식(surfaces.yaml `token_copy` 파일):
  Python  ``_BG = (16, 18, 20)   # --ground #101214``
  Kotlin  ``val Ground = Color(0xFF101214) // --ground``
토큰이 아닌 색 상수는 ``token-exempt: <이유>``를 같은 줄에 적어야 한다.
"""

from __future__ import annotations

import re

import surface_registry as registry
import token_themes

TOKENS = registry.REPO / "src" / "hmi" / "web_common" / "tokens.css"

_PY_COLOUR = re.compile(
    r"^_?[A-Za-z][A-Za-z0-9_]*\s*=\s*\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})"
    r"(?:,\s*(?:\d{1,3}|(?:\d+\.\d*|\.\d+)))?\)(.*)$"
)
_KT_COLOUR = re.compile(r"Color\(0x([0-9a-fA-F]{2})([0-9a-fA-F]{6})\)(.*)$")
_TOKEN_NAME = re.compile(r"(?:#|//)\s*(--[a-z0-9-]+)")


def dark_tokens(text: str) -> dict[str, str]:
    """D-359 §3.4 — 네이티브·LCD 사본은 어두운 팔레트에 고정한다.

    파일 전체를 훑으면 밝게 블록이 섞인다. 사본 형식에 테마 열이 생기기 전까지는
    `:root, [data-theme="dark"]` 블록 하나와 비교한다.
    """
    return {f"--{name}": value for name, value in token_themes.palettes(text)["dark"].items()}


def copy_colours(text: str) -> list[tuple[int, str, str | None, str]]:
    """(줄 번호, #rrggbb, 토큰 이름 또는 None, 줄 꼬리)."""
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        py = _PY_COLOUR.match(line.strip())
        kt = _KT_COLOUR.search(line)
        if py:
            value = "#" + "".join(f"{int(c):02x}" for c in py.group(1, 2, 3))
            tail = py.group(4)
        elif kt:
            value = "#" + kt.group(2).lower()
            tail = kt.group(3)
        else:
            continue
        name = _TOKEN_NAME.search(tail)
        rows.append((number, value, name.group(1) if name else None, tail))
    return rows


def parity_problems(tokens: dict[str, str], label: str, text: str) -> list[str]:
    rows = copy_colours(text)
    if not rows:
        return [f"{label}: 색 사본이 한 줄도 없다 — token_copy 경로나 형식이 틀렸다"]
    problems = []
    for number, value, name, tail in rows:
        where = f"{label}:{number}"
        if name is None:
            if "token-exempt:" not in tail:
                problems.append(f"{where}: 토큰 이름도 token-exempt 이유도 없는 색 {value}")
        elif name not in tokens:
            problems.append(f"{where}: tokens.css에 없는 토큰 {name}")
        elif tokens[name] != value:
            problems.append(f"{where}: {name}는 tokens.css에서 {tokens[name]}인데 사본은 {value}")
    return problems


def test_every_token_copy_matches_tokens_css():
    tokens = dark_tokens(TOKENS.read_text(encoding="utf-8"))
    assert tokens, "tokens.css dark 블록에서 --이름: #hex 선언을 읽지 못했다"
    rows = [row for row in registry.load() if "token_parity" in (row.get("contracts") or [])]
    assert rows, "token_parity를 받는 표면이 레지스트리에 없다"
    problems = []
    for row in rows:
        path = registry.REPO / row["token_copy"]
        problems += parity_problems(tokens, row["token_copy"], path.read_text(encoding="utf-8"))
    assert problems == []


def test_a_drifted_or_unnamed_colour_is_caught():
    tokens = {"--ground": "#101214"}
    drifted = "_BG = (16, 18, 21)   # --ground #101215\n"
    unnamed = "_X = (1, 2, 3)\n"
    kotlin = "val Ground = Color(0xFF101214) // --ground\n"
    assert parity_problems(tokens, "py", drifted) == ["py:1: --ground는 tokens.css에서 #101214인데 사본은 #101215"]
    assert parity_problems(tokens, "py", unnamed) == ["py:1: 토큰 이름도 token-exempt 이유도 없는 색 #010203"]
    assert parity_problems(tokens, "kt", kotlin) == []
    assert parity_problems(tokens, "kt", "val Rose = Color(0xFFE11D48) // --rose\n") == [
        "kt:1: tokens.css에 없는 토큰 --rose"
    ]
    assert parity_problems(tokens, "empty", "") != []


def test_an_rgba_copy_line_is_compared_too():
    """2026-10-01 감사: LCD `_rose = (r, g, b, a)` 4-튜플이 정규식을 빠져나갔다.

    네 번째 성분(알파)은 값 비교에서 덜어내고 RGB 세 값으로 팔레트와 맞춘다.
    """
    tokens = {"--brand-rose": "#f697e7"}
    drifted = "_rose = (227, 27, 93, 255)  # --brand-rose #f697e7\n"
    assert parity_problems(tokens, "py", drifted) == [
        "py:1: --brand-rose는 tokens.css에서 #f697e7인데 사본은 #e31b5d"
    ]
    assert parity_problems(tokens, "py", "_rose = (246, 151, 231, 255)  # --brand-rose\n") == []
