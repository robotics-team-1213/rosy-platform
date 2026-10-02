"""D-411 A: Pilot robot recording contract. ROS-free; shared by the camera-unit
recorder (control), CORE (core_common.domain, core_api_web) and the PC fetch tool.

Recording is evidence only: nothing on the control path reads these topics (D-2, D-209).
"""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PILOT_RECORDING_ROOT = "/var/lib/rosy/pilot-recordings"
MAX_DURATION_S = 600
TELEOP_INTENT_TOPIC = "teleop/intent"
SET_ACTIVE_SERVICE = "pilot_recorder/set_active"
STATUS_TOPIC = "pilot_recorder/status"
ACTIVE_TOPIC = "pilot_recorder/active"
FETCHED_TOPIC = "pilot_recorder/fetched"
INTENT_SCHEMA = "rosy.teleop.intent/1"
STATUS_SCHEMA = "rosy.pilot.recording.status/1"
MANIFEST_SCHEMA = "rosy.pilot.recording.manifest/1"
MANIFEST_NAME = "manifest.json"
SESSION_NAME = "session.json"
FETCHED_NAME = "fetched.json"
RECORDING_ID = re.compile(r"\d{8}T\d{6}Z_[A-Za-z0-9_.-]{1,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def recording_id_ok(value: object) -> bool:
    return isinstance(value, str) and RECORDING_ID.fullmatch(value) is not None \
        and not value.endswith("_")


def safe_member(path: object) -> bool:
    """A manifest path that may become a tar member: relative POSIX, no '.', '..' or empty part."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path or path.startswith("/"):
        return False
    raw_parts = path.split("/")
    return all(part not in ("", ".", "..") for part in raw_parts) \
        and PurePosixPath(path).as_posix() == path


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


class TeleopIntent(_Wire):
    schema_id: Literal["rosy.teleop.intent/1"] = Field(INTENT_SCHEMA, alias="schema")
    raw_linear: float | None
    raw_angular: float | None
    linear: float | None
    angular: float | None
    source: str = Field(min_length=1, max_length=32)
    mode: str = Field(min_length=1, max_length=32)
    accepted: bool
    code: str = Field(max_length=64)
    t_mono_ns: int = Field(ge=0)

    @model_validator(mode="after")
    def clipped_iff_accepted(self) -> "TeleopIntent":
        has_clip = self.linear is not None and self.angular is not None
        if self.accepted != has_clip or (self.accepted and self.code):
            raise ValueError("an accepted intent carries clipped values and no code")
        return self


def teleop_intent(*, raw_linear, raw_angular, clipped, source, mode, accepted, code, t_mono_ns) -> dict:
    linear, angular = (None, None) if clipped is None else (_finite(clipped[0]), _finite(clipped[1]))
    return TeleopIntent(raw_linear=_finite(raw_linear), raw_angular=_finite(raw_angular),
                        linear=linear, angular=angular, source=source, mode=mode,
                        accepted=bool(accepted), code=code or "", t_mono_ns=int(t_mono_ns),
                        ).model_dump(by_alias=True)


#: A session exists in these states. `starting`: rosbag2 runs but has not opened its first
#: file yet (CLI start + discovery take seconds); nothing is recorded until `recording`.
ACTIVE_STATES = ("starting", "recording", "stopping")


class RecorderStatus(_Wire):
    schema_id: Literal["rosy.pilot.recording.status/1"] = Field(STATUS_SCHEMA, alias="schema")
    state: Literal["idle", "starting", "recording", "stopping", "error"]
    id: str | None = None
    elapsed_s: float = Field(ge=0)
    bytes: int = Field(ge=0)
    max_duration_s: int = Field(gt=0, le=MAX_DURATION_S)
    quota_free_bytes: int = Field(ge=0)
    last_stop_reason: str = Field("", max_length=64)
    # Per recorder boot, seq grows with every status it builds, so CORE can drop one that
    # arrives after a newer one it already adopted. 0 / "" means unsequenced.
    boot_id: str = Field("", max_length=64)
    seq: int = Field(0, ge=0)

    @model_validator(mode="after")
    def id_when_active(self) -> "RecorderStatus":
        if self.state in ACTIVE_STATES and not recording_id_ok(self.id):
            raise ValueError("an active recording names its id")
        return self


class ManifestFile(_Wire):
    path: str
    bytes: int = Field(ge=0)
    sha256: str

    @field_validator("path")
    @classmethod
    def _safe(cls, value: str) -> str:
        if not safe_member(value) or value in (MANIFEST_NAME, FETCHED_NAME):
            raise ValueError("unsafe or reserved manifest path")
        return value

    @field_validator("sha256")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex")
        return value


class RecordingManifest(_Wire):
    schema_id: Literal["rosy.pilot.recording.manifest/1"] = Field(MANIFEST_SCHEMA, alias="schema")
    id: str
    started_at: str
    ended_at: str
    duration_s: float = Field(ge=0)
    topics: tuple[str, ...]
    stop_reason: str = Field(max_length=64)
    files: tuple[ManifestFile, ...] = Field(min_length=1)
    # How rosbag2 ended: its exit status (None when unknown, e.g. a crash recovery) and
    # whether it had to be killed (its last split file may then be unindexed).
    bag_returncode: int | None = None
    writer_killed: bool = Field(False, strict=True)

    @model_validator(mode="after")
    def _identity(self) -> "RecordingManifest":
        if not recording_id_ok(self.id):
            raise ValueError("invalid recording id")
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate manifest path")
        return self


class RecordingSummary(_Wire):
    id: str
    started_at: str
    ended_at: str | None
    duration_s: float | None
    bytes: int = Field(ge=0)
    topics: tuple[str, ...]
    status: Literal["recording", "complete", "incomplete"]
    manifest_sha256: str | None
    fetched: bool
