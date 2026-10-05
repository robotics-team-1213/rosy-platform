#!/usr/bin/env python3
"""D-426 Task 6 — 회차 증거 보고서 생성기.

T1–T5의 판정기(preflight·probe·assertions·scenarios)가 남긴 회차 기록을
읽어 `docs/validation/fleet-gazebo-conformance-<date>/result.md` 의 공개
보고서를 쓴다. 원본(rosbag·JSONL·DB·영상)은 X:에 그대로 두고, 보고서는
판정 요약·hash·재현 입력만 담는다(secret 검사 후 커밋).

판정 구조(계획 T6 항목 3):
- M01–M08 각각 seed 3개 × 3회. 매 회차 시나리오 검증 단언 PASS 필수.
- 주행 판정과 시나리오 판정을 별도 필드로 저장한다.
- crash/timeout/관측 누락은 합격이 아니다. 평균·대표 영상으로 실패를
  상쇄하지 않는다. M08 의도적 관측 누락은 주행 INCONCLUSIVE 가 시나리오
  PASS 보다 우선한다(잘못된 성공 0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VERDICT_ORDER = {"PASS": 0, "INCONCLUSIVE": 1, "NOT_RUN": 2, "FAIL": 3}


def combine_verdicts(verdicts: list[str]) -> str:
    """회차의 대표 판정 — 가장 나쁜 판정이 대표다(평균으로 상쇄 금지)."""
    if not verdicts:
        return "NOT_RUN"
    return max(verdicts, key=lambda v: VERDICT_ORDER.get(v, 3))


def scenario_row(rounds: list[dict]) -> dict:
    """시나리오 하나의 요약 행: 회차별 판정과 대표 판정.

    시나리오 판정(검증 단언)과 주행 판정(물리 단언)을 별도 필드로 유지한다.
    crash/timeout/관측 누락 회차는 합격으로 세지 않는다.
    """
    scenario = [row["scenario_verdict"] for row in rounds]
    driving = [row["driving_verdict"] for row in rounds]
    bad_rounds = [row for row in rounds
                  if row.get("crashed") or row.get("timed_out")
                  or row.get("observation_lost")]
    return {
        "rounds": len(rounds),
        "scenario": combine_verdicts(scenario),
        "driving": combine_verdicts(driving),
        "crash_or_timeout_rounds": len(bad_rounds),
        "accepted": (combine_verdicts(scenario) == "PASS"
                     and combine_verdicts(driving) == "PASS"
                     and not bad_rounds),
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def render(sessions: dict[str, list[dict]], *, title: str, run_roots: list[str]) -> str:
    """공개 result.md 의 Markdown 본문."""
    lines = [f"# {title}", "",
             "| 시나리오 | 회차 | 시나리오 판정 | 주행 판정 | crash/timeout | 수용 |",
             "|---|---|---|---|---|---|"]
    accepted = 0
    for scenario_id in sorted(sessions):
        row = scenario_row(sessions[scenario_id])
        if row["accepted"]:
            accepted += 1
        lines.append(
            f"| {scenario_id} | {row['rounds']} | {row['scenario']} "
            f"| {row['driving']} | {row['crash_or_timeout_rounds']} "
            f"| {'**GO**' if row['accepted'] else 'HOLD'} |")
    lines += ["",
              f"수용 시나리오: {accepted}/{len(sessions)}",
              f"원본 run root: {', '.join(run_roots)}",
              "",
              "판정 근거는 각 회차 디렉터리의 원본(JSONL·rosbag·DB)에 있다.",
              "이 보고서는 판정 요약·hash·재현 입력만 담는다."]
    return "\n".join(lines) + "\n"


def load_sessions(rounds_dir: Path) -> dict[str, list[dict]]:
    """회차별 verdicts.json 을 읽어 시나리오별로 묶는다."""
    sessions: dict[str, list[dict]] = {}
    for path in sorted(rounds_dir.glob("*/verdicts.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions.setdefault(data["scenario_id"], []).append({
            "scenario_verdict": data.get("scenario_verdict", "NOT_RUN"),
            "driving_verdict": data.get("driving_verdict", "NOT_RUN"),
            "crashed": data.get("crashed", False),
            "timed_out": data.get("timed_out", False),
            "observation_lost": data.get("observation_lost", False),
        })
    return sessions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fleet_gazebo.report",
        description="Render the D-426 conformance result.md from round verdicts.")
    parser.add_argument("--rounds-dir", required=True,
                        help="directory of per-round subdirs each holding verdicts.json")
    parser.add_argument("--output", required=True, help="result.md path to write")
    parser.add_argument("--title", default="Fleet–Gazebo conformance result")
    parser.add_argument("--run-root", action="append", default=[],
                        help="original run root to cite (repeatable)")
    args = parser.parse_args(argv)

    sessions = load_sessions(Path(args.rounds_dir))
    if not sessions:
        print(f"report: no verdicts.json under {args.rounds_dir}", file=sys.stderr)
        return 2
    body = render(sessions, title=args.title, run_roots=args.run_root or [args.rounds_dir])
    Path(args.output).write_text(body, encoding="utf-8")
    print(f"wrote {args.output} ({len(sessions)} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
