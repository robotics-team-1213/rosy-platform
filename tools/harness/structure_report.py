"""Structure report: where the tree is over its size rule and what to split next (D-773).

python tools/harness/structure_report.py [--json | --issue | --picks-json] [--top N]

Measures the current tree with the same counter as test/architecture/test_module_structure.py
(``size_limits.measure``), so every number matches the size gate. For each unit or package above
the 10,000-line unit limit it groups the files the unit still owns directly (not yet in a
registered sub-unit) by folder and file-name prefix and lists the largest groups: those are the
split candidates. It also counts the frozen exception lists that should only shrink (known import
violations, known safety violations, Fleet ledger writers). Read-only; it changes nothing.

--issue prints the weekly GitHub issue body (the task issue form's sections) and --picks-json the
split candidates chosen by fixed rules (``pick``): one per unit, at most three, largest excess
first; a group must hold several files and at least 1,000 lines (a new unit's floor), touch no
safety file (``platform_parts.yaml``) and no file whose fate an ADR left open (``PENDING``).
.github/workflows/structure-report.yml runs both every Monday; whether a group is one
responsibility stays a person's call when the issue is triaged.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/harness"))
import size_limits  # noqa: E402

ARCH = ROOT / "test/architecture"
#: test module -> the exception set it keeps (each only shrinks).
FROZEN_LISTS = (
    ("test_platform_parts.py", "KNOWN_VIOLATIONS", "import edges across manifest roots"),
    ("test_safety_separation.py", "KNOWN_SAFETY_VIOLATIONS", "safety separation exceptions"),
    ("test_fleet_ledger_writers.py", "KNOWN_WRITERS", "modules writing Fleet ledger tables"),
)
MIN_GROUP_LINES = 300
NEW_UNIT_FLOOR = 1000
MAX_PICKS = 3
#: files whose move or retirement an ADR left open -> the reason (never picked).
PENDING = {
    "operations/fleet/fleet/server/traffic_reservations.py": "D-517: move or retire at the M4 re-judge",
    "operations/fleet/fleet/server/segment_store.py": "D-517: move or retire at the M4 re-judge",
}
#: path prefix -> Jira Epic (team-guide 5.1); first match wins, no match = Epic undecided.
EPICS = (
    ("middleware/devices/omx", "KAN-21"), ("integrations/robots/omx", "KAN-21"),
    ("learning/curation/omx", "KAN-21"), ("learning/training/omx", "KAN-21"),
    ("operations/fleet", "KAN-19"), ("applications/fleet/web", "KAN-19"),
    ("operations/site_devices", "KAN-19"),
    ("middleware/drive", "KAN-20"), ("middleware/devices/pinky", "KAN-20"),
    ("middleware/perception/front_camera", "KAN-22"), ("learning", "KAN-22"),
)


def _load(name: str):
    path = ARCH / name
    if not path.is_file():
        return None
    sys.path.insert(0, str(ARCH))
    spec = importlib.util.spec_from_file_location(f"_structure_report_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _group(path: str) -> str:
    """folder + the file name's first word: server/goal_evidence_store.py -> server/goal_*."""
    pure = PurePosixPath(path)
    return f"{pure.parent.as_posix()}/{pure.stem.split('_', 1)[0]}*"


def report(top: int = 5) -> dict:
    structure = _load("test_module_structure.py")
    files_lines = {}
    counts, over, owner = structure._measure()
    for path in owner:
        full = ROOT / path
        if full.is_file():
            files_lines[path] = structure._lines(full)  # the gate's own count (bytes, not text)
    units = []
    for key, lines in sorted(counts.items(), key=lambda item: -item[1]):
        if lines <= size_limits.UNIT_LIMIT:
            continue
        groups: dict[str, list[str]] = defaultdict(list)
        for path, unit in owner.items():
            if unit == key and path in files_lines:
                groups[_group(path)].append(path)
        sized = [(g, sum(files_lines[f] for f in fs), sorted(fs)) for g, fs in groups.items()]
        candidates = sorted((c for c in sized if c[1] >= MIN_GROUP_LINES), key=lambda c: -c[1])
        every = [{"group": g, "lines": n, "files": fs} for g, n, fs in candidates]
        units.append({"unit": key, "lines": lines, "limit": size_limits.UNIT_LIMIT,
                      "excess": lines - size_limits.UNIT_LIMIT,
                      "split_candidates": every[:top], "all_candidates": every})
    over_files = sorted(((k, v) for k, v in over.items() if PurePosixPath(k).suffix), key=lambda kv: -kv[1])
    frozen = []
    for module_name, attribute, meaning in FROZEN_LISTS:
        module = _load(module_name)
        found = module is not None and hasattr(module, attribute)
        frozen.append({"list": f"{module_name}::{attribute}", "meaning": meaning,
                       "entries": len(getattr(module, attribute)) if found else None})
    return {"units_over_limit": units, "files_over_limit": len(over_files),
            "largest_files": [{"file": k, "lines": v} for k, v in over_files[:top]], "frozen_lists": frozen}


