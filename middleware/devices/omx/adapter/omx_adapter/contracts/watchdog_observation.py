"""Immutable scalar evidence; never participates in command or freshness decisions."""
from dataclasses import dataclass
import math


def _number(value):
    return value if type(value) in (int, float) and abs(value) <= 2**63 - 1 and math.isfinite(value) else None


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


@dataclass(frozen=True)
class JointIntakeObservation:
    stamp_ns: int | None
    source_now_ns: int | None
    received_at: float | None
    callback_entered_steady: float | None
    intake_received_steady: float | None
    intake_observed_steady: float | None
    accepted: bool | None
    intake_sequence: int | None
    rejection_code: str | None


def intake_observation(facts, *, callback_entered_steady, intake_observed_steady, intake_sequence):
    """Publish intake validation facts before waiting for owner delivery; no freshness credit."""
    if type(facts) is not dict:
        return None
    code = facts.get('rejection_code')
    codes = {'STAMP_REJECTED', 'SOURCE_STALE', 'ARRAY_SHAPE', 'NONFINITE', 'INPUT_INVALID'}
    return JointIntakeObservation(
        stamp_ns=_count(facts.get('stamp_ns')), source_now_ns=_count(facts.get('source_now_ns')),
        received_at=_number(facts.get('received_at')),
        callback_entered_steady=_number(callback_entered_steady),
        intake_received_steady=_number(facts.get('wall_received_at')),
        intake_observed_steady=_number(intake_observed_steady),
        accepted=facts.get('accepted') if type(facts.get('accepted')) is bool else None,
        intake_sequence=_count(intake_sequence),
        rejection_code=code if type(code) is str and code in codes else None)


@dataclass(frozen=True)
class WatchdogObservation:
    reason: str
    command_id: str | None
    command_id_truncated: bool
    owner_now: float | None
    steady_now: float | None
    joint_sequence: int | None
    joint_received_at: float | None
    source_age_s: float | None
    joint_wall: float | None
    active_started_at: float | None
    active_wall: float | None
    wall_now: float | None
    max_joint_state_age_s: float | None
    action_timeout_s: float | None
    wall_clock_bound_factor: float | None
    intake: JointIntakeObservation | None = None
    owner_now_steady_before: float | None = None
    owner_now_steady_after: float | None = None


def watchdog_observation(reason, command, snapshot, config, *, owner_now, steady_now,
                         joint_wall, active_started_at, active_wall, wall_now, intake=None,
                         owner_now_steady_before=None, owner_now_steady_after=None):
    """Copy fixed, allowlisted fields, without calling any owner/provider/transport."""
    command_id = command.command_id if type(command.command_id) is str else None
    sequence = None if snapshot is None else snapshot.sequence
    received = None if snapshot is None else snapshot.received_at
    return WatchdogObservation(
        reason=reason, command_id=None if command_id is None else command_id[:256],
        command_id_truncated=command_id is not None and len(command_id) > 256,
        owner_now=_number(owner_now), steady_now=_number(steady_now),
        joint_sequence=sequence if type(sequence) is int and 0 <= sequence <= 2**63 - 1 else None,
        joint_received_at=_number(received),
        source_age_s=None if received is None else _number(owner_now - received),
        joint_wall=_number(joint_wall), active_started_at=_number(active_started_at),
        active_wall=_number(active_wall), wall_now=_number(wall_now),
        max_joint_state_age_s=_number(config.max_joint_state_age_s),
        action_timeout_s=_number(config.action_timeout_s),
        wall_clock_bound_factor=_number(config.wall_clock_bound_factor),
        intake=intake if type(intake) is JointIntakeObservation else None,
        owner_now_steady_before=_number(owner_now_steady_before),
        owner_now_steady_after=_number(owner_now_steady_after))
