"""Formation member preflight and all-or-nothing follow arming."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Sequence

from core_common.protocol.schemas import RobotMode, SwarmFollowParams
from fleet.swarm.api.types import Formation, SlotOffset, ArmingFailed, FormationSpec, SessionError, SessionState
from fleet.swarm.api.ports import RobotApiError, RobotClient

# Keep the original session log channel after extraction.
log = logging.getLogger("fleet.swarm.session")


def check_leader_ready(leader_state: dict, leader_id: Optional[str] = None) -> None:
    """리더가 무장을 받을 상태인가. 팔로워를 한 대도 묶기 전에 본다.

    팔로워를 리더에 묶는 것이 무장이다. 선 리더에 묶으면 e-stop 이 풀리는 순간
    전원이 그 프레임을 따라간다.
    """
    if leader_state.get("mode") == RobotMode.EMERGENCY.value:
        raise ArmingFailed(leader_id or str(leader_state.get("robot_id") or "leader"), "EMERGENCY_ACTIVE",
                           "leader is in e-stop")


async def require_capability(client: RobotClient, feature: str) -> dict:
    """Fresh CAP-001 preflight; cached presentation never authorizes a command.
    Returns the capabilities it read."""
    caps = value = await client.capabilities()
    for part in feature.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    if value is not True:
        raise RobotApiError(client.robot_id, 501, "NOT_SUPPORTED", f"{feature} is not advertised")
    return caps


class SessionArming:
    """Arming operations on the formation session's owned state."""

    async def _state_of(self, robot: RobotClient) -> dict:
        """`state()` 한 번. 전송 실패도 세션의 거절 언어로 올린다.

        `HttpRobotClient.state()` 는 날것의 `httpx` 예외를 던진다. 그것이 그대로
        올라가면 호출자의 `except SessionError` 를 지나쳐, 사전 점검 실패인데도
        세션이 어중간한 상태로 남는다.
        """
        try:
            return await robot.state()
        except SessionError:
            raise
        except Exception as exc:
            raise ArmingFailed(robot.robot_id, "TRANSPORT", str(exc)) from exc

    async def _plan(self, spec: FormationSpec) -> dict[str, SlotOffset]:
        """상태·지원 기능을 읽고 배정한다. 동작 명령은 보내지 않는다."""
        leader_state = await self._state_of(self._leader)
        check_leader_ready(leader_state, self._leader.robot_id)
        # 팔로워는 동시에 묻는다. 한 대씩 물으면 로봇 수 × 타임아웃(5 s)이 그대로
        # 대형이 멈춰 있는 시간이 된다. `return_exceptions` 인 이유는 둘 이상이 같이
        # 죽는 경우다 — 첫 번째만 올리고 나머지를 버리면 "회수되지 않은 예외"가 된다.
        results = await asyncio.gather(*(self._state_of(f) for f in self._followers),
                                       return_exceptions=True)
        states: dict[str, dict] = {}
        failure: Optional[BaseException] = None
        for follower, result in zip(self._followers, results):
            if isinstance(result, BaseException):
                if failure is None:
                    failure = result
                else:
                    # 올라가는 것은 첫 번째뿐이다. 나머지를 조용히 버리면 두 대가 함께
                    # 죽은 사고가 한 대의 사고로 보이고, 운영자는 한 대만 고치러 간다.
                    log.warning("%s: state unavailable while planning: %s",
                                follower.robot_id, result)
            else:
                states[follower.robot_id] = result
        if failure is not None:
            raise failure
        # CAP-001 is checked before any pose/reference socket opens or follow is sent.
        members = [(self._leader, "lead"), *((f, "follow") for f in self._followers)]
        results = await asyncio.gather(*(require_capability(robot, f"swarm.{role}") for robot, role in members),
                                       return_exceptions=True)
        for (robot, _), result in zip(members, results):
            if isinstance(result, RobotApiError):
                raise ArmingFailed(robot.robot_id, result.code, result.message) from result
            if isinstance(result, BaseException):
                raise ArmingFailed(robot.robot_id, "TRANSPORT", str(result)) from result
        return self._plan_assignment(leader_state, states, spec, self._assigner,
                               leader_id=self._leader.robot_id)

    async def _arm(self, spec: FormationSpec, assignment: dict[str, SlotOffset]) -> None:
        armed: list[RobotClient] = []
        for follower in self._followers:
            if self.state is SessionState.STOPPED:
                # 무장하는 동안 세션이 끝났다. 죽은 릴레이를 보는 팔로워를 더 만들지 않는다.
                await self._disarm(armed)
                raise SessionError("session stopped while arming")
            offset = assignment[follower.robot_id]
            order = self._member_order or [
                self._leader.robot_id, *[robot.robot_id for robot in self._followers]]
            params = SwarmFollowParams(
                target_robot_id=self._leader.robot_id,
                distance=offset.distance, lateral=offset.lateral,
                max_speed=spec.max_speed, stream_timeout_ms=spec.stream_timeout_ms,
                members=order, mode="trail" if spec.formation is Formation.TRAIL else "offset",
            )
            try:
                reply = await follower.follow(params)
            except RobotApiError as exc:
                # 거절이다 — 이 로봇은 무장되지 않았다.
                await self._disarm(armed)
                raise ArmingFailed(exc.robot_id, exc.code, exc.message) from exc
            except Exception as exc:
                # 결과를 모른다. 타임아웃 뒤에 로봇이 follow 를 받아 놓았을 수 있으므로
                # 이 로봇도 함께 푼다 — 무장된 채 잊히는 것보다 두 번 푸는 것이 낫다.
                await self._disarm([*armed, follower])
                raise ArmingFailed(follower.robot_id, "TRANSPORT", str(exc)) from exc
            if params.mode == "trail" and (reply or {}).get("mode") != "trail":
                # D-559: an older CORE ignores the field and follows by offset. It is armed.
                await self._disarm([*armed, follower])
                raise ArmingFailed(follower.robot_id, "TRAIL_NOT_SUPPORTED",
                                   "robot did not report trail follow")
            armed.append(follower)
            if self.state is SessionState.STOPPED:
                await self._disarm(armed)
                raise SessionError("session stopped while arming")

    async def _disarm(self, armed: Sequence[RobotClient]) -> None:
        for follower in armed:
            try:
                await follower.swarm_cancel()
            except Exception as exc:
                log.warning("%s: swarm/cancel failed while disarming: %s", follower.robot_id, exc)
