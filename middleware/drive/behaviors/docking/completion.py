"""Measured seating and charger termination gates, independent of charging-current windows."""
from __future__ import annotations

import math

from core_common.protocol.station_charging import ChargeCompletionEvidence, SeatingEvidence


def _positive_limits(values):
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
           for v in values):
        raise ValueError('MEASURED_OPERATING_LIMITS_REQUIRED')


class SeatingGate:
    def __init__(self, *, scope, position_tolerance_m, heading_tolerance_rad,
                 linear_limit_m_s, angular_limit_rad_s, still_s, debounce_s, sample_max_age_s):
        _positive_limits((position_tolerance_m, heading_tolerance_rad, linear_limit_m_s,
                          angular_limit_rad_s, still_s, debounce_s, sample_max_age_s))
        if set(scope) != {'robot_id', 'station_id', 'session_id', 'boot_id', 'pose_revision', 'odom_epoch'}:
            raise ValueError('SEATING_SCOPE_REQUIRED')
        self.scope = dict(scope)
        self.position_tolerance_m, self.heading_tolerance_rad = position_tolerance_m, heading_tolerance_rad
        self.linear_limit_m_s, self.angular_limit_rad_s = linear_limit_m_s, angular_limit_rad_s
        self.still_s, self.debounce_s, self.sample_max_age_s = still_s, debounce_s, sample_max_age_s
        self._since, self._proof_at, self._now = None, None, None

    def reset(self):
        self._since, self._proof_at, self._now = None, None, None

    def update(self, evidence: SeatingEvidence, *, now: float) -> bool:
        try:
            evidence = SeatingEvidence.model_validate(evidence.model_dump(), context=self.scope | {'now': now})
            proof_at = min(evidence.captured_at, evidence.motion_sample_at,
                           evidence.contact_sample_at, evidence.position_sample_at)
            if (self._now is not None and now < self._now
                    or now - proof_at > self.sample_max_age_s
                    or self._proof_at is not None and proof_at <= self._proof_at):
                self._since = None
                return False
            self._now = now
            if self._proof_at is not None and proof_at - self._proof_at > self.sample_max_age_s:
                self._since = None
            self._proof_at = proof_at
            if (not evidence.load_present or evidence.position_error_m > self.position_tolerance_m
                    or evidence.heading_error_rad > self.heading_tolerance_rad
                    or abs(evidence.measured_linear_m_s) > self.linear_limit_m_s
                    or abs(evidence.measured_angular_rad_s) > self.angular_limit_rad_s):
                self._since = None
                return False
            if self._since is None:
                self._since = proof_at
            return proof_at - self._since >= max(self.still_s, self.debounce_s)
        except (ValueError, TypeError):
            self._since = None
            return False


class ChargeCompletionTracker:
    def __init__(self, *, scope, session_started_at, min_full_voltage_v, max_voltage_v, pack_max_age_s):
        _positive_limits((min_full_voltage_v, max_voltage_v, pack_max_age_s))
        if min_full_voltage_v >= max_voltage_v:
            raise ValueError('PACK_VOLTAGE_LIMITS_UNORDERED')
        if set(scope) != {'station_id', 'robot_id', 'session_id', 'boot_id', 'battery_id'}:
            raise ValueError('CHARGE_COMPLETION_SCOPE_REQUIRED')
        self.scope = dict(scope)
        self.min_full_voltage_v, self.max_voltage_v = min_full_voltage_v, max_voltage_v
        self.pack_max_age_s = pack_max_age_s
        self.reset(scope['session_id'], session_started_at=session_started_at)

    def update(self, evidence: ChargeCompletionEvidence, *, now: float) -> bool:
        try:
            evidence = ChargeCompletionEvidence.model_validate(evidence.model_dump(), context=self.scope | {'now': now})
            return (evidence.termination == 'NORMAL' and evidence.source in ('charger', 'bms')
                    and evidence.pack_sample_at is not None and evidence.pack_voltage_v is not None
                    and evidence.termination_sample_at is not None
                    and evidence.termination_sample_at >= self.session_started_at
                    and now - evidence.pack_sample_at <= self.pack_max_age_s
                    and self.min_full_voltage_v <= evidence.pack_voltage_v <= self.max_voltage_v)
        except (ValueError, TypeError):
            return False

    def reset(self, session_id: str, *, session_started_at: float) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError('CHARGE_SESSION_REQUIRED')
        if (isinstance(session_started_at, bool) or not isinstance(session_started_at, (int, float))
                or not math.isfinite(session_started_at) or session_started_at < 0):
            raise ValueError('CHARGE_SESSION_START_TIME_REQUIRED')
        self.session_started_at = session_started_at
        self.scope = self.scope | {'session_id': session_id}
