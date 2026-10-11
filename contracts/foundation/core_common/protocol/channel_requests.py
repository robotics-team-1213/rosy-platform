"""D-671 reception receipts carry no execution grant."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Snowflake = str


class DiscordRequestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    guild_id: Snowflake = Field(pattern=r"^[0-9]{17,20}$")
    channel_id: Snowflake = Field(pattern=r"^[0-9]{17,20}$")
    author_id: Snowflake = Field(pattern=r"^[0-9]{17,20}$")
    message_id: Snowflake = Field(pattern=r"^[0-9]{17,20}$")
    content: str = Field(min_length=1, max_length=2000)
    mentions: list[str] = Field(max_length=100)
    author_bot: bool
    webhook_id: str | None


class ChannelRequestReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    principal_id: str
    guild_id: str
    channel_id: str
    message_id: str
    author_id: str
    content: str
    content_hash: str
    received_at: str
    status: Literal["REQUESTED"] = "REQUESTED"


class ChannelRequestList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rows: list[ChannelRequestReceipt] = Field(max_length=50)


class ChannelNavigationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    robot_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_.-]+$")
    x: FiniteFloat
    y: FiniteFloat
    yaw: FiniteFloat = 0.0


class ChannelReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=0)
    state: Literal["READY", "HOLD", "REJECTED"]
    candidate: ChannelNavigationCandidate | None = None
    reason: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def candidate_scope(self):
        if (self.state == "READY") != (self.candidate is not None) or not self.reason.strip():
            raise ValueError("READY requires a candidate; HOLD/REJECTED require only a reason")
        return self


class ChannelSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=0)


class ChannelTaskLinkRequest(ChannelSubmitRequest):
    task_id: str = Field(min_length=1, max_length=128)


class ChannelWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    content_hash: str
    revision: int
    state: Literal["REQUESTED", "READY", "HOLD", "REJECTED", "LINKED"]
    candidate: ChannelNavigationCandidate | None
    reason: str | None
    work_kind: Literal["task"] | None
    work_id: str | None
    work_status: str | None
    request_key: str
