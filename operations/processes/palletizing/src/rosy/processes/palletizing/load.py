"""Box and pallet value objects (SI units)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    length: float
    width: float
    height: float
    mass_kg: float
    # How far below the top face the tool point (TCP) grasps the box (C3b B1, D-401 보강).
    # 0 = at the top face (the original contract). It is per item because the safe squeeze
    # height depends on the item, and a slip sheet is always taken at its top face.
    grasp_depth: float = 0.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.length, self.width, self.height, self.mass_kg, self.grasp_depth)):
            raise ValueError("box sizes and mass must be finite")
        if min(self.length, self.width, self.height) <= 0 or self.mass_kg < 0:
            raise ValueError("box sizes must be positive and mass non-negative")
        if not 0 <= self.grasp_depth < self.height:
            raise ValueError("grasp_depth must be in [0, height): the TCP grasps inside the box")


@dataclass(frozen=True)
class Pallet:
    length: float
    width: float
    max_stack_height: float
    max_load_kg: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.length, self.width, self.max_stack_height, self.max_load_kg)):
            raise ValueError("pallet sizes and max load must be finite")
        if min(self.length, self.width, self.max_stack_height) <= 0 or self.max_load_kg < 0:
            raise ValueError("pallet sizes must be positive and max load non-negative")
