"""D-971: an OMX arm incident reported by its control PC, explained by the AI PC, cleared by a named operator.

Display and hold only: nothing here is a command. Measured facts are a bounded JSON object, frames are JPEG with a
sha256 the receiver recomputes."""
import base64
import binascii
import hashlib
import json
import re
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
#: command; the arm then folded home with torque OFF). The whole error must be exactly the runner's text
#: (deploy/robot/omx/chunk_runner_run.py: "contact in {chunk}: {motor} lag rose to {lag:.1f} units at PWM {pwm} of
#: {limit} (lags: {joint} {lag:.1f}, ...)"), nothing before or after it. Not the jaws stopping short in park.
_JOINT = r"(?:shoulder_pan|shoulder_lift|elbow_flex|wrist_flex|wrist_roll)"
_LAG = r"[0-9]{1,4}\.[0-9]"
PARK_STRAIN = re.compile(
    rf"(?:runner: )?contact in park: {_JOINT} lag rose to {_LAG} units at PWM -?[0-9]{{1,4}} of [0-9]{{1,4}}"
    rf" \(lags: (?:{_JOINT} {_LAG}(?:, {_JOINT} {_LAG}){{0,3}})?\)", re.ASCII)


def _park_strain(row) -> bool:
    """One flagged row of that stop as omx_incident.facts() keeps it (2026-11-17 arm_b, arm_s): the runner's "run park"
    row carries the text in both error and fault, and the "state" row after it in fault alone. Each set field is
    exactly the text; when both are set they are the same text; nothing caught, no person needed."""
    if (not isinstance(row, dict) or row.get("command") not in ("run park", "state") or row.get("caught")
            or row.get("person_needed")):
        return False
    texts = [row.get(k) for k in ("error", "fault") if row.get(k) not in (None, "")]
    if not texts or not all(isinstance(t, str) for t in texts):  # a list or dict here is unhashable: refuse, never 500
        return False
    return len(set(texts)) == 1 and all(PARK_STRAIN.fullmatch(t) is not None for t in texts)


#: D-1047: the runner's exact text when a session ended on the bus link alone (2026-11-18 arm_s: a USB hiccup, EIO in
#: tcdrain, then every torque-off write "Port is in use"; guarded_device.torque_off). Whole-text match like PARK_STRAIN:
#: anything before, after or between the motor entries stays with a person.
_LINK_WRITE = (r"ConnectionError\(\"Failed to write 'Torque_Enable' on id_=1[1-6] with '0' after [0-9] tries\. "
               r"\[TxRxResult\] (?:Port is in use!|There is no status packet!)\"\)")
LINK_END = re.compile(rf"session ended: RuntimeError: torque OFF not confirmed: \[{_LINK_WRITE}(?:, {_LINK_WRITE}){{0,5}}\]",
                      re.ASCII)
LINK_FAULT = "(5, 'Input/output error')"  # motor-health thread, exactly as it records the read that failed
REST_TOL = 8.0  # units: torque OFF settles a folded arm a few units (11-18 arm_s elbow 55.9 for home 50)
STILL_TOL = 3.0  # units: the runner held its target (it was not moving) when the link went
STILL_COMMANDS = ("state", "tick", "start", "stop")  # runner rows of a standing arm; any other label fails closed


def _comm_end(row) -> bool:
    """One flagged row that is exactly the link-failure end; caught or person-needed rows never are."""
    if not isinstance(row, dict) or row.get("caught") or row.get("person_needed"):
        return False
    texts = [row.get(k) for k in ("error", "fault") if row.get(k) not in (None, "")]
    if not texts or not all(isinstance(t, str) for t in texts):
        return False
    return len(set(texts)) == 1 and LINK_END.fullmatch(texts[0]) is not None


