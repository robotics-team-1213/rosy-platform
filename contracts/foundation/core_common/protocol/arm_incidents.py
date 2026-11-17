"""D-971: an OMX arm incident reported by its control PC, explained by the AI PC, cleared by a named operator.

Display and hold only: nothing here is a command. Measured facts are a bounded JSON object, frames are JPEG with a
sha256 the receiver recomputes."""
import base64
import binascii
import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SessionId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
SourceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
IncidentId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Text = Annotated[str, Field(min_length=1, max_length=400, pattern=r"^[^\x00-\x1f\x7f]+$")]
ARM_INCIDENT_FRAME_BYTES = 200_000            # one JPEG
ARM_INCIDENT_BODY_BYTES = 700_000             # report: two frames in base64 plus the facts
ARM_INCIDENT_JSON_BYTES = 12_288              # each of facts, decision, recovery


def _depth(value, level=0):
    if level > 6:
        raise ValueError("JSON nested too deep")
    for item in (value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()):
        _depth(item, level + 1)
    return value


def _bounded(value):
    try:
        text = json.dumps(_depth(value), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("a finite JSON object is required") from error
    if len(text.encode()) > ARM_INCIDENT_JSON_BYTES:
        raise ValueError("JSON object too large")
    return value


BoundedJson = Annotated[dict[str, Any], AfterValidator(_bounded)]


def _intact_jpeg(frame):
    try:
        data = base64.b64decode(frame.jpeg_b64, validate=True)
    except binascii.Error as error:
        raise ValueError("frame is not base64") from error
    if len(data) > ARM_INCIDENT_FRAME_BYTES or data[:2] != b"\xff\xd8":
        raise ValueError("frame is not a JPEG within the size limit")
    if hashlib.sha256(data).hexdigest() != frame.sha256:
        raise ValueError("frame sha256 differs")
    return frame


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ArmIncidentFrame(_Strict):
    role: Literal["top", "side"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    jpeg_b64: Annotated[str, Field(min_length=8, max_length=ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 8)]

    @model_validator(mode="after")
    def intact_jpeg(self):
        return _intact_jpeg(self)


class ArmIncidentReport(_Strict):
    source_id: SourceId
    session_id: SessionId
    facts: BoundedJson        # latched motors with hw_error and bits, torque_after, folded, windup hits, runner rows
    decision: BoundedJson     # the measurement decision (hold, reason, offered actions)
    recovery: BoundedJson | None = None  # the device's own safety reboot result, registers before and after
    frames: Annotated[list[ArmIncidentFrame], Field(max_length=2)] = []

    @model_validator(mode="after")
    def one_frame_per_role(self):
        UUID(self.session_id)
        if len({f.role for f in self.frames}) != len(self.frames):
            raise ValueError("one frame per role")
        return self


class ArmIncidentHold(_Strict):
    held: bool
    incident_ids: Annotated[list[IncidentId], Field(max_length=64)]
    reason: Text | None = None


class ArmIncidentAccepted(_Strict):
    incident_id: IncidentId
    hold: ArmIncidentHold


class ArmIncidentExplanation(_Strict):
    seen: Text
    suspected_cause: Text
    model: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@/-]+$")]


#: what stopped the arm, as the cell names it (cell_why's causes and the kinds of stop); and how the person knows it.
#: 2026-11-07: people, models and frame strips all misread contact while measurement and repeats decided, so a cause
#: comes with its basis and only a repeat or a measurement is scored as truth.
CAUSES = ("blocked", "wrong_position", "snagged", "too_fast", "no_room", "software_or_config", "camera_or_map", "other",
          "unknown")
BASES = ("repeat", "measured", "seen", "unknown")
ARM_INCIDENT_EVIDENCE_FRAMES = 24             # per incident, beside the report's two stills


class ArmIncidentClear(_Strict):
    note: Text
    cause: Literal[CAUSES] | None = None
    basis: Literal[BASES] | None = None


class ArmIncidentEvidenceFrame(_Strict):
    """One frame of the seconds around a stop, sent after the report and on its own (each within the frame limit), so
    the report stays small and a dropped link loses a frame, not the incident."""
    camera: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    t_rel_s: Annotated[float, Field(ge=-30, le=30)]
    kind: Literal["full", "tip"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    jpeg_b64: Annotated[str, Field(min_length=8, max_length=ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 8)]

    @model_validator(mode="after")
    def intact_jpeg(self):
        return _intact_jpeg(self)


#: The guard's own bookkeeping stops (a deadline of its start-up crawl), not a load. 2026-11-09 02:21 both arms: a jog
#: sent before the guard switched to tracking crawled at 1 deg/s, tripped the deadline, and two folded, untouched arms
#: waited for a person. Only with the arm on its command (it followed; nothing pushed back) is such a stop released.
SOFTWARE_STOPS = ("alignment deadline exceeded",)
FOLLOWED_TICKS = 28                           # 2.5 deg: the guard's own alignment tolerance


def _ticks(text, name):
    import ast
    import re

    found = re.search(name + r"=(\{[^{}]*\})", text)
    try:
        value = ast.literal_eval(found.group(1)) if found else None
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, dict) and all(isinstance(v, (int, float)) for v in value.values()) else None


def software_stop(facts) -> str | None:
    """Why measured facts show a session ended by a software stop alone (folded, safe end, nothing latched or wound up,
    every joint on its command), or when baseline caps were verified restored after a transient teardown check.
    The control PC does not hold on it and Fleet's hold does not count it; the incident stays listed for a person."""
    if not isinstance(facts, dict) or facts.get("truncated") or facts.get("folded") is not True \
            or facts.get("latched") or facts.get("windup_hits"):
        return None
    flagged = facts.get("flagged")
    if (not flagged and facts.get("caps_verified_restored") is True
            and isinstance(facts.get("torque_after"), dict) and facts["torque_after"]
            and all(isinstance(v, int) and not isinstance(v, bool) and v == 0
                    for v in facts["torque_after"].values())):
        return "baseline caps confirmed restored on folded torque-OFF bus; nothing physical held it"
    if facts.get("safe_end") is not True or not flagged or not isinstance(flagged, list):
        return None
    for row in flagged:
        text = str((row or {}).get("error") or (row or {}).get("fault") or "") if isinstance(row, dict) else ""
        stop = next((s for s in SOFTWARE_STOPS if s in text), None)
        current, command = _ticks(text, "current"), _ticks(text, "command")
        if row.get("caught") or not text.startswith("session ended:") or stop is None or not current or not command \
                or set(current) != set(command) or any(abs(current[n] - command[n]) > FOLLOWED_TICKS for n in current):
            return None
    return f"software stop ({stop}) with the arm folded on its command; nothing physical held it"


#: D-1039: the one flagged runner row a machine may clear: the guard's strain stop while parking (a joint lagged its
#: command; the arm then folded home with torque OFF). Not the jaws stopping short in park, which is something held.
PARK_STRAIN = r"^(?:runner: )?contact in park: [a-z_]+ lag rose to [0-9.]+ units at PWM -?[0-9]+ of [0-9]+"


def _park_strain(row) -> bool:
    import re

    if not isinstance(row, dict) or row.get("caught") or row.get("person_needed"):
        return False
    texts = [str(row.get(k) or "") for k in ("error", "fault")]
    return (re.match(PARK_STRAIN, texts[0] or texts[1]) is not None
            and not any(word in t for t in texts for word in ("pushing", "session ended", "caught")))


def machine_clearable(facts) -> tuple[bool, str]:
    """D-1039: may an AI assessor service clear this incident without a person? Default deny on the stored measured
    facts, never looser than the cell's own rule (omx_incident.decide: a latch, a wind-up, a flagged runner row or an
    unsafe end holds): the keys must be there with their types, the arm folded at a safe end with torque confirmed OFF
    on every motor and caps confirmed restored, and nothing latched, wound up, stopped on contact or recorded as a
    motor fault. Flagged runner rows only when every one is a PARK_STRAIN stop. A truncated report lacks the lists
    and stays with a person."""
    if not isinstance(facts, dict):
        return False, "facts unreadable"
    torque, latched, windup, flagged = (facts.get(k) for k in ("torque_after", "latched", "windup_hits", "flagged"))
    if not (isinstance(torque, dict) and isinstance(latched, dict) and isinstance(windup, list)
            and isinstance(flagged, list)):
        return False, "facts incomplete (torque_after, latched, windup_hits, flagged)"
    if facts.get("safe_end") is not True or facts.get("folded") is not True:
        return False, "arm not at a safe end folded at home"
    if not torque or not all(isinstance(v, int) and not isinstance(v, bool) and v == 0 for v in torque.values()):
        return False, "torque not confirmed OFF"
    if facts.get("caps_restored") is not True:
        return False, "caps not confirmed restored"
    if latched:
        return False, "latched hardware error"
    if windup:
        return False, "wind-up or snag hit"
    if not all(_park_strain(r) for r in flagged):
        return False, "runner flagged the session for a person"
    for key, why in (("stops", "guard contact stop"), ("fault_records", "motor fault record")):
        value = facts.get(key)
        if value is not None and (not isinstance(value, list) or value):
            return False, why
    return True, (("park strain stop, then " if flagged else "")
                  + "folded safe end, torque OFF, caps restored, nothing latched, wound up or stopped")
