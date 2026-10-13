"""D-400: the policy answer contract and the one rule that validates it. ROS-free.

Lives beside ``manager.py`` for that file's size budget; ``manager`` re-exports every name here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core_features.safety.velocity import finite_velocity

#: Longest the in-process policy may take to answer one request, in seconds: one period of the
#: loop that asks. CORE's sole cmd_vel timer runs at 50 Hz (D-2; ``core.bridge.ros_bridge``,
#: ``create_timer(1.0 / 50.0, self._publish_cmd_vel)``, pinned by ``test_bridge_timers.py``) and an
#: answer must be applied to the tick it judged. It was a literal 10 ms, which is the D-400 6 G-sim
#: performance gate (eval_ms p99), not a safety bound. The age of the EVIDENCE is bounded
#: separately by the lease terms in ``decision_fault`` (D-400 revision 2026-10-14).
POLICY_ANSWER_BUDGET_S = 1.0 / 50.0


@dataclass(frozen=True)
class SafetyRequest:
    command_id: int
    source: str
    calibration_revision: str
    now: float
    linear: float
    angular: float


@dataclass(frozen=True)
class SafetyDecision:
    command_id: int
    source: str
    calibration_revision: str
    observed_at: float
    expires_at: float
    linear_limit: float
    angular_limit: float
    disposition: str = 'allow'
    reason: str = ''


_DISPOSITIONS = ('allow', 'limit', 'stop')


class PolicyObservationUnavailable(ValueError):
    """The policy has no current sensor evidence to answer with: a sensor gap (D-400 4)."""


def decision_fault(decision: object, request: SafetyRequest, elapsed: float) -> str:
    """'' when ``decision`` is a well-formed, current answer to ``request`` (any disposition).
    'timing' when it is well-formed and matches the request but came later than the answer budget
    or outside its evidence lease: the only fault that can be a sensor gap (D-400 4).
    'malformed' for everything else, a clock that is not finite or runs backwards included."""
    if (not isinstance(decision, SafetyDecision) or not math.isfinite(elapsed) or elapsed < 0
            or not math.isfinite(request.now)
            or type(decision.command_id) is not int or decision.command_id != request.command_id
            or not isinstance(decision.source, str) or decision.source != request.source
            or not isinstance(decision.calibration_revision, str)
            or decision.calibration_revision != request.calibration_revision
            or not finite_velocity(decision.observed_at, decision.expires_at)
            or not 0 < decision.expires_at - decision.observed_at <= .5
            or not finite_velocity(decision.linear_limit, decision.angular_limit)
            or min(decision.linear_limit, decision.angular_limit) < 0
            or not isinstance(decision.disposition, str) or decision.disposition not in _DISPOSITIONS
            or not isinstance(decision.reason, str) or len(decision.reason) > 128):
        return 'malformed'
    if (elapsed > POLICY_ANSWER_BUDGET_S
            or not decision.observed_at <= request.now <= request.now + elapsed <= decision.expires_at):
        return 'timing'
    return ''


def decision_valid(decision: object, request: SafetyRequest, elapsed: float) -> bool:
    """True when ``decision`` is a well-formed, current answer to ``request`` (any disposition)."""
    return not decision_fault(decision, request, elapsed)


def check_decision(decision: object, request: SafetyRequest, elapsed: float) -> str:
    """'' when ``decision`` is a valid, current answer to ``request`` that permits motion;
    otherwise the policy_reason CORE reports. One rule for enforce and shadow (D-400).
    A stop returns the policy's own reason (or 'policy_stop'); any validation failure returns
    'policy_invalid'. Callers that must tell stop from invalid read decision.disposition, not this string."""
    if not decision_valid(decision, request, elapsed):
        return 'policy_invalid'
    if decision.disposition == 'stop':
        return decision.reason or 'policy_stop'
    return ''
