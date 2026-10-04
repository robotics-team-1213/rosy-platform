"""In-process doubles for the match loop. No HTTP."""

from __future__ import annotations

from games.game import Observation


class FakeObserver:
    def __init__(self, frames: Observation | list[Observation]) -> None:
        self.frames = frames if isinstance(frames, list) else [frames]
        self.i = 0

    def observe(self) -> Observation:
        frame = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return frame


class FakePlayerClient:
    def __init__(
        self,
        robot_id: str,
        *,
        fail_teleop: bool = False,
        fail_estop: bool = False,
        fail_manual: bool = False,
    ) -> None:
        self.robot_id = robot_id
        self.fail_teleop = fail_teleop
        self.fail_estop = fail_estop
        self.fail_manual = fail_manual
        self.teleops: list[tuple[float, float]] = []
        self.estops = 0
        self.manual = 0
        self.limits: list[tuple[float, float]] = []

    def set_manual(self) -> None:
        if self.fail_manual:
            raise RuntimeError("set_manual failed")
        self.manual += 1

    def set_limits(self, linear: float, angular: float) -> None:
        self.limits.append((linear, angular))

    def teleop(self, linear: float, angular: float) -> None:
        if self.fail_teleop:
            raise RuntimeError("teleop failed")
        self.teleops.append((linear, angular))

    def estop(self) -> None:
        self.estops += 1
        if self.fail_estop:
            raise RuntimeError(f"{self.robot_id} estop failed")
