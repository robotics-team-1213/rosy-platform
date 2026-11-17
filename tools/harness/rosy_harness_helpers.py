"""Constants, parsers, validators, and status/brief renderers for rosy_harness."""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from log_validation import LOG_FIELDS, LOG_FIELD_ALIASES, validate_entries  # noqa: E402,F401
from generated_records import _normalize  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adr_gaps import ADR_ID  # noqa: E402

CONFIG = Path("tools") / "harness" / "harness.yaml"
GATES = ("SOURCE", "LOCAL", "ROS-SIM", "ARTIFACT", "DEVICE", "FIELD")
STATES = ("GO", "HOLD", "PARKED", "N/A")
REQUIRED_PROGRESS = ("module", "owner", "last_verified", "gates")
RECENT_LOGS = 5
UNCOMMITTED = "uncommitted"

# Historical reference data is separate from the generic harness implementation.
KNOWN_LOG_ENCODING_REPAIRS = yaml.safe_load(
    Path(__file__).with_name("log_repairs.yaml").read_text(encoding="utf-8"))

COMMIT = re.compile(rf"^(?:[0-9a-f]{{7,40}}|{UNCOMMITTED})$")
LOGICAL_MODULE = re.compile(r"^M\d{2}$")
LOG_HEADING = re.compile(rf"^## (\d{{4}}-\d{{2}}-\d{{2}}) · ([0-9a-f]{{7,40}}|{UNCOMMITTED}) · (\S.*)$")
FENCE = re.compile(r"^(```|~~~)")
CONFLICT_MARKER = re.compile(r"^(<<<<<<<|=======|>>>>>>>)( |$)")
ADR_INDEX_ROW = re.compile(r"^\| (D-\d+) \| ([^|]+?) \| ([^|]+?) \|\s*$", re.MULTILINE)
# D-36 was recorded as "## D-36: title (date)"; accept that form rather than rewrite the log.
ADR_BODY_HEADING = re.compile(r"^## (D-\d+):? (.+)$", re.MULTILINE)

# Committed historical log headings that predate the strict LOG_HEADING schema
# or were merged before the missing commit/bullet check existed; logs.md is
# append-only so exact committed headings are allowlisted rather than rewritten.
KNOWN_LEGACY_HEADINGS = frozenset({
    "## 2026-10-12 · 대화 요청 상태와 잠금 사유 보완",
    "## 2026-10-12 · D-693 계약 설명 정렬",
    "## 2026-10-09 · uncommitted · fix(pilot): 승인 코드 입력칸이 한글 키보드에서 깨졌다",
    "## 2026-10-09 · uncommitted · fix(core): 화면 코드 승인이 실기에서 항상 409였다 (D-483)",
    "## 2026-10-08 \u00b7 uncommitted \u00b7 docs(api): v1.124 version pin",
    "## 2026-10-08 \u00b7 uncommitted \u00b7 fix(fleet): D-509 power health at state response",
    "## 2026-10-07 · uiux/pilot-empty-copy · Pilot 로봇 미발견 안내 줄바꿈",
    "## 2026-10-04 · uncommitted · site(D-441): automatic site stack updates",
    "## 2026-09-26 - prepare selected OMX-AI workcell target",
    "## 2026-09-19: Core 패키지 모듈화 (Level 3 Phase 1)",
    "## 2026-09-19: Core 패키지 모듈화 (Level 3 Phase 2 & 3)",
    "## 2026-09-19: Core 패키지 모듈화 완료 (Level 3 Phase 4 & 5)",
    "## 2026-09-19: Fleet 도메인 폴더명 변경 (site)",
    "## 2026-09-20 · uncommitted · feat(fleet): Robot Selection lands (FOR-001) and the gather bench puts a number on N (D-131 phases 2-3)",
    "## 2026-09-20 · uncommitted · test(fleet): the sim runs end-to-end and the console exposes two real defects (D-131 phase 1 LOCAL evidence)",
    "## 2026-09-20 · uncommitted · chore(fleet): relay diagnosis fields exposed; live iteration deferred to D-83 (environment)",
    "## 2026-09-20 · uncommitted · fix(fleet): defect (a) resolved in the live sim — relay delivers, no early HOLD (D-132 validated)",
    "## 2026-09-28 - uiux/device-refresh-access - rerun latest-main role G2",
    "## 2026-09-28 - uiux/mobile-acceptance - test: verify localization pending action state",
    "## 2026-09-28 - uiux/device-security-feedback-evidence - fix: clear stale token list after mutation refresh failure",
    "## 2026-09-28 - uiux/host-console-readback-evidence - verify independent readbacks and mode feedback",
    "## 2026-09-28 - uiux/console-teleop-feedback-evidence - verify readiness and action feedback",
    "## 2026-09-28 - uiux/host-console-readback-evidence - verify line-follow and docking feedback",
    "## 2026-09-28 - uiux/host-console-readback-evidence - verify console map feedback",
    "## 2026-09-28 - uiux/host-console-readback-evidence - verify device hardware refresh feedback",
    "## 2026-09-28 - uiux/host-console-readback-evidence - verify identity editor polling",
    "## 2026-09-28 - uiux/device-refresh-access - check hardware permission hint reachability",
    "## 2026-09-28 · uncommitted · test(device): verify identity draft and hardware action feedback at two widths",
    "## 2026-09-22",
    "## 2026-09-27 · docs(validation): record merged-main site candidate smoke",
    "## 2026-09-27 ? docs(validation): record merged-main site candidate smoke",
    "## 2026-09-26 \u00b7 uncommitted \u00b7 docs(adr): propose D-282 per-hardware ROS ownership",
    "## 2026-09-26 \u00b7 uncommitted \u00b7 OMX \ub2e8\uc77c \uc18c\uc720\uc790 ROS-SIM \ud6c4\uc18d\uacfc \uc774\uc804 \uc808\ucc28",
    "## 2026-09-29 · 5545ce37..uncommitted · feat(fleet): land policy evidence config and store (T2/T3)",
    "## 2026-09-29 · 72802f30·895786cf · feat: 실물 차선 자동 주행(D-349 보조 자율)",
    "## 2026-09-29 · 35efb5ba · feat(core): 차선 추종 앞 물체 정지(LiDAR, D-349 §11)",
    "## 2026-10-01 - D-392 P3 closed model-tool catalog",
})

