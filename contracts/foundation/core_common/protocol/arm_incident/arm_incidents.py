"""Evidence rules for clearing OMX arm incidents (D-971)."""
import re

from .arm_incident_models import (  # noqa: F401  (public protocol exports)
    ARM_INCIDENT_BODY_BYTES, ARM_INCIDENT_EVIDENCE_FRAMES, ARM_INCIDENT_FRAME_BYTES, ARM_INCIDENT_JSON_BYTES,
    BASES, BODY_JOINTS, CAUSES, HELD_ROLES, MOTOR_IDS, ArmHeldVerdict, ArmIncidentAccepted, ArmIncidentClear,
    ArmIncidentEvidenceFrame, ArmIncidentExplanation, ArmIncidentFaultRecord, ArmIncidentFrame, ArmIncidentHold,
    ArmIncidentRemeasure, ArmIncidentRemeasureFrame, ArmIncidentReport, BoundedJson, IncidentId, MotorInts,
    SessionId, Sha, SourceId, Text,
)


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


def _runner_row(row, pattern, commands=None) -> bool:
    """One flagged row as omx_incident.facts() keeps it whose set error and fault are each exactly `pattern`'s text
    (the same text when both are set), with nothing caught and no person needed. `commands`: the rows it may be."""
    if (not isinstance(row, dict) or (commands is not None and row.get("command") not in commands) or row.get("caught")
            or row.get("person_needed")):
        return False
    texts = [row.get(k) for k in ("error", "fault") if row.get(k) not in (None, "")]
    if not texts or not all(isinstance(t, str) for t in texts):  # a list or dict here is unhashable: refuse, never 500
        return False
    return len(set(texts)) == 1 and all(pattern.fullmatch(t) is not None for t in texts)


def _park_strain(row) -> bool:
    """One flagged row of that stop (2026-11-17 arm_b, arm_s): the runner's "run park" row carries the text in both
    error and fault, and the "state" row after it in fault alone."""
    return _runner_row(row, PARK_STRAIN, ("run park", "state"))


#: D-1040: three kinds cleared only with a fresh motionless read (ArmIncidentRemeasure), each exact whole text from its
#: producer (guarded_device.py, joint_push.py, guarded_native_effort.py). Never the jaws' "something is in them".
_BUSY = (r"ConnectionError\(\"Failed to write 'Torque_Enable' on id_=1[1-6] with '0' after [0-9] tries\."
         r" \[TxRxResult\] Port is in use!\"\)")
TORQUE_UNCONFIRMED = re.compile(
    rf"(?:runner: )?session ended: RuntimeError: torque OFF not confirmed: \[{_BUSY}(?:, {_BUSY}){{0,5}}\]", re.ASCII)
WINDUP = re.compile(r"(?:shoulder_pan|shoulder_lift|elbow_flex|wrist_flex) still [0-9]{1,4}\.[0-9] units short, PWM "
                    r"winding up [0-9]{1,4} -> [0-9]{1,4} of [0-9]{1,4}: pushing against something", re.ASCII)
_STALE_T = r"(?:-?[0-9]+\.[0-9]|n/a)"
_STALE_CORE = rf"stale effort sample \(>0\.5 seconds\)(?:: tick_ms={_STALE_T} last_tick_ms={_STALE_T} last_effort_ms={_STALE_T} pwm_ms={_STALE_T} monitor_ms={_STALE_T})?"
STALE_EFFORT = re.compile(rf"(?:runner: )?session ended: ValueError: {_STALE_CORE}", re.ASCII)
STALE_EFFORT_FAULT_TEXT = re.compile(_STALE_CORE, re.ASCII)
STALE_EFFORT_FAULT = ("ValueError", "stale effort sample (>0.5 seconds)")
REMEASURE_MAX_AGE_S, REMEASURE_SKEW_S, REMEASURE_HOME_TOL = 900, 60, 3.0  # D-1040 freshness/skew/fold tolerances


