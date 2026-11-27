#!/usr/bin/env python3
"""Canonical OMX-cell acceptance-scenario catalog (Confluence 164138 v17 draft).

    python tools/sim/scenario_catalog.py list    # id / title / sim command table
    python tools/sim/scenario_catalog.py json    # SCENARIOS as JSON
    python tools/sim/scenario_catalog.py check   # validate against the real tool surfaces, exit 1 on error

LOCAL evidence only (D-91): a listed sim run is never device or field acceptance.
Every entry keeps the 팀 검토 전 초안 marker from the source page.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEACHER = "tools/sim/omx_two_arm_teacher.py"
SOURCE = "Confluence 164138 v17 (2026-11-14 백업)"
NOTE = "팀 검토 전 초안 (Confluence 164138 v17)"
# the cell the MuJoCo runs model: without these the teacher uses assumed defaults (stack 0/9 on 2026-11-27).
# 20261110-1231 passes every row; 20261115-0415 still needs a real arm-base measurement (plate fan vs belt disagree).
SNAP = ["--choice", "cell_snapshot=deploy/robot/omx/sim/cell_snapshots/20261110-1231.json", "--choice", "temp_lanes=snapshot",
        "--choice", "ship_pose=snapshot", "--choice", "belt_pose=snapshot"]

SCENARIOS: list[dict] = [
    {
        "id": "AT-01",
        "title": "입고·적층 1순환",
        "source": SOURCE,
        "sim": [TEACHER, "run", "stack", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["stack-*-seed0.json", "stack.mp4"],
        "dry_run": ["cell_dry_run", "cell_area_dry_run"],
        "real_blockers": ["SITE_NOT_MEASURED", "CELL_AB_RELEASE_DISABLED"],
        "note": NOTE,
    },
    {
        "id": "AT-02",
        "title": "매몰 화물 회수(재취급)",
        "source": SOURCE,
        "sim": [TEACHER, "run", "rehandle", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["rehandle-*-seed0.json", "rehandle.mp4"],
        "dry_run": ["cell_dry_run", "cell_area_dry_run"],
        "real_blockers": ["SITE_NOT_MEASURED", "CELL_AB_RELEASE_DISABLED"],
        "note": NOTE + "; 대표 시나리오",
    },
    {
        "id": "AT-03",
        "title": "상태 일치·이력",
        "source": SOURCE,
        "sim": [],
        "sim_host": None,
        "evidence": [],
        "dry_run": ["job_status", "cell_queue"],
        "real_blockers": [],
        "note": NOTE + "; sim 대신 원장 계약 시험으로 대체",
    },
    {
        "id": "AT-04",
        "title": "동시 작업·충돌",
        "source": SOURCE,
        "sim": [TEACHER, "run", "plan", "--plan", "FILE", "--concurrent", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["plan-*.json", "plan.mp4"],
        "dry_run": [],
        "real_blockers": ["CELL_AB_RELEASE_DISABLED"],
        "note": NOTE + "; omx_two_arm_plan.py compare 결과 two-arm plan을 --plan FILE로",
    },
    {
        "id": "AT-05",
        "title": "중단·실패 복구",
        "source": SOURCE,
        "sim": [TEACHER, "run", "plan", "--plan", "FILE", "--concurrent",
                "--belt-unknown", "0.3", "--seed", "3", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["plan-*-seed3.json", "plan.mp4"],
        "dry_run": ["cell_failure_context"],
        "real_blockers": ["FALLBACK_NAMED_APPROVAL"],
        "note": NOTE,
    },
    {
        "id": "AT-06",
        "title": "한 팔 vs 두 팔 비교",
        "source": SOURCE,
        "sim": ["tools/sim/omx_two_arm_plan.py", "compare", "--scenario", "all",
                "--replay-dir", "DIR", "--out", "FILE", *SNAP],
        "sim_host": "ai",
        "evidence": ["compare.json"],
        "dry_run": [],
        "real_blockers": [],
        "note": NOTE,
    },
    {
        "id": "AT-07",
        "title": "반복 운용",
        "source": SOURCE,
        "sim": [TEACHER, "run", "stack", "--seed", "N", *SNAP],
        "sim_host": "ai",
        "evidence": ["stack-*-seed[1-5].json"],
        "dry_run": [],
        "real_blockers": ["ACCEPTANCE_CRITERIA_UNDEFINED"],
        "note": NOTE + "; N=1..5, 횟수·합격 기준 미정",
    },
    {
        "id": "X-SLOT",
        "title": "Harbor JSON·말 지정 칸 이송 (D-1076)",
        "source": SOURCE,
        "sim": [TEACHER, "run", "outbound-stand", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["outbound-stand-*-seed0.json", "outbound-stand.mp4"],
        "dry_run": ["cell_area_dry_run"],
        "real_blockers": ["SITE_NOT_MEASURED"],
        "note": NOTE,
    },
    {
        "id": "X-3TIER",
        "title": "3단 적층",
        "source": SOURCE,
        "sim": [TEACHER, "run", "stack-t3", "--video", *SNAP],
        "sim_host": "ai",
        "evidence": ["stack-t3-*-seed0.json", "stack-t3.mp4"],
        "dry_run": [],
        "real_blockers": [],
        "note": NOTE,
    },
    {
        "id": "X-FALLBACK",
        "title": "AI 실패 폴백 (D-1072)",
        "source": SOURCE,
        "sim": [],
        "sim_host": None,
        "evidence": [],
        "dry_run": ["cell_failure_context", "fleet_propose_cell_task"],
        "real_blockers": ["FALLBACK_NAMED_APPROVAL"],
        "note": NOTE,
    },
    {
        "id": "X-PINKY",
        "title": "Pinky 운반 구간",
        "source": SOURCE,
        "sim": ["tools/remote/remote_sim.py", "fleet_trips", "--", "--render", "gpu", "--record"],
        "sim_host": "model",
        "evidence": ["trips/result.json", "trips/frames/*"],
        "dry_run": [],
        "real_blockers": ["PINKY_TASK_DISPATCH_DISABLED", "NO_MODEL_TRIP_PROPOSAL_REAL"],
        "note": NOTE,
    },
]

REQUIRED_KEYS = {"id", "title", "source", "sim", "sim_host", "evidence",
                 "dry_run", "real_blockers", "note"}
LIST_KEYS = ("sim", "evidence", "dry_run", "real_blockers")


def teacher_tasks() -> set[str]:
    """Task names from the teacher's argparse choices, read as text (no MuJoCo import)."""
    text = (ROOT / TEACHER).read_text(encoding="utf-8")
    m = re.search(r'add_argument\("task", choices=\[(.*?)\]\)', text, re.S)
    return set(re.findall(r'"([a-z0-9-]+)"', m.group(1))) if m else set()


