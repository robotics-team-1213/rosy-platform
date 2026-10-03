"""swarm.arming — 무장하기 전에 순수하게 끝나는 몫.

여기 있는 것은 전부 로봇을 만지기 전에 답이 나온다. 그래서 세션이 릴레이를 멈추기
**전에** 부를 수 있고, 거절되는 reform 이 멀쩡한 대형을 세운 채로 남기지 않는다.
"""

import pytest

from core_common.protocol.schemas import RobotMode
from fleet.formation.assignment import GreedyDistanceAssigner
from fleet.formation.geometry import Formation, SlotOffset
from fleet.swarm.arming import (
    ArmingFailed,
    FormationSpec,
    InvalidFormation,
    MapMismatch,
    SessionError,
    check_leader_ready,
    plan_assignment,
)


def _leader(x=0.0, y=0.0, yaw=0.0, map_id="m1", mode=RobotMode.IDLE.value):
    return {"robot_id": "rosy_01", "map_id": map_id, "mode": mode,
            "pose": {"x": x, "y": y, "yaw": yaw}}


def _follower(x, y, map_id="m1"):
    return {"map_id": map_id, "pose": {"x": x, "y": y, "yaw": 0.0}}


def _plan(followers, spec=None, leader=None):
    return plan_assignment(leader or _leader(), followers,
                           spec or FormationSpec(Formation.V, spacing=0.6),
                           GreedyDistanceAssigner(), leader_id="rosy_01")


def test_the_nearest_robot_takes_the_nearest_slot():
    # V, spacing 0.6: 슬롯은 리더 뒤 0.6 · 좌 +0.6 과 뒤 0.6 · 우 −0.6. rosy_02 는 왼쪽에 있다.
    assignment = _plan({"rosy_02": _follower(-0.6, 0.6), "rosy_03": _follower(-0.6, -0.6)})
    assert assignment == {"rosy_02": SlotOffset(0.6, 0.6), "rosy_03": SlotOffset(0.6, -0.6)}
    assert all(isinstance(v, SlotOffset) for v in assignment.values())


def test_a_map_mismatch_is_refused_and_names_the_maps():
    with pytest.raises(MapMismatch) as exc:
        _plan({"rosy_02": _follower(0.0, 0.0), "rosy_03": _follower(0.0, 0.0, map_id="other")})
    assert exc.value.map_ids["rosy_03"] == "other"
    assert exc.value.map_ids["rosy_01"] == "m1"


def test_a_robot_without_a_map_id_is_not_a_mismatch():
    """맵을 모르는 로봇은 "다른 맵에 있다"의 증거가 아니다. 판단 대상에서 뺀다."""
    assert _plan({"rosy_02": _follower(0.0, 0.0, map_id=None),
                  "rosy_03": _follower(0.0, 0.0)})


@pytest.mark.parametrize("spec", [
    FormationSpec(Formation.FOLLOW, spacing=0.6),   # FOLLOW 는 팔로워 한 대짜리다
    FormationSpec(Formation.LINE, spacing=0.1),     # spacing 이 하한(0.4) 아래다
    FormationSpec(Formation.GRID, spacing=0.6, grid_cols=0),
], ids=["follow_with_two", "spacing_below_floor", "no_columns"])
def test_a_spec_that_cannot_be_built_is_a_session_error(spec):
    """`slots()` 는 `FormationError`(= `ValueError`)를 던진다. 그대로 새어 나가면 세션
    호출자의 `except SessionError` 를 지나친다 — 여기서 세션의 언어로 바꾼다."""
    with pytest.raises(InvalidFormation) as exc:
        _plan({"rosy_02": _follower(0.0, 0.0), "rosy_03": _follower(0.0, 0.0)}, spec=spec)
    assert isinstance(exc.value, SessionError)


def test_an_input_that_cannot_be_assigned_is_a_session_error_too():
    """`AssignmentError` 도 `ValueError` 다 — 같은 방식으로 샌다."""
    with pytest.raises(InvalidFormation) as exc:
        _plan({"rosy_02": {"map_id": "m1", "pose": {"x": float("nan"), "y": 0.0}},
               "rosy_03": _follower(0.0, 0.0)})
    assert isinstance(exc.value, SessionError)


def test_a_leader_in_estop_is_refused_before_anything_else():
    """팔로워를 리더에 묶는 것이 무장이다. 선 리더에 묶으면 e-stop 이 풀리는 순간
    전원이 그 프레임을 따라간다."""
    with pytest.raises(ArmingFailed) as exc:
        check_leader_ready(_leader(mode=RobotMode.EMERGENCY.value), "rosy_01")
    assert exc.value.robot_id == "rosy_01" and exc.value.code == "EMERGENCY_ACTIVE"
    assert isinstance(exc.value, SessionError)


def test_a_leader_that_is_not_in_estop_passes():
    assert check_leader_ready(_leader(), "rosy_01") is None
    assert check_leader_ready({"robot_id": "rosy_01"}, None) is None
