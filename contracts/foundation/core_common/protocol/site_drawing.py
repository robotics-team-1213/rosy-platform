"""Immutable drawing registration; neither localization nor permission to move."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .site_survey import Point

Finite = Annotated[float, Field(allow_inf_nan=False)]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class DrawingTransform(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    plane: Literal['xy', 'xz', 'yz']
    unit: Literal['m', 'cm', 'mm']
    source_origin: tuple[Finite, Finite]
    map_origin_m: Point
    heading_rad: float = Field(ge=-math.tau, le=math.tau, allow_inf_nan=False)
    scale: float = Field(gt=0, allow_inf_nan=False)


class DrawingReference(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    asset_sha256: Digest
    projection_sha256: Digest
