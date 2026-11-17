"""D-998 independent delivery contract; acceptance is not business completion."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identity = Annotated[str, Field(pattern=r'^[A-Za-z0-9_.:-]{1,96}$')]


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)

    producer: Literal['fleet', 'harbor']
    notification_id: Identity
    channel: Identity
    kind: Literal['OPEN', 'CLOSED', 'FINAL_REVIEW', 'HOLD']
    subject_id: Identity
    occurrence_id: Identity
    revision: Identity
    classification: Identity
    observed_at: float = Field(ge=0)
    expires_at: float = Field(gt=0)

    @model_validator(mode='after')
    def valid_profile(self):
        if (self.producer == 'harbor') != (self.kind == 'HOLD'):
            raise ValueError('producer notification kind mismatch')
        if self.expires_at <= self.observed_at:
            raise ValueError('expiry must follow observation')
        return self


class DeliveryReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    producer: str
    notification_id: str
    state: Literal['PENDING', 'RETRY', 'SENDING', 'SENT', 'UNKNOWN', 'EXPIRED', 'SUPERSEDED', 'FAILED']
    attempts: int


class DeliveryOwnerReply(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    notification_id: Identity
    revision: Identity
    valid: bool
