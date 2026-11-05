"""Camera preview decision chain rows 3-5: the headline names the layer that stops the robot."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

WEB_COMMON = Path(__file__).resolve().parents[1]


def _chain(status):
    source = base64.b64encode((WEB_COMMON / "core_ui_logic.js").read_bytes()).decode("ascii")
    script = (f'import * as logic from "data:text/javascript;base64,{source}";\n'
              f"console.log(JSON.stringify(logic.lineDecisionChain({json.dumps(status)})));\n")
    result = subprocess.run(["node", "--input-type=module", "--eval", script],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def test_a_core_gate_hold_with_an_open_stuck_is_stopped_by_core():
    view = _chain({"state": "HOLD", "reason": "lane_departure", "linear": 0, "angular": 0,
                   "stuck": {"stuck_id": "stuck-3d", "cause": "no_motion", "detail": "lane_departure",
                             "phase": "WAITING_CONSOLE", "held_s": 5.5, "last_answer": "WAIT"}})
    assert view["headline"] == {"level": "error",
                                "text": "정지 사유: 3 로봇 안전 확인 - 차선 이탈 (막힘 6초, 관제 대기)"}
    assert [row["level"] for row in view["rows"]] == ["error", "error", "warning"]
    assert view["rows"][1]["text"].startswith("움직임 없음/차선 이탈")


def test_each_reason_family_points_at_its_layer():
    assert "1–2 인식·조향" in _chain({"state": "LOST", "reason": "camera_reselection_required"})["headline"]["text"]
    assert "5 관제 판단 - 관제 역방향 감지" in _chain({"state": "HOLD", "reason": "fleet_wrong_way"})["headline"]["text"]
    recovering = _chain({"state": "RECOVERING", "reason": "stuck_back_off"})["headline"]
    assert recovering == {"level": "warning", "text": "복구 중: 4 막힘 - 막힘 복구 후진"}
    assert _chain({"state": "TRACKING", "reason": "tracking"})["headline"] == {"level": "ready", "text": "주행 중 · 차선 추종"}
    assert _chain({})["headline"]["level"] == "unavailable"


def test_only_reported_gates_are_shown():
    gates = _chain({"state": "HOLD", "reason": "obstacle_ahead", "body_gap_m": 0.04, "stop_gap_m": 0.06,
                    "crosswalk": {"state": "clear"}, "authority": {"state": "granted"}})["rows"][0]["text"]
    assert gates == "멈춤 · 전방 장애물 · 전진 속도 - m/s · 회전 속도 - rad/s · 차체 여유 거리 0.04/정지 기준 0.06 m · 횡단보도 통과 가능 · 통행권 허용"
    assert "차로 정보 수신 없음" in _chain({"state": "TRACKING"})["rows"][2]["text"]


def test_default_camera_copy_and_crosswalk_uncertainty_are_operator_readable():
    assert _chain({})['headline']['text'] == '차선 추종 꺼짐'
    view = _chain({'state': 'HOLD', 'reason': 'pose_stale',
                   'crosswalk': {'state': 'unknown', 'reason': 'pose_stale'}})
    assert '횡단보도 확인 전 · 위치 정보 지연' in view['rows'][0]['text']
    assert '위치 정보 지연' in view['headline']['text']
    assert [row['layer'] for row in view['rows']] == ['3 로봇 안전 확인', '4 막힘', '5 관제 판단']
    assert '판단 방식 수신 없음' in view['rows'][2]['text']
    unknown = _chain({'state': 'HOLD', 'reason': 'future_gate'})
    assert '해석되지 않은 사유' in unknown['headline']['text']
    assert 'future_gate' in unknown['diagnostic']
    assert 'future_gate' not in unknown['headline']['text']


def test_current_stuck_answers_phases_and_causes_keep_their_meaning():
    # Current LineStuckDecisionRequest, StuckRecovery and RealignRecovery vocabulary.
    answers = {'WAIT': '대기', 'RESUME': '재개', 'BACK_AND_RETRY': '후진 후 재시도',
               'MANUAL': '수동 조작', 'ABORT': '중단', 'YIELD': '양보', 'REALIGN': '방향 정렬'}
    phases = {'ASKING': '응답 요청 중', 'WAITING_CONSOLE': '관제 응답 대기', 'BACKING': '후진 중',
              'SETTLING': '정지 후 안정 대기', 'TURNING': '양보 회전 중', 'CRAWLING': '양보 서행 중',
              'YIELDED': '양보 후 대기', 'REALIGNING': '방향 정렬 중', 'REALIGN_SETTLING': '방향 정렬 후 안정 대기'}
    causes = {'obstacle_ahead': '전방 장애물', 'lane_lost': '차선 놓침', 'crosswalk_blocked': '횡단보도 막힘',
              'no_motion': '움직임 없음', 'no_progress': '전진하지 못함', 'dithering': '방향 흔들림'}
    for field, labels in [('last_answer', answers), ('phase', phases), ('cause', causes)]:
        for code, label in labels.items():
            stuck = {'cause': 'no_motion', 'phase': 'BACKING', 'held_s': 2, field: code}
            view = _chain({'state': 'RECOVERING', 'reason': 'stuck_back_off', 'stuck': stuck})
            assert label in view['rows'][2 if field == 'last_answer' else 1]['text']
            assert view['rows'][1]['level'] == ('error' if stuck['phase'] in ('ASKING', 'WAITING_CONSOLE') else 'warning')
            assert view['rows'][2]['level'] == ('warning' if stuck.get('last_answer') == 'WAIT' else 'ready')
            assert '해석되지 않은' not in view['rows'][1]['text'] + view['rows'][2]['text']
    for phase in phases:
        view = _chain({'state': 'HOLD', 'reason': 'stuck_' + phase.lower()})
        assert '해석되지 않은' not in view['headline']['text']
        assert view['headline']['level'] == 'error'
