"""Immutable drawing registration; neither localization nor permission to move."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class RasterDrawingTransform(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    source_origin_px: tuple[Finite, Finite]
    map_origin_m: Point
    heading_rad: float = Field(ge=-math.tau, le=math.tau, allow_inf_nan=False)
    meters_per_pixel: float = Field(gt=0, allow_inf_nan=False)


class ExtractionSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    canny_low: int = Field(default=50, ge=0, le=255, strict=True)
    canny_high: int = Field(default=150, ge=0, le=255, strict=True)
    threshold: int = Field(default=20, ge=1, le=8192, strict=True)
    min_line_length_px: int = Field(default=30, ge=2, le=8192, strict=True)
    max_gap_px: int = Field(default=3, ge=0, le=64, strict=True)
    tolerance_px: float = Field(default=1, ge=0, le=10, allow_inf_nan=False)

    @model_validator(mode='after')
    def thresholds(self):
        if self.canny_low >= self.canny_high:
            raise ValueError('Canny low must be less than high')
        return self


PixelIndex = Annotated[int, Field(ge=0, le=8192, strict=True)]


class DrawingExtractionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    crop_px: tuple[PixelIndex, PixelIndex, PixelIndex, PixelIndex]
    method: Literal['lines', 'contours']
    settings: ExtractionSettings = Field(default_factory=ExtractionSettings)

    @model_validator(mode='after')
    def rectangle(self):
        x0, y0, x1, y1 = self.crop_px
        if x0 >= x1 or y0 >= y1:
            raise ValueError('crop must have positive width and height')
        return self
