"""D-789 media delegation HTTP shapes; no motion or Fleet authority."""

from typing import Literal
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, StrictInt


@dataclass(frozen=True)
class MediaGrant:
    grant_id: str
    token: str = field(repr=False)
    expires_at: int
    audience: str
    robot_id: str
    path: str
    action: str


class MediaGrantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    robot_id: str = Field(pattern=r'^[A-Za-z0-9._-]{1,96}$')


class MediaSourceGrantRequest(MediaGrantRequest):
    grant_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class MediaGrantResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    grant_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    token: str = Field(min_length=1, max_length=4096, repr=False)
    expires_at: StrictInt
    audience: str = Field(pattern=r'^site:[A-Za-z0-9._-]{1,96}$')
    robot_id: str
    path: str
    action: Literal['read', 'publish']
    site_url: str
