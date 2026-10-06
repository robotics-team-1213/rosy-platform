"""Candidate typed wire input; request consent is not a control grant."""
from datetime import datetime, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RepositoryDenied(ValueError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PeerRequest(Strict):
    receiver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    receiver_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    client_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    client_public_key: str = Field(min_length=1, max_length=256)
    role: Literal["viewer", "operator"]
    nonce: str = Field(pattern=r"^[0-9a-f]{64}$")


class SignedRequest(Strict):
    fields: PeerRequest
    signature: str = Field(min_length=1, max_length=128)


class ReceiverDecision(Strict):
    action: Literal["approve", "reject"]
    revision: int = Field(ge=0)
    persist_requested: bool = False


#: D-483: the robot-screen approval code alphabet and length.
APPROVAL_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
APPROVAL_CODE_LENGTH = 6
#: D-483: the issuer marker of a relationship approved by the robot-screen code.
SCREEN_CODE_ISSUER = "screen-code"
#: D-483 5: a screen-code approval never outlives this.
SCREEN_CODE_LIFETIME = timedelta(hours=168)
#: D-483 R3: clock skew tolerated before a screen-code approval dated in the future is refused.
SCREEN_CODE_SKEW = timedelta(seconds=60)


def screen_code_dated(grant, now) -> bool:
    """False for a screen-code row whose approved_at lies in the future (a forged or skewed row)."""
    if grant.get("issuer_source") != SCREEN_CODE_ISSUER:
        return True
    approved = grant.get("approved_at")
    return approved is not None and datetime.fromisoformat(approved) <= now + SCREEN_CODE_SKEW


class ApprovalCodeConfirm(Strict):
    approval_code: str = Field(pattern=r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{6}$")


class ChallengeFields(Strict):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    challenge_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    nonce: str = Field(pattern=r'^[0-9a-f]{64}$')
    receiver_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    receiver_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    client_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    client_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    role: Literal['viewer', 'operator']
    generation: int = Field(ge=0)
    expires_at: str = Field(max_length=64)


class SignedSession(Strict):
    fields: ChallengeFields
    signature: str = Field(min_length=1, max_length=128)


class IdentitySnapshot(Strict):
    receiver_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    receiver_public_key: str = Field(max_length=256)
    receiver_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    tls_hostname: str | None = Field(default=None, max_length=253)
    tls_ca_pem: str | None = Field(default=None, max_length=8192)
    tls_ca_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class StateSnapshot(Strict):
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    state: Literal['pending', 'approved', 'rejected', 'cancelled', 'expired']
    revision: int = Field(default=0, ge=0)
    paired: Literal[False]
    display_code: str = Field(pattern=r'^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$')
    expires_at: str = Field(max_length=64)
    relationship_id: str | None = Field(default=None, max_length=32)
    authorization_expires_at: str | None = Field(default=None, max_length=64)
    persistent: bool | None = None
    generation: int | None = Field(default=None, ge=0)
    authorization_available: bool = False


class CreatedRequest(StateSnapshot):
    request_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class PendingRequest(StateSnapshot):
    client_id: str = Field(max_length=64)
    label: str = Field(max_length=64)
    role: Literal['viewer', 'operator']
    client_key_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ChallengeSnapshot(Strict):
    fields: ChallengeFields
    receiver_signature: str = Field(max_length=128)


class SessionSnapshot(Strict):
    id: str = Field(max_length=128)
    token: str = Field(min_length=16, max_length=128)
    role: Literal['viewer', 'operator']
    expires_at: str = Field(max_length=64)


class RevokedSnapshot(Strict):
    relationship_id: str = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    state: Literal['revoked']
    generation: int = Field(ge=1)


class Relationship(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    receiver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    receiver_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    client_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    client_public_key: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    role: Literal["viewer", "operator"]
    generation: int = Field(ge=0)
    revoked: bool
    issuer_id: str = Field(min_length=1, max_length=128)
    issuer_source: Literal["card", "manual", "pair-physical", "pair-admin", "screen-code"]
    issuer_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=128)
    persistent: bool
    persist_requested: bool
    expires_at: str | None = Field(max_length=64)
    used_challenges: list[str] = Field(max_length=64)
    session_ids: list[str] = Field(default_factory=list, max_length=8)
    #: D-483 L2: when a screen-code approval was made; bounds its lifetime. None on owner approvals.
    approved_at: str | None = Field(default=None, max_length=64)

    @model_validator(mode='after')
    def persistent_authority_shape(self):
        if self.persistent != (self.expires_at is None):
            raise ValueError('relationship lifetime shape mismatch')
        if self.persistent and (not self.persist_requested or self.issuer_source not in {'card', 'manual'}):
            raise ValueError('persistent issuer provenance required')
        # D-483 5: a screen-code approval is always bounded and names no token issuer.
        screen = SCREEN_CODE_ISSUER in (self.issuer_source, self.issuer_id, self.approved_by)
        if screen and not (self.issuer_source == self.issuer_id == self.approved_by == SCREEN_CODE_ISSUER
                           and self.issuer_digest == self.receiver_key_sha256 and self.expires_at is not None
                           and self.approved_at is not None and not self.persist_requested
                           and timedelta(0) < datetime.fromisoformat(self.expires_at)
                           - datetime.fromisoformat(self.approved_at) <= SCREEN_CODE_LIFETIME):
            raise ValueError('screen-code approval shape mismatch')
        return self

    def stored(self) -> dict:
        """The row as written to the overlay. A key added after D-456 is left out while unset,
        so an owner row stays readable by a release before D-483 (its Strict model forbids extras)."""
        row = self.model_dump()
        if row["approved_at"] is None:
            del row["approved_at"]
        return row

    @field_validator("expires_at", "approved_at")
    @classmethod
    def aware_expiry(cls, value):
        if value is not None and datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("timezone required")
        return value

    @field_validator("used_challenges", "session_ids")
    @classmethod
    def bounded_identifiers(cls, values):
        if len(values) != len(set(values)) or any(not v or len(v) > 128 for v in values):
            raise ValueError("invalid bounded identifiers")
        return values
