#!/usr/bin/env python3
"""An arm session that ends in trouble is handled by a pipeline, not by hand (2026-11-03).

arm_b's elbow latched an overload at 13:27 and the way out took an hour of reading logs, frames and registers by
hand. Every step of that is now this module, run by record_session at the end of every session:

1. collect: session.json, the runner's status rows, the motor-fault records and the health log of the session;
2. facts (measured only): latched hardware errors (decoded), torque after, folded at home or not, joint_push's
   wind-up hits in the health log, jaws caught or stopped short, the frames kept at the fault;
3. decide: measurement first (judge_seat's rule): a reboot is offered only for an overload or voltage latch with
   every motor torque OFF and the arm folded at home; any physical sign (a wind-up, a caught jaw, a latch) holds
   the arm for a person. A decision model, when given, only explains the frames and picks among what is left;
4. record: a rosy.omx-cell-decision.v1 row (stage "incident") in decisions.jsonl, which the judge seat reads back
   as context, and an agenda file (incidents/<stamp>/agenda.md + incident.json) a person reads and closes;
5. act: the one automatic recovery, the Dynamixel Reboot of a latched follower motor (no motion, torque stays
   OFF), with the registers read before and after; then HOLD-<arm>.json refuses the next session until
   `clear` records who checked the arm.

  omx_incident.py handle --session session.json --arm arm_b [--act] [--model http://127.0.0.1:11434]
  omx_incident.py clear --arm arm_b --by NAME --note TEXT
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_decisions  # noqa: E402
import push_replay  # noqa: E402

HW_BITS = {1: "input voltage", 4: "overheating", 8: "motor encoder", 16: "electrical shock", 32: "overload"}
REBOOTABLE = 1 | 32       # a latch the cause of which is load or supply, not heat or damage
HOME_TOL = 3.0            # units: the runner's SETTLE_TOL
INCIDENTS = Path("incidents")


def bits(code: int) -> list[str]:
    return [name for bit, name in HW_BITS.items() if code & bit]


def hold_path(arm: str) -> Path:
    return INCIDENTS / f"HOLD-{arm}.json"


def held(arm: str) -> str | None:
    """Why the next session of `arm` must not start, or None (record_session refuses on it)."""
    path = hold_path(arm)
    return json.loads(path.read_text())["reason"] if path.is_file() else None


def refuse_if_held(arm: str | None) -> None:
    if arm and held(arm):
        raise SystemExit(f"{arm} held for a person: {held(arm)} (omx_incident.py clear --arm {arm} --by --note)")


def after_session(arm: str | None, device: str | None, session=Path("session.json")) -> dict:
    """record_session's end: the pipeline with the reboot on this arm's follower and the model from
    ROSY_DECISION_MODEL (an Ollama URL; unset = measurement only). No arm name: nothing to hold."""
    import os

    if not arm:
        return {"incident": None, "reason": "no --arm"}
    import judge_seat

    url = os.environ.get("ROSY_DECISION_MODEL")
    return handle(session, arm, act=reboot_latched(device) if device else None, model=judge_seat.ollama(url) if url else None)


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


def facts(session: dict, home=None) -> dict:
    """Measured facts of one ended session (session.json as record_session writes it)."""
    chunks = session.get("chunks") or {}
    status = rows(Path(chunks["io"]) / "chunk-status.jsonl", session.get("started", 0)) if chunks.get("io") else []
    flagged = [r for r in status if r.get("person_needed") or r.get("caught")
               or str(r.get("error") or r.get("fault") or "").startswith(("pushing", "contact in park"))]
    latched = {str(m): {"hw_error": f.get("hw_error"), "bits": bits(int(f.get("hw_error") or 0)),
                        "packet_alert": f.get("packet_alert")} for m, f in (session.get("hardware_faults") or {}).items()}
    last = next((r["state"] for r in reversed(status) if r.get("state")), None)
    log = session.get("motor_health_log")
    replay = push_replay.replay([log]) if log and Path(log).is_file() else {}
    faults_dir, owner = Path(session.get("motor_health_state") or ".").parent / "faults", session.get("motor_health_owner")
    kept = sorted(faults_dir.glob(f"{owner}-*.json")) if owner and faults_dir.is_dir() else []
    kept = [p for p in kept if json.loads(p.read_text()).get("session_id") == session.get("motor_health_session")]
    return {"safe_end": bool(session.get("safe_end")), "latched": latched,
            "torque_after": session.get("torque_after") or {}, "caps_restored": session.get("caps_restored"),
            "folded": bool(home and last and all(abs(a - b) <= HOME_TOL for a, b in zip(last[:5], home[:5]))),
            "last_state": last, "flagged": [{k: r.get(k) for k in ("command", "error", "fault", "caught", "t")}
                                           for r in flagged][-5:],
            "windup_hits": [h for arm in replay.values() for h in arm["hits"]],
            "fault_records": [str(p) for p in kept],
            "frames": [str(p.with_name(f"{p.stem}-{v}.jpg")) for p in kept[-1:] for v in ("top", "side")]}


def decide(f: dict) -> dict:
    """Measurement first: (chosen actions, hold or not, why). Returns {"actions", "hold", "reason", "offered"}."""
    signs = bool(f["latched"] or f["windup_hits"] or f["flagged"] or not f["safe_end"])
    if not signs:
        return {"actions": [], "hold": False, "offered": [], "reason": "no incident sign"}
    caught_only = (f["safe_end"] and not f["latched"] and not f["windup_hits"]
                   and all(r.get("caught") for r in f["flagged"]))
    if caught_only:  # the runner already let go where the jaws pinched: a note, not a hold
        return {"actions": [], "hold": False, "offered": [], "reason": "jaws caught and reopened by the runner"}
    off = all(int(v) == 0 for v in f["torque_after"].values()) and bool(f["torque_after"])
    rebootable = [m for m, l in f["latched"].items() if l["hw_error"] and not int(l["hw_error"]) & ~REBOOTABLE]
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
    return {"actions": offered, "hold": True, "offered": offered,
            "reason": "; ".join(why) + "; a person checks the arm (jaws, contacts, wedged objects) before torque ON"}


def explain(model, f: dict) -> dict | None:
    """The decision model only explains what the frames show; it never adds an action."""
    import base64

    images = [base64.b64encode(Path(p).read_bytes()).decode() for p in f["frames"] if Path(p).is_file()]
    schema = {"type": "object", "properties": {"seen": {"type": "string"}, "suspected_cause": {"type": "string"}},
              "required": ["seen", "suspected_cause"]}
    prompt = ("An OMX arm session ended with these measured facts:\n" + json.dumps({k: f[k] for k in
              ("latched", "folded", "flagged", "windup_hits")}, default=str)[:3000]
              + "\nThe images are the top and side cameras at the fault. Say what you see near the arm and the jaws "
                "(objects caught, leaning, wedged) and the most likely physical cause. Do not suggest motions.")
    try:
        return model(prompt, images, schema)
    except Exception as exc:  # an unreachable model must not stop the record
        return {"error": str(exc)[:200]}


def agenda(stamp, arm, f, d, seen, acted) -> str:
    lines = [f"# {arm} incident {stamp}", "", f"- decision: {', '.join(d['actions']) or 'none automatic'}; "
             f"{'HOLD until a person clears it' if d['hold'] else 'no hold'}", f"- why: {d['reason']}",
             f"- safe end: {f['safe_end']}; folded at home: {f['folded']}; torque after: {f['torque_after']}"]
    lines += [f"- latched ID {m}: hw_error {l['hw_error']} ({', '.join(l['bits'])})" for m, l in f["latched"].items()]
    lines += [f"- wind-up: {h['session']} t={h['t']} {h['reason']}" for h in f["windup_hits"][:3]]
    lines += [f"- runner: {r.get('command')}: {r.get('error') or r.get('fault')}" for r in f["flagged"]]
    lines += [f"- frames: {', '.join(f['frames'])}" if f["frames"] else "- frames: none kept"]
    if seen:
        lines.append(f"- model (explanation only): {json.dumps(seen, ensure_ascii=False)}")
    if acted:
        lines.append(f"- automatic recovery: {json.dumps(acted, default=str)}")
    lines += ["", "## Person", "1. Look at the arm and the jaws: remove anything caught, leaning or wedged.",
              f"2. `omx_incident.py clear --arm {arm} --by <name> --note <what you found>`",
              "3. Add the cause to the lesson (docs/solutions) if it is new."]
    return "\n".join(lines) + "\n"


def handle(session_path: Path, arm: str, act=None, model=None, decisions=Path("decisions.jsonl"), home=None) -> dict:
    """Run the pipeline for one ended session; returns the incident (or {"incident": False})."""
    session = json.loads(Path(session_path).read_text())
    if home is None and (session.get("chunks") or {}).get("library"):
        library = json.loads(Path(session["chunks"]["library"]).read_text())
        home = (library.get("chunks", {}).get("home") or [None])[0]
    f = facts(session, home)
    d = decide(f)
    if not d["actions"] and not d["hold"] and d["reason"] == "no incident sign":
        return {"incident": False}
    stamp = time.strftime("%Y%m%dT%H%M%S")
    seen = explain(model, f) if model else None
    acted = act([int(m) for m in f["latched"]]) if act and "reboot_latched" in d["actions"] else None
    folder = INCIDENTS / f"{stamp}-{arm}"
    folder.mkdir(parents=True, exist_ok=True)
    incident = {"schema": "rosy.omx-incident.v1", "arm": arm, "stamp": stamp, "session": str(session_path),
                "facts": f, "decision": d, "model": seen, "recovery": acted}
    (folder / "incident.json").write_text(json.dumps(incident, indent=1, default=str))
    (folder / "agenda.md").write_text(agenda(stamp, arm, f, d, seen, acted))
    cell_decisions.append(decisions, {
        "schema": cell_decisions.SCHEMA, "decision_id": f"{stamp}-{arm}-incident", "attempt_id": None,
        "stage": "incident", "facts": {k: f[k] for k in ("latched", "folded", "windup_hits", "flagged", "safe_end")},
        "options": d["offered"] + ["hold_for_person"], "chosen": d["actions"] + (["hold_for_person"] if d["hold"] else []),
        "by": "measurement", "reason": d["reason"], "frames": f["frames"], "arm_id": arm, "t": round(time.time(), 3)})
    if d["hold"]:
        hold_path(arm).write_text(json.dumps({"reason": f"{folder}/agenda.md: {d['reason']}", "since": stamp}))
    return {"incident": True, "folder": str(folder), **incident}


def reboot_latched(device: str):
    """Reboot the latched follower IDs on `device`, only while every follower motor reads torque 0."""
    def act(ids):
        from dynamixel_sdk import PacketHandler, PortHandler

        port, packet = PortHandler(device), PacketHandler(2.0)
        if not (port.openPort() and port.setBaudRate(1_000_000)):
            return {"error": "port"}
        try:
            read = lambda i, a: packet.read1ByteTxRx(port, i, a)[0]  # noqa: E731
            before = {i: {"torque": read(i, 64), "hw_error": read(i, 70)} for i in range(11, 17)}
            if any(v["torque"] for v in before.values()):
                return {"refused": "a follower motor has torque ON", "before": before}
            for i in ids:
                packet.reboot(port, i)
            time.sleep(1.5)
            return {"rebooted": ids, "before": before,
                    "after": {i: {"torque": read(i, 64), "hw_error": read(i, 70)} for i in range(11, 17)}}
        finally:
            port.closePort()
    return act


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    h = sub.add_parser("handle")
    h.add_argument("--session", type=Path, default=Path("session.json"))
    h.add_argument("--arm", required=True)
    h.add_argument("--device", help="follower by-id path: reboots an allowed latch (no motion)")
    h.add_argument("--model", help="Ollama URL of the decision model (explanation only)")
    c = sub.add_parser("clear")
    c.add_argument("--arm", required=True)
    c.add_argument("--by", required=True)
    c.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    if args.command == "clear":
        reason = held(args.arm)
        if reason is None:
            print(f"{args.arm}: no hold")
            return 0
        cell_decisions.note(Path("decisions.jsonl"), "incident", f"cleared by {args.by}: {args.note} (was: {reason})",
                            chosen="cleared")
        hold_path(args.arm).unlink()
        print(f"{args.arm}: hold cleared")
        return 0
    import judge_seat

    out = handle(args.session, args.arm, act=reboot_latched(args.device) if args.device else None,
                 model=judge_seat.ollama(args.model) if args.model else None)  # by hand on an old session.json
    print(json.dumps({k: out.get(k) for k in ("incident", "folder", "decision", "recovery")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
