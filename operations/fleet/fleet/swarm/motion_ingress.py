"""Fleet-issued CORE requests that can start or sustain base motion."""

PREPARED_GOALS = frozenset({
    "/api/v1/navigation/bound-goal",
    "/api/v1/navigation/line-handoff-goal",
})

# D-1079: only these navigation starts have a CORE admission deadline. Planning never starts motion.
ADMIT_DEADLINE_PATHS = PREPARED_GOALS | frozenset({
    "/api/v1/navigation/goal", "/api/v1/navigation/home", "/api/v1/navigation/route",
    "/api/v1/navigation/bound-route",
})
MOTION_TIMEOUT_S = 5.0
# Leave 2 s of the existing 5 s transport budget for the reply; reject queued starts after 3 s.
MOTION_ADMIT_WITHIN_S = 3.0
# shortcut: expiry starts at CORE route receipt, use generation fencing for delays before that point.
# 0.5 s is a design margin, not a field measurement (real hardware measurement required).
MOTION_RELEASE_MARGIN_S = 0.5

_MOTION = frozenset({
    "/api/v1/navigation/goal", "/api/v1/navigation/home", "/api/v1/navigation/route",
    "/api/v1/navigation/bound-route", "/api/v1/navigation/goal/lease",
    "/api/v1/swarm/follow", "/api/v1/motion/rotate_to", "/api/v1/motion/nudge", "/api/v1/motion/repark",
    "/api/v1/motion/repark/run", "/api/v1/localization/mission",
    "/api/v1/docking/dock", "/api/v1/docking/undock",
    "/api/v1/docking/station-dock", "/api/v1/docking/station-undock",
    "/api/v1/docking/station-departure", "/api/v1/docking/station-return",
    "/api/v1/line-follow/junction", "/api/v1/line-follow/authority", "/api/v1/line-follow/hold",
})


def starts_or_sustains_motion(method, path, body):
    if method.upper() not in {"POST", "PUT"}:
        return False
    body = body or {}
    if path == "/api/v1/line-follow/mode":
        return body.get("mode") != "OFF"
    if path == "/api/v1/mode":
        return body.get("mode") not in {"IDLE", "EMERGENCY"}
    if path == "/api/v1/teleop":
        return (body.get("linear"), body.get("angular")) != (0, 0)
    if path == "/api/v1/line-follow/stuck/decision":
        return body.get("decision") not in {"WAIT", "ABORT"}
    # An e-stop release is not here: CORE only moves EMERGENCY to IDLE (safety.py _release) and resumes nothing.
    return path in _MOTION
