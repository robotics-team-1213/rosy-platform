"""D-329 표면 레지스트리 로더 (test-support).

`surfaces.yaml`이 표면 계약 적용 범위의 단일 출처다. 이 모듈은 그 파일을 읽고
D-329 필드 규칙을 대조할 뿐이다 — 계약 내용이나 표면 목록을 여기에 다시 적지
않는다(D-92 "어휘만 공유", D-75 무번들러).

문자열 규칙 위반은 규칙 접두사로 시작한다(`path:`·`value:`·`reason:`·`baseline:`).
각 시험이 자기 접두사만 걸러 대조하므로, 빨개지면 무엇을 어겼는지 그 줄이 말해준다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

REGISTRY = "src/hmi/web_common/surfaces.yaml"
CONTRACTS = ("shared_controls", "typography_focus", "dialog")
KINDS = ("robot", "site", "sim", "dev")
#: D-345 — 매체마다 받는 계약이 다르다. 웹은 공용 컨트롤 세 계약, 웹이 아닌
#: 표면(휴대폰 앱·로봇 LCD)은 tokens.css 값 사본의 일치(token_parity)를 받는다.
CONTRACTS_BY_MEDIUM = {
    "web": CONTRACTS,
    "native": ("token_parity",),
    "lcd": ("token_parity",),
}
MEDIA = tuple(CONTRACTS_BY_MEDIUM)

#: 이 파일은 `src/hmi/web_common/test/surface_registry.py` — parents[4]가 저장소 루트다.
REPO = Path(__file__).resolve().parents[4]

_GRAMMARS_DECL = re.compile(r"GRAMMARS\s*=\s*\[([^\]]*)\]")
_ITEM = re.compile(r"['\"]([^'\"]+)['\"]")
_SCOPES = ("path", "value", "reason", "baseline", "shape", "port", "theme", "breakpoint", "colour")

#: D-359 §2·§3 — 표면이 따를 수 있는 테마. tokens.css의 테마 블록과 같은 이름이다.
THEMES = ("dark", "light")
TOKENS = "src/hmi/web_common/tokens.css"
_THEME_JS = re.compile(
    r'<link rel="stylesheet" href="/common/tokens\.css">\s*<script src="/common/theme\.js"></script>')
_PIN = re.compile(r"<html\b[^>]*\bdata-theme-pin=\"dark\"", re.I)
_THEME_COLOUR = re.compile(r'<meta\s+name="theme-color"\s+content="([^"]*)"', re.I)
_COLOUR_SCHEME = re.compile(r"color-scheme\s*:")


#: D-359 §6.1 — 세 단 어휘. 범위 문법만 쓰고 값은 rem이다. 표면이 이 밖의 값을 쓰면
#: surfaces.yaml의 그 표면 `breakpoints`에 값과 이유를 적는다(§6.2).
TIERS = ("(width < 30rem)", "(30rem <= width < 64rem)", "(width >= 64rem)")
#: 이웃한 두 단의 합(compact+medium, medium+wide)도 같은 경계만 쓰므로 세 단 어휘다.
TIER_UNIONS = ("(width < 64rem)", "(width >= 30rem)")
#: §6.5 고정 높이 프레임 규칙 — 높이 질의는 이 두 조건만 세 단과 같이 허용된다.
FRAME_HEIGHT = ("(height >= 40rem)", "(height < 40rem)")
TIER_VALUES = ("30rem", "64rem", "40rem")
_BREAKPOINT_VALUE = re.compile(r"^[1-9][0-9]*(?:px|rem)$")
_MEDIA_RULE = re.compile(r"@media\b([^{;]*)\{")
_CONTAINER_RULE = re.compile(r"@container\b([^{;]*)\{")
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CONDITION = re.compile(r"\([^()]*\)")
_SIZE_FEATURE = re.compile(r"(?<![-a-z])(?:min-|max-)?(?:device-)?(?:width|height|aspect-ratio)(?![-a-z])")
_LEGACY_FEATURE = re.compile(r"(?<![-a-z])(?:min|max)-(?:device-)?(?:width|height|aspect-ratio)(?![-a-z])")
_LENGTH = re.compile(r"(?<![\w.])([0-9]+(?:\.[0-9]+)?)(px|rem|em)\b")


def git_available(root=None) -> bool:
    """D-329 발견 스캔은 git 체크아웃에서만 성립한다(파일시스템 훑기는 금지다)."""
    base = REPO if root is None else Path(root)
    return shutil.which("git") is not None and (base / ".git").exists()


def _git(root, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )


def grammars(root=None) -> tuple[str, ...]:
    """`web_common/ui.js`의 GRAMMARS — 구문이 바뀌면 빈 튜플로 떨어져 실패한다."""
    base = REPO if root is None else Path(root)
    try:
        text = (base / "src" / "hmi" / "web_common" / "ui.js").read_text(encoding="utf-8")
    except OSError:
        return ()
    match = _GRAMMARS_DECL.search(text)
    return tuple(_ITEM.findall(match.group(1))) if match else ()


def raw_rows(root=None) -> list:
    """레지스트리 원문 항목. 형식이 아니면 그대로 내보내 문제가 보이게 한다."""
    base = REPO if root is None else Path(root)
    data = yaml.safe_load((base / REGISTRY).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("surfaces"), list):
        return []
    return data["surfaces"]


def load(root=None) -> list[dict]:
    return [row for row in raw_rows(root) if isinstance(row, dict)]


def for_contract(root=None, name: str | None = None) -> list[Path]:
    """`name` 계약을 받는 표면의 경로(등록 순서 그대로, 절대 경로)."""
    base = REPO if root is None else Path(root)
    return [base / row["path"] for row in load(base) if name in (row.get("contracts") or [])]


def discover_html(root=None) -> list[Path]:
    """`src/`·`operations/`(D-427 wave 3b) 아래 HTML 전부 — 추적 파일과 아직 add하지 않은 파일.

    `git ls-files -c -o --exclude-standard`를 쓴다. 파일시스템 `rglob`은
    `.gitignore`된 빌드 산출물을 집어오고, `-c`만 쓰면 아직 add하지 않은 새 표면이
    빠진다. 둘 다 잡는 것이 이 함수의 이유다.
    """
    base = REPO if root is None else Path(root)
    if not git_available(base):
        raise RuntimeError("D-329 발견 스캔은 git 체크아웃이 필요하다")
    out = _git(base, "ls-files", "-c", "-o", "--exclude-standard", "--", "src", "operations")
    return [base / line for line in out.stdout.splitlines() if line.endswith(".html")]


def tracked(root, relative: str) -> bool:
    base = Path(root)
    return _git(base, "ls-files", "--error-unmatch", "--", relative).returncode == 0


def _pages(base: Path, path: str, suffix: str = ".html") -> list[Path]:
    """표면 경로 아래 파일 — 파일 표면은 그 파일, 폴더는 추적·새 파일(git) 또는 훑기."""
    target = base / path
    if target.is_file():
        return [target] if target.suffix == suffix else []
    if not target.is_dir():
        return []
    if git_available(base):
        out = _git(base, "ls-files", "-c", "-o", "--exclude-standard", "--", path)
        return [base / line for line in out.stdout.splitlines() if line.endswith(suffix)]
    return sorted(target.rglob(f"*{suffix}"))


def _dark_ground(base: Path) -> str | None:
    import token_themes

    try:
        return token_themes.palettes(token_themes.read(base / TOKENS)).get("dark", {}).get("ground")
    except OSError:
        return None


def _theme_problems(base: Path, row: dict, label: str, medium) -> list[str]:
    """D-359 themes 필드와 그 표면의 HTML·CSS가 서로 맞는지."""
    themes = row.get("themes")
    if not isinstance(themes, list) or not themes:
        return [f"theme: {label}에 themes 목록이 없다"]
    found: list[str] = []
    if len(set(themes)) != len(themes) or any(theme not in THEMES for theme in themes):
        found.append(f"theme: {label} themes가 {THEMES} 안의 중복 없는 값이 아니다: {themes!r}")
    if themes[0] != "dark":
        found.append(f"theme: {label} themes의 첫 값(기본)이 dark가 아니다: {themes!r}")
    if medium != "web":
        if themes != ["dark"]:
            found.append(f"theme: {label}는 웹이 아닌 사본이라 [dark]에 고정한다(D-359 §3.4): {themes!r}")
        return found

    path = row.get("path")
    if not isinstance(path, str):
        return found
    pinned = themes == ["dark"]
    if pinned and not str(row.get("theme_reason") or "").strip():
        found.append(f"theme: {label}는 [dark] 고정 웹 표면인데 theme_reason이 없다")
    if not pinned and row.get("theme_reason"):
        found.append(f"theme: {label}는 테마를 따르는데 theme_reason이 남아 있다")
    ground = _dark_ground(base)
    for page in _pages(base, path):
        here = page.relative_to(base).as_posix()
        text = page.read_text(encoding="utf-8")
        if pinned and not _PIN.search(text):
            found.append(f'theme: {label} {here}가 [dark] 표면인데 <html data-theme-pin="dark">가 없다')
        if not pinned and not _THEME_JS.search(text):
            found.append(f"theme: {label} {here}가 tokens.css 바로 뒤에 /common/theme.js를 싣지 않는다")
        if not pinned and _PIN.search(text):
            found.append(f"theme: {label} {here}가 테마를 따르는 표면인데 고정 속성을 가진다")
        for colour in _THEME_COLOUR.findall(text):
            if ground is None or colour.lower() != ground:
                found.append(f"theme: {label} {here} 정적 theme-color {colour}가 dark --ground {ground}가 아니다")
    if not pinned:
        for sheet in _pages(base, path, ".css"):
            if sheet.name != "tokens.css" and _COLOUR_SCHEME.search(sheet.read_text(encoding="utf-8")):
                found.append(f"theme: {label} {sheet.relative_to(base).as_posix()}가 color-scheme을 선언한다 — 테마 블록의 몫이다")
    return found


def _style_sources(base: Path, path: str) -> list[tuple[Path, str]]:
    """표면의 CSS 파일과 HTML 안 `<style>` 본문. 주석과 `<style>` 밖은 줄바꿈만 남겨 줄 번호를 지킨다."""
    found: list[tuple[Path, str]] = []
    for suffix in (".css", ".html"):
        for page in _pages(base, path, suffix):
            if "test" in page.relative_to(base).parts:
                continue
            text = page.read_text(encoding="utf-8")
            if suffix == ".html":
                kept, cursor = [], 0
                for match in _STYLE_BLOCK.finditer(text):
                    kept.append("\n" * text.count("\n", cursor, match.start(1)))
                    kept.append(match.group(1))
                    cursor = match.end(1)
                text = "".join(kept)
            text = _CSS_COMMENT.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
            found.append((page, text))
    return found


def _size_conditions(base: Path, row: dict | None, rule: re.Pattern) -> list[tuple[str, int, str]]:
    path = (row or {}).get("path")
    if not isinstance(path, str):
        return []
    out: list[tuple[str, int, str]] = []
    for page, css in _style_sources(base, path):
        here = page.relative_to(base).as_posix()
        for match in rule.finditer(css):
            line = css.count("\n", 0, match.start()) + 1
            for condition in _CONDITION.findall(match.group(1)):
                normal = "(" + " ".join(condition[1:-1].split()) + ")"
                if _SIZE_FEATURE.search(normal):
                    out.append((here, line, normal))
    return out


def media_conditions(root=None, row: dict | None = None) -> list[tuple[str, int, str]]:
    """표면의 모든 `@media` 크기 조건 — (파일, 줄, 정규화한 괄호 조건)."""
    return _size_conditions(REPO if root is None else Path(root), row, _MEDIA_RULE)


def container_conditions(root=None, row: dict | None = None) -> list[tuple[str, int, str]]:
    """표면의 모든 `@container` 크기 조건(§6.3 칸 질의) — (파일, 줄, 정규화한 괄호 조건)."""
    return _size_conditions(REPO if root is None else Path(root), row, _CONTAINER_RULE)


def _size_problems(conditions, listed: set, where_label: str, allowed: tuple, field: str) -> list[str]:
    found: list[str] = []
    for here, line, condition in conditions:
        where = f"breakpoint: {where_label} {here}:{line} {condition}"
        if _LEGACY_FEATURE.search(condition):
            found.append(f"{where} — min-/max- 문법이다. 범위 문법(width < …)을 쓴다")
            continue
        if condition in allowed:
            continue
        values = ["".join(value) for value in _LENGTH.findall(condition)]
        if not values:
            found.append(f"{where} — 크기 값을 읽을 수 없다")
        for value in values:
            if "." in value:
                found.append(f"{where} — {value}는 소수 보정값이다(.01 금지)")
            elif value not in listed:
                found.append(f"{where} — {value}가 세 단도 아니고 surfaces.yaml {field}에도 없다")
    return found


def _listed(row: dict | None, field: str) -> set:
    return {entry.get("value") for entry in (row or {}).get(field) or [] if isinstance(entry, dict)}


def breakpoint_problems(root=None, row: dict | None = None) -> list[str]:
    """D-359 §6.1·§6.2 — `@media` 크기 조건은 세 단(또는 §6.5 높이)이거나 표면 허용 목록 값이다."""
    base = REPO if root is None else Path(root)
    return _size_problems(media_conditions(base, row), _listed(row, "breakpoints"), (row or {}).get("id"),
                          TIERS + TIER_UNIONS + FRAME_HEIGHT, "breakpoints")


def container_problems(root=None, row: dict | None = None) -> list[str]:
    """D-359 §6.3 — `@container` 크기 조건은 세 단 경계이거나 표면 `container_breakpoints` 값이다."""
    base = REPO if root is None else Path(root)
    return _size_problems(container_conditions(base, row), _listed(row, "container_breakpoints"),
                          (row or {}).get("id"), TIERS + TIER_UNIONS, "container_breakpoints")


def _breakpoint_field_problems(base: Path, row: dict, label: str, medium) -> list[str]:
    """`breakpoints`·`container_breakpoints` 필드 모양 — 값·이유, 세 단 값의 중복 등재 금지, 쓰이지 않는 값 금지."""
    found: list[str] = []
    for field, conditions, at in (("breakpoints", media_conditions, "@media"),
                                  ("container_breakpoints", container_conditions, "@container")):
        entries = row.get(field)
        if entries is None:
            continue
        tag = "" if field == "breakpoints" else f"{field} "
        if medium != "web":
            found.append(f"breakpoint: {label}는 웹 표면이 아닌데 {field}가 있다")
            continue
        if not isinstance(entries, list) or not entries:
            found.append(f"breakpoint: {label} {field}가 비어 있지 않은 목록이 아니다")
            continue
        used = {"".join(value) for _, _, condition in conditions(base, row)
                for value in _LENGTH.findall(condition)}
        seen: set[str] = set()
        for entry in entries:
            value = entry.get("value") if isinstance(entry, dict) else None
            reason = entry.get("reason") if isinstance(entry, dict) else None
            if not isinstance(value, str) or not _BREAKPOINT_VALUE.match(value):
                found.append(f"breakpoint: {label} {field} 값이 정수 px/rem이 아니다: {value!r}")
                continue
            if value in seen:
                found.append(f"breakpoint: {label} {field}에 {value}가 두 번 있다")
            seen.add(value)
            if value in TIER_VALUES:
                found.append(f"breakpoint: {label} {tag}{value}는 세 단 값이라 등재하지 않는다")
            if not isinstance(reason, str) or not reason.strip():
                found.append(f"breakpoint: {label} {tag}{value}에 reason이 없다")
            if value not in used:
                found.append(f"breakpoint: {label} {tag}{value}를 쓰는 {at}가 없다 — 목록에서 지운다")
    return found


#: D-359 §7.2 — 원시 색. hex와 함수형 색 전부(`color-mix(`와 `var(`는 아니다).
RAW_COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:rgba?|hsla?|hwb|oklch|oklab|lab|lch|color)\(")
_COLOUR_SUFFIXES = (".css", ".js", ".html")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_JS_LINE_COMMENT = re.compile(r"(?:(?<=^)|(?<=[\s;{}(),]))//[^\n]*", re.M)
_THEME_COLOUR_VALUE = re.compile(r'(<meta\s+name="theme-color"\s+content=")([^"]*)(")', re.I)
_TOP_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
#: 라이브러리 예외 — 저장소 상대 파일 → 그대로 지울 조각. 각 조각의 이유:
#: ui.js `cssColor`는 RosyPalette가 풀어 낸 [r,g,b,a] 바이트를 캔버스 fillStyle 문자열로
#: 옮기는 형식기다. 값은 tokens.css에서 오고 이 글자에는 색 리터럴이 없다.
LIBRARY_COLOUR_FORMATS = {
    "src/hmi/web_common/ui.js": ("rgba(${r}, ${g}, ${b}, ${a})",),
}


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def colour_sources(root=None, row: dict | None = None) -> list[tuple[Path, str]]:
    """표면의 CSS·JS·HTML(시험 폴더 제외) — 주석과 정적 theme-color 값을 공백으로 지운 본문.

    줄 번호는 지킨다. 정적 theme-color는 `_theme_problems`(§7.3)가 dark `--ground`와 대조한다.
    """
    base = REPO if root is None else Path(root)
    path = (row or {}).get("path")
    if not isinstance(path, str):
        return []
    out: list[tuple[Path, str]] = []
    for suffix in _COLOUR_SUFFIXES:
        for page in _pages(base, path, suffix):
            if "test" in page.relative_to(base).parts:
                continue
            text = page.read_text(encoding="utf-8")
            if suffix == ".html":
                text = _HTML_COMMENT.sub(_blank, text)
                text = _THEME_COLOUR_VALUE.sub(
                    lambda m: m.group(1) + " " * len(m.group(2)) + m.group(3), text)
            text = _CSS_COMMENT.sub(_blank, text)
            if suffix != ".css":
                text = _JS_LINE_COMMENT.sub(_blank, text)
            for snippet in LIBRARY_COLOUR_FORMATS.get(page.relative_to(base).as_posix(), ()):
                text = text.replace(snippet, " " * len(snippet))
            out.append((page, text))
    return out


def _colour_folder(base: Path, path: str) -> Path:
    target = base / path
    return target.parent if target.is_file() else target


def _raw_colour_entries(base: Path, row: dict, label: str) -> tuple[list[str], list[dict]]:
    """`raw_colours` 필드 — (문제, 쓸 수 있는 항목). 이유·파일·블록이 맞는 항목만 가린다."""
    entries = row.get("raw_colours")
    if entries is None:
        return [], []
    if row.get("medium") != "web" or row.get("themes") != ["dark"]:
        return [f"colour: {label} raw_colours는 [dark] 고정 웹 표면만 가진다(D-359 §7.2)"], []
    if not isinstance(entries, list) or not entries:
        return [f"colour: {label} raw_colours가 비어 있지 않은 목록이 아니다"], []
    path = row.get("path")
    if not isinstance(path, str):
        return [], []
    folder = _colour_folder(base, path)
    sources = {page.relative_to(folder).as_posix(): text for page, text in colour_sources(base, row)}
    found: list[str] = []
    usable: list[dict] = []
    for entry in entries:
        name = entry.get("file") if isinstance(entry, dict) else None
        block = entry.get("block") if isinstance(entry, dict) else None
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not isinstance(name, str) or name not in sources:
            found.append(f"colour: {label} raw_colours {name}가 표면 파일이 아니다")
            continue
        if block is not None and block not in [sel.strip() for sel, _ in _TOP_RULE.findall(sources[name])]:
            found.append(f"colour: {label} raw_colours {name}에 {block} 블록이 없다")
            continue
        if not isinstance(reason, str) or not reason.strip():
            found.append(f"colour: {label} raw_colours {name}에 reason이 없다")
            continue
        usable.append({"file": name, "block": block})
    return found, usable


def _colour_hits(base: Path, row: dict, usable: list[dict]) -> tuple[list[str], set[int]]:
    """가려지지 않은 원시 색 줄과, 무언가를 가린 항목 번호."""
    label = row.get("id")
    folder = _colour_folder(base, row["path"])
    tokens = (base / TOKENS).resolve()
    hits: list[str] = []
    used: set[int] = set()
    for page, text in colour_sources(base, row):
        name = page.relative_to(folder).as_posix()
        spans: list[tuple[int, int, int | None]] = []
        if page.resolve() == tokens:
            # 테마 팔레트 블록은 색의 원본이다(§1.1). 파생 `:root`는 여기서도 본다.
            spans += [(m.start(2), m.end(2), None) for m in _TOP_RULE.finditer(text)
                      if "[data-theme=" in m.group(1)]
        for index, entry in enumerate(usable):
            if entry["file"] != name:
                continue
            if entry["block"] is None:
                spans.append((0, len(text), index))
            else:
                spans += [(m.start(2), m.end(2), index) for m in _TOP_RULE.finditer(text)
                          if m.group(1).strip() == entry["block"]]
        for match in RAW_COLOUR.finditer(text):
            cover = [owner for start, end, owner in spans if start <= match.start() < end]
            if cover:
                used.update(owner for owner in cover if owner is not None)
                continue
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"colour: {label} {page.relative_to(base).as_posix()}:{line} {match.group(0)}")
    return hits, used


def raw_colour_problems(root=None, row: dict | None = None) -> list[str]:
    """D-359 §7.2 — 표면의 CSS·JS·HTML에 가려지지 않은 원시 색."""
    base = REPO if root is None else Path(root)
    if not isinstance((row or {}).get("path"), str):
        return []
    _, usable = _raw_colour_entries(base, row, row.get("id"))
    return _colour_hits(base, row, usable)[0]


def _raw_colour_field_problems(base: Path, row: dict, label: str) -> list[str]:
    found, usable = _raw_colour_entries(base, row, label)
    if usable:
        _, used = _colour_hits(base, row, usable)
        found += [f"colour: {label} raw_colours {entry['file']}가 가리는 원시 색이 없다 — 목록에서 지운다"
                  for index, entry in enumerate(usable) if index not in used]
    return found


def problems(root=None) -> list[str]:
    """D-329 필드 규칙 위반. 빈 리스트면 레지스트리가 규칙을 지킨다."""
    base = REPO if root is None else Path(root)
    rows = raw_rows(base)
    if not rows:
        return [f"shape: {REGISTRY}에 표면 항목이 없다"]

    known_grammars = grammars(base)
    found: list[str] = []
    if not known_grammars:
        found.append("value: web_common/ui.js가 GRAMMARS를 선언하지 않는다")

    seen: set[str] = set()
    ports_seen: dict[int, object] = {}
    for index, row in enumerate(rows, start=1):
        where = f"{REGISTRY} 항목 {index}"
        if not isinstance(row, dict):
            found.append(f"shape: {where}이(가) 표 형식이 아니다")
            continue

        ident = row.get("id")
        label = f"{where} ({ident})" if isinstance(ident, str) and ident else where
        if not isinstance(ident, str) or not ident.strip():
            found.append(f"value: {where}에 id가 없다")
        elif ident in seen:
            found.append(f"value: {label} id가 중복이다")
        else:
            seen.add(ident)

        path = row.get("path")
        if not isinstance(path, str) or not path.strip():
            found.append(f"path: {label}에 path가 없다")
        elif path.startswith(("/", "\\")) or ".." in Path(path).parts:
            found.append(f"path: {label} path가 저장소 상대 경로가 아니다: {path}")
        elif not (base / path).exists():
            found.append(f"path: {label} path가 저장소에 없다: {path}")

        kind = row.get("surface")
        if kind not in KINDS:
            found.append(f"value: {label} surface가 {KINDS} 밖이다: {kind!r}")

        audience = row.get("audience")
        if not isinstance(audience, str) or not audience.strip() or "\n" in audience:
            found.append(f"value: {label}에 한 줄짜리 audience가 없다")

        # D-370 1·4항: 표면마다 역할 한 줄과 소유 조작 목록. 겹침 판정은 test/architecture/test_app_roles.py.
        role = row.get("role")
        if not isinstance(role, str) or not role.strip() or "\n" in role:
            found.append(f"value: {label}에 한 줄짜리 role이 없다")
        owns = row.get("owns")
        if not isinstance(owns, list):
            found.append(f"value: {label}에 owns 목록이 없다")
        else:
            names = []
            for entry in owns:
                name = entry.get("id") if isinstance(entry, dict) else entry
                if not isinstance(name, str) or not name.strip():
                    found.append(f"value: {label} owns 항목이 이름이 아니다: {entry!r}")
                    continue
                if isinstance(entry, dict) and not (
                        isinstance(entry.get("transitional"), str) and entry["transitional"].strip()):
                    found.append(f"value: {label} owns {name}이(가) 표이지만 transitional 사유가 없다")
                names.append(name)
            if len(set(names)) != len(names):
                found.append(f"value: {label} owns에 중복이 있다")

        medium = row.get("medium")
        if medium not in MEDIA:
            found.append(f"value: {label} medium이 {MEDIA} 밖이다: {medium!r}")
        expected = CONTRACTS_BY_MEDIUM.get(medium, CONTRACTS)

        contracts = row.get("contracts")
        if not isinstance(contracts, list):
            found.append(f"value: {label}에 contracts 목록이 없다")
            contracts = []
        else:
            if len(set(contracts)) != len(contracts):
                found.append(f"value: {label} contracts에 중복이 있다")
            for name in contracts:
                if name not in expected:
                    found.append(f"value: {label} contracts가 {medium} 매체의 {expected} 밖이다: {name!r}")

        reason = row.get("contract_reason")
        if set(contracts) != set(expected) and not (isinstance(reason, str) and reason.strip()):
            found.append(f"reason: {label}이(가) 매체 계약 일부만 받는데 contract_reason이 없다")

        copy = row.get("token_copy")
        if "token_parity" in contracts:
            if not isinstance(copy, str) or not copy.strip():
                found.append(f"path: {label}이(가) token_parity를 받는데 token_copy가 없다")
            elif not (base / copy).is_file():
                found.append(f"path: {label} token_copy 파일이 저장소에 없다: {copy}")

        found.extend(_theme_problems(base, row, label, medium))
        found.extend(_breakpoint_field_problems(base, row, label, medium))
        found.extend(_raw_colour_field_problems(base, row, label))

        grammar = row.get("grammar")
        if grammar is not None and grammar not in known_grammars:
            found.append(f"value: {label} grammar가 GRAMMARS 밖이다: {grammar!r}")

        for entry in row.get("ports") or []:
            port = entry.get("port") if isinstance(entry, dict) else None
            source = entry.get("source") if isinstance(entry, dict) else None
            if not isinstance(port, int) or not 1 <= port <= 65535:
                found.append(f"port: {label} ports 항목의 port가 1–65535 정수가 아니다: {port!r}")
                continue
            if port in ports_seen:
                found.append(f"port: {label}의 {port}를 {ports_seen[port]}도 쓴다")
            ports_seen[port] = ident
            if not isinstance(source, str) or not (base / source).is_file():
                found.append(f"port: {label} {port}의 source 파일이 없다: {source!r}")
            elif not re.search(rf"(?<!\d){port}(?!\d)", (base / source).read_text(encoding="utf-8")):
                found.append(f"port: {label} {port}가 source {source}의 기본값에 없다")

        baseline = row.get("baseline")
        if baseline is None:
            why = row.get("baseline_reason")
            if not (isinstance(why, str) and why.strip()):
                found.append(f"reason: {label}에 baseline이 없는데 baseline_reason도 없다")
        elif not isinstance(baseline, str) or not baseline.strip():
            found.append(f"baseline: {label} baseline이 문자열이 아니다")
        elif not (base / baseline).is_file():
            found.append(f"baseline: {label} baseline 파일이 저장소에 없다: {baseline}")
        elif git_available(base) and not tracked(base, baseline):
            found.append(f"baseline: {label} baseline이 추적 파일이 아니다: {baseline}")

    return found


def problems_with(root, scope: str) -> list[str]:
    if scope not in _SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    prefix = f"{scope}: "
    return [line for line in problems(root) if line.startswith(prefix)]