GENERATED_MARK = (
    "<!-- GENERATED by tools/harness/rosy_harness.py generate. "
    "Edit progress.md, logs.md, or the ADR log instead. -->"
)


class HarnessError(ValueError):
    """A harness record cannot be read at all."""


def _adr_number(adr_id: str) -> int:
    return int(adr_id.split("-")[1])


def split_frontmatter(text: str) -> tuple[dict, str]:
    text = _normalize(text)
    if not text.startswith("---\n"):
        raise HarnessError("missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise HarnessError("unterminated YAML frontmatter")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise HarnessError("frontmatter is not a mapping")
    return meta, text[end + len("\n---\n"):].lstrip("\n")


def validate_progress(meta: dict, known_adrs: set[str] | None = None) -> list[str]:
    errors = [f"missing field: {key}" for key in REQUIRED_PROGRESS if key not in meta]

    if "last_verified" in meta:
        verified = meta["last_verified"]
        if not isinstance(verified, dict):
            errors.append("last_verified must map commit and date")
        else:
            commit = verified.get("commit")
            if not isinstance(commit, str) or not COMMIT.match(commit):
                errors.append(f"last_verified.commit must be a quoted 7-40 hex commit or {UNCOMMITTED!r}")
            if not isinstance(verified.get("date"), dt.date):
                errors.append("last_verified.date must be YYYY-MM-DD")

    gates = meta.get("gates")
    if "gates" in meta and not isinstance(gates, dict):
        errors.append("gates must be a mapping")
        gates = {}
    gates = gates or {}
    if "gates" in meta:
        errors += [f"missing gate: {g} (write N/A when the profile excludes it)" for g in GATES if g not in gates]
    for name, gate in gates.items():
        if name not in GATES:
            errors.append(f"unknown gate: {name}")
            continue
        if not isinstance(gate, dict):
            errors.append(f"{name}: gate must be a mapping")
            continue
        state = gate.get("state")
        if state not in STATES:
            errors.append(f"{name}: unknown state {state!r}")
        elif state == "GO":
            errors += [f"{name}: GO requires {field}" for field in ("evidence", "cmd") if not gate.get(field)]
        elif state == "HOLD" and not gate.get("blocker"):
            errors.append(f"{name}: HOLD requires blocker")

    for adr_id in meta.get("adrs") or []:
        if not isinstance(adr_id, str) or not ADR_ID.match(adr_id):
            errors.append(f"malformed ADR id: {adr_id}")
        elif known_adrs is not None and adr_id not in known_adrs:
            errors.append(f"unknown ADR: {adr_id}")

    for logical in meta.get("logical_modules") or []:
        if not isinstance(logical, str) or not LOGICAL_MODULE.match(logical):
            errors.append(f"malformed logical module: {logical}")

    return errors


@dataclass(frozen=True)
class LogEntry:
    date: str
    commit: str
    summary: str
    body: str

    @property
    def heading(self) -> str:
        return f"## {self.date} · {self.commit} · {self.summary}"


def _scan_log(text: str) -> tuple[list[LogEntry], list[str]]:
    entries: list[LogEntry] = []
    errors: list[str] = []
    current: tuple[str, str, str] | None = None
    body: list[str] = []
    in_fence = False

    def close() -> None:
        if current is not None:
            entries.append(LogEntry(*current, body="\n".join(body)))

    for number, line in enumerate(_normalize(text).split("\n"), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
        if in_fence or FENCE.match(line) or not line.startswith("## "):
            if current is not None:
                body.append(line)
            continue
        close()
        body = []
        match = LOG_HEADING.match(line)
        if line in KNOWN_LEGACY_HEADINGS:
            current = None
        elif match:
            current = match.groups()
        else:
            current = None
            errors.append(f"line {number}: malformed heading {line!r}")
    close()
    return entries, errors


def parse_log(text: str) -> list[LogEntry]:
    return _scan_log(text)[0]


def validate_log(text: str) -> list[str]:
    return validate_entries(*_scan_log(text), KNOWN_LEGACY_HEADINGS)


def _log_entry_blocks(text: str) -> set:
    """`## ` 헤딩 단위로 로그를 항목 블록으로 분해한다(정규화·양끝 여백 제거)."""
    blocks: set = set()
    current: list = []
    for line in _normalize(text).split("\n"):
        if line.startswith("## "):
            if current:
                blocks.add("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.add("\n".join(current).strip())
    return blocks


@dataclass(frozen=True)
class AdrLog:
    index: dict[str, tuple[str, str]]
    bodies: dict[str, str]
    duplicates: tuple[str, ...] = ()
    #: D-n appearing in more than one index row (D-346: dict collapse hid these).
    index_duplicates: tuple[str, ...] = ()


def parse_adr_log(text: str, adr_dir: Path | None = None) -> AdrLog:
    text = _normalize(text)
    if adr_dir and adr_dir.is_dir():
        for p in adr_dir.glob("*.md"):
            text += "\n\n" + _normalize(p.read_text(encoding="utf-8"))
    first_body = ADR_BODY_HEADING.search(text)
    index_text = text[: first_body.start()] if first_body else text
    index: dict[str, tuple[str, str]] = {}
    index_duplicates: list[str] = []
    for m in ADR_INDEX_ROW.finditer(index_text):
        if m.group(1) in index:
            index_duplicates.append(m.group(1))
        index[m.group(1)] = (m.group(2).strip(), m.group(3).strip())
    bodies: dict[str, str] = {}
    duplicates: list[str] = []
    for match in ADR_BODY_HEADING.finditer(text):
        if match.group(1) in bodies:
            duplicates.append(match.group(1))
        bodies[match.group(1)] = match.group(2).strip()
    return AdrLog(index=index, bodies=bodies, duplicates=tuple(duplicates),
                  index_duplicates=tuple(index_duplicates))


def load_config(repo: Path) -> dict:
    return yaml.safe_load((repo / CONFIG).read_text(encoding="utf-8"))


def _link(from_dir: Path, target: Path) -> str:
    return quote(os.path.relpath(target, from_dir).replace(os.sep, "/"), safe="/-._~")


def _names_module(meta: dict, name: str) -> bool:
    modules = meta.get("modules") or []
    return meta.get("module") == name or (isinstance(modules, list) and name in modules)


def _read_progress(repo: Path, module: dict) -> dict:
    path = repo / module["path"] / "progress.md"
    try:
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HarnessError(f"{module['name']}: missing progress.md") from exc
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise HarnessError(f"{module['name']}: unreadable progress.md: {exc}") from exc
    return meta


def _read_log(repo: Path, module: dict) -> list[LogEntry]:
    path = repo / module["path"] / "logs.md"
    return parse_log(path.read_text(encoding="utf-8")) if path.is_file() else []


def render_status(repo: Path, config: dict) -> str:
    status_dir = (repo / config["status"]).parent
    lines = [
        GENERATED_MARK,
        "# Rosy OS module status",
        "",
        "각 모듈 `progress.md`의 gate 스냅샷을 모은 것이다. 계약은 SRS·API·ADR이 우선한다.",
        "",
        "| 모듈 | owner | last verified | " + " | ".join(GATES) + " |",
        "|---|---|---|" + "---|" * len(GATES),
    ]
    blockers: list[str] = []
    for module in config["modules"]:
        meta = _read_progress(repo, module)
        gates = meta.get("gates") or {}
        verified = meta.get("last_verified") or {}
        cells = [str((gates.get(g) or {}).get("state", "—")) for g in GATES]
        link = _link(status_dir, repo / module["path"] / "progress.md")
        lines.append(
            f"| [{module['name']}]({link}) | {meta.get('owner', '?')} | "
            f"{verified.get('commit', '?')} ({verified.get('date', '?')}) | " + " | ".join(cells) + " |"
        )
        for gate in GATES:
            if (gates.get(gate) or {}).get("state") == "HOLD":
                blockers.append(f"- {module['name']} {gate}: {gates[gate].get('blocker')}")
    lines += ["", "## HOLD blockers", ""] + (blockers or ["- 없음"])
    return "\n".join(lines) + "\n"


def render_brief(repo: Path) -> str:
    """Short session-start context: every module's gates and the record loop."""
    config = load_config(repo)
    lines = ["[Rosy OS module harness, ADR D-61] 모듈 gate (각 progress.md 기준, 계약은 SRS·API·ADR 우선):"]
    for module in config["modules"]:
        try:
            meta = _read_progress(repo, module)
        except HarnessError as exc:
            lines.append(f"- {module['name']}: {exc}")
            continue
        problems = validate_progress(meta)
        if problems:
            lines.append(f"- {module['name']} ({module['path']}): invalid progress.md ({len(problems)} errors: {problems[0]})")
            continue
        gates = meta.get("gates") or {}
        cells = " ".join(f"{g}={(gates.get(g) or {}).get('state', '—')}" for g in GATES)
        commit = (meta.get("last_verified") or {}).get("commit", "?")
        lines.append(f"- {module['name']} ({module['path']}, verified {commit}): {cells}")
    lines += [
        "작업 순서: 모듈 progress.md·index.md 읽기 → 변경 → logs.md에 항목 추가 → gate가 바뀌면 progress.md 덮어쓰기"
        " → `python tools/harness/rosy_harness.py generate` → `lint`.",
        "HOLD blocker 전체: STATUS.md",
    ]
    return "\n".join(lines) + "\n"


def find_conflict_markers(text: str) -> list[int]:
    """1-based line numbers of git conflict markers at the start of a line."""
    return [number for number, line in enumerate(_normalize(text).split("\n"), start=1) if CONFLICT_MARKER.match(line)]


def find_mojibake(text: str) -> list[int]:
    """1-based line numbers with '??' runs — a codepage ate the Korean (D-346)."""
    return [number for number, line in enumerate(text.split("\n"), start=1)
            if "??" in line]


def _moved_roots(repo: Path) -> list[dict]:
    """D-427 manifest roots that record their pre-move path as ``legacy``."""
    manifest = repo / "tools" / "harness" / "platform_parts.yaml"
    if not manifest.is_file():
        return []
    roots = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("roots") or []
    return [root for root in roots if root.get("legacy")]


def _moved_owner(module_path: str, moved_roots: list[dict]) -> dict | None:
    owners = [root for root in moved_roots
              if module_path == root["path"] or module_path.startswith(root["path"] + "/")]
    return max(owners, key=lambda root: len(root["path"]), default=None)