def _list_complete(facts, total_key: str, items) -> bool:
    total = facts.get(total_key)
    return total is None or (type(total) is int and total == len(items))


def _stale_effort_kinds_ok(records, kinds) -> bool:
    return (isinstance(kinds, list) and len(kinds) == len(records)
            and all(isinstance(k, dict) and isinstance(k.get("fault"), str)
                    and STALE_EFFORT_FAULT_TEXT.fullmatch(k["fault"]) and k.get("stop_reasons") == [] for k in kinds))


def remeasure_kind(facts) -> str | None:
    """D-1040 kind requiring ArmIncidentRemeasure (port-busy torque OFF, body wind-up, or stale effort sample), else None."""
    windup, flagged, faults = facts.get("windup_hits"), facts.get("flagged"), facts.get("fault_records")
    if (facts.get("truncated")
            or not _list_complete(facts, "flagged_total", flagged or ())
            or not _list_complete(facts, "fault_records_total", faults or ())):
        return None
    if flagged and not windup and all(_runner_row(r, TORQUE_UNCONFIRMED) for r in flagged):
        return "torque OFF not confirmed (port in use)"
    if flagged and not windup and all(_runner_row(r, STALE_EFFORT) for r in flagged):
        return "stale effort sample"
    if windup and not flagged and all(isinstance(h, dict) and isinstance(h.get("reason"), str)
                                      and WINDUP.fullmatch(h["reason"]) for h in windup):
        return "wind-up before the end"
    return None


#: held_object: every flagged row is the runner's exact jaw text: grip stop-short rows (caught, reopened) and the park
#: row (error == fault, held). Nothing on the arm body, no person_needed row, no other row.
_JAW = r"the jaws stopped [0-9]{1,3}\.[0-9] units short at PWM -?[0-9]{1,4} of [0-9]{1,4}: something is in them"
JAW_GRIP = re.compile(rf"{_JAW}; reopened", re.ASCII)
JAW_PARK = re.compile(rf"(?:runner: )?contact in park: {_JAW}; held at gripper [0-9]{{1,3}}\.[0-9]", re.ASCII)
HELD_GAP = (50.8, 56.0)          # units: a 30 mm catalogue box across the jaws (shortcut: fixed, not per-cell config)
HELD_GAP_STABLE = 0.3            # units between the two reads


def _jaw_grip(row) -> bool:
    texts = isinstance(row, dict) and [row.get("error")]
    return bool(texts and row.get("command") == "grip" and row.get("caught") is True and not row.get("fault")
                and not row.get("person_needed") and isinstance(texts[0], str) and JAW_GRIP.fullmatch(texts[0]))


def held_facts(facts) -> bool:
    """Stored facts of a box stuck in the jaws: only jaw rows as above, at least one park row, the last row of park."""
    flagged = facts.get("flagged")
    if not flagged or facts.get("windup_hits") or facts.get("stops") or facts.get("fault_records") or facts.get("latched"):
        return False
    parks = [_runner_row(r, JAW_PARK, ("run park", "state")) for r in flagged]
    return all(g or p for g, p in zip((_jaw_grip(r) for r in flagged), parks)) and any(
        p and r.get("command") == "run park" for p, r in zip(parks, flagged)) and parks[-1]


