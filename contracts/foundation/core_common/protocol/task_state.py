"""Fleet task lifecycle, canonically re-exported by schemas."""
import enum


class FleetTaskStatus(str, enum.Enum):
    """Site Fleet task lifecycle; separate from a robot command ACK."""

    REQUESTED = "REQUESTED"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    HOLD = "HOLD"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
