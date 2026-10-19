"""D-772 station installation and charge evidence; DTOs never grant motion authority."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')]
Number = Annotated[float, Field(allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[Number, Field(ge=0)]
Positive = Annotated[Number, Field(gt=0)]
Percent = Annotated[Number, Field(ge=0, le=100)]
Revision = Annotated[int, Field(strict=True, ge=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, validate_default=True)


class Pose2D(Contract):
    x: Number
    y: Number
    yaw: Number


class TimedEvidence(Contract):
    captured_at: Nonnegative
    valid_until: Nonnegative

    @model_validator(mode='after')
    def check_scope_and_time(self, info: ValidationInfo):
        if self.valid_until <= self.captured_at:
            raise ValueError('evidence validity must follow capture')
        context = info.context or {}
        if 'now' in context:
            now = context['now']
            if isinstance(now, bool) or not isinstance(now, (float, int)) or not math.isfinite(now):
                raise ValueError('validation clock must be finite seconds')
            if not self.captured_at <= now < self.valid_until:
                raise ValueError('evidence is future dated or expired')
        for key in ('robot_id', 'station_id', 'map_id', 'map_revision', 'pose_revision',
                    'session_id', 'boot_id', 'odom_epoch', 'battery_id', 'source_epoch',
                    'calibration_revision'):
            if key in context and key in type(self).model_fields and getattr(self, key) != context[key]:
                raise ValueError(f'evidence {key} does not match expected scope')
        return self


class StationPoseRecord(TimedEvidence):
    station_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    pose: Pose2D
    approach_pose: Pose2D | None
    approach_verified: bool
    source_id: Identifier
    source_epoch: Identifier
    calibration_revision: Identifier
    uncertainty_m: Nonnegative
    uncertainty_rad: Nonnegative
    status: Literal['CANDIDATE', 'VALID', 'INVALID']

    @model_validator(mode='after')
    def valid_installation_needs_approach(self):
        if self.status == 'VALID' and (not self.approach_verified or self.approach_pose is None):
            raise ValueError('valid station needs a verified approach')
        return self


class StationPoseAck(TimedEvidence):
    station_id: Identifier
    robot_id: Identifier
    boot_id: Identifier
    session_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    accepted: bool


class MapPoseEvidence(TimedEvidence):
    robot_id: Identifier
    boot_id: Identifier
    odom_epoch: Identifier
    map_id: Identifier
    map_revision: Identifier
    frame: Literal['map'] = 'map'
    pose: Pose2D
    uncertainty_m: Nonnegative
    uncertainty_rad: Nonnegative
    source_id: Identifier
    source_epoch: Identifier
    calibration_revision: Identifier


class StationObservation(TimedEvidence):
    robot_id: Identifier
    station_id: Identifier
    session_id: Identifier
    boot_id: Identifier
    odom_epoch: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    source_id: Identifier
    source_epoch: Identifier
    calibration_revision: Identifier
    sequence: Annotated[int, Field(strict=True, ge=0)]
    frame: Literal['base_link']
    pose: Pose2D | None
    uncertainty_m: Nonnegative
    uncertainty_rad: Nonnegative
    visible: bool

    @model_validator(mode='after')
    def visible_needs_pose(self):
        if self.visible and self.pose is None:
            raise ValueError('visible observation requires relative pose')
        return self


class SeatingEvidence(TimedEvidence):
    robot_id: Identifier
    station_id: Identifier
    session_id: Identifier
    boot_id: Identifier
    pose_revision: Revision
    odom_epoch: Identifier
    position_error_m: Nonnegative
    heading_error_rad: Nonnegative
    measured_linear_m_s: Number
    measured_angular_rad_s: Number
    motion_sample_at: Nonnegative
    contact_sample_at: Nonnegative
    position_sample_at: Nonnegative
    load_present: bool

    @model_validator(mode='after')
    def samples_precede_snapshot(self):
        if max(self.motion_sample_at, self.contact_sample_at, self.position_sample_at) > self.captured_at:
            raise ValueError('seating samples cannot follow snapshot')
        return self


class ChargeCompletionEvidence(TimedEvidence):
    station_id: Identifier
    robot_id: Identifier
    session_id: Identifier
    boot_id: Identifier
    battery_id: Identifier
    load_present: bool
    charging: bool
    termination: Literal['NORMAL', 'CHARGING', 'UNKNOWN', 'FAULT']
    source: Literal['charger', 'bms', 'unknown']
    pack_voltage_v: Positive | None
    pack_sample_at: Nonnegative | None
    termination_sample_at: Nonnegative | None = None
    faults: list[Identifier] = Field(default_factory=list, max_length=32)

    @model_validator(mode='after')
    def consistent_termination(self):
        if self.pack_sample_at is not None and self.pack_sample_at > self.captured_at:
            raise ValueError('pack sample cannot follow snapshot')
        if self.termination_sample_at is not None and self.termination_sample_at > self.captured_at:
            raise ValueError('termination sample cannot follow snapshot')
        if self.termination == 'NORMAL' and (self.source == 'unknown' or self.charging
                                             or not self.load_present or self.faults
                                             or self.pack_voltage_v is None or self.pack_sample_at is None
                                             or self.termination_sample_at is None):
            raise ValueError('normal termination needs measured intact contact and pack evidence')
        return self


class BatteryEnergyEvidence(TimedEvidence):
    battery_id: Identifier
    source: Literal['bms', 'fuel_gauge', 'bench', 'voltage_only', 'unknown']
    capacity_revision: Identifier | None
    soc_percent: Percent | None
    soh_percent: Percent | None
    usable_energy_wh: Nonnegative | None
    temperature_c: Number | None
    fault: Identifier | None

    @model_validator(mode='after')
    def capacity_needs_measurement(self):
        measured = self.source in ('bms', 'fuel_gauge', 'bench')
        if (self.soh_percent is not None or self.usable_energy_wh is not None) and (
                not measured or self.capacity_revision is None):
            raise ValueError('capacity and SOH require measured provenance')
        return self


class ChargePolicyProfile(Contract):
    profile_id: Identifier
    revision: Identifier
    battery_id: Identifier
    reevaluate_interval_s: Positive
    return_soc_percent: Percent
    redeploy_soc_percent: Percent
    reserve_wh: Nonnegative
    max_work_s: Positive | None
    max_return_s: Positive | None
    conservative_profile_verified: bool
    min_temperature_c: Number
    max_temperature_c: Number
    min_soh_percent: Percent

    @model_validator(mode='after')
    def ordered_operating_limits(self):
        if self.redeploy_soc_percent <= self.return_soc_percent:
            raise ValueError('redeploy threshold must exceed return threshold')
        if self.max_temperature_c <= self.min_temperature_c:
            raise ValueError('temperature limits must be ordered')
        if self.conservative_profile_verified and (self.max_work_s is None or self.max_return_s is None):
            raise ValueError('conservative profile requires verified time bounds')
        return self


class ChargeDecision(Contract):
    decision: Literal['WORK_ALLOWED', 'RETURN_REQUIRED', 'WAIT', 'MAINTENANCE_HOLD']
    reason: Identifier
    profile_revision: Identifier
    capacity_revision: Identifier | None
    required_wh: Nonnegative | None = None


class ChargeSessionStatus(Contract):
    session_id: Identifier
    robot_id: Identifier
    station_id: Identifier
    battery_id: Identifier
    boot_id: Identifier
    pose_revision: Revision
    map_id: Identifier
    map_revision: Identifier
    state: Literal['RETURN_RESERVED', 'RETURNING', 'DOCKING', 'CHARGE_CONFIRMING',
                   'CHARGING', 'CHARGED_HOLD', 'DEPARTURE_CHECK', 'UNDOCKING',
                   'WORK_AVAILABLE', 'HOLD', 'CANCELED']
    attempt_id: Identifier
    operation_id: Identifier | None = None
    reason: Identifier
    updated_at: Nonnegative


class StationMotionCommand(Contract):
    session_id: Identifier
    correlation_id: Identifier
    expected_boot_id: Identifier
    expected_owner_generation: Annotated[int, Field(strict=True, ge=0)]


class StationTargetBinding(Contract):
    session: ChargeSessionStatus
    target: StationPoseRecord
    observation_scope: StationObservation
    expected_boot_id: Identifier
    expected_owner_generation: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode='after')
    def matching_scope(self):
        if self.expected_boot_id != self.session.boot_id:
            raise ValueError('binding boot must match session')
        for item, keys in ((self.target, ('station_id', 'map_id', 'map_revision', 'pose_revision')),
                           (self.observation_scope, ('robot_id', 'station_id', 'session_id', 'boot_id',
                                                     'map_id', 'map_revision', 'pose_revision'))):
            if any(getattr(item, key) != getattr(self.session, key) for key in keys):
                raise ValueError('binding evidence must match session scope')
        if self.target.status != 'VALID':
            raise ValueError('binding requires valid installation')
        return self


class StationReturnPermit(TimedEvidence):
    robot_id: Identifier
    station_id: Identifier
    battery_id: Identifier
    session_id: Identifier
    boot_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    correlation_id: Identifier
    lease_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$')]
    trip_id: Identifier
    expected_owner_generation: Annotated[int, Field(strict=True, ge=0)]


class _DepartureScope(Contract):
    robot_id: Identifier
    station_id: Identifier
    session_id: Identifier
    attempt_id: Identifier
    boot_id: Identifier
    battery_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    correlation_id: Identifier
    work_task_id: Identifier
    work_request_digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]

    @model_validator(mode='after')
    def expected_departure_scope(self, info: ValidationInfo):
        context = info.context or {}
        if any(key in context and getattr(self, key) != context[key] for key in _DepartureScope.model_fields):
            raise ValueError('departure does not match expected session and work')
        return self


class StationDeparturePermit(TimedEvidence, _DepartureScope):
    expected_owner_generation: Annotated[int, Field(strict=True, ge=0)]
    policy_profile_revision: Identifier
    capacity_revision: Identifier | None


class StationDepartureReceipt(TimedEvidence, _DepartureScope):
    operation_id: Identifier
    owner_generation: Revision
    odom_epoch: Identifier
    departure_profile_revision: Identifier
    source_id: Identifier
    source_epoch: Identifier
    stopped_since: Nonnegative
    motion_sample_at: Nonnegative
    contact_sample_at: Nonnegative
    space_sample_at: Nonnegative
    isolation_sample_at: Nonnegative
    contact_released: Literal[True]
    power_isolated: Literal[True]
    route_clear: Literal[True]
    stopped: Literal[True]

    @field_validator('contact_released', 'power_isolated', 'route_clear', 'stopped', mode='before')
    @classmethod
    def exact_proof_flags(cls, value):
        if value is not True:
            raise ValueError('departure proof requires a JSON true flag')
        return value

    @model_validator(mode='after')
    def source_times(self):
        if (not self.stopped_since <= self.motion_sample_at <= self.captured_at
                or any(getattr(self, key) > self.captured_at for key in (
                    'contact_sample_at', 'space_sample_at', 'isolation_sample_at'))):
            raise ValueError('departure proof cannot precede its measurements')
        return self


class StationTargetStatus(TimedEvidence):
    state: Literal['UNBOUND', 'BOUND', 'RETURNING', 'DOCKING', 'SEATING', 'CHARGE_CONFIRMING', 'CHARGING',
                   'CHARGED_HOLD', 'DEPARTURE_CHECK', 'UNDOCKING', 'WORK_AVAILABLE', 'HOLD']
    reason: Identifier | None
    session_id: Identifier | None
    boot_id: Identifier | None
    battery_id: Identifier | None
    target: StationPoseRecord | None
    ack: StationPoseAck | None
    operation_id: Identifier | None
    correlation_id: Identifier | None
    binding_valid: bool
    seating_verified: bool
    charging_verified: bool
    completion_verified: bool
    return_permit: StationReturnPermit | None = None
    return_ready: bool = False
    departure_permit: StationDeparturePermit | None = None
    departure_receipt: StationDepartureReceipt | None = None

    @model_validator(mode='after')
    def verified_evidence_chain(self):
        if self.binding_valid:
            if (self.state in ('UNBOUND', 'HOLD') or not all((self.session_id, self.boot_id, self.battery_id))
                    or self.target is None or self.target.status != 'VALID'
                    or self.ack is None or not self.ack.accepted):
                raise ValueError('valid binding requires accepted scoped installation')
            for key in ('station_id', 'map_id', 'map_revision', 'pose_revision'):
                if getattr(self.target, key) != getattr(self.ack, key):
                    raise ValueError('binding acknowledgement must match installation')
            if self.ack.session_id != self.session_id or self.ack.boot_id != self.boot_id:
                raise ValueError('binding acknowledgement must match session')
            if not (self.target.captured_at <= self.captured_at < self.target.valid_until
                    and self.ack.captured_at <= self.captured_at < self.ack.valid_until
                    and self.valid_until <= min(self.target.valid_until, self.ack.valid_until)):
                raise ValueError('binding status cannot outlive its evidence')
        if self.seating_verified and not self.binding_valid:
            raise ValueError('seating requires live binding')
        if (self.charging_verified or self.completion_verified) and not self.seating_verified:
            raise ValueError('charging and completion require measured seating')
        if self.completion_verified and (self.state != 'CHARGED_HOLD' or self.charging_verified):
            raise ValueError('normal completion requires held, non-charging state')
        if self.return_ready:
            permit = self.return_permit
            if (not self.binding_valid or self.state != 'RETURNING' or permit is None
                    or permit.session_id != self.session_id or permit.boot_id != self.boot_id
                    or permit.battery_id != self.battery_id or permit.robot_id != self.ack.robot_id
                    or any(getattr(permit, key) != getattr(self.target, key) for key in (
                        'station_id', 'map_id', 'map_revision', 'pose_revision'))
                    or not permit.captured_at <= self.captured_at < self.valid_until <= permit.valid_until):
                raise ValueError('return readiness requires live scoped return permission')
        for evidence, states in ((self.departure_permit, ('UNDOCKING', 'DEPARTURE_CHECK')),
                                 (self.departure_receipt, ('WORK_AVAILABLE',))):
            if evidence is None:
                continue
            if (self.state not in states or self.seating_verified or self.charging_verified or self.completion_verified
                    or evidence.session_id != self.session_id or evidence.boot_id != self.boot_id
                    or evidence.battery_id != self.battery_id or evidence.correlation_id != self.correlation_id
                    or self.operation_id is None
                    or not evidence.captured_at <= self.captured_at < self.valid_until <= evidence.valid_until):
                raise ValueError('departure status requires live scoped evidence')
            if isinstance(evidence, StationDeparturePermit):
                if (not self.binding_valid or evidence.robot_id != self.ack.robot_id
                        or any(getattr(evidence, key) != getattr(self.target, key) for key in (
                            'station_id', 'map_id', 'map_revision', 'pose_revision'))):
                    raise ValueError('departure permission requires the current binding')
            elif evidence.operation_id != self.operation_id:
                raise ValueError('departure receipt requires the exact native operation')
        return self
