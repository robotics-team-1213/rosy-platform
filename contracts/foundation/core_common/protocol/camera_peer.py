"""D456 camera relationship profile: no CORE control or site operator credential."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Profile(Strict):
    profile: Literal['rosy.camera-peer/1']
    audience: Literal['fleet-camera-ingest']
    device_kind: Literal['overhead-camera']
    source_role: Literal['camera']


class CameraRequest(Profile):
    receiver_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    receiver_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    client_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    client_public_key: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=64, pattern=r'^[^\x00-\x1f\x7f]+$')
    nonce: str = Field(pattern=r'^[0-9a-f]{64}$')


class SignedRequest(Strict):
    fields: CameraRequest
    signature: str = Field(min_length=1, max_length=128)


class ReceiverDecision(Strict):
    action: Literal['approve', 'reject']
    revision: int = Field(ge=0)
    source_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    persist_requested: bool


class IdentitySnapshot(Profile):
    receiver_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    receiver_public_key: str = Field(min_length=1, max_length=256)
    receiver_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    tls_hostname: str = Field(min_length=1, max_length=253)
    tls_ca_pem: str = Field(min_length=1, max_length=8192)
    tls_ca_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class StateSnapshot(Profile):
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    state: Literal['pending', 'approved', 'rejected', 'cancelled', 'expired']
    revision: int = Field(ge=0)
    display_code: str = Field(pattern=r'^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$')
    expires_at: str = Field(max_length=64)
    credential_issued: Literal[False] = False
    relationship_id: str | None = Field(default=None, max_length=32)
    generation: int | None = Field(default=None, ge=0)
    source_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,32}$')
    persistent: bool | None = None
    authorization_expires_at: str | None = Field(default=None, max_length=64)
    authorization_available: bool = False


class CreatedRequest(StateSnapshot):
    request_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class PendingRequest(StateSnapshot):
    client_id: str = Field(max_length=64)
    label: str = Field(max_length=64)
    client_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ChallengeRequest(Strict):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    generation: int = Field(ge=0)


class ChallengeFields(Profile):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    challenge_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    nonce: str = Field(pattern=r'^[0-9a-f]{64}$')
    receiver_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    receiver_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    client_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    client_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    generation: int = Field(ge=0)
    expires_at: str = Field(max_length=64)


class ChallengeSnapshot(Strict):
    fields: ChallengeFields
    receiver_signature: str = Field(min_length=1, max_length=128)


class SignedSession(Strict):
    fields: ChallengeFields
    signature: str = Field(min_length=1, max_length=128)


class SessionSnapshot(Profile):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    generation: int = Field(ge=0)
    credential_id: str = Field(pattern=r'^cam-peer-[A-Za-z0-9_-]{24}$')
    token: str = Field(min_length=16, max_length=128)
    source_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    role: Literal['overhead-camera']
    expires_at: str = Field(max_length=64)


class RelationshipSnapshot(Profile):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    source_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    label: str = Field(min_length=1,max_length=64)
    client_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    generation: int = Field(ge=0)
    state: Literal['approved','revoked']
    persistent: bool
    authorization_available: bool
    authorization_expires_at: str | None = Field(default=None,max_length=64)
