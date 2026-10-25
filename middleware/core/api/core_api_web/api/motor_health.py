"""Configured native-owner evidence; never opens a device or accepts caller paths."""
import os

from core_common.motor_health import read_motor_health_snapshot
from core_common.protocol.motor_health import MotorHealthResponse


def read_motor_health(*, now=None):
    unavailable = lambda: MotorHealthResponse(evidence='unavailable', status='unavailable',
                                               support_reason='No verified motor telemetry available')
    source, owner = os.environ.get('ROSY_MOTOR_HEALTH_FILE'), os.environ.get('ROSY_MOTOR_HEALTH_OWNER')
    if not source or not owner:
        return unavailable()
    try:
        result, _ = read_motor_health_snapshot(source, owner, now=now)
        session = os.environ.get('ROSY_MOTOR_HEALTH_SESSION')
        return unavailable() if session is not None and session != result.session_id else result
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return unavailable()
