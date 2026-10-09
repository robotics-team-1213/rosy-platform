"""D-193/D-341/D-432 approval request models, exported by schemas."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class ConnectionInfo(BaseModel):
    mode: Literal['paired', 'development']
    robot_id: str
    transport: Literal['http', 'https']
    # D-535 reachability (optional: robots before it answer the three fields above only).
    connect_contract: int | None = None
    api: str | None = None
    core_ready: bool | None = None
    stage: str | None = Field(default=None, max_length=128)
    release: str | None = Field(default=None, max_length=64)
    tls_hostname: str | None = Field(default=None, max_length=253)
    pairing: Literal['open', 'console_only', 'full', 'unavailable'] | None = None


class RoomDiscoveryHint(BaseModel):
    """Public LAN observation, never an approved identity or a control grant."""
    model_config = ConfigDict(extra='forbid', strict=True)
    hostname: str = Field(pattern=r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$')
    address: str = Field(min_length=7, max_length=15)
    port: int = Field(ge=1, le=65535)
    kind: Literal['robot']
    url: str = Field(min_length=1, max_length=512)


class SiteRoomsSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    rooms: list[RoomDiscoveryHint] = Field(max_length=64)


class LoginPairRequest(BaseModel):
    """Existing eight-symbol screen code."""
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(default='', max_length=64)


class CameraPairApprovalRequest(BaseModel):
    """Existing six-digit camera approval code."""
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^[0-9]{6}$')
    source_id: str = Field(min_length=1, max_length=32)


class SshPairRequest(BaseModel):
    """Administrator approval registers one public key at the fixed operator account."""
    model_config = ConfigDict(extra='forbid')
    public_key: str = Field(min_length=1, max_length=512)
    confirmed: bool = False
