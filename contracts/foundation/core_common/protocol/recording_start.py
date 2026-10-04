"""Closed, additive options for Pilot recording starts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class RecordingStartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preview_mode: Literal['raw', 'annotated'] = 'raw'