def held_refused(remeasured, verdict, stills, since, now, *, incident_id=None, binding=None) -> str | None:
    """Why this read and verdict do not show one catalogue box in the jaws of a quiet folded arm, or None."""
    why = remeasure_refused(remeasured, since, now, incident_id=incident_id, binding=binding)
    if why:
        return why
    read = ArmIncidentRemeasure.model_validate(remeasured)
    if not (read.folded and read.max_home_err <= REMEASURE_HOME_TOL):
        return "not folded at home at the remeasure"
    if read.gripper_pos is None or read.first_gripper_pos is None or not HELD_GAP[0] < read.gripper_pos <= HELD_GAP[1] \
            or abs(read.gripper_pos - read.first_gripper_pos) > HELD_GAP_STABLE:
        return "jaw gap is not a steady catalogue box"
    shas = {f.role: f.sha256 for f in read.frames}
    if len(shas) != len(read.frames) or set(shas) != HELD_ROLES:
        return "the read needs one top and one wrist still"
    try:
        v = ArmHeldVerdict.model_validate(verdict)
    except (TypeError, ValueError):
        return "no valid picture verdict"
    if v.incident_id != incident_id or v.frame_sha256 != shas or not isinstance(stills, (set, frozenset)) \
            or not set(shas.values()) <= stills:
        return "verdict not of the stored stills of this incident"
    if not read.at <= v.evaluated_at <= now + REMEASURE_SKEW_S or now - v.evaluated_at > REMEASURE_MAX_AGE_S:
        return "verdict not fresh after the read"
    return None


#: the pyserial text of the port gone under the session (2026-11-17 arm_b's one fault record of that USB hub loss)
PORT_LOST_FAULT = ("SerialException", "device reports readiness to read but returned no data (device disconnected or "
                                      "multiple access on port?)")


SAG_MAX = 6.5                    # units: a torque-OFF rest pose may sag past REMEASURE_HOME_TOL (the torque-ON settle
SAG_JOINTS = ("shoulder_lift", "elbow_flex", "wrist_flex")  # tolerance) on the gravity-loaded joints only
SAG_STABLE = 0.3                 # units per joint between the two reads
SAG_GAP_S = 5.0                  # the two reads are at least this far apart


def sag_stable(read) -> bool:
    """Two whole reads at least SAG_GAP_S apart, each joint within SAG_STABLE of the other (a creep is not a rest)."""
    a, b = read.first_home_err, read.home_err
    return bool(a and b and set(a) == set(b) == set(BODY_JOINTS) and read.first_at is not None
                and read.at - read.first_at >= SAG_GAP_S and all(abs(a[j] - b[j]) <= SAG_STABLE for j in BODY_JOINTS))


def sag_ok(read) -> bool:
    """Torque-OFF rest sag, judged here from the per-joint errors: stable reads, torque 0, hardware error 0, pan and
    wrist_roll within the home tolerance, lift/elbow/wrist_flex within SAG_MAX. shortcut: the gravity direction is not
    established from data (only max errors were stored), so the sign is not checked; add it after a signed read."""
    if not sag_stable(read) or any(read.torque_after.values()) or any(read.hardware_error.values()):
        return False
    err = read.home_err
    return all(abs(err[j]) <= (SAG_MAX if j in SAG_JOINTS else REMEASURE_HOME_TOL) for j in BODY_JOINTS)


def classify(read, facts=None) -> str:
    """"machine_clearable" (folded within the settle tolerance), "sag_only" (the sag envelope) or "needs_person". `read`:
    an ArmIncidentRemeasure or its dict, `facts`: the incident facts when known (a latch or guard stop needs a person)."""
    try:
        read = ArmIncidentRemeasure.model_validate(read)
    except (TypeError, ValueError):
        return "needs_person"
    if isinstance(facts, dict) and (facts.get("latched") or facts.get("stops")):
        return "needs_person"
    if any(read.torque_after.values()) or any(read.hardware_error.values()):
        return "needs_person"
    if read.folded and read.max_home_err <= REMEASURE_HOME_TOL:
        return "machine_clearable"
    return "sag_only" if sag_ok(read) else "needs_person"


