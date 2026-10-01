"""Order inside one layer: boxes far from the robot go first so the gripper never reaches over a placed box.

Distance is measured in the pallet frame's xy plane from the box centre to the robot base
(the base-frame origin), so the order follows the taught frame, not a recipe setting.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .geometry import Frame
from .stack import PlacedBox

_DIGITS = 9  # float slack (1e-9 m) so equal distances tie and fall through to (x, y); not a physical tolerance


def place_order(layer: Sequence[PlacedBox], frame: Frame) -> tuple[PlacedBox, ...]:
    rx, ry, _ = frame.from_base((0.0, 0.0, 0.0))
    return tuple(sorted(layer, key=lambda b: (-round(math.hypot(b.x - rx, b.y - ry), _DIGITS), b.x, b.y)))