def _safety_paths() -> tuple[set[str], tuple[str, ...]]:
    import yaml
    parts = yaml.safe_load((ROOT / "tools/harness/platform_parts.yaml").read_text(encoding="utf-8"))
    roots = tuple(r["path"] for r in parts.get("roots", []) if isinstance(r, dict) and r.get("concern") == "safety")
    return set(parts.get("safety_modules", [])), roots


def epic_for(path: str) -> str | None:
    return next((epic for prefix, epic in EPICS if path == prefix or path.startswith(prefix + "/")), None)


def _skip_reason(files: list[str], lines: int, modules: set[str], roots: tuple[str, ...]) -> str | None:
    if len(files) < 2:
        return "one file: split the file, not a holder move"
    if any(not f.endswith(".py") for f in files):
        return "not Python: a size unit is a Python subpackage or holder (split by hand)"
    if lines < NEW_UNIT_FLOOR:
        return f"under the {NEW_UNIT_FLOOR}-line floor of a new unit"
    if any(f in modules or any(f == r or f.startswith(r + "/") for r in roots) for f in files):
        return "touches a safety file (Safety-Review)"
    return next((PENDING[f] for f in files if f in PENDING), None)


def pick(data: dict) -> tuple[list[dict], list[dict]]:
    """(picks, skipped): the fixed weekly rules; each skip names its reason."""
    modules, roots = _safety_paths()
    picks, skipped = [], []
    for unit in sorted(data["units_over_limit"], key=lambda u: -u["excess"]):
        if len(picks) == MAX_PICKS:
            break
        for cand in unit.get("all_candidates", unit["split_candidates"]):
            reason = _skip_reason(cand["files"], cand["lines"], modules, roots)
            if reason:
                skipped.append({"unit": unit["unit"], "group": cand["group"], "reason": reason})
                continue
            picks.append({"unit": unit["unit"], "group": cand["group"], "lines": cand["lines"],
                          "files": cand["files"], "epic": epic_for(cand["files"][0])})
            break
    return picks, skipped


def issue(data: dict) -> str:
    picks, skipped = pick(data)
    table = markdown(data).split("\n", 2)[2].strip().replace("\n## ", "\n#### ").replace("## ", "#### ", 1)
    out = ["### 문제와 원하는 결과", "",
           f"크기 단위 한도({size_limits.UNIT_LIMIT:,}줄)를 넘은 단위가 {len(data['units_over_limit'])}개입니다. "
           "아래는 `python tools/harness/structure_report.py`의 측정이며 `size_ratchet.txt`와 같은 counter입니다.",
           "", table, "", "### 담당자와 수정 경로", "", "담당: 미정(리드 배정, team-guide 5.1)", ""]
    for p in picks:
        out.append(f"- `{p['unit']}` / `{p['group']}` {p['lines']}줄, Epic {p['epic'] or '미정'}: "
                   + ", ".join(f"`{f}`" for f in p["files"]))
    out += ["", "### 완료 조건과 검증 방법", ""]
    out += [f"- [ ] `{p['group']}` 분리: import 이름을 바꾸지 않는 순수 이동, 새 단위 등록, `size_ratchet.txt` 행 낮춤, "
            "경로 문자열 시험·문서 갱신, 고정 깊이 경로(`parents[N]`) 확인, NEW 0, CI 통과" for p in picks]
    out += ["- [ ] 묶음이 한 책임(같은 ADR·기능)인지 사람이 확인", "", "### 관련 계약과 참고 자료", "",
            "D-773, D-766, D-750, `docs/reference/platform-folder-responsibilities.md`", ""]
    out += [f"- 제외 `{s['unit']}` / `{s['group']}`: {s['reason']}" for s in skipped]
    return "\n".join(out) + "\n"


def markdown(data: dict) -> str:
    out = ["# Structure report", "", "## Units over the 10,000-line limit", "",
           "| unit | lines | over by | split candidates (folder/prefix: lines) |", "|---|---|---|---|"]
    for unit in data["units_over_limit"]:
        hint = ", ".join(f"`{c['group']}` {c['lines']}" for c in unit["split_candidates"]) or "-"
        out.append(f"| `{unit['unit']}` | {unit['lines']} | {unit['excess']} | {hint} |")
    out += ["", f"## Files over their limit: {data['files_over_limit']}", ""]
    out += [f"- `{f['file']}` {f['lines']}" for f in data["largest_files"]]
    out += ["", "## Frozen lists (only shrink)", "", "| list | entries | what |", "|---|---|---|"]
    out += [f"| `{f['list']}` | {'not on this branch' if f['entries'] is None else f['entries']} | {f['meaning']} |"
            for f in data["frozen_lists"]]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="machine-readable output")
    mode.add_argument("--issue", action="store_true", help="the weekly GitHub issue body")
    mode.add_argument("--picks-json", action="store_true", help="the chosen split candidates as JSON")
    ap.add_argument("--top", type=int, default=5, help="candidates and files to list per section")
    args = ap.parse_args(argv)
    data = report(max(args.top, 1))
    if args.picks_json:
        picks, skipped = pick(data)
        sys.stdout.write(json.dumps({"picks": picks, "skipped": skipped}, indent=2, ensure_ascii=False) + "\n")
    elif args.issue:
        sys.stdout.write(issue(data))
    else:
        sys.stdout.write(json.dumps(data, indent=2) + "\n" if args.json else markdown(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
