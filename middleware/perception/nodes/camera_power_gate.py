"""Subject: camera and perception tick plan under the per-device power policy (D-440). ROS-free.

CORE publishes a latched JSON board on `power/devices`, for example
`{"camera": "off", "perception": "reduced"}`, and only while the bench switch
(`power.device_policy.enabled`) or a device's own switch is on. Without a board
this gate says "run" every tick, so the node behaves exactly as before.

Plans per tick:

* `off`  — camera off (or perception off): stop capturing, report blocked.
* `skip` — perception reduced: only every `reduced_every`-th tick is processed;
  the others capture nothing and republish the held verdict.
* `run`  — normal.

After the camera comes back on, the node reports `ready: false` until its own
warmup gate (`CameraPolicy.ready`) passes, then `ready: true`, on
`power/device_ready`.
"""

from __future__ import annotations

import json
from typing import Optional

LEVELS = ("on", "reduced", "off")
# D-440 1: "reduced" perception classifies one tick in four. The rate is the node's
# fact (it owns the tick), so it lives here and not in the CORE device table.
REDUCED_EVERY = 4


class DevicePowerGate:
    def __init__(self, reduced_every: int = REDUCED_EVERY) -> None:
        self.reduced_every = max(1, int(reduced_every))
        self.camera = "on"
        self.perception = "on"
        self._tick = 0

    def update(self, raw: str) -> Optional[tuple[str, str]]:
        """Apply one board. Returns (previous, new) camera level when it changed."""
        try:
            board = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(board, dict):
            return None
        previous = self.camera
        camera = board.get("camera", "on")
        perception = board.get("perception", "on")
        self.camera = camera if camera in LEVELS else "on"
        self.perception = perception if perception in LEVELS else "on"
        return (previous, self.camera) if previous != self.camera else None

    def plan(self) -> str:
        if self.camera == "off" or self.perception == "off":
            return "off"
        if self.perception == "reduced":
            self._tick += 1
            return "run" if self._tick % self.reduced_every == 1 or self.reduced_every == 1 else "skip"
        self._tick = 0
        return "run"


def ready_report(device: str, ready: bool) -> str:
    return json.dumps({"device": device, "ready": bool(ready)}, sort_keys=True)