def remeasure_refused(remeasured, since, now, *, incident_id=None, binding=None, faults=None,
                      expected_fault=PORT_LOST_FAULT) -> str | None:
    """Why `remeasured` does not show a quiet read of this arm/board/incident after `since`, or None."""
    try:
        read = ArmIncidentRemeasure.model_validate(remeasured)
    except (TypeError, ValueError):
        return "no valid remeasure"
    if binding is None or (read.arm, read.board_serial) != tuple(binding):
        return "remeasure not of this arm's board"
    if incident_id is None or read.incident_id != incident_id:
        return "remeasure not of this incident"
    seen = {r.name: (r.fault_type, r.fault) for r in read.fault_records}
    ok_fault = ((lambda v: isinstance(v, tuple) and v[0] == "ValueError" and isinstance(v[1], str) and bool(STALE_EFFORT_FAULT_TEXT.fullmatch(v[1])))
                if expected_fault == STALE_EFFORT_FAULT else (lambda v: v == expected_fault))
    if any(not isinstance(n, str) or not ok_fault(seen.get(n)) for n in faults or ()):
        return ("a motor fault record that is not the lost port" if expected_fault == PORT_LOST_FAULT
                else "a motor fault record that is not the expected fault")
    if not isinstance(since, (int, float)) or not isinstance(now, (int, float)) or not since < read.at <= now + REMEASURE_SKEW_S:
        return "remeasure not newer than the incident"
    if now - read.at > REMEASURE_MAX_AGE_S:
        return "remeasure too old"
    if any(read.torque_after.values()):
        return "torque ON at the remeasure"
    if any(read.hardware_error.values()):
        return "hardware error at the remeasure"
    if not (read.folded and read.max_home_err <= REMEASURE_HOME_TOL) and not sag_ok(read):
        return "not folded at home at the remeasure"
    return None


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
    """One flagged row that is exactly the link-failure end (_runner_row: nothing caught, no person needed)."""
    return _runner_row(row, LINK_END)


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


def machine_clearable(facts, remeasured=None, *, since=None, now=None, incident_id=None, binding=None,
                      verdict=None, stills=None) -> tuple[bool, str]:
    """D-1039/D-1040/D-1047: default-deny rule for whether an AI assessor may clear this incident without a person."""
    if not isinstance(facts, dict):
        return False, "facts unreadable"
    torque, latched, windup, flagged, stops, faults = (facts.get(k) for k in (
        "torque_after", "latched", "windup_hits", "flagged", "stops", "fault_records"))
    if not (isinstance(torque, dict) and isinstance(latched, dict)
            and all(isinstance(v, list) for v in (windup, flagged, stops, faults))):
        return False, "facts incomplete (torque_after, latched, windup_hits, flagged, stops, fault_records)"
    if (facts.get("truncated") or not _list_complete(facts, "flagged_total", flagged)
            or not _list_complete(facts, "fault_records_total", faults)):
        return False, "facts truncated (flagged_total or fault_records_total mismatch)"
    # D-1047: a link-failure end alone may stand on a rested arm (recomputed from last_state/last_target/home); others need folded.
    link = (bool(flagged) and all(_comm_end(r) for r in flagged)
            and facts.get("flagged_total") == len(flagged) and facts.get("fault_records_total") == len(faults))
    if facts.get("safe_end") is not True or (facts.get("folded") is not True and not (link and _rested(facts))):
        return False, "arm not at a safe end folded at home"
    off = bool(torque) and all(isinstance(v, int) and not isinstance(v, bool) and v == 0 for v in torque.values())
    link_clear = link and off and not latched and not stops and (not faults or _link_faults_only(faults, facts.get("fault_record_kinds")))
    kind = None if link_clear else remeasure_kind(facts)
    if kind:
        expected_fault = STALE_EFFORT_FAULT if kind == "stale effort sample" else PORT_LOST_FAULT
        held = ("latched hardware error" if latched else "guard contact stop" if stops
                else "motor fault record" if faults and kind.startswith("wind-up")
                else "motor fault record with stop reason" if kind == "stale effort sample" and (faults or facts.get("fault_record_kinds")) and not _stale_effort_kinds_ok(faults, facts.get("fault_record_kinds"))
                else "torque not confirmed OFF" if not off and kind != "torque OFF not confirmed (port in use)"
                else "caps not confirmed restored" if facts.get("caps_restored") is not True
                else remeasure_refused(remeasured, since, now, incident_id=incident_id, binding=binding, faults=faults, expected_fault=expected_fault))
        if held:
            return False, f"{kind}: {held}"
        return True, f"{kind}, then a fresh read: every motor torque OFF with no hardware error, folded at home"
    if not off:
        return False, "torque not confirmed OFF"
    if facts.get("caps_restored") is not True:
        return False, "caps not confirmed restored"
    if held_facts(facts):
        why = held_refused(remeasured, verdict, stills, since, now, incident_id=incident_id, binding=binding)
        return (False, f"box in the jaws: {why}") if why else (
            True, "box in the jaws, then a fresh read and picture verdict: one catalogue box, nothing else")
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


