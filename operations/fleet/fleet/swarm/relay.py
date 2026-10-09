"""fleet.swarm.relay — 리더 pose 소켓 1 → 팔로워 reference 소켓 N (D-31).

규칙:
- 프레임을 바꾸지 않는다. 계측을 위해 파싱은 하되 전달하는 바이트는 그대로다.
- 합성하지 않는다. 리더가 끊기면 팔로워는 SWM-004 로 스스로 HOLD 한다. 마지막
  프레임을 반복하면 죽은 리더가 살아 있는 것으로 보인다.
- 팔로워 하나의 실패가 나머지를 막지 않는다. 소켓별 태스크, 소켓별 재연결.
- 느린 팔로워에 밀리지 않는다. 소켓별 큐는 깊이 1, 최신이 이전을 덮는다.
- `pause()` 중에는 리더를 계속 읽되 팔로워에 쓰지 않는다. FOR-004 의 "전체 HOLD"
  가 이것이다 (설계 §6.4, D-35 후보).
- D-581 예외 하나: `anchor`(TRAIL 대형, `fleet.swarm.anchor`)가 있으면 리더가 `frame: odom`
  으로 보낸 프레임은 팔로워마다 그 팔로워의 odom 좌표로 다시 쓴다. 천장 카메라 기준이
  없거나 낡았으면 그 팔로워에게는 보내지 않는다 — 합성은 하되 반복은 하지 않는다.
  `map` 프레임은 지금처럼 바이트 그대로다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence

from fleet.swarm.transport import RobotApiError, RobotClient

log = logging.getLogger(__name__)

_BACKOFF_FIRST_S = 0.1
_RATE_WINDOW = 20
#: 마지막 표본이 이보다 오래됐으면 주기는 0 이다. 10 Hz 스트림에서 5 프레임 분량.
_RATE_STALE_S = 0.5
#: 예외 없이, 프레임 하나 없이 끝난 리더 소켓. `leader_last_error` 에 이 문장이 들어간다.
_QUIET_END = "leader pose stream ended without frames"
#: 한 프레임 송신이 이 시간 안에 끝나지 않으면 그 레인은 죽은 것으로 본다. 수신 측이
#: 읽지 않으면 send 는 영원히 리턴하지 않고, connected=true · tx=0 인 "살아 있는 것
#: 같은 죽은 레인"을 남긴다 — 이 릴레이가 금지한 이름 없는 0 Hz 의 WS 판이다.
_SEND_TIMEOUT_S = 2.0


@dataclass
class RelayStats:
    leader_frames: int = 0
    leader_dropped: int = 0
    leader_rx_hz: float = 0.0
    #: 리더 소켓이 마지막으로 끝난 이유 — 거부(4401/4403), 전송 오류, 그리고 프레임 없이
    #: 조용히 끝난 연결(`_QUIET_END`)까지. 재연결은 계속하지만, "0 Hz 가 영원히" 인 화면에
    #: 이유가 붙어야 한다. 프레임이 오면 None 으로 돈다.
    leader_last_error: Optional[str] = None
    leader_age_s: Optional[float] = None
    paused: bool = False
    follower_tx: dict[str, int] = field(default_factory=dict)
    follower_tx_hz: dict[str, float] = field(default_factory=dict)
    follower_last_tx_age_s: dict[str, Optional[float]] = field(default_factory=dict)
    follower_connected: dict[str, bool] = field(default_factory=dict)
    follower_last_error: dict[str, Optional[str]] = field(default_factory=dict)


class _Rate:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._stamps: deque[float] = deque(maxlen=_RATE_WINDOW)

    def tick(self) -> None:
        self._stamps.append(self._clock())

    def age_s(self) -> Optional[float]:
        """마지막 표본 이후 흐른 시간. 표본이 없으면 None."""
        if not self._stamps:
            return None
        return self._clock() - self._stamps[-1]

    def hz(self) -> float:
        """최근 창의 주기. 표본이 멎으면 0 으로 떨어진다 — 멎은 스트림이 살아 보이면 안 된다."""
        if len(self._stamps) < 2:
            return 0.0
        if self._clock() - self._stamps[-1] > _RATE_STALE_S:
            return 0.0
        span = self._stamps[-1] - self._stamps[0]
        return (len(self._stamps) - 1) / span if span > 0 else 0.0


class _Lane:
    """팔로워 하나. 깊이 1 큐 + 연결 상태 + 송신 계측."""

    def __init__(self, robot: RobotClient, clock: Callable[[], float]) -> None:
        self.robot = robot
        self.latest: Optional[str] = None
        self.wake = asyncio.Event()
        self.connected = False
        self.tx = 0
        self.rate = _Rate(clock)
        self.sink = None
        self.last_error: Optional[str] = None


class Relay:
    def __init__(self, leader: RobotClient, followers: Sequence[RobotClient], *,
                 clock: Callable[[], float] = time.monotonic,
                 reconnect_max_s: float = 2.0,
                 send_timeout_s: float = _SEND_TIMEOUT_S,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 anchor=None) -> None:
        follower_ids = [f.robot_id for f in followers]
        if len(set(follower_ids)) != len(follower_ids):
            raise ValueError(f"duplicate robot_id among followers: {follower_ids}")
        if leader.robot_id in follower_ids:
            raise ValueError(f"leader {leader.robot_id!r} cannot also be a follower")
        self._leader = leader
        self._lanes = {f.robot_id: _Lane(f, clock) for f in followers}
        self._clock = clock
        self._reconnect_max = reconnect_max_s
        self._send_timeout = send_timeout_s
        self._sleep = sleep
        self._paused = False
        self._tasks: list[asyncio.Task] = []
        self._leader_frames = 0
        self._leader_dropped = 0
        self._leader_rate = _Rate(clock)
        self._last_seq: Optional[int] = None
        self._leader_last_error: Optional[str] = None
        self._running = False
        self._leader_connected = False
        #: D-581 `TrailAnchor` or None (every frame byte for byte).
        self.anchor = anchor

    # --- 수명 --------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self._read_leader()))
        for lane in self._lanes.values():
            self._tasks.append(asyncio.create_task(self._feed(lane)))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.error("relay task died: %r", exc)
        self._tasks.clear()
        # D-134 — lane과 대칭. Cancel로 _read_leader가 죽는 경로도 이 한 줄로 커버된다.
        self._leader_connected = False
        for lane in self._lanes.values():
            if lane.sink is not None:
                try:
                    await lane.sink.close()
                except Exception:
                    pass
                lane.sink = None
            lane.connected = False

    def pause(self) -> None:
        # 이미 sink.send 안에 들어간 프레임은 되돌릴 수 없다 — pause 뒤에도 최대 한 프레임은
        # 나갈 수 있다. 여기서 지우는 것은 아직 보내지 않은, 큐에 있는 최신 프레임뿐이다.
        self._paused = True
        for lane in self._lanes.values():
            lane.latest = None   # 멈추기 전 프레임이 resume 뒤에 나가면 안 된다

    def resume(self) -> None:
        if self.anchor is not None:
            self.anchor.reset()   # a robot whose anchor jumped starts over after the reform
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def is_connected(self, robot_id: str) -> bool:
        lane = self._lanes.get(robot_id)
        return bool(lane and lane.connected)

    def streams_ready(self) -> bool:
        """리더 스트림과 전 팔로워 sink 가 열려 있는가. 무장은 이 뒤에 한다 (D-132)."""
        return bool(self._leader_connected) and all(lane.connected for lane in self._lanes.values())

    def stats(self) -> RelayStats:
        return RelayStats(
            leader_frames=self._leader_frames,
            leader_dropped=self._leader_dropped,
            leader_rx_hz=self._leader_rate.hz(),
            leader_last_error=self._leader_last_error,
            leader_age_s=self._leader_rate.age_s(),
            paused=self._paused,
            follower_tx={rid: lane.tx for rid, lane in self._lanes.items()},
            follower_tx_hz={rid: lane.rate.hz() for rid, lane in self._lanes.items()},
            follower_last_tx_age_s={rid: lane.rate.age_s() for rid, lane in self._lanes.items()},
            follower_connected={rid: lane.connected for rid, lane in self._lanes.items()},
            follower_last_error={rid: lane.last_error for rid, lane in self._lanes.items()},
        )

    # --- 리더 --------------------------------------------------------------------

    async def _read_leader(self) -> None:
        backoff = _BACKOFF_FIRST_S
        while self._running:
            got_frame = False
            try:
                async for frame in self._leader.pose_stream():
                    got_frame = True
                    # D-134 — 접속 시도가 아니라 첫 프레임 수신 때만 참이다.
                    # pose_stream()은 async generator라 첫 __anext__ 전까지 접속이
                    # 일어나지 않는다 — 시도 전에 세우면 리더 down이어도 찰나 참이 돼
                    # 검증 안 된 리더에 무장한다.
                    self._leader_connected = True
                    backoff = _BACKOFF_FIRST_S
                    self._leader_last_error = None
                    self._on_frame(frame)
            except asyncio.CancelledError:
                raise
            except RobotApiError as exc:
                # 4401/4403: 토큰이나 capability 문제다. 재연결은 계속하되 이유를 남긴다 —
                # 조용히 0 Hz 로 도는 것이 이 릴레이의 가장 나쁜 실패다.
                self._leader_connected = False
                self._leader_last_error = str(exc)
                log.warning("%s: leader socket refused: %s", self._leader.robot_id, exc)
            except Exception as exc:
                # 팔로워 레인과 같은 규칙이다: 이름 없는 0 Hz 는 없다. 리더는 더 나쁜 쪽이다 —
                # 리더가 죽으면 팔로워 전원이 굶는다.
                self._leader_connected = False
                self._leader_last_error = str(exc)
                log.warning("%s: leader socket failed: %s", self._leader.robot_id, exc)
            else:
                self._leader_connected = False
                if not got_frame:
                    # 예외 없이, 프레임 하나 없이 끝났다. 전송계층이 연결 거부(OSError)를
                    # 삼키면 이 모양이 된다 — 이유 없는 0 Hz 로 남기지 않는다.
                    self._leader_last_error = _QUIET_END
                    log.warning("%s: leader pose stream ended without frames",
                                self._leader.robot_id)
            # 연결(성공이든 거절이든)이 끝났다 — 시퀀스 이어붙임은 한 연결 안에서만 유효
            # 하다. 끊긴 동안의 간격을 드롭으로 세면 안 되므로 여기서 리셋한다.
            self._last_seq = None
            if not self._running:
                return
            # 소켓이 끝났다. 합성하지 않고 다시 연다.
            await self._sleep(backoff)
            backoff = min(backoff * 2, self._reconnect_max)

    def _on_frame(self, frame: str) -> None:
        self._leader_frames += 1
        self._leader_rate.tick()
        seq = _seq_of(frame)
        if seq is not None:
            if self._last_seq is not None and seq > self._last_seq + 1:
                self._leader_dropped += seq - self._last_seq - 1
            self._last_seq = seq
        if self._paused:
            return
        routed = self.anchor.route(frame) if self.anchor is not None else None
        for robot_id, lane in self._lanes.items():
            out = frame if routed is None else routed.get(robot_id)
            if out is None:
                continue               # D-581: no anchor for this follower; it holds on silence
            lane.latest = out          # 깊이 1: 덮는다
            lane.wake.set()

    # --- 팔로워 ------------------------------------------------------------------

    async def _feed(self, lane: _Lane) -> None:
        backoff = _BACKOFF_FIRST_S
        while self._running:
            try:
                lane.sink = await lane.robot.open_reference_sink()
            except asyncio.CancelledError:
                raise
            except RobotApiError as exc:
                # 거부(핸드셰이크 403, 4401/4403): 토큰이나 역할 문제다. 재연결은 계속하되
                # 이유를 남긴다 — 리더와 같은 규칙이다.
                lane.connected = False
                lane.last_error = str(exc)
                log.warning("%s: reference socket refused: %s", lane.robot.robot_id, exc)
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._reconnect_max)
                continue
            except Exception as exc:
                # 거부든 전송 오류든 화면에는 이유가 붙어야 한다 — 이름 없는 0 Hz 는
                # 릴레이의 가장 나쁜 실패다. RobotApiError 만 이름이 붙던 자리다.
                lane.connected = False
                lane.last_error = str(exc)
                log.warning("%s: reference socket open failed: %s", lane.robot.robot_id, exc)
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._reconnect_max)
                continue
            lane.connected = True
            # 소켓이 다시 열렸다는 것 자체가 지난 이유가 지났다는 뜻이다. 첫 프레임을
            # 보낼 때까지 기다리면, 리더가 조용한 동안 고쳐진 소켓이 옛 이유를 달고 있다.
            lane.last_error = None
            # A quiet leader sends nothing, so watch the socket itself: a refusal
            # (4401 after first-message auth) must not leave a healthy-looking lane.
            closed = asyncio.ensure_future(lane.sink.wait_closed())
            closed.add_done_callback(lambda _f, wake=lane.wake: wake.set())
            try:
                while self._running:
                    await lane.wake.wait()
                    if closed.done() and not closed.cancelled():
                        raise closed.result()
                    lane.wake.clear()
                    frame, lane.latest = lane.latest, None
                    if frame is None:
                        continue
                    try:
                        await asyncio.wait_for(lane.sink.send(frame), self._send_timeout)
                    except asyncio.TimeoutError:
                        # 수신 측이 읽지 않는다. 끊고 다시 열어 이름을 붙인다 —
                        # connected=true · tx=0 인 유령 레인을 남기지 않는다.
                        raise TimeoutError(
                            f"reference send timed out after {self._send_timeout}s")
                    lane.tx += 1
                    lane.rate.tick()
                    lane.last_error = None
                    backoff = _BACKOFF_FIRST_S   # 실제로 보냈을 때만 초기화한다
            except asyncio.CancelledError:
                closed.cancel()
                raise
            except Exception as exc:
                lane.connected = False
                lane.last_error = str(exc)
                log.warning("%s: reference socket send failed: %s", lane.robot.robot_id, exc)
                closed.cancel()
                try:
                    await lane.sink.close()
                except Exception:
                    pass
                lane.sink = None
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._reconnect_max)


def _seq_of(frame: str) -> Optional[int]:
    try:
        payload = json.loads(frame).get("payload") or {}
        seq = payload.get("seq")
        if isinstance(seq, bool):
            return None
        if isinstance(seq, int):
            return seq
        if isinstance(seq, float) and seq.is_integer():
            return int(seq)
        return None
    except (TypeError, ValueError, AttributeError):
        return None
