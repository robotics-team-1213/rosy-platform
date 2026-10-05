"""D-426 Task 6 — 회차 보고서 생성기 계약 (host, ROS-free). 실패 시험 먼저(규칙 5).

- 시나리오 판정과 주행 판정을 별도 필드로 유지한다(같은 열에 섞지 않는다).
- 가장 나쁜 회차 판정이 대표다 — 평균·대표 영상으로 실패을 상쇄하지 않는다.
- crash/timeout/관측 누락 회차가 하나라도 있으면 수용은 GO가 아니다.
- M08의 의도적 관측 누락: 주행 INCONCLUSIVE 그대로, 잘못된 성공 0이면
  시나리오는 PASS일 수 있지만 수용(accepted)은 주행 판정을 따른다.
- 회차가 없으면 보고서를 만들지 않는다(exit 2).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "validation" / "fleet_gazebo"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from report import combine_verdicts, load_sessions, render, scenario_row  # noqa: E402


def round_row(scenario="M01", scenario_verdict="PASS", driving_verdict="PASS",
              crashed=False, timed_out=False, observation_lost=False):
    return {"scenario_verdict": scenario_verdict, "driving_verdict": driving_verdict,
            "crashed": crashed, "timed_out": timed_out,
            "observation_lost": observation_lost}


def test_worst_verdict_represents_the_scenario_not_the_average():
    assert combine_verdicts(["PASS", "PASS", "FAIL"]) == "FAIL"
    assert combine_verdicts(["PASS", "PASS", "INCONCLUSIVE"]) == "INCONCLUSIVE"
    assert combine_verdicts([]) == "NOT_RUN"
    assert combine_verdicts(["PASS", "PASS", "PASS"]) == "PASS"


def test_crash_or_timeout_round_blocks_acceptance_even_with_green_verdicts():
    row = scenario_row([
        round_row(), round_row(),
        round_row(scenario_verdict="PASS", driving_verdict="PASS", timed_out=True),
    ])
    assert row["crash_or_timeout_rounds"] == 1
    assert row["accepted"] is False


def test_driving_and_scenario_verdicts_stay_separate_fields():
    row = scenario_row([round_row(scenario_verdict="PASS", driving_verdict="INCONCLUSIVE")])
    assert row["scenario"] == "PASS"
    assert row["driving"] == "INCONCLUSIVE"
    assert row["accepted"] is False       # 주행 불명은 수용이 아니다


def test_m08_intentional_observation_loss_stays_inconclusive_not_success():
    # 시나리오 검증(잘못된 성공 0)은 PASS, 주행은 INCONCLUSIVE — 수용은 HOLD.
    row = scenario_row([
        round_row(scenario_verdict="PASS", driving_verdict="INCONCLUSIVE",
                  observation_lost=True),
    ])
    assert row["scenario"] == "PASS"
    assert row["driving"] == "INCONCLUSIVE"
    assert row["accepted"] is False


def test_rendered_markdown_keeps_two_verdict_columns():
    sessions = {"M01": [round_row(), round_row()], "M02": [round_row()]}
    body = render(sessions, title="t", run_roots=["X:/DevTemp/fleet-gazebo/run-1"])
    assert "| 시나리오 | 회차 | 시나리오 판정 | 주행 판정 |" in body
    assert "| M01 | 2 | PASS | PASS | 0 | **GO** |" in body
    assert "X:/DevTemp/fleet-gazebo/run-1" in body


def test_loading_reads_verdicts_json_per_round(tmp_path):
    for name, driving in (("r1", "PASS"), ("r2", "INCONCLUSIVE")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "verdicts.json").write_text(json.dumps({
            "scenario_id": "M03", "scenario_verdict": "PASS",
            "driving_verdict": driving}), encoding="utf-8")
    sessions = load_sessions(tmp_path)
    assert [row["driving_verdict"] for row in sessions["M03"]] == ["PASS", "INCONCLUSIVE"]


def test_cli_refuses_empty_rounds_dir_and_writes_on_success(tmp_path):
    empty = tmp_path / "rounds"
    empty.mkdir()
    result = subprocess.run([sys.executable, str(TOOLS / "report.py"),
                             "--rounds-dir", str(empty), "--output", str(tmp_path / "out.md")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2

    good = tmp_path / "rounds" / "r1"
    good.mkdir()
    (good / "verdicts.json").write_text(json.dumps({
        "scenario_id": "M01", "scenario_verdict": "PASS",
        "driving_verdict": "PASS"}), encoding="utf-8")
    out = tmp_path / "result.md"
    result = subprocess.run([sys.executable, str(TOOLS / "report.py"),
                             "--rounds-dir", str(empty), "--output", str(out),
                             "--run-root", "X:/DevTemp/fleet-gazebo/run-9"],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert "M01" in out.read_text(encoding="utf-8")
