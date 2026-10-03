"""D-193/D-341/D-432 approval request models, exported by schemas."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class ConnectionInfo(BaseModel):
    mode: Literal['paired', 'development']
    robot_id: str
    transport: Literal['http', 'https']


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
