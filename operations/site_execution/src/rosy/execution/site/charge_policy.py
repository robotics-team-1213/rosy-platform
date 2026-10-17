"""Pure energy admission; decisions carry no dispatch authority or battery-health guesses."""
from __future__ import annotations

import math

from core_common.protocol.station_charging import BatteryEnergyEvidence, ChargeDecision, ChargePolicyProfile


def _nonnegative(value):
    return (not isinstance(value, bool) and isinstance(value, (float, int))
            and math.isfinite(value) and value >= 0)


def evaluate_charge_policy(battery: BatteryEnergyEvidence, profile: ChargePolicyProfile, *,
                           now: float, work_wh: float | None, return_wh: float | None,
                           dock_wh: float | None, reserve_wh: float, dock_valid: bool,
                           work_duration_s: float | None = None, return_duration_s: float | None = None,
                           departing_charge: bool = False) -> ChargeDecision:
    """Fallback return_duration_s includes queue, docking and retries within its verified envelope."""
    def decision(kind, reason, required=None):
        return ChargeDecision(decision=kind, reason=reason, profile_revision=profile.revision,
                              capacity_revision=battery.capacity_revision, required_wh=required)

    try:
        battery = BatteryEnergyEvidence.model_validate(battery.model_dump(), context={
            'now': now, 'battery_id': profile.battery_id})
    except ValueError:
        return decision('WAIT', 'BATTERY_EVIDENCE_UNUSABLE')
    if battery.source == 'unknown':
        return decision('WAIT', 'BATTERY_NOT_MEASURED')
    if battery.fault is not None:
        return decision('MAINTENANCE_HOLD', 'BATTERY_FAULT')
    if battery.temperature_c is None:
        return decision('WAIT', 'TEMPERATURE_NOT_MEASURED')
    if not profile.min_temperature_c <= battery.temperature_c <= profile.max_temperature_c:
        return decision('MAINTENANCE_HOLD', 'BATTERY_TEMPERATURE_OUTSIDE_PROFILE')
    if battery.soh_percent is not None and battery.soh_percent < profile.min_soh_percent:
        return decision('MAINTENANCE_HOLD', 'BATTERY_HEALTH_BELOW_PROFILE')
    if dock_valid is not True:
        return decision('WAIT', 'NO_VERIFIED_STATION')
    if not _nonnegative(reserve_wh):
        return decision('WAIT', 'INVALID_ENERGY_RESERVE')
    low = battery.soc_percent is not None and battery.soc_percent <= profile.return_soc_percent
    if battery.usable_energy_wh is None:
        if not profile.conservative_profile_verified:
            return decision('WAIT', 'CAPACITY_NOT_MEASURED')
        if (not _nonnegative(return_duration_s) or return_duration_s > profile.max_return_s):
            return decision('WAIT', 'RETURN_TIME_NOT_VERIFIED')
        if low:
            return decision('RETURN_REQUIRED', 'CONSERVATIVE_LOW_SOC_RETURN')
        if (not _nonnegative(work_duration_s) or work_duration_s > profile.max_work_s
                or battery.soc_percent is None or battery.soc_percent < profile.redeploy_soc_percent):
            return decision('WAIT', 'CONSERVATIVE_WORK_NOT_VERIFIED')
        return decision('WORK_ALLOWED', 'VERIFIED_CONSERVATIVE_TIME_PROFILE')
    if any(not _nonnegative(value) for value in (return_wh, dock_wh)):
        return decision('WAIT', 'RETURN_COST_NOT_VERIFIED')
    return_budget = return_wh + dock_wh + max(reserve_wh, profile.reserve_wh)
    if not math.isfinite(return_budget):
        return decision('WAIT', 'ENERGY_BUDGET_OVERFLOW')
    if battery.usable_energy_wh < return_budget:
        return decision('MAINTENANCE_HOLD', 'INSUFFICIENT_RETURN_RESERVE', return_budget)
    if low:
        return decision('RETURN_REQUIRED', 'LOW_SOC_RETURN', return_budget)
    if departing_charge and (battery.soc_percent is None or battery.soc_percent < profile.redeploy_soc_percent):
        return decision('WAIT', 'CHARGE_TARGET_NOT_REACHED')
    if not _nonnegative(work_wh):
        return decision('WAIT', 'WORK_COST_NOT_VERIFIED')
    required = work_wh + return_budget
    if not math.isfinite(required):
        return decision('WAIT', 'ENERGY_BUDGET_OVERFLOW')
    if battery.usable_energy_wh < required:
        return decision('RETURN_REQUIRED', 'WORK_WOULD_CONSUME_RETURN_RESERVE', required)
    return decision('WORK_ALLOWED', 'ENERGY_BUDGET_VERIFIED', required)