def bridge_tools() -> set[str]:
    """Tool names in tools/remote/rosy_agent_bridge.py TOOL_SPECS, read as text."""
    text = (ROOT / "tools" / "remote" / "rosy_agent_bridge.py").read_text(encoding="utf-8")
    return set(re.findall(r'\{"name": "([a-z0-9_]+)"', text))


def check() -> list[str]:
    """Return catalog errors; an empty list means the catalog matches the tool surfaces."""
    errors: list[str] = []
    seen: set[str] = set()
    tasks = teacher_tasks()
    tools = bridge_tools()
    for s in SCENARIOS:
        where = s.get("id", "?")
        if set(s) != REQUIRED_KEYS:
            errors.append(f"{where}: 키 집합 불일치 {sorted(s)}")
            continue
        if not s["id"] or s["id"] in seen:
            errors.append(f"{where}: id가 비었거나 중복")
        seen.add(s["id"])
        if s["sim_host"] not in ("ai", "model", None):
            errors.append(f"{where}: sim_host {s['sim_host']!r}는 ai/model/None이어야 함")
        for key in LIST_KEYS:
            if not (isinstance(s[key], list) and all(isinstance(v, str) for v in s[key])):
                errors.append(f"{where}: {key}는 str list여야 함")
        if s["sim"] and not (ROOT / s["sim"][0]).exists():
            errors.append(f"{where}: sim 명령 파일 {s['sim'][0]} 없음")
        if s["sim"] and s["sim"][0] == TEACHER and (len(s["sim"]) < 3 or s["sim"][2] not in tasks):
            errors.append(f"{where}: teacher task {s['sim'][2] if len(s['sim']) > 2 else ''!r}"
                          f"가 omx_two_arm_teacher.py choices에 없음")
        if s["sim_host"] == "ai" and not all(c in s["sim"] for c in SNAP):
            errors.append(f"{where}: MuJoCo 명령에 셀 스냅샷 선택지(SNAP)가 없음")
        unknown = sorted(set(s["dry_run"]) - tools)
        if unknown:
            errors.append(f"{where}: dry_run 도구 {unknown}가 rosy_agent_bridge.py TOOL_SPECS에 없음")
    return errors


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 console
    args = sys.argv[1:] if argv is None else argv
    action = args[0] if args else ""
    if action == "list":
        # shortcut: CJK 제목 폭 계산 생략 — 열 정렬은 ASCII 필드만 보장
        print(f"{'id':8} {'host':5} title | sim")
        for s in SCENARIOS:
            cmd = " ".join(s["sim"]) or "(sim 없음)"
            print(f"{s['id']:8} {s['sim_host'] or '-':5} {s['title']} | {cmd}")
        return 0
    if action == "json":
        print(json.dumps(SCENARIOS, indent=2, ensure_ascii=False))
        return 0
    if action == "check":
        errors = check()
        for e in errors:
            print(f"FAIL {e}")
        print("scenario catalog ok" if not errors else f"{len(errors)} error(s)")
        return 1 if errors else 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
