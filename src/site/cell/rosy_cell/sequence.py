"""Order inside one layer: boxes far from the robot go first so the gripper never reaches over a placed box.

`approach` names the pallet side the robot reaches in from. A robot on the +x side reaches
toward -x, so the far side is the smallest x.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .stack import PlacedBox

APPROACHES: dict[str, Callable[[PlacedBox], tuple[float, float]]] = {
    "+x": lambda b: (b.x, b.y),
    "-x": lambda b: (-b.x, b.y),
    "+y": lambda b: (b.y, b.x),
    "-y": lambda b: (-b.y, b.x),
}


def place_order(layer: Sequence[PlacedBox], *, approach: str) -> tuple[PlacedBox, ...]:
    try:
        key = APPROACHES[approach]
    except KeyError:
        raise ValueError(f"unknown approach {approach!r}") from None
    return tuple(sorted(layer, key=key))
