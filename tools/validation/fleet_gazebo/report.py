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
SCENARIOS = tuple(f"M{i:02d}" for i in range(1, 9))
FAILURE_FLAGS = ("crashed", "timed_out", "observation_lost")


def _sources_valid(row: dict) -> bool:
    sources = row.get("source_files")
    if not isinstance(sources, list) or not sources:
        return False
    seen = set()
    try:
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                return False
            path, digest = source["path"], source["sha256"]
            if not isinstance(path, str) or not isinstance(digest, str):
                return False
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                return False
            file = Path(path)
            if not file.is_absolute() or file.is_symlink() or not file.is_file():
                return False
            resolved = file.resolve()
            if resolved in seen or file_sha256(file) != digest:
                return False
            seen.add(resolved)
    except (OSError, ValueError):
        return False
    return True


def _coverage(rounds: list[dict]) -> bool:
    keys = []
    for row in rounds:
        seed, repeat = row.get("seed"), row.get("repeat")
        if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
            return False
        if type(repeat) is not int or repeat not in (1, 2, 3):
            return False
        if any(type(row.get(flag)) is not bool for flag in FAILURE_FLAGS):
            return False
        if not _sources_valid(row):
            return False
        keys.append((seed, repeat))
    seeds = {seed for seed, _ in keys}
    return (len(seeds) == 3 and len(keys) == 9
            and set(keys) == {(seed, repeat) for seed in seeds for repeat in (1, 2, 3)})


def combine_verdicts(verdicts: list[str]) -> str:
    """회차의 대표 판정 — 가장 나쁜 판정이 대표다(평균으로 상쇄 금지)."""
    if not verdicts:
        return "NOT_RUN"
    return max((v if isinstance(v, str) and v in VERDICT_ORDER else "INCONCLUSIVE" for v in verdicts),
               key=lambda v: VERDICT_ORDER[v])


def scenario_row(rounds: list[dict]) -> dict:
    """시나리오 하나의 요약 행: 회차별 판정과 대표 판정.

    시나리오 판정(검증 단언)과 주행 판정(물리 단언)을 별도 필드로 유지한다.
    crash/timeout/관측 누락 회차는 합격으로 세지 않는다.
    """
    scenario = [row.get("scenario_verdict", "NOT_RUN") for row in rounds]
    driving = [row.get("driving_verdict", "NOT_RUN") for row in rounds]
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
                     and not bad_rounds and _coverage(rounds)),
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
    seed_sets = [{row.get("seed") for row in rounds if type(row.get("seed")) is int}
                 for rounds in sessions.values()]
    same_seeds = bool(seed_sets) and all(seeds == seed_sets[0] for seeds in seed_sets)
    complete = set(sessions) == set(SCENARIOS) and same_seeds
    for scenario_id in SCENARIOS:
        row = scenario_row(sessions.get(scenario_id, []))
        if row["accepted"]:
            accepted += 1
        lines.append(
            f"| {scenario_id} | {row['rounds']} | {row['scenario']} "
            f"| {row['driving']} | {row['crash_or_timeout_rounds']} "
            f"| {'**GO**' if row['accepted'] else 'HOLD'} |")
    lines += ["",
              f"Overall: {'GO' if complete and accepted == 8 else 'HOLD'}",
              "Scope: supplied report metadata and file digests only; producer/verdict truth "
              "and actual ROS-SIM/device/physical acceptance are not verified.",
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
        if not isinstance(data, dict) or data.get("scenario_id") not in SCENARIOS:
            raise ValueError(f"invalid scenario record: {path}")
        sources = data.get("source_files")
        if isinstance(sources, list):
            sources = [dict(source, path=str(path.parent / source["path"]))
                       if isinstance(source, dict) and isinstance(source.get("path"), str)
                       and not Path(source["path"]).is_absolute() else source
                       for source in sources]
        sessions.setdefault(data["scenario_id"], []).append({
            "scenario_verdict": data.get("scenario_verdict", "NOT_RUN"),
            "driving_verdict": data.get("driving_verdict", "NOT_RUN"),
            "crashed": data.get("crashed"),
            "timed_out": data.get("timed_out"),
            "observation_lost": data.get("observation_lost"),
            "seed": data.get("seed"), "repeat": data.get("repeat"),
            "source_files": sources,
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

    try:
        sessions = load_sessions(Path(args.rounds_dir).resolve())
    except (OSError, ValueError, TypeError) as exc:
        print(f"report: invalid evidence: {exc}", file=sys.stderr)
        return 2
    if not sessions:
        print(f"report: no verdicts.json under {args.rounds_dir}", file=sys.stderr)
        return 2
    body = render(sessions, title=args.title, run_roots=args.run_root or [args.rounds_dir])
    Path(args.output).write_text(body, encoding="utf-8")
    print(f"wrote {args.output} ({len(sessions)} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
