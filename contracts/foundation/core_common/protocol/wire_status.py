"""Shared wire status enums (API Ref section 4)."""
import enum


class RobotMode(str, enum.Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    NAVIGATION = "NAVIGATION"
    DOCKING = "DOCKING"
    EMERGENCY = "EMERGENCY"


class NavigationState(str, enum.Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    NAVIGATING = "NAVIGATING"
    ARRIVED = "ARRIVED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class HealthState(str, enum.Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AckStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
