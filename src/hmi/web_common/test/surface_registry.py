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
_SCOPES = ("path", "value", "reason", "baseline", "shape", "port", "theme", "breakpoint")

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
    """`src/` 아래 HTML 전부 — 추적 파일과 아직 add하지 않은 파일.

    `git ls-files -c -o --exclude-standard`를 쓴다. 파일시스템 `rglob`은
    `.gitignore`된 빌드 산출물을 집어오고, `-c`만 쓰면 아직 add하지 않은 새 표면이
    빠진다. 둘 다 잡는 것이 이 함수의 이유다.
    """
    base = REPO if root is None else Path(root)
    if not git_available(base):
        raise RuntimeError("D-329 발견 스캔은 git 체크아웃이 필요하다")
    out = _git(base, "ls-files", "-c", "-o", "--exclude-standard", "--", "src")
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


def media_conditions(root=None, row: dict | None = None) -> list[tuple[str, int, str]]:
    """표면의 모든 `@media` 크기 조건 — (파일, 줄, 정규화한 괄호 조건)."""
    base = REPO if root is None else Path(root)
    path = (row or {}).get("path")
    if not isinstance(path, str):
        return []
    out: list[tuple[str, int, str]] = []
    for page, css in _style_sources(base, path):
        here = page.relative_to(base).as_posix()
        for rule in _MEDIA_RULE.finditer(css):
            line = css.count("\n", 0, rule.start()) + 1
            for condition in _CONDITION.findall(rule.group(1)):
                normal = "(" + " ".join(condition[1:-1].split()) + ")"
                if _SIZE_FEATURE.search(normal):
                    out.append((here, line, normal))
    return out


def breakpoint_problems(root=None, row: dict | None = None) -> list[str]:
    """D-359 §6.1·§6.2 — `@media` 크기 조건은 세 단(또는 §6.5 높이)이거나 표면 허용 목록 값이다."""
    base = REPO if root is None else Path(root)
    listed = {entry.get("value") for entry in (row or {}).get("breakpoints") or [] if isinstance(entry, dict)}
    label = (row or {}).get("id")
    found: list[str] = []
    for here, line, condition in media_conditions(base, row):
        where = f"breakpoint: {label} {here}:{line} {condition}"
        if _LEGACY_FEATURE.search(condition):
            found.append(f"{where} — min-/max- 문법이다. 범위 문법(width < …)을 쓴다")
            continue
        if condition in TIERS or condition in TIER_UNIONS or condition in FRAME_HEIGHT:
            continue
        values = ["".join(value) for value in _LENGTH.findall(condition)]
        if not values:
            found.append(f"{where} — 크기 값을 읽을 수 없다")
        for value in values:
            if "." in value:
                found.append(f"{where} — {value}는 소수 보정값이다(.01 금지)")
            elif value not in listed:
                found.append(f"{where} — {value}가 세 단도 아니고 surfaces.yaml breakpoints에도 없다")
    return found


def _breakpoint_field_problems(base: Path, row: dict, label: str, medium) -> list[str]:
    """`breakpoints` 필드 모양 — 값·이유, 세 단 값의 중복 등재 금지, 쓰이지 않는 값 금지."""
    entries = row.get("breakpoints")
    if entries is None:
        return []
    if medium != "web":
        return [f"breakpoint: {label}는 웹 표면이 아닌데 breakpoints가 있다"]
    if not isinstance(entries, list) or not entries:
        return [f"breakpoint: {label} breakpoints가 비어 있지 않은 목록이 아니다"]
    found: list[str] = []
    used = {"".join(value) for _, _, condition in media_conditions(base, row)
            for value in _LENGTH.findall(condition)}
    seen: set[str] = set()
    for entry in entries:
        value = entry.get("value") if isinstance(entry, dict) else None
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not isinstance(value, str) or not _BREAKPOINT_VALUE.match(value):
            found.append(f"breakpoint: {label} breakpoints 값이 정수 px/rem이 아니다: {value!r}")
            continue
        if value in seen:
            found.append(f"breakpoint: {label} breakpoints에 {value}가 두 번 있다")
        seen.add(value)
        if value in TIER_VALUES:
            found.append(f"breakpoint: {label} {value}는 세 단 값이라 등재하지 않는다")
        if not isinstance(reason, str) or not reason.strip():
            found.append(f"breakpoint: {label} {value}에 reason이 없다")
        if value not in used:
            found.append(f"breakpoint: {label} {value}를 쓰는 @media가 없다 — 목록에서 지운다")
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