#: D-1048: kinds an automatic fold may close. A latch (hardware error) or a wind-up/snag (a cable or a hose) is never
#: folded by a machine; contact, strain, caught jaws and link failures are what the fold is for.
FOLD_HOME_TOL = 3.0  # units: omx_incident.HOME_TOL / chunk_runner.SETTLE_TOL


def clearable_after_fold(facts, recovery, incident_id=None, reported_at=None) -> tuple[bool, str]:
    """D-1048 (user 2026-11-19): may an assessor clear an incident whose arm the cell folded home by itself? Default
    deny. The incident's facts must be complete and free of a latch and a wind-up; the recovery must be cell_auto_fold's
    measured result: folded_state within FOLD_HOME_TOL of home on every body joint, the same home the incident reported
    (when it did), torque confirmed 0 on every motor after the recovery session, and a clear corridor (or no motion)."""
    if not isinstance(facts, dict):
        return False, "facts unreadable"
    torque, latched, windup, flagged, stops, faults = (facts.get(k) for k in (
        "torque_after", "latched", "windup_hits", "flagged", "stops", "fault_records"))
    if not (isinstance(torque, dict) and isinstance(latched, dict)
            and all(isinstance(v, list) for v in (windup, flagged, stops, faults))):
        return False, "facts incomplete (torque_after, latched, windup_hits, flagged, stops, fault_records)"
    if latched:
        return False, "latched hardware error"
    if windup:
        return False, "wind-up or snag hit"
    if faults and not _link_faults_only(faults, facts.get("fault_record_kinds")):
        return False, "motor fault record"
    if not isinstance(recovery, dict) or recovery.get("kind") != "auto_fold":
        return False, "no auto-fold evidence"
    if incident_id is not None and recovery.get("incident_id") != incident_id:
        return False, "auto-fold evidence is for another incident"
    taken = recovery.get("taken_at")
    if reported_at is not None and (type(taken) not in (int, float) or taken < reported_at - 120.0):  # cell/Fleet clocks
        return False, "auto-fold evidence older than the incident"
    state, home, after = (recovery.get(k) for k in ("folded_state", "home", "torque_after"))
    if not all(isinstance(r, list) and len(r) >= 6 and all(type(v) in (int, float) for v in r[:6]) for r in (state, home)):
        return False, "auto-fold evidence incomplete"
    reported = facts.get("home")
    if not isinstance(reported, list) or reported[:5] != home[:5]:
        return False, "auto-fold home is not the incident's reported home"
    if not all(abs(a - b) <= FOLD_HOME_TOL for a, b in zip(state[:5], home[:5])):
        return False, "auto-fold did not reach home"
    if not (isinstance(after, dict) and len(after) >= 6 and all(type(v) is int and v == 0 for v in after.values())):
        return False, "torque not confirmed OFF on every motor after the fold"
    if recovery.get("corridor_clear") is not True:
        return False, "auto-fold corridor not confirmed clear"
    return True, f"folded home by the cell ({recovery.get('candidate')}), torque OFF; nothing latched or wound up"
