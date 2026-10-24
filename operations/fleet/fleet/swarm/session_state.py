"""Formation session states and operator-selected loss policy."""

from enum import Enum


class SessionState(str, Enum):
    IDLE = "IDLE"
    ARMING = "ARMING"
    RUNNING = "RUNNING"
    HOLDING = "HOLDING"
    STOPPED = "STOPPED"


class HoldPolicy(str, Enum):
    HOLD = "HOLD"      # 릴레이 pause + 리더 navigation/cancel. 팔로워 follow 세션은 산다.
    ABORT = "ABORT"    # 전 팔로워 swarm/cancel + 리더 navigation/cancel. 세션 종료.
