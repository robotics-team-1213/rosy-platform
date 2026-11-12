#!/usr/bin/env python3
"""An arm session that ends in trouble is measured here and reported to Fleet (D-971, 2026-11-03).

arm_b's elbow latched an overload at 13:27 and the way out took an hour of reading logs, frames and registers by
hand. The control PC now only measures, reports and keeps the device safe; Fleet owns the incident ledger, the AI PC
explains the frames, and a named operator clears the hold in the Fleet console. record_session runs this at the end
of every session:

1. collect: session.json, the runner's status rows, the motor-fault records and the health log of the session;
2. facts (measured only): latched hardware errors (decoded), torque after, folded at home or not, joint_push's
   wind-up hits in the health log, jaws caught or stopped short, the frames kept at the fault;
3. decide: measurement first (judge_seat's rule): a reboot is offered only for an overload or voltage latch with
   every motor torque OFF and the arm folded at home; any physical sign (a wind-up, a caught jaw, a latch) holds
   the arm for a person;
4. record: a rosy.omx-cell-decision.v1 row (stage "incident") in decisions.jsonl, which the judge seat reads back
   as learning context, and incidents/<stamp>-<arm>/incident.json (a local copy, not the ledger);
5. act: the one automatic recovery, the Dynamixel Reboot of a latched follower motor (no motion, torque stays
   OFF), with the registers read before and after; the hold stays after it;
6. report: a held incident goes to Fleet (facts, decision, recovery, up to two frames). Unsent reports wait in
   incidents/outbox/ and go again before the next session.

Before a session `refuse_if_held` resends unsent reports and asks Fleet for the hold. Fleet unreachable: refuse only
when a local hold exists (the last hold Fleet sent, or one made at an incident that could not be reported). A local
hold is lifted only when Fleet answers that the arm is not held and nothing is unsent. Clearing is Fleet's.

  omx_incident.py handle --session session.json --arm arm_b [--device /dev/serial/by-id/...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_decisions  # noqa: E402
import push_replay  # noqa: E402
from omx_incident_fleet import (  # noqa: E402
    INCIDENTS,
    _bridge_environ,
    _effectively_held,
    default_token_file,
    evidence_of,
    held,
    hold_file,
    hold_path,
    incidents_dir,
    keep_hold,
    label_box,
    link_for,
    outbox,
    report_for,
    send,
    upload_evidence,
)

HW_BITS = {1: "input voltage", 4: "overheating", 8: "motor encoder", 16: "electrical shock", 32: "overload"}
REBOOTABLE = 1 | 32       # a latch the cause of which is load or supply, not heat or damage
HOME_TOL = 3.0            # units: the runner's SETTLE_TOL
STILLS = INCIDENTS / "stills"  # <arm>-<camera>.jpg, kept by the carry at a stop no fault record covers (cell_hooks.stills)


def bits(code: int) -> list[str]:
    return [name for bit, name in HW_BITS.items() if code & bit]


def refuse_if_held(arm: str | None, link=None) -> None:
    """Before a session: resend unsent reports, ask Fleet for the hold. Fleet unreachable: refuse only on a local hold."""
    if not arm:
        return
    link = link or link_for(arm)
    if link and label_box(arm):  # label-only reports go when they can; they never decide the start
        send(arm, link, label_box(arm))
    sent = send(arm, link) if link and outbox(arm) else not outbox(arm)
    answer = None
    if link:
        try:
            answer = link.hold()
        except Exception as exc:
            print(f"fleet hold unreachable: {type(exc).__name__}: {str(exc)[:120]}")
    if _effectively_held(answer):
        keep_hold(arm, answer.reason or "arm incident not cleared", answer.incident_ids, "fleet")
        raise SystemExit(f"{arm} held for a person: {answer.reason} (clear it in the Fleet console)")
    if answer is not None and sent:
        for gone in (hold_path(arm), INCIDENTS / f"HOLD-{arm}.json"):
            gone.unlink(missing_ok=True)  # only Fleet's "not held", with nothing unsent, lifts a hold
        return
    reason = held(arm) or ("an incident report could not be sent to Fleet" if outbox(arm) else None)
    if reason:
        raise SystemExit(f"{arm} held for a person: {reason} (Fleet not reached; Fleet clears it)")


def after_session(arm: str | None, device: str | None, session=Path("session.json"), link=None) -> dict:
    """record_session's end: the pipeline with the reboot on this arm's follower. No arm name: nothing to hold."""
    if not arm:
        return {"incident": None, "reason": "no --arm"}
    return handle(session, arm, act=reboot_latched(device) if device else None, link=link or link_for(arm))


def rows(path, since=0.0):
    out = []
    if path and Path(path).is_file():
        for line in Path(path).read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("t", since) >= since:
                out.append(row)
    return out


def stop_reading(status: list) -> dict | None:
    """What the 30 Hz trace says of the session's last contact stop: too fast or blocked (cell_why). 2026-11-07: an hour of guessing
    with the answer on disk, and the explanation had no frames and no such fact."""
    import os
    import re

    import cell_why

    stops = [re.match(r"contact in (.+?):", str(r.get("error") or "")) for r in status]
    stops = [m.group(1) for m in stops if m and m.group(1) != "park"]  # a fold refused on what it holds follows the real stop
    path = os.environ.get("ROSY_CHUNK_TRACE")
    if not stops or not path or not Path(path).is_file():
        return None
    try:
        return {"chunk": stops[-1], **cell_why.read_motion(cell_why.last_run(cell_why.read_trace(path), stops[-1]))}
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:  # a damaged trace must not lose the report
        return {"chunk": stops[-1], "verdict": "undetermined", "why": f"trace unreadable: {type(exc).__name__}"}


def stills_of(arm: str | None, since: float) -> list:
    """This session's stop frames, those the explanation's prompt names first (the report carries two)."""
    if not arm or not STILLS.is_dir():
        return []
    kept = [p for p in STILLS.glob(f"{arm}-*.jpg") if p.stat().st_mtime >= since]
    return [str(p) for p in sorted(kept, key=lambda p: (p.stem.rsplit("-", 1)[-1] not in ("top", "side"), p.name))][:2]


def facts(session: dict, home=None, arm: str | None = None) -> dict:
    """Measured facts of one ended session (session.json as record_session writes it)."""
    chunks = session.get("chunks") or {}
    status = rows(Path(chunks["io"]) / "chunk-status.jsonl", session.get("started", 0)) if chunks.get("io") else []
    flagged = [r for r in status if r.get("person_needed") or r.get("caught")
               or str(r.get("error") or r.get("fault") or "").startswith(("pushing", "contact in park", "session ended"))]
    latched = {str(m): {"hw_error": f.get("hw_error"), "bits": bits(int(f.get("hw_error") or 0)),
                        "packet_alert": f.get("packet_alert")} for m, f in (session.get("hardware_faults") or {}).items()}
    last = next((r["state"] for r in reversed(status) if r.get("state")), None)
    log = session.get("motor_health_log")
    replay = push_replay.replay([log]) if log and Path(log).is_file() else {}
    faults_dir, owner = Path(session.get("motor_health_state") or ".").parent / "faults", session.get("motor_health_owner")
    kept = sorted(faults_dir.glob(f"{owner}-*.json")) if owner and faults_dir.is_dir() else []
    kept = [p for p in kept if json.loads(p.read_text()).get("session_id") == session.get("motor_health_session")]
    n_arm = min(len(last) - 1, len(home) - 1) if (last and home and len(last) >= 6 and len(home) >= 6) else 5
    return {"safe_end": bool(session.get("safe_end")), "latched": latched,
            "torque_after": session.get("torque_after") or {}, "caps_restored": session.get("caps_restored"),
            "folded": bool(home and last and all(abs(a - b) <= HOME_TOL for a, b in zip(last[:n_arm], home[:n_arm]))),
            "last_state": last, "flagged": [{k: r.get(k) for k in ("command", "error", "fault", "caught", "t")}
                                           for r in flagged][-5:],
            "windup_hits": [h for arm in replay.values() for h in arm["hits"]],
            "stop_reading": stop_reading(status),
            # every guard stop on contact, held or not: what a person names the cause of (labels for learning)
            "stops": [{k: r.get(k) for k in ("command", "error", "t")} for r in status
                      if str(r.get("error") or "").startswith("contact in ") and not str(r["error"]).startswith("contact in park")][-5:],
            "fault_records": [str(p) for p in kept],
            "frames": ([str(p.with_name(f"{p.stem}-{v}.jpg")) for p in kept[-1:] for v in ("top", "side")]
                       or stills_of(arm, session.get("started", 0)))}


def software_stop(f: dict) -> str | None:
    """The shared rule (core_common, so Fleet's hold judges the same facts); not importable here: hold, as before."""
    try:
        from core_common.protocol.arm_incidents import software_stop as rule
    except ImportError:
        return None
    return rule(f)


def decide(f: dict) -> dict:
    """Measurement first: (chosen actions, hold or not, why). Returns {"actions", "hold", "reason", "offered"}."""
    released = software_stop(f)
    if released:  # the guard's own stop on a folded arm that followed its command: listed for a cause, not held
        return {"actions": [], "hold": False, "offered": [], "reason": released}
    signs = bool(f["latched"] or f["windup_hits"] or f["flagged"] or not f["safe_end"])
    if not signs and f.get("stops"):  # the recovery handled it; a person still names what stopped it
        return {"actions": [], "hold": False, "offered": [],
                "reason": f"guard stop: {f['stops'][-1]['error']}; reported for a person's cause, the arm is not held"}
    if not signs:
        return {"actions": [], "hold": False, "offered": [], "reason": "no incident sign"}
    caught_only = (f["safe_end"] and not f["latched"] and not f["windup_hits"]
                   and all(r.get("caught") for r in f["flagged"]))
    if caught_only:  # the runner already let go where the jaws pinched: a note, not a hold
        return {"actions": [], "hold": False, "offered": [], "reason": "jaws caught and reopened by the runner"}
    off = bool(f["torque_after"]) and all(isinstance(v, int) and not isinstance(v, bool) and v == 0
                                          for v in f["torque_after"].values())
    rebootable = [m for m, l in f["latched"].items()
                  if isinstance(l.get("hw_error"), int) and l["hw_error"] and not int(l["hw_error"]) & ~REBOOTABLE]
    offered = ["reboot_latched"] if rebootable and len(rebootable) == len(f["latched"]) and off and f["folded"] else []
    why = []
    if f["latched"]:
        why.append("latched " + ", ".join(f"ID {m} {'/'.join(l['bits']) or l['hw_error']}" for m, l in f["latched"].items()))
    if f["windup_hits"]:
        why.append(f"wind-up before the end: {f['windup_hits'][0]['reason']}")
    if f["flagged"]:
        why.append(f"runner: {f['flagged'][-1].get('error') or f['flagged'][-1].get('fault')}")
    if not offered and f["latched"]:
        why.append("no automatic reboot: " + ("torque not confirmed OFF" if not off else
                                               "arm not folded at home" if not f["folded"] else "a latch that is not load or supply"))
    if not why and not f["safe_end"]:
        if not off:
            why.append("torque not confirmed OFF")
        if f.get("caps_restored"):
            why.append("caps not confirmed restored")
        if not why:
            why.append("unsafe session end")
    return {"actions": offered, "hold": True, "offered": offered,
            "reason": "; ".join(why) + "; a person checks the arm (jaws, contacts, wedged objects) before torque ON"}


def handle(session_path: Path, arm: str, act=None, decisions=Path("decisions.jsonl"), home=None, link=None) -> dict:
    """Run the pipeline for one ended session; returns the incident (or {"incident": False})."""
    session = json.loads(Path(session_path).read_text())
    if "safe_end" not in session:  # failed before the bus opened (2026-11-03 23:19: a leader port gone): never reached the arm
        return {"incident": False}
    if home is None and (session.get("chunks") or {}).get("library"):
        library = json.loads(Path(session["chunks"]["library"]).read_text())
        home = (library.get("chunks", {}).get("home") or [None])[0]
    f = facts(session, home, arm)
    d = decide(f)
    if not d["actions"] and not d["hold"] and d["reason"] == "no incident sign":
        return {"incident": False}
    stamp = time.strftime("%Y%m%dT%H%M%S")
    folder = INCIDENTS / f"{stamp}-{arm}"
    folder.mkdir(parents=True, exist_ok=True)
    if d["hold"]:  # the local hold exists before any device recovery and before Fleet is asked
        keep_hold(arm, f"{folder}: {d['reason']}"[:380])
    acted = act([int(m) for m in f["latched"]]) if act and "reboot_latched" in d["actions"] else None
    incident = {"schema": "rosy.omx-incident.v1", "arm": arm, "stamp": stamp, "session": str(session_path),
                "facts": f, "decision": d, "recovery": acted, "reported": False}
    cell_decisions.append(decisions, {
        "schema": cell_decisions.SCHEMA, "decision_id": f"{stamp}-{arm}-incident", "attempt_id": None,
        "stage": "incident", "facts": {k: f[k] for k in ("latched", "folded", "windup_hits", "flagged", "safe_end")},
        "options": d["offered"] + ["hold_for_person"], "chosen": d["actions"] + (["hold_for_person"] if d["hold"] else []),
        "by": "measurement", "reason": d["reason"], "frames": f["frames"], "arm_id": arm, "t": round(time.time(), 3)})
    if d["hold"] or f.get("stops") or software_stop(f):  # if Fleet cannot be reached a held arm's next session is still refused
        sid = session.get("motor_health_session")
        try:
            sid = str(uuid.UUID(str(sid)))
        except ValueError:
            sid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{arm}/{sid or stamp}"))
        try:
            report = report_for(link.source_id if link else arm, sid, f, d, acted)
        except Exception as exc:  # the contract is not importable here: nothing can be sent, the hold stays
            print(f"incident report not built: {type(exc).__name__}: {str(exc)[:120]}")
            report = None
        if report is not None:
            box = incidents_dir() / ("outbox" if d["hold"] else "labels")  # a label-only report never blocks a start
            box.mkdir(parents=True, exist_ok=True)
            (box / f"{arm}-{sid}.json").write_text(report.model_dump_json())
            chosen = evidence_of(session.get("started", 0))
            if chosen:
                (box / f"{arm}-{sid}.evidence").write_text(json.dumps(chosen))
            incident["reported"] = bool(link) and send(arm, link, None if d["hold"] else label_box(arm))
    (folder / "incident.json").write_text(json.dumps(incident, indent=1, default=str))
    return {"incident": True, "folder": str(folder), **incident}


def reboot_latched(device: str):
    """Reboot the latched follower IDs on `device`, only while every follower motor reads torque 0."""
    def act(ids):
        from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

        port, packet = PortHandler(device), PacketHandler(2.0)
        before, after = {}, {}

        def verified(result, error):
            if result != COMM_SUCCESS or error & ~128:
                raise ValueError(f"bus response failed: communication={result}, packet={error}")

        def read(motor, address):
            value, result, error = packet.read1ByteTxRx(port, motor, address)
            verified(result, error)  # alert 0x80 reports the latch; lower bits are packet errors
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError("invalid register readback")
            return value

        def snapshot():
            return {i: {"torque": read(i, 64), "hw_error": read(i, 70)} for i in range(11, 17)}

        try:
            if not (port.openPort() and port.setBaudRate(1_000_000)):
                return {"error": "port"}
            if not ids or any(type(i) is not int or i not in range(11, 17) for i in ids):
                return {"refused": "invalid follower reboot IDs"}
            before = snapshot()
            if any(v["torque"] for v in before.values()):
                return {"refused": "a follower motor has torque ON", "before": before}
            if any(v["hw_error"] & ~REBOOTABLE for v in before.values()) or any(not before[i]["hw_error"] for i in ids):
                return {"refused": "current hardware faults do not permit reboot", "before": before}
            for i in ids:
                verified(*packet.reboot(port, i))
            time.sleep(1.5)
            after = snapshot()
            if any(v["torque"] or v["hw_error"] for v in after.values()):
                return {"refused": "reboot readback is not torque OFF and fault-free", "before": before, "after": after}
            return {"rebooted": ids, "before": before, "after": after}
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"error": str(exc), "before": before, "after": after}
        finally:
            port.closePort()
    return act


