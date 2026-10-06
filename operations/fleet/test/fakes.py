"""릴레이·세션 테스트가 공유하는 가짜 전송계층.

`RobotClient` 프로토콜을 만족하되 네트워크는 없다. 스트림은 큐로 밀어 넣고,
`None` 을 넣으면 그 스트림은 끝난다(소켓 단절). 모든 호출은 `calls` 에 남는다.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional, Sequence

from core_common.protocol.schemas import SwarmFollowParams
from fleet.swarm.relay import RelayStats

END = None


def run(coro):
    return asyncio.run(coro)


class FakeClock:
    """단조 시계 대역. `advance()` 로 시간을 흘려보낸다 — 벽시계 sleep 은 쓰지 않는다."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        # round() 는 반복적인 0.1 더하기가 뜬셈 오차를 쌓아 age_s 비교를 미세하게
        # 어긋나게 하는 것을 막는다 — 실제 시계라면 없는, 가짜 시계만의 문제다.
        self.now = round(self.now + s, 9)


async def settle(rounds: int = 20) -> None:
    """대기 중인 태스크들이 한 바퀴씩 돌게 한다. 시간이 아니라 스케줄 회전이다."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeSink:
    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.fail_on_send = fail_on_send
        #: 잡혀 있으면 send 가 여기서 기다린다 — 느린 팔로워를 흉내낸다.
        self.gate: Optional[asyncio.Event] = None
        self.peer_closed = asyncio.Event()
        self.close_reason: Optional[BaseException] = None

    async def send(self, frame: str) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail_on_send:
            raise ConnectionError("sink broke")
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True
        self.peer_closed.set()

    async def wait_closed(self) -> BaseException:
        await self.peer_closed.wait()
        return self.close_reason or ConnectionError("reference socket closed by robot")

    def close_from_robot(self, reason: Optional[BaseException] = None) -> None:
        """The robot closes the socket (e.g. 4401 after first-message auth)."""
        self.close_reason = reason
        self.peer_closed.set()


class FakeRobot:
    def __init__(self, robot_id: str, *, state: Optional[dict] = None,
                 follow_error: Optional[BaseException] = None,
                 swarm_state: Optional[dict] = None, log: Optional[list] = None,
                 map: Optional[dict] = None) -> None:
        self.robot_id = robot_id
        self.calls: list[tuple] = []
        #: 여러 로봇의 호출 순서를 한 줄로 보고 싶을 때 같은 리스트를 넘긴다.
        self.log = log if log is not None else []
        self._state = state or {"robot_id": robot_id, "map_id": "m1",
                                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}
        self._swarm_state = swarm_state or {"active": True, "holding": False}
        #: 관제 콘솔이 읽는 점유 격자. `None` 이면 빈 dict 를 돌려준다(맵 없는 로봇).
        self._map = map
        #: 설정돼 있으면 map() 이 이것을 raise 한다 — 한 대가 못 줘도 다음 대로 넘어가는지 본다.
        self.map_error: Optional[BaseException] = None
        #: Fleet 교통 정리가 읽는 계획 경로. (x, y) 목록이다.
        self._path: list = []
        self.path_error: Optional[BaseException] = None
        #: RobotApiError 든 평범한 ConnectionError 든 그대로 raise 된다.
        self.follow_error = follow_error
        #: 잡혀 있으면 follow 가 여기서 기다린다 — 무장이 여러 await 짜리 구간임을 드러낸다.
        self.follow_gate: Optional[asyncio.Event] = None
        #: 잡혀 있으면 swarm_state 가 여기서 기다린다 — 재개 전 확인도 여러 await 짜리다.
        self.swarm_state_gate: Optional[asyncio.Event] = None
        #: 잡혀 있으면 state 가 여기서 기다린다 — `_plan` 도 여러 await 짜리 구간이고,
        #: 그 사이에 감시가 돌거나 운영자가 stop 한다.
        self.state_gate: Optional[asyncio.Event] = None
        #: 설정돼 있으면 state()/swarm_state() 가 이것을 raise 한다. 실제
        #: `HttpRobotClient` 는 날것의 httpx 예외를 올린다 — 세션이 그것을 감싸는지 본다.
        self.state_error: Optional[BaseException] = None
        self.swarm_state_error: Optional[BaseException] = None
        self.pose_frames: asyncio.Queue = asyncio.Queue()
        self.event_frames: asyncio.Queue = asyncio.Queue()
        self.sinks: list[FakeSink] = []
        #: 다음 open_reference_sink 가 이만큼 실패한다.
        self.sink_failures = 0
        self.next_sink_fail_on_send = False
        self.pose_opens = 0
        self.event_opens = 0
        #: 설정돼 있으면 pose_stream 이 열리자마자 이것을 raise 한다 (4401/4403 거부 흉내).
        self.pose_error = None
        #: 설정돼 있으면 open_reference_sink 가 이것을 한 번 raise 한다 (거부된 소켓 흉내).
        self.sink_error = None
        #: 참이면 `sink_error` 가 지워지지 않는다 — 고쳐질 때까지 계속 거부하는 소켓.
        #: 소켓이 다시 열리는 순간 이유가 지워지므로, 이유를 보려면 계속 닫혀 있어야 한다.
        self.sink_error_sticky = False
        #: D-395: what `localization_candidates` returns (None = not in CANDIDATES).
        self.candidates = None
        self.decisions: list = []
        self.suspects: list[str] = []
        #: Raised by `localization_decision` (e.g. RobotApiError 409 STALE_REQUEST).
        self.decision_error: Optional[BaseException] = None
        #: D-395 P2-7: `(kind, max_distance_m, max_time_s, target)` per mission request.
        self.missions: list[tuple] = []
        #: Raised by `localization_mission` (e.g. RobotApiError 409 unsupported).
        self.mission_error: Optional[BaseException] = None
        #: What `GET /localization/mission` answers, and what it raises instead.
        self.mission_status: dict = {"kind": None, "state": "idle", "reason": None}
        self.mission_status_error: Optional[BaseException] = None
        #: D-407: raised by `line_stuck_decision` (e.g. RobotApiError 409 STUCK_ID_MISMATCH).
        self.stuck_decision_error: Optional[BaseException] = None

    def _record(self, *call) -> None:
        self.calls.append(call)
        self.log.append((self.robot_id,) + call)

    async def state(self) -> dict:
        self._record("state")
        if self.state_gate is not None:
            await self.state_gate.wait()
        if self.state_error is not None:
            raise self.state_error
        return dict(self._state)

    async def map(self) -> dict:
        self._record("map")
        if self.map_error is not None:
            raise self.map_error
        return dict(self._map) if self._map is not None else {}

    async def capabilities(self) -> dict:
        return {"navigation": {"goal_navigation": True},
                "swarm": {"lead": True, "follow": True}}

    async def swarm_state(self) -> dict:
        self._record("swarm_state")
        if self.swarm_state_gate is not None:
            await self.swarm_state_gate.wait()
        if self.swarm_state_error is not None:
            raise self.swarm_state_error
        return dict(self._swarm_state)

    async def follow(self, params: SwarmFollowParams) -> dict:
        self._record("follow", params)
        if self.follow_gate is not None:
            await self.follow_gate.wait()
        if self.follow_error is not None:
            raise self.follow_error
        return {"role": "follower", "active": True}

    async def swarm_cancel(self) -> dict:
        self._record("swarm_cancel")
        return {"active": False}

    async def navigation_cancel(self) -> dict:
        self._record("navigation_cancel")
        return {"canceled": True}

    async def navigation_path(self) -> dict:
        self._record("navigation_path")
        if self.path_error is not None:
            raise self.path_error
        return {"poses": [{"x": x, "y": y} for x, y in self._path]}

    async def navigation_goal(self, x: float, y: float, yaw: float, *,
                              correlation_id: str | None = None) -> dict:
        call = ("navigation_goal", x, y, yaw)
        if correlation_id is not None:
            call += (correlation_id,)
        self._record(*call)
        return {"accepted": True}

    async def line_follow_mode(self, mode: str) -> dict:
        self._record("line_follow_mode", mode)
        return {"mode": mode, "state": "WAITING" if mode == "IR_LINE" else "OFF"}

    async def line_stuck_decision(self, stuck_id: str, decision: str, **_extra) -> dict:
        self._record("line_stuck_decision", stuck_id, decision)
        if self.stuck_decision_error is not None:
            raise self.stuck_decision_error
        return {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": None, "outcome": "hold"}

    async def estop(self) -> dict:
        self._record("estop")
        return {"estop": True}

    async def identify_lamp(self, color: str) -> dict:
        self._record("identify_lamp", color)
        return {"accepted": True, "request_id": "fake-led-test"}

    async def localization_candidates(self):
        self._record("localization_candidates")
        return self.candidates

    async def localization_decision(self, decision) -> dict:
        self._record("localization_decision", decision.request_id)
        if self.decision_error is not None:
            raise self.decision_error
        self.decisions.append(decision)
        return {"request_id": decision.request_id}

    async def localization_suspect(self, reason: str) -> dict:
        self._record("localization_suspect", reason)
        self.suspects.append(reason)
        return {}

    async def localization_mission(self, kind: str, *, max_distance_m: float, max_time_s: float,
                                   target: Optional[dict] = None) -> dict:
        self._record("localization_mission", kind)
        self.missions.append((kind, max_distance_m, max_time_s, target))
        if self.mission_error is not None:
            raise self.mission_error
        return {"kind": kind, "state": "running", "reason": None}

    async def localization_mission_status(self) -> dict:
        self._record("localization_mission_status")
        if self.mission_status_error is not None:
            raise self.mission_status_error
        return dict(self.mission_status)

    async def pose_stream(self) -> AsyncIterator[str]:
        self.pose_opens += 1
        if self.pose_error is not None:
            await asyncio.sleep(0)
            raise self.pose_error
        while True:
            frame = await self.pose_frames.get()
            if frame is END:
                return
            # 실제 소켓은 프레임 사이에 제어권을 놓는다. 큐는 비어 있지 않으면 놓지
            # 않으므로 여기서 한 번 양보한다 — 아니면 N 프레임이 한 번에 처리돼
            # 깊이 1 큐가 그것을 하나로 합치고, "프레임마다 전달" 테스트가 거짓 실패한다.
            await asyncio.sleep(0)
            yield frame

    async def open_reference_sink(self) -> FakeSink:
        if self.sink_error is not None:
            err = self.sink_error
            if not self.sink_error_sticky:
                self.sink_error = None
            raise err
        if self.sink_failures > 0:
            self.sink_failures -= 1
            raise ConnectionError("cannot open reference socket")
        sink = FakeSink(fail_on_send=self.next_sink_fail_on_send)
        self.next_sink_fail_on_send = False
        self.sinks.append(sink)
        return sink

    async def events(self, types: Sequence[str]) -> AsyncIterator[dict]:
        self.event_opens += 1
        self._record("events", tuple(types))
        while True:
            ev = await self.event_frames.get()
            if ev is END:
                return
            await asyncio.sleep(0)
            yield ev


class FakeRelay:
    """세션 테스트용. 실제 소켓 대신 호출 순서만 남긴다."""

    def __init__(self, leader, followers, *, log: Optional[list] = None, ready: bool = True) -> None:
        self.leader = leader
        self.followers = list(followers)
        self.log = log if log is not None else []
        self.paused = False
        self.started = False
        self.stopped = False
        self.ready = ready

    def stats(self) -> RelayStats:
        return RelayStats(paused=self.paused)

    async def start(self) -> None:
        self.started = True
        self.log.append(("relay", "start"))

    async def stop(self) -> None:
        self.stopped = True
        self.log.append(("relay", "stop"))

    def pause(self) -> None:
        self.paused = True
        self.log.append(("relay", "pause"))

    def resume(self) -> None:
        self.paused = False
        self.log.append(("relay", "resume"))

    def is_connected(self, robot_id: str) -> bool:
        return True

    def streams_ready(self) -> bool:
        return self.ready
