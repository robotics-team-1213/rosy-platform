"""Read-only power health contract. Hardware intent and physical evidence stay distinct."""
from typing import Literal, Optional

from pydantic import BaseModel

from .schemas import BatteryLevel, PowerMode, PowerStatus


class BatteryHealth(BaseModel):
    evidence: Literal['missing', 'fresh', 'stale']
    sample_age_s: Optional[float]
    stale_after_s: float
    level: BatteryLevel
    percent: Optional[float]
    filtered_voltage: Optional[float]
    charging_state: Literal['confirmed', 'unconfirmed']
    charging_evidence_age_s: Optional[float]
    charging_latched: bool
    shutdown_armed: bool
    shutdown_request_written: bool
    remaining_runtime_s: Optional[float]
    remaining_runtime_reason: str


class PowerPolicyHealth(BaseModel):
    sleep_blockers: list[str]
    deepest_available_mode: PowerMode
    deepest_mode_basis: Literal["policy_target"]
    battery_alert: str
    idle_after_s: float
    standby_after_s: float
    effective_idle_after_s: float
    effective_standby_after_s: float
    wake_sources: list[str]
    wake_sources_basis: Literal["policy_supported_not_hardware_verified"]
    api_wake_requires_running_os: bool
    os_halt_remote_wake: Literal['not_verified']
    lidar_standby_stop_enabled: bool
    lidar_state_basis: Literal['policy_intent']


class PowerHealthResponse(BaseModel):
    power: PowerStatus
    battery: BatteryHealth
    policy: PowerPolicyHealth
    recommendation: Literal['restore_battery_telemetry', 'charge_and_conserve', 'normal_idle_policy']
    health: dict[str, str]
