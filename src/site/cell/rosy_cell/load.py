"""Box and pallet value objects (SI units)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    length: float
    width: float
    height: float
    mass_kg: float

    def __post_init__(self) -> None:
        if min(self.length, self.width, self.height) <= 0 or self.mass_kg < 0:
            raise ValueError("box sizes must be positive and mass non-negative")


@dataclass(frozen=True)
class Pallet:
    length: float
    width: float
    max_stack_height: float
    max_load_kg: float

    def __post_init__(self) -> None:
        if min(self.length, self.width, self.max_stack_height) <= 0 or self.max_load_kg < 0:
            raise ValueError("pallet sizes must be positive and max load non-negative")