def _rested(facts) -> bool:
    """Recomputed, not trusted: torque 0 on every motor, the runner standing still on its target when the link went
    (its last command not a move), and the body within REST_TOL of home."""
    last, home, target, command = (facts.get(k) for k in ("last_state", "home", "last_target", "last_command"))
    torque = facts.get("torque_after")
    if not (isinstance(torque, dict) and torque and all(type(v) is int and v == 0 for v in torque.values())):
        return False
    rows = (last, home, target)
    if not all(isinstance(r, list) and len(r) >= 6 and all(type(v) in (int, float) for v in r[:6]) for r in rows):
        return False
    # a link failure mid-move is written as "run <chunk>" (chunk_runner_settle.tick_or_report) while the last state row
    # is still the one before the move: the last command and every flagged row must be a standing-arm label
    flagged = facts.get("flagged") if isinstance(facts.get("flagged"), list) else []
    if command not in STILL_COMMANDS or not all(isinstance(r, dict) and r.get("command") in STILL_COMMANDS for r in flagged):
        return False
    return (all(abs(a - b) <= STILL_TOL for a, b in zip(last[:5], target[:5]))
            and all(abs(a - b) <= REST_TOL for a, b in zip(last[:5], home[:5])))


def _link_faults_only(records, kinds) -> bool:
    """D-1047: every motor-health fault record of the session is exactly the health thread's EIO with no stop reason;
    the cell lists each record's fault and stop_reasons beside its path (omx_incident.facts)."""
    if not isinstance(kinds, list) or len(kinds) != len(records):
        return False
    return all(isinstance(k, dict) and k.get("fault") == LINK_FAULT and k.get("stop_reasons") == [] for k in kinds)


def machine_clearable(facts) -> tuple[bool, str]:
    """D-1039: may an AI assessor service clear this incident without a person? Default deny on the stored measured
    facts, never looser than the cell's own rule (omx_incident.decide: a latch, a wind-up, a flagged runner row or an
    unsafe end holds): the keys must be there with their types, the arm folded at a safe end with torque confirmed OFF
    on every motor and caps confirmed restored, and nothing latched, wound up, stopped on contact or recorded as a
    motor fault. Flagged runner rows only when every one is exactly a PARK_STRAIN stop (_park_strain). A truncated
    report lacks the lists and stays with a person."""
    if not isinstance(facts, dict):
        return False, "facts unreadable"
    torque, latched, windup, flagged, stops, faults = (facts.get(k) for k in (
        "torque_after", "latched", "windup_hits", "flagged", "stops", "fault_records"))
    if not (isinstance(torque, dict) and isinstance(latched, dict)
            and all(isinstance(v, list) for v in (windup, flagged, stops, faults))):
        return False, "facts incomplete (torque_after, latched, windup_hits, flagged, stops, fault_records)"
    # D-1047: a link-failure end alone may stand on a rested arm (recomputed here from last_state, last_target, home);
    # every other kind still needs folded (HOME_TOL). Truncated lists never qualify for it.
    link = (bool(flagged) and all(_comm_end(r) for r in flagged)
            and facts.get("flagged_total") == len(flagged) and facts.get("fault_records_total") == len(faults))
    if facts.get("safe_end") is not True or (facts.get("folded") is not True and not (link and _rested(facts))):
        return False, "arm not at a safe end folded at home"
    if not torque or not all(isinstance(v, int) and not isinstance(v, bool) and v == 0 for v in torque.values()):
        return False, "torque not confirmed OFF"
    if facts.get("caps_restored") is not True:
        return False, "caps not confirmed restored"
    if latched:
        return False, "latched hardware error"
    if windup:
        return False, "wind-up or snag hit"
    if not (link or all(_park_strain(r) for r in flagged)):
        return False, "runner flagged the session for a person"
    if stops:
        return False, "guard contact stop"
    if faults and not (link and _link_faults_only(faults, facts.get("fault_record_kinds"))):
        return False, "motor fault record"
    kind = "bus link failure, then " if link else "park strain stop, then " if flagged else ""
    return True, (kind + ("folded" if facts.get("folded") is True else "rested near home")
                  + " safe end, torque OFF, caps restored, nothing latched, wound up or stopped")
