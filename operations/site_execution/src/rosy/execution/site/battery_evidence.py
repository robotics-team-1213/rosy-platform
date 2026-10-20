"""Adapt legacy power readback without inferring SOH, capacity or temperature."""
from __future__ import annotations

import math
from collections.abc import Mapping

from core_common.protocol.station_charging import BatteryEnergyEvidence


def battery_evidence_from_health(health: Mapping, *, battery_id: str, now: float,
                                 max_age_s: float) -> BatteryEnergyEvidence:
    if (isinstance(now, bool) or not math.isfinite(now) or now < 0
            or isinstance(max_age_s, bool) or not math.isfinite(max_age_s) or max_age_s <= 0):
        raise ValueError('BATTERY_EVIDENCE_CLOCK_REQUIRED')
    age = health.get('sample_age_s')
    has_sample = (health.get('evidence') in ('fresh', 'stale') and not isinstance(age, bool)
                  and isinstance(age, (int, float)) and math.isfinite(age) and 0 <= age <= now)
    return BatteryEnergyEvidence(
        battery_id=battery_id, captured_at=now - age if has_sample else now,
        valid_until=now - age + max_age_s if has_sample else now + max_age_s,
        source='voltage_only' if has_sample else 'unknown', capacity_revision=None,
        soc_percent=health.get('percent') if has_sample else None,
        soh_percent=None, usable_energy_wh=None, temperature_c=None,
        fault=None if has_sample else 'BATTERY_TELEMETRY_MISSING')
