"""LeRobot teleoperator that replays a taught trajectory instead of a hand on the leader (scripted teacher).

Found by LeRobot's third-party plugin discovery through the sibling dist-info when record_session.py
--replay puts this directory on PYTHONPATH. One frame per get_action() call, so recording and reset
loops advance it at the recorder's fps; after the last frame the last pose is held.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lerobot.teleoperators.config import TeleoperatorConfig
from lerobot.teleoperators.teleoperator import Teleoperator


@TeleoperatorConfig.register_subclass("rosy_replay")
@dataclass(kw_only=True)
class RosyReplayConfig(TeleoperatorConfig):
    trajectory: str = ""


class RosyReplay(Teleoperator):
    config_class = RosyReplayConfig
    name = "rosy_replay"

    def __init__(self, config: RosyReplayConfig):
        super().__init__(config)
        self.config, self.frames, self.names, self.calls = config, None, None, 0

    @property
    def action_features(self) -> dict:
        return {name: float for name in self.names} if self.names else {}

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_connected(self) -> bool:
        return self.frames is not None

    def connect(self, calibrate: bool = True) -> None:
        trajectory = json.loads(Path(self.config.trajectory).read_text())  # validated by record_session
        self.frames, self.names, self.calls = trajectory["frames"], trajectory["names"], 0

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def get_action(self) -> dict[str, float]:
        frame = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return dict(zip(self.names, frame))

    def send_feedback(self, feedback: dict[str, float]) -> None:
        pass

    def disconnect(self) -> None:
        self.frames = None
