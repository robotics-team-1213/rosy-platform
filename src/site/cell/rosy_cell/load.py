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

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.length, self.width, self.height, self.mass_kg)):
            raise ValueError("box sizes and mass must be finite")
        if min(self.length, self.width, self.height) <= 0 or self.mass_kg < 0:
            raise ValueError("box sizes must be positive and mass non-negative")


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