def status(arm: str, link=None) -> dict:
    """Return local and Fleet hold state for `arm`."""
    link = link or link_for(arm)
    local_reason = held(arm)
    fleet_held, fleet_ids, fleet_reason = None, [], None
    if link is not None:
        try:
            ans = link.hold()
            fleet_held, fleet_ids, fleet_reason = _effectively_held(ans), list(ans.incident_ids), ans.reason
        except Exception as exc:
            fleet_reason = f"unreachable: {type(exc).__name__}: {str(exc)[:120]}"
    return {"arm": arm, "local_held": bool(local_reason), "local_reason": local_reason,
            "unsent_outbox": len(outbox(arm)), "fleet_held": fleet_held,
            "incident_ids": fleet_ids, "fleet_reason": fleet_reason}


def clear(arm, note, token_file=None, link=None, *, cause=None, basis=None) -> int:
    """Clear every open incident of one arm as the named operator whose token this is, then lift the local hold."""
    if not note.strip():
        raise SystemExit("a note of what was checked is required")
    token_file = token_file or default_token_file()
    if token_file is None or not Path(token_file).is_file():
        raise SystemExit("an operator --token-file (chmod 600) is required")
    token_file = Path(token_file)
    if token_file.stat().st_mode & 0o077:
        raise SystemExit(f"{token_file} must be readable by its owner only (chmod 600)")
    link = link or link_for(arm)
    if link is None:
        raise SystemExit(f"{arm}: no Fleet channel configured on this PC (source the observation bridge env)")
    token = token_file.read_text(encoding="utf-8").strip()
    answer = link.hold()
    cleared = list(answer.incident_ids)
    for incident_id in cleared:
        if cause is not None or basis is not None:
            try:
                answer = link.clear(incident_id, note, token, cause=cause, basis=basis)
            except OSError as exc:
                if getattr(exc, "code", None) != 422:
                    raise
                answer = link.clear(incident_id, note, token)
        else:
            answer = link.clear(incident_id, note, token)
    print(json.dumps({"arm": arm, "cleared": cleared, "held": answer.held,
                      **({"cause": cause} if cause else {}), **({"basis": basis} if basis else {})}))
    refuse_if_held(arm, link)  # Fleet's "not held" lifts the local hold file too
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    h = sub.add_parser("handle")
    h.add_argument("--session", type=Path, default=Path("session.json"))
    h.add_argument("--arm", required=True)
    h.add_argument("--device", help="follower by-id path: reboots an allowed latch (no motion)")
    s = sub.add_parser("status", help="check local and Fleet hold state for this arm")
    s.add_argument("--arm", required=True)
    c = sub.add_parser("clear", help="a named operator clears this arm's open incidents over the Fleet API")
    c.add_argument("--arm", required=True)
    c.add_argument("--note", required=True, help="what the person checked on the arm")
    c.add_argument("--token-file", type=Path, help="the operator's own Fleet bearer (0600); defaults to ~/.config/rosy/*-operator-*.token")
    c.add_argument("--cause", help="optional structured stop cause (API v1.375)")
    c.add_argument("--basis", help="optional cause basis: repeat, measured, seen, unknown (API v1.375)")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status(args.arm)))
        return 0
    if args.command == "clear":
        return clear(args.arm, args.note, args.token_file, cause=args.cause, basis=args.basis)
    from joint_tune import session_lock

    lock = session_lock(args.arm)  # a by-hand run never overlaps a recording session of the same arm
    try:
        out = handle(args.session, args.arm, act=reboot_latched(args.device) if args.device else None,
                     link=link_for(args.arm))  # by hand on an old session.json
    finally:
        lock.close()
    print(json.dumps({k: out.get(k) for k in ("incident", "folder", "decision", "recovery", "reported")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
