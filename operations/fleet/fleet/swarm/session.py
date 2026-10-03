"""fleet.swarm.session — 대형 세션: 무장 → 릴레이 → 감시 → FOR-004.

- 무장은 **전부 아니면 전무**다. 하나라도 거절되면 이미 무장된 팔로워를 풀고 끝낸다.
  무장된 팔로워만 남기면 참조 프레임 하나에 달려나갈 준비가 된 채로 남는다.
- FOR-004 기본 정책 HOLD 는 릴레이를 멈추는 것이다(설계 §6.4, D-35 후보). 팔로워는
  SWM-004 로 스스로 자리를 지키고, 리더 항법만 취소한다.
- 재개는 운영자만 한다. 자동 재개는 SRS 가 금지한 자동 재시도다.
- HOLDING 중에 온 트리거는 버리지 않고 `pending_triggers` 에 쌓는다. 그것이 남아
  있으면 `resume()` 은 거절한다 — 운영자는 `reform` 으로 다시 무장하거나 `stop` 한다.
  같은 `(사유, robot_id)` 는 한 번만 쌓는다. 끊긴 소켓은 2 s 마다 다시 열리므로
  그러지 않으면 같은 사고 하나가 목록을 끝없이 늘린다.
- `resume()` 도 `reform()` 도 await 여러 개짜리 구간이다. 그 사이에 감시가 돌고
  운영자가 `stop` 할 수 있다 — 릴레이를 만지기 직전에 무엇이 들어왔는지 다시 본다.
- 계획(`swarm/arming.py`)은 릴레이를 만지기 **전에** 끝난다. 거절될 reform 이 멀쩡한
  대형을 세워서는 안 된다 — 사전 점검이 실패하면 세션은 손대기 전 그대로다.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Awaitable, Callable, Optional, Sequence

from core_common.protocol.schemas import RobotMode, SwarmFollowParams
from fleet.formation.assignment import GreedyDistanceAssigner, SlotAssigner
from fleet.formation.geometry import SlotOffset
from fleet.swarm.arming import (
    ArmingFailed,
    FormationSpec,
    InvalidFormation,
    MapMismatch,
    SessionError,
    check_leader_ready,
    plan_assignment,
)
from fleet.swarm.relay import Relay
from fleet.swarm.transport import RobotApiError, RobotClient

#: `from fleet.swarm.session import ArmingFailed` 는 계속 된다 — 정의만 옮겼다.
__all__ = [
    "ArmingFailed",
    "EVENT_TYPES",
    "FormationSession",
    "FormationSpec",
    "HoldPolicy",
    "InvalidFormation",
    "MapMismatch",
    "SessionError",
    "SessionState",
    "TRIGGERS",
]

log = logging.getLogger(__name__)

#: 이 이벤트 중 하나가 어느 로봇에서든 오면 정책을 적용한다 (FOR-004).
#: `nav.blocked` 는 현재 CORE 가 발행하지 않는다(API 참조 §8 "미구현") — 막힌 주행은
#: NAV-006 `nav.stuck` 으로 온다. 구현되면 그대로 트리거가 되도록 남겨 둔다.
TRIGGERS = frozenset({"nav.stuck", "nav.failed", "nav.blocked", "swarm.aborted", "safety.estop"})
#: 구독 필터. `swarm.hold` 는 정보이고 트리거가 아니지만 로그에 남기기 위해 받는다.
EVENT_TYPES = ("nav.*", "swarm.*", "safety.estop")

_BACKOFF_FIRST_S = 0.1
_BACKOFF_MAX_S = 2.0


class SessionState(str, Enum):
    IDLE = "IDLE"
    ARMING = "ARMING"
    RUNNING = "RUNNING"
    HOLDING = "HOLDING"
    STOPPED = "STOPPED"


class HoldPolicy(str, Enum):
    HOLD = "HOLD"      # 릴레이 pause + 리더 navigation/cancel. 팔로워 follow 세션은 산다.
    ABORT = "ABORT"    # 전 팔로워 swarm/cancel + 리더 navigation/cancel. 세션 종료.


class FormationSession:
    def __init__(self, leader: RobotClient, followers: Sequence[RobotClient],
                 spec: FormationSpec, *,
                 assigner: Optional[SlotAssigner] = None,
                 policy: HoldPolicy = HoldPolicy.HOLD,
                 relay_factory: Callable[..., Relay] = Relay,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 member_order: Optional[Sequence[str]] = None) -> None:
        follower_ids = [f.robot_id for f in followers]
        if len(set(follower_ids)) != len(follower_ids):
            # 릴레이도 같은 검사를 하지만 그때는 이미 팔로워가 무장돼 있다. 세션이 먼저 본다.
            raise ValueError(f"duplicate robot_id among followers: {follower_ids}")
        if leader.robot_id in follower_ids:
            raise ValueError(f"leader {leader.robot_id!r} cannot also be a follower")
        self._leader = leader
        self._followers = list(followers)
        self.spec = spec
        self._assigner = assigner or GreedyDistanceAssigner()
        self._policy = policy
        self._relay_factory = relay_factory
        self._sleep = sleep
        self.state = SessionState.IDLE
        #: `(사유, robot_id)`. HOLDING/STOPPED 의 이유.
        self.reason: Optional[tuple[str, Optional[str]]] = None
        #: HOLDING 중에 온 트리거. 비어 있지 않으면 `resume()` 은 거절한다.
        self.pending_triggers: list[tuple[str, str]] = []
        self.assignment: dict[str, SlotOffset] = {}
        self.relay: Optional[Relay] = None
        self._watchers: list[asyncio.Task] = []
        #: 정책이 상태를 바꿀 때마다 오른다. `reform` 이 "무장 중에 무엇인가 걸렸다"를
        #: 이것으로 안다 — 무장은 await 여러 개짜리 구간이고 그 사이에 감시가 돈다.
        self._policy_seq = 0
        #: 진행 중인 `reform` 이 책임지기로 한 `pending_triggers` 앞부분의 길이. 그 몫은
        #: reform 이 끝나며 잘라내므로, 무장 중에 같은 `(사유, id)` 가 다시 오면 그것은
        #: 중복이 아니라 새 사건이다 — 잘려 나갈 항목에 묻어 사라지면 안 된다.
        self._carried = 0
        self._member_order = list(member_order) if member_order else None

    # --- 운영자 명령 --------------------------------------------------------------

    async def start(self) -> None:
        if self.state is not SessionState.IDLE:
            raise SessionError(f"cannot start from {self.state.value}")
        self.state = SessionState.ARMING
        try:
            assignment = await self._plan(self.spec)
        except SessionError as exc:
            self.state = SessionState.STOPPED
            self.reason = (f"arming_failed:{exc}", getattr(exc, "robot_id", None))
            raise
        # D-132 — 무장은 스트림이 연 뒤에 한다. follow 의 1 s 시계는 명령 시점에
        # 시작하므로, 릴레이 기동을 그 시계와 경주시키지 않는다. 무장 전에 흐르는
        # 프레임은 매니저가 버린다(on_reference_pose 의 params-None 드롭) — 안전하다.
        await self._open_relay()
        try:
            await self._arm(self.spec, assignment)
            self.assignment = assignment
        except SessionError as exc:
            # 무장 거절 — 이미 흐르는 스트림을 끊고 팔로워를 푼다.
            await self._stop_relay()
            await self._disarm(self._followers)
            self.state = SessionState.STOPPED
            self.reason = (f"arming_failed:{exc}", getattr(exc, "robot_id", None))
            raise
        for robot in [self._leader, *self._followers]:
            self._watchers.append(asyncio.create_task(self._watch(robot)))
        self.state = SessionState.RUNNING
        self.reason = None

    async def _open_relay(self) -> None:
        """릴레이를 켜고 스트림이 열리기를 기다린다 (D-132, D-134).

        실패 시 로봇을 만지기 전이므로 relay.stop() 만으로 끝난다 — 무장된 팔로워를
        되돌릴 필요가 없는 것이 이 순서의 이득이다. D-134: self.relay 대입은
        streams_ready() 확인 뒤로, SessionError 원문은 보존하고, 대기 중 stop이면
        즉시 탈출해 운영자의 종료 사유를 덮어쓰지 않는다.
        """
        relay = None
        try:
            relay = self._relay_factory(self._leader, self._followers)
            await relay.start()
            for _ in range(60):                      # 3 s — 개방 상한
                if self.state is SessionState.STOPPED:
                    raise SessionError("session stopped while waiting for relay streams")
                if relay.streams_ready():
                    self.relay = relay
                    return
                await self._sleep(0.05)
            raise SessionError("relay streams did not open within 3s")
        except SessionError as exc:
            if relay is not None:
                try:
                    await relay.stop()
                except Exception as stop_exc:
                    log.warning("relay stop failed after a failed start: %s", stop_exc)
            if self.state is not SessionState.STOPPED:
                self.state = SessionState.STOPPED
                self.reason = (f"relay_failed:{exc}", None)
            raise
        except Exception as exc:
            if relay is not None:
                try:
                    await relay.stop()
                except Exception as stop_exc:
                    log.warning("relay stop failed after a failed start: %s", stop_exc)
            if self.state is not SessionState.STOPPED:
                self.state = SessionState.STOPPED
                self.reason = (f"relay_failed:{exc}", None)
            raise SessionError(f"relay could not be started: {exc}") from exc

    async def reform(self, spec: FormationSpec) -> None:
        """새 대형으로 다시 무장한다. 거절에는 두 종류가 있고 결과가 다르다.

        - **사전 점검 거절** (`_plan`): 아무 로봇도 만지지 않았다. 세션은 부르기 전과
          똑같이 남고(RUNNING 은 릴레이가 멈추지도 않은 채 RUNNING, HOLDING 은 HOLDING)
          예외만 올라간다. 멀쩡한 대형이 잘못된 명령 한 줄에 무너지지 않는다.
        - **무장 중 실패** (`_arm`): 이미 몇 대가 새 오프셋으로 follow 를 다시 받았다.
          남은 대형은 둘로 갈려 있으므로 정책과 무관하게 `_abort` 다.

        무장이 끝나도 바로 재개하지 않는다. `follow` 가 200 이었다는 것과 그 로봇이
        아직 따르고 있다는 것은 다르다 — 재개 직전에 전원의 `swarm/state` 를 다시 본다.
        하나라도 아니면 **예외 없이** HOLDING 으로 남는다(릴레이는 멈춘 채, 그 로봇이
        `pending_triggers` 에). 대형은 이미 새 배정으로 서 있고 운영자가 다음을 정한다.
        """
        if self.state not in (SessionState.RUNNING, SessionState.HOLDING):
            raise SessionError(f"cannot reform from {self.state.value}")
        assert self.relay is not None
        # 계획도 무장도 await 여러 개짜리 구간이다. 그 사이에 걸린 트리거를 재개가
        # 지워서는 안 되므로, 세대와 몫은 아무것도 하기 전에 잡는다.
        seq = self._policy_seq
        carried = len(self.pending_triggers)
        self._carried = carried
        try:
            await self._reform(spec, seq, carried)
        finally:
            self._carried = 0

    async def _reform(self, spec: FormationSpec, seq: int, carried: int) -> None:
        assert self.relay is not None
        # 계획이 릴레이보다 먼저다. 거절되는 reform 은 아무것도 만지지 않은 채 던진다 —
        # 맵 불일치도, 만들 수 없는 대형도, e-stop 인 리더도, 응답 없는 로봇도 여기서
        # 걸린다. 멈춘 채 남는 대형은 `resume()` 도 듣지 않는다(상태가 HOLDING 이 아니다).
        assignment = await self._plan(spec)
        if self.state is SessionState.STOPPED:
            # 계획하는 동안 ABORT 가 걸렸다. 죽은 릴레이를 다시 켤 이유가 없다.
            raise SessionError(self._interrupted_text())
        self.relay.pause()
        try:
            await self._arm(spec, assignment)
        except SessionError as exc:
            if self.state is SessionState.STOPPED:
                await self._disarm(self._followers)
                raise SessionError(self._interrupted_text()) from exc
            # 정책과 무관하게 끝낸다. 재무장된 팔로워는 _arm 이 이미 풀었고 나머지는 옛
            # 오프셋의 follow 세션을 쥐고 있다 — 그 위에 스트림을 다시 켜면 대형이 둘로
            # 갈린다. HOLD 로 두면 resume 이 그것을 그대로 살린다.
            await self._abort(f"reform_failed:{exc}", getattr(exc, "robot_id", None))
            raise
        self.assignment = assignment
        self.spec = spec
        await self._abandon_if_stopped()
        # 무장이 성공했다는 것은 follow 가 200 이었다는 뜻일 뿐이다. 그 사이에 다시
        # 이탈한 로봇은 이벤트로 알려지지 않을 수도 있다 — 스트림을 다시 켜기 전에
        # 전원에게 직접 묻는다. 떠난 로봇을 향해 대형이 달리는 것이 여기서 가장 나쁘다.
        blocker = await self._verify_still_following()
        await self._abandon_if_stopped()
        # 이 reform 이 책임지는 몫은 시작 시점에 쌓여 있던 것까지다. 무장하는 동안 새로
        # 들어온 것은 아직 아무도 보지 않았다.
        self.pending_triggers = self.pending_triggers[carried:]
        if blocker is not None and blocker not in self.pending_triggers:
            self.pending_triggers.append(blocker)
        if self._policy_seq != seq or self.pending_triggers:
            # 무장 도중 HOLD 가 걸렸다. 새 배정은 살리되 재개하지 않는다 — 운영자가 본다.
            if self.pending_triggers and self._policy_seq == seq:
                self.reason = self.pending_triggers[0]
            self.state = SessionState.HOLDING
            log.warning("reform finished but the formation is not whole: %s", self.reason_text())
            return
        self.relay.resume()
        self.state = SessionState.RUNNING
        self.reason = None

    async def _abandon_if_stopped(self) -> None:
        """무장 도중 ABORT 가 걸렸으면 방금 무장한 팔로워를 다시 푼다. 그들은 이미 죽은
        릴레이를 보고 있다. 사유는 ABORT 쪽이 옳으므로 덮어쓰지 않는다."""
        if self.state is not SessionState.STOPPED:
            return
        await self._disarm(self._followers)
        raise SessionError(self._interrupted_text())

    async def _verify_still_following(self) -> Optional[tuple[str, str]]:
        """전원이 아직 따라오고 있는지 본다. 아니면 `(사유, robot_id)`, 맞으면 None.

        `resume()` 이 재개 전에 하는 확인과 같은 것이다. reform 에도 필요한 이유는
        중복 제거 때문이다: 무장 중에 다시 이탈한 로봇의 `swarm.aborted` 는 이미
        pending 에 같은 `(사유, id)` 가 있으면 지워지고, 그 pending 은 이 reform 의
        몫으로 잘려 나간다. 그러면 떠난 로봇을 향해 대형이 다시 달린다.
        """
        for follower in self._followers:
            try:
                swarm_state = await follower.swarm_state()
            except Exception as exc:
                # 물어볼 수 없으면 따라온다고 볼 수 없다. 재개하지 않는 쪽이 안전하다.
                log.warning("%s: swarm/state unavailable after re-arming: %s",
                            follower.robot_id, exc)
                return ("swarm.state_unavailable", follower.robot_id)
            if not swarm_state.get("active"):
                return ("swarm.aborted", follower.robot_id)
        return None

    async def resume(self) -> None:
        if self.state is not SessionState.HOLDING:
            return
        assert self.relay is not None
        if self.pending_triggers:
            raise SessionError(
                f"cannot resume: unhandled triggers {self.pending_triggers}; "
                "reform to re-arm or stop")
        # 확인은 await 여러 개짜리 구간이다. 그 사이에 온 것을 재개가 덮어써서는 안 된다.
        # 위에서 이미 거절했으므로 여기 도달했다는 것은 목록이 비어 있다는 뜻이다 —
        # 재개가 책임지고 지울 몫은 없고, 확인 중에 하나라도 들어오면 그것으로 끝이다.
        seq = self._policy_seq
        for follower in self._followers:
            # HOLD 중에 팔로워가 대형을 떠났을 수 있다. 스트림만 다시 켜면 남은 팔로워만
            # 달려나간다 — 재개 전에 전원이 아직 따라오고 있는지 직접 본다.
            try:
                swarm_state = await follower.swarm_state()
            except Exception as exc:
                raise SessionError(
                    f"cannot resume: {follower.robot_id} swarm/state unavailable: {exc}") from exc
            if not swarm_state.get("active"):
                raise SessionError(
                    f"cannot resume: {follower.robot_id} is no longer following; "
                    "reform to re-arm or stop")
        await self._verify_resumable(seq)
        self.relay.resume()
        self.state = SessionState.RUNNING
        self.reason = None

    async def _verify_resumable(self, seq: int) -> None:
        """재개 직전의 마지막 확인. 릴레이를 만지기 전에 이 구간 동안 무엇이 들어왔는지 본다."""
        try:
            leader_state = await self._state_of(self._leader)
        except SessionError as exc:
            raise SessionError(
                f"cannot resume: {self._leader.robot_id} state unavailable: {exc}") from exc
        if leader_state.get("mode") == RobotMode.EMERGENCY.value:
            # 팔로워만 물어보면 리더가 선 채로 스트림이 다시 열린다.
            raise SessionError(
                f"cannot resume: {self._leader.robot_id} is in e-stop; clear it first")
        if self.state is not SessionState.HOLDING:
            raise SessionError(
                f"cannot resume: the session became {self.state.value} while it was being checked")
        if self.pending_triggers:
            raise SessionError(
                f"cannot resume: {self.pending_triggers} arrived while it was being checked; "
                "reform to re-arm or stop")
        if self._policy_seq != seq:
            raise SessionError(
                f"cannot resume: the policy fired again while it was being checked "
                f"({self.reason_text()}); reform to re-arm or stop")

    async def stop(self) -> None:
        # 운영자가 세운 것도 이유다. 적어 두지 않으면 `_plan` 한가운데로 들어온 stop 이
        # reform 쪽에서 "aborted ... unknown" 으로 보고된다 — 사고가 아니라 명령이었는데.
        # 이미 이유가 있으면(HOLD, ABORT, 무장 실패) 그쪽이 먼저 일어난 일이므로 둔다.
        if self.reason is None:
            self.reason = ("stopped", None)
        if self.state is SessionState.IDLE:
            # 무장도 릴레이도 감시도 없다. 끌 것이 없다.
            self.state = SessionState.STOPPED
            return
        await self._cancel_watchers()
        self._watchers.clear()
        await self._stop_relay()
        for follower in self._followers:
            try:
                await follower.swarm_cancel()
            except Exception as exc:  # 한 대가 안 받아도 나머지는 푼다
                log.warning("%s: swarm/cancel failed on stop: %s", follower.robot_id, exc)
        self.state = SessionState.STOPPED

    # --- 무장 ---------------------------------------------------------------------

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
        """사전 점검과 배정. 로봇에게 `state()` 말고는 아무것도 보내지 않는다."""
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
        return plan_assignment(leader_state, states, spec, self._assigner,
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
                members=order,
            )
            try:
                await follower.follow(params)
            except RobotApiError as exc:
                # 거절이다 — 이 로봇은 무장되지 않았다.
                await self._disarm(armed)
                raise ArmingFailed(exc.robot_id, exc.code, exc.message) from exc
            except Exception as exc:
                # 결과를 모른다. 타임아웃 뒤에 로봇이 follow 를 받아 놓았을 수 있으므로
                # 이 로봇도 함께 푼다 — 무장된 채 잊히는 것보다 두 번 푸는 것이 낫다.
                await self._disarm([*armed, follower])
                raise ArmingFailed(follower.robot_id, "TRANSPORT", str(exc)) from exc
            armed.append(follower)

    async def _disarm(self, armed: Sequence[RobotClient]) -> None:
        for follower in armed:
            try:
                await follower.swarm_cancel()
            except Exception as exc:
                log.warning("%s: swarm/cancel failed while disarming: %s", follower.robot_id, exc)

    # --- FOR-004 감시 ------------------------------------------------------------

    async def _watch(self, robot: RobotClient) -> None:
        backoff = _BACKOFF_FIRST_S
        first = True
        while self.state is not SessionState.STOPPED:
            if not first:
                await self._reconcile(robot)
                if self.state is SessionState.STOPPED:
                    return
            first = False
            try:
                async for event in robot.events(EVENT_TYPES):
                    backoff = _BACKOFF_FIRST_S
                    await self._handle_event(robot.robot_id, event)
                    if self.state is SessionState.STOPPED:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("%s: events socket error: %s", robot.robot_id, exc)
            if self.state is SessionState.STOPPED:
                return
            # 조용히 닫혔든 예외였든 같은 backoff 다. 로봇이 꺼져 있으면 events() 는
            # 조용히 끝나므로, 여기서 기다리지 않으면 꺼진 로봇을 향해 빈 루프를 돈다.
            await self._sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    async def _cancel_watchers(self) -> None:
        """감시를 끝낸다. 자기 자신은 취소하지 않는다 — 그 태스크는 상태 검사로 나간다."""
        current = asyncio.current_task()
        cancelled = [task for task in self._watchers if task is not current]
        # 목록에는 살아 있는 감시만 남긴다. 두 번 부르는 abort→stop 이 끝난 태스크를
        # 다시 await 하지 않게, 그리고 "남은 감시"를 묻는 쪽이 참을 보게.
        self._watchers = [task for task in self._watchers if task is current]
        for task in cancelled:
            task.cancel()
        for task in cancelled:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                # 삼키면 감시가 왜 죽었는지 아무도 모른다.
                log.error("watcher task ended with an error: %r", exc)

    async def _reconcile(self, robot: RobotClient) -> None:
        """이벤트 소켓이 끊긴 동안의 이벤트는 놓쳤다. 로봇이 대형을 떠났는지 직접 본다."""
        if self.state not in (SessionState.RUNNING, SessionState.HOLDING):
            return
        if robot is self._leader:
            try:
                state = await self._leader.state()
            except Exception as exc:
                log.warning("%s: state unavailable after reconnect: %s", robot.robot_id, exc)
                return
            if state.get("mode") == RobotMode.EMERGENCY.value:
                # 리더의 e-stop 이벤트를 놓쳤다. 팔로워는 리더를 따라갈 준비가 돼 있다.
                await self._trigger("safety.estop", robot.robot_id)
            return
        try:
            swarm_state = await robot.swarm_state()
        except Exception as exc:
            log.warning("%s: swarm/state unavailable after reconnect: %s", robot.robot_id, exc)
            return
        if not swarm_state.get("active"):
            await self._trigger("swarm.aborted", robot.robot_id)

    async def _handle_event(self, robot_id: str, event: dict) -> None:
        type_ = str(event.get("type", ""))
        if type_ == "swarm.hold":
            self._log_hold(robot_id, event)
            return
        if self.state not in (SessionState.RUNNING, SessionState.HOLDING):
            return
        if type_ in TRIGGERS:
            await self._trigger(type_, robot_id)

    def _log_hold(self, robot_id: str, event: dict) -> None:
        # 릴레이가 멈춰 있거나 그 팔로워 소켓이 끊겨 있으면 우리가 만든 HOLD 다(정보).
        # 둘 다 아니면 로봇 쪽이 스스로 선 것이고, 그것은 우리가 모르는 이유다(경고).
        reason = (event.get("data") or {}).get("reason")
        if reason == "map_mismatch":
            # 설계 §6.2: 맵이 어긋난 것은 우리가 만든 HOLD 가 아니다. 릴레이가 멈춰 있어도
            # 경고다 — 정보로 흘리면 아무도 맵을 고치러 가지 않는다.
            log.warning("%s: swarm.hold %s", robot_id, reason)
            return
        ours = self.relay is None or self.relay.paused or not self.relay.is_connected(robot_id)
        (log.info if ours else log.warning)("%s: swarm.hold %s", robot_id, reason)

    async def _trigger(self, type_: str, robot_id: str) -> None:
        if self.state is SessionState.HOLDING:
            # 이미 서 있다고 해서 새 사고가 없던 일이 되지는 않는다. resume 이 이것을 본다.
            if (type_, robot_id) in self.pending_triggers[self._carried:]:
                # 끊긴 소켓은 2 s 마다 다시 열리고 그때마다 같은 사실을 다시 말한다.
                # 같은 사고를 두 번 세면 목록만 끝없이 길어진다. 다만 진행 중인 reform 이
                # 이미 책임지기로 한 앞부분과는 견주지 않는다 — 그 몫은 곧 잘려 나가므로,
                # 거기 묻으면 무장 중에 새로 일어난 사고가 통째로 사라진다.
                log.debug("%s: %s while HOLDING (already pending)", robot_id, type_)
                return
            self.pending_triggers.append((type_, robot_id))
            log.warning("%s: %s while HOLDING — resume is blocked until reform or stop",
                        robot_id, type_)
            return
        await self._apply_policy(type_, robot_id)

    async def _apply_policy(self, reason: str, robot_id: Optional[str]) -> None:
        if self.state is not SessionState.RUNNING:
            return
        assert self.relay is not None
        if self._policy is HoldPolicy.HOLD:
            # 상태를 먼저 바꾼다 — 아래 await 사이에 들어오는 이벤트는 pending 으로 간다.
            self.relay.pause()
            self.state = SessionState.HOLDING
            self.reason = (reason, robot_id)
            self._policy_seq += 1
            await self._cancel_leader()
            return
        await self._abort(reason, robot_id)

    async def _abort(self, reason: str, robot_id: Optional[str]) -> None:
        """ABORT 정책, 그리고 reform 실패: 전 팔로워를 풀고 릴레이를 끝내고 리더를 세운다."""
        self.state = SessionState.STOPPED
        self.reason = (reason, robot_id)
        self._policy_seq += 1
        # 감시를 먼저 끝낸다. 끝난 세션의 소켓을 계속 다시 여는 감시는 유령이다.
        await self._cancel_watchers()
        # 릴레이를 못 끄는 것은 로봇을 무장한 채 두는 이유가 되지 못한다. 안전 작업이
        # 릴레이 뒤에 있으면, 릴레이가 던지는 순간 팔로워는 풀리지 않고 리더는 선다.
        await self._stop_relay()
        await self._disarm(self._followers)
        await self._cancel_leader()

    async def _stop_relay(self) -> None:
        if self.relay is None:
            return
        try:
            await self.relay.stop()
        except Exception as exc:
            log.error("relay stop failed: %s", exc)

    async def _cancel_leader(self) -> None:
        try:
            await self._leader.navigation_cancel()
        except Exception as exc:
            log.warning("%s: navigation/cancel failed: %s", self._leader.robot_id, exc)

    def _interrupted_text(self) -> str:
        """`reform` 이 중단된 이유 한 줄. 운영자의 `stop` 은 사고가 아니다 — 정책이
        세션을 끝낸 것과 운영자가 끝낸 것을 같은 문장으로 보고하면, 운영자는 자기가
        방금 누른 것을 사고로 읽고 로그를 뒤진다."""
        stopped = self.reason is not None and self.reason[0] == "stopped"
        return f"session {'stopped' if stopped else 'aborted'} during reform: {self.reason_text()}"

    def reason_text(self) -> str:
        """`reason` 을 한 줄로. CLI 가 세션이 스스로 끝난 이유를 찍을 때도 쓴다."""
        if self.reason is None:
            return "unknown"
        why, robot_id = self.reason
        return f"{why} ({robot_id})" if robot_id else why
