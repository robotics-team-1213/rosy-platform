"""Source-aged energy inputs for the existing pure charge policy; no health guesses."""
import math
import hashlib
import json
from types import MappingProxyType

from pydantic import TypeAdapter

from core_common.protocol.station_charging import (
    BatteryEnergyEvidence, ChargeDecision, ChargePolicyProfile, Identifier, Nonnegative,
    Revision, StationPoseRecord, TimedEvidence,
)
from rosy.execution.site.charge_policy import evaluate_charge_policy


class ChargeEnergyBudget(TimedEvidence):
    """Internal adapter estimate, pinned to installation, boot and approved cost model."""
    robot_id: Identifier
    boot_id: Identifier
    station_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    profile_revision: Identifier
    source_id: Identifier
    source_epoch: Identifier
    cost_revision: Identifier
    work_wh: Nonnegative | None
    return_wh: Nonnegative | None
    dock_wh: Nonnegative | None
    reserve_wh: Nonnegative
    work_duration_s: Nonnegative | None
    return_duration_s: Nonnegative | None
    work_task_id: Identifier | None
    work_request_digest: Identifier | None


def work_request_digest(task):
    """The estimator binds the immutable selected work, not a robot-wide Wh guess."""
    body = {key: task[key] for key in ('task_id', 'robot_id', 'task_type', 'request')}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


class ChargePolicyAdmission:
    def __init__(self, *, profiles, clock, budget_source, max_age_s):
        if (type(max_age_s) not in (int, float) or not math.isfinite(max_age_s) or max_age_s <= 0
                or not isinstance(budget_source, tuple) or len(budget_source) != 3
                or any(not isinstance(value, str) or not value for value in budget_source)):
            raise ValueError('CHARGE_POLICY_SOURCE_PROFILE_REQUIRED')
        self.profiles = MappingProxyType({robot: ChargePolicyProfile.model_validate(value.model_dump())
                                         for robot, value in profiles.items()})
        self.clock, self.budget_source, self.max_age_s = clock, budget_source, max_age_s

    def __call__(self, snapshot, target, *, departing_charge=False):
        profile = self.profiles[snapshot['robot_id']]
        try:
            now = self.clock()
            captured, expiry = snapshot['captured_at'], snapshot['valid_until']
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (now, captured, expiry)) or not captured <= now < expiry
                    or now-captured > self.max_age_s or snapshot['battery_id'] != profile.battery_id):
                raise ValueError('snapshot is not original live source evidence')
            target = StationPoseRecord.model_validate(target.model_dump(), context={'now': now,
                'map_id': snapshot['map_id'], 'map_revision': snapshot['map_revision']})
            battery = BatteryEnergyEvidence.model_validate(snapshot['battery_energy'],
                context={'now': now, 'battery_id': profile.battery_id})
            budget = ChargeEnergyBudget.model_validate(snapshot['charge_budget'], context={'now': now,
                'robot_id': snapshot['robot_id'], 'boot_id': snapshot['boot_id'],
                **{key: getattr(target, key) for key in ('station_id', 'map_id', 'map_revision', 'pose_revision')}})
            if (budget.profile_revision != profile.revision
                    or (budget.source_id, budget.source_epoch, budget.cost_revision) != self.budget_source
                    or now-battery.captured_at > self.max_age_s or now-budget.captured_at > self.max_age_s):
                raise ValueError('unapproved or aged energy source')
            return evaluate_charge_policy(battery, profile, now=now,
                **{key: getattr(budget, key) for key in ('work_wh', 'return_wh', 'dock_wh', 'reserve_wh',
                    'work_duration_s', 'return_duration_s')},
                dock_valid=target.status == 'VALID' and target.approach_verified,
                departing_charge=departing_charge)
        except (KeyError, TypeError, ValueError, AttributeError):
            return ChargeDecision(decision='WAIT', reason='CHARGE_POLICY_INPUT_UNVERIFIED',
                                  profile_revision=profile.revision, capacity_revision=None)


class MeasuredChargePolicyAdmission(ChargePolicyAdmission):
    """Operational health policy over authenticated snapshots, never source attestation.

    Installation pins each robot's measured source kind and accepted capacity
    revision. Actual readers, calibration acceptance and CORE admission remain
    separate requirements; these bindings cannot turn voltage into energy.
    """
    def __init__(self, *, measured_sources, **kwargs):
        super().__init__(**kwargs)
        try:
            if type(measured_sources) is not dict or set(measured_sources) != set(self.profiles):
                raise ValueError('source bindings must match installed robots')
            identifier = TypeAdapter(Identifier)
            bindings = {}
            for robot, binding in measured_sources.items():
                if (type(binding) is not tuple or len(binding) != 2
                        or binding[0] not in ('bms', 'fuel_gauge', 'bench')):
                    raise ValueError('measured source and capacity required')
                bindings[robot] = (binding[0], identifier.validate_python(binding[1], strict=True))
            self.measured_sources = MappingProxyType(bindings)
        except (TypeError, ValueError) as exc:
            raise ValueError('CHARGE_MEASURED_SOURCE_PROFILE_REQUIRED') from exc

    def __call__(self, snapshot, target, *, departing_charge=False):
        decision = super().__call__(snapshot, target, departing_charge=departing_charge)
        if decision.decision in ('WAIT', 'MAINTENANCE_HOLD'):
            return decision
        battery = snapshot['battery_energy']
        source, capacity = self.measured_sources[snapshot['robot_id']]
        if (battery['source'] != source or battery['capacity_revision'] != capacity
                or battery['soh_percent'] is None or battery['usable_energy_wh'] is None
                or battery['temperature_c'] is None):
            return ChargeDecision(decision='WAIT', reason='CHARGE_MEASURED_HEALTH_REQUIRED',
                                  profile_revision=decision.profile_revision, capacity_revision=None)
        return decision
