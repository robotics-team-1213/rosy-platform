"""Read-only motor evidence; availability never implies permission to actuate."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


class MotorHealthSample(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    group: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.-]+$')
    joint: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.-]+$')
    id: int = Field(ge=1, le=253)
    sample_age_s: FiniteFloat = Field(ge=0)
    command_raw: FiniteFloat
    present_raw: FiniteFloat
    error_deg: FiniteFloat = Field(ge=0)
    pwm: FiniteFloat
    pwm_limit: FiniteFloat = Field(gt=0)
    pwm_utilization: FiniteFloat = Field(ge=0)
    temperature_c: FiniteFloat
    temperature_limit_c: FiniteFloat = Field(gt=0, le=100)
    voltage_v: FiniteFloat
    min_voltage_v: FiniteFloat = Field(gt=0)
    max_voltage_v: FiniteFloat = Field(gt=0)
    hardware_error: int | None = Field(default=None, ge=0, le=255)
    fault: bool = False
    torque_enabled: bool | None = None
    warnings: list[Literal['high_pwm', 'near_temperature_limit']] = Field(default_factory=list, max_length=2)


class MotorHealthResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['rosy.motor-health.v1'] = 'rosy.motor-health.v1'
    evidence: Literal['fresh', 'delayed', 'disconnected', 'unavailable']
    status: Literal['active', 'fault', 'ended', 'unavailable']
    owner_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')
    session_id: str | None = None
    sample_age_s: FiniteFloat | None = Field(default=None, ge=0)
    stale_after_s: Literal[2] = 2
    motors: list[MotorHealthSample] = Field(default_factory=list, max_length=128)
    stop_reasons: list[str] = Field(default_factory=list, max_length=12)
    support_reason: str | None = Field(default=None, max_length=160)

    @field_validator('session_id')
    @classmethod
    def canonical_session(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError('session_id must be a canonical UUID')
        return value

    @model_validator(mode='after')
    def coherent_evidence(self):
        if self.evidence == 'fresh' and (self.status != 'active' or not self.owner_id or not self.session_id
                or not self.motors or self.sample_age_s is None or self.sample_age_s > 2
                or any(m.sample_age_s > 2 for m in self.motors)):
            raise ValueError('fresh evidence requires active bound complete measured samples')
        if self.status in ('fault', 'ended') and self.evidence != 'disconnected':
            raise ValueError('terminal sessions require disconnected evidence')
        if self.status == 'unavailable' and (self.evidence != 'unavailable' or self.motors):
            raise ValueError('unavailable source cannot fabricate motors')
        if self.evidence == 'delayed' and (self.status != 'active' or not self.motors):
            raise ValueError('delayed evidence requires active measured samples')
        return self


def age_motor_health(health, elapsed):
    """Transport and receipt time only increase existing measurement ages."""
    if elapsed < 0:
        elapsed = 2.000001  # A regressing receipt clock cannot retain fresh evidence.
    data = health.model_dump()
    if data['sample_age_s'] is not None:
        data['sample_age_s'] += elapsed
    for motor in data['motors']:
        motor['sample_age_s'] += elapsed
    if data['evidence'] == 'fresh' and (data['sample_age_s'] > 2 or any(m['sample_age_s'] > 2 for m in data['motors'])):
        data['evidence'] = 'delayed'
    return MotorHealthResponse.model_validate(data)
