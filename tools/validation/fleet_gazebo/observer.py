"""D-426 Task 3 — 독립 관측기 기록 계층(ROS-free 판정 입력 제작).

observer만 Gazebo model pose/contact 와 최종 cmd_vel publisher 를 읽는다(계획 T3
항목 2). 추가 observer truth 를 Fleet/CORE 판단에 주입하지 않는다 — 이 모듈은
기록만 만들고 판정은 assertions.py 가 내린다.

수집 경로(실제 gz transport 연결)는 주입한다: 호스트 시험은 가짜 공급원을 넣고,
T6 WSL 회차는 gz-transport 구독 공급원을 넣는다. epoch(pause/reset) 전환·빈 구간
표시·20 Hz 확인·publisher 소유권 검사가 이 계층의 책임이다.

물리 시계(sim)와 관측 시계(monotonic)를 한 표본에 함께 실어 나른다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from assertions import (ContactEvent, PoseSample, observation_gaps,
                        observation_rate_hz)

#: 관측 빈 구간 판정 한계(assertions.MAX_GAP_S 와 같은 값).
MAX_GAP_S = 0.15
MIN_OBSERVATION_HZ = 20.0


@dataclass
class Epoch:
    """pause/reset 사이의 물리 구간. 경계를 넘는 단언은 이어 붙이지 않는다."""

    index: int
    opened_mono: float
    closed_mono: float | None = None
    reason: str = "run-start"

    @property
    def closed(self) -> bool:
        return self.closed_mono is not None


class Recorder:
    """주입된 공급원에서 표본을 받아 epoch별 기록을 만든다."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self.epochs: list[Epoch] = [Epoch(index=0, opened_mono=clock())]
        self.poses: list[PoseSample] = []
        self.contacts: list[ContactEvent] = []
        self.publisher_events: list[dict] = []

        self._pose_source = None
        self._contact_source = None

    # ------------------------------------------------------------- wiring
    def attach_pose_source(self, source) -> None:
        """``source()`` 는 관측 시점의 ``list[PoseSample]`` 를 반환한다."""
        self._pose_source = source

    def attach_contact_source(self, source) -> None:
        """``source()`` 는 관측 시점의 ``list[ContactEvent]`` 를 반환한다."""
        self._contact_source = source

    # -------------------------------------------------------------- record
    def poll(self) -> None:
        """공급원을 한 번 긁어 현재 epoch 에 기록한다."""
        if self._pose_source is not None:
            self.poses.extend(self._pose_source())
        if self._contact_source is not None:
            self.contacts.extend(self._contact_source())

    def mark_epoch_end(self, reason: str) -> None:
        """pause/reset — 현재 epoch 를 닫고 새 epoch 를 연다(이전 단언 불이어붙임)."""
        current = self.epochs[-1]
        if current.closed:
            return
        current.closed_mono = self._clock()
        current.reason = reason
        self.epochs.append(Epoch(index=current.index + 1, opened_mono=self._clock()))

    def current_epoch(self) -> Epoch:
        return self.epochs[-1]

    # -------------------------------------------------------------- slices
    def poses_in(self, epoch: Epoch, *, robot_id: str | None = None) -> list[PoseSample]:
        """한 epoch 의 관측만 돌려준다 — 경계 밖 표본은 판정에 섞지 않는다."""
        opened = epoch.opened_mono
        closed = epoch.closed_mono if epoch.closed else float("inf")
        return [s for s in self.poses
                if opened <= s.mono <= closed and (robot_id is None or s.robot_id == robot_id)]

    def contacts_in(self, epoch: Epoch) -> list[ContactEvent]:
        opened = epoch.opened_mono
        closed = epoch.closed_mono if epoch.closed else float("inf")
        return [e for e in self.contacts if opened <= e.mono <= closed]

    def gap_report(self, epoch: Epoch, *, robot_id: str) -> dict:
        return observation_gaps(self.poses_in(epoch, robot_id=robot_id))

    def rate_hz(self, epoch: Epoch, *, robot_id: str) -> float:
        return observation_rate_hz(self.poses_in(epoch, robot_id=robot_id),
                                   robot_id=robot_id)

    def rate_ok(self, epoch: Epoch, *, robot_id: str,
                min_hz: float = MIN_OBSERVATION_HZ) -> bool:
        return self.rate_hz(epoch, robot_id=robot_id) >= min_hz


def check_publisher_ownership(observed: list[dict], expected: dict) -> dict:
    """최종 cmd_vel publisher 검사 — 이름뿐 아니라 endpoint/GID·프로세스 소유권.

    ``observed``: [{topic, publisher, pid, endpoint, gid}] (관측된 것)
    ``expected``: {topic: {publisher, pid, endpoint, gid}} (run 소유 프로세스와 endpoint 결속)
    """
    problems: list[str] = []
    if not expected:
        problems.append("expected run-owned publishers are missing")
    for topic in expected:
        if sum(row.get("topic") == topic for row in observed) != 1:
            problems.append(f"{topic}: exactly one observed publisher is required")
    for row in observed:
        topic = row.get("topic", "")
        want = expected.get(topic)
        if want is None:
            problems.append(f"{topic}: unexpected publisher {row.get('publisher')!r}")
            continue
        for field in ("publisher", "endpoint", "gid"):
            if not want.get(field) or not row.get(field) or row[field] != want[field]:
                problems.append(f"{topic}: {field} missing or != this run's binding")
        if (type(want.get("pid")) is not int or want["pid"] <= 0 or
                type(row.get("pid")) is not int or row["pid"] != want["pid"]):
            problems.append(f"{topic}: publisher pid missing or not this run's CORE pid")
    return {"ok": not problems, "problems": problems}
