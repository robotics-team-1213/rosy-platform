"""fleet.swarm.arming — 무장하기 **전에** 순수하게 끝나는 몫.

세션이 릴레이를 만지기 전에 거절할 수 있는 것은 전부 여기 있다: 맵 검사, 슬롯
계산, 배정, 그리고 리더가 무장을 받을 상태인지. 입력은 이미 읽어 둔 `state()`
응답이고 출력은 배정이다 — 전송도 태스크도 모른다.

이 분리가 있는 이유는 `reform` 이다. 계획이 릴레이 `pause()` 뒤에 있으면, 거절된
reform 이 멀쩡히 달리던 대형을 세운 채로 남긴다(계획 실패는 `HOLDING` 이 아니라
`RUNNING` + paused 이므로 `resume()` 도 듣지 않는다). 계획이 순수하면 세션은
"계산이 끝난 뒤에만 스트림을 만진다"를 지킬 수 있다.

세션이 던지는 거절은 전부 `SessionError` 다. `slots()` 의 `FormationError` 는
`ValueError` 라서 그대로 새어 나가면 호출자의 `except SessionError` 를 지나친다 —
`InvalidFormation` 으로 감싼다.
"""

from __future__ import annotations

from typing import Optional

from fleet.swarm.api.types import (FormationSpec, SessionError, ArmingFailed, MapMismatch, InvalidFormation)
from fleet.swarm.session_arming import check_leader_ready

from core_common.protocol.schemas import RobotMode
from fleet.formation.assignment import AssignmentError, SlotAssigner
from fleet.formation.geometry import (
    DEFAULT_SPACING,
    Formation,
    FormationError,
    SlotOffset,
    slot_world_position,
    slots,
)


def _leader_key(leader_state: dict, leader_id: Optional[str]) -> str:
    return leader_id or str(leader_state.get("robot_id") or "leader")


def plan_assignment(leader_state: dict, follower_states: dict[str, dict],
                    spec: FormationSpec, assigner: SlotAssigner,
                    *, leader_id: Optional[str] = None) -> dict[str, SlotOffset]:
    """`robot_id → SlotOffset`. 로봇에게는 아무것도 보내지 않는다.

    거절: `MapMismatch` (서로 다른 맵), `InvalidFormation` (만들 수 없는 spec 이나
    배정할 수 없는 입력). 어느 쪽이든 `SessionError` 이므로 호출자는 한 곳에서 받는다.
    """
    map_ids = {_leader_key(leader_state, leader_id): leader_state.get("map_id"),
               **{rid: s.get("map_id") for rid, s in follower_states.items()}}
    known = {m for m in map_ids.values() if m}
    if len(known) > 1:
        # 로봇 쪽도 프레임마다 검사하지만(map_mismatch HOLD), 시작 전에 알 수 있는
        # 것을 시작 뒤에 알게 하지 않는다. 값이 없는 로봇은 판단 대상이 아니다.
        raise MapMismatch(map_ids)

    try:
        offsets = slots(spec.formation, len(follower_states), spec.spacing,
                        grid_cols=spec.grid_cols)
    except FormationError as exc:
        raise InvalidFormation(str(exc)) from exc

    pose = leader_state.get("pose") or {}
    lx, ly, lyaw = float(pose.get("x", 0.0)), float(pose.get("y", 0.0)), float(pose.get("yaw", 0.0))
    slot_points = [slot_world_position(o, lx, ly, lyaw) for o in offsets]
    robot_points = {
        rid: (float((s.get("pose") or {}).get("x", 0.0)), float((s.get("pose") or {}).get("y", 0.0)))
        for rid, s in follower_states.items()
    }
    try:
        chosen = assigner.assign(robot_points, slot_points)
    except AssignmentError as exc:
        # `AssignmentError` 도 `ValueError` 다 — 여기서 감싸지 않으면 같은 방식으로 샌다.
        raise InvalidFormation(str(exc)) from exc
    return {rid: offsets[j] for rid, j in chosen.items()}
