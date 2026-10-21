"""D-810 operator-owned Console dialogue; no execution authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator


class AssistantStrict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class AssistantMessage(AssistantStrict):
    conversation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')
    text: str = Field(min_length=1, max_length=2000)
    selected_robot_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_.:-]{1,96}$')
    locale: Literal['ko-KR', 'en-US'] = 'ko-KR'

    @field_validator('text')
    @classmethod
    def readable_text(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in '\n\r\t' or ord(c) == 127 for c in value):
            raise ValueError('ASSISTANT_TEXT_INVALID')
        return value


class AssistantFact(AssistantStrict):
    ref: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    text: str = Field(min_length=1, max_length=512)
    observed_at: FiniteFloat


class AssistantResult(AssistantStrict):
    request_id: str
    conversation_id: str
    text: str
    state: Literal['PENDING', 'RUNNING', 'ANSWERED', 'HOLD', 'UNKNOWN']
    response: str | None = None
    reason: str | None = None
    facts: list[AssistantFact] = Field(default_factory=list, max_length=64)
    created_at: FiniteFloat
    completed_at: FiniteFloat | None = None
    action_admissible: Literal[False] = False


class AssistantStatus(AssistantStrict):
    available: bool
    mode: Literal['READ_ONLY'] = 'READ_ONLY'
    reason: str | None = None
    execution_enabled: bool = False


class AssistantNavigation(AssistantStrict):
    robot_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,96}$')
    x: FiniteFloat = Field(ge=-100000, le=100000)
    y: FiniteFloat = Field(ge=-100000, le=100000)
    yaw: FiniteFloat = Field(default=0., ge=-3.141592653589793, le=3.141592653589793)


class AssistantHistory(AssistantStrict):
    conversation_id: str
    messages: list[AssistantResult] = Field(max_length=40)
