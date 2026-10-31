#!/usr/bin/env python3
"""Every decision the arm S auto pick takes, as a row a decision model can learn from (rosy.omx-cell-decision.v1).

attempts.jsonl says what happened; this says what was decided and on what. One row per decision point, in
work_dir/decisions.jsonl, linked to its attempt by attempt_id (the id the attempt row gets when it is written):

  {"schema", "decision_id", "attempt_id", "stage", "facts" (measured values only), "options" (considered),
   "chosen", "by" rule|measurement|model|person, "reason", "frames", "knowledge_ids", "knowledge_sha",
   "params_sha", "code", "t"}   (+ "supersedes" on a person's correction)

stages: target (chosen or refused, per object), bias (saved region reused or pivot needed), closing_axis (the
ledger candidate picked), safety (rule, joint, value against limit), retry (next candidate after a contact or
an empty grasp, or stop), transport_stop (stopped with the object held: joint, lag, PWM), verify (the placement verdict), and any stage a person names. The outcome arrives
later in the attempt row (held/contact/empty/placed) or as a safety row (aborted), so a row is labelled good
or bad afterwards. A person's correction is a row too (by person) and replaces the row it supersedes.

  cell_decisions.py note --decisions D --stage S --text T [--chosen C] [--supersedes DECISION_ID]
  cell_decisions.py export --decisions D --attempts A [--knowledge K] --out dataset.jsonl
  cell_decisions.py export --decisions D [--attempts A] --context      # compact per-stage digest for the judge seat

Export labels: validated_by_outcome (the choice led to a hold / a placement), corrected_by_person (target is the
person's), unvalidated (outcome bad or unknown; "outcome" says which, so it can serve as a negative). Only
verified and partial knowledge goes into an example. No file started = nothing written, old behaviour.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

SCHEMA = "rosy.omx-cell-decision.v1"
APPLIES = {"target": ["objects", "map"], "bias": ["map"], "closing_axis": ["grasp"], "safety": ["lift", "idle"],
           "retry": ["grasp"], "verify": ["map"], "wrist_align": ["grasp", "map"], "failure": ["grasp", "map"]}
RUN = {"path": None, "knowledge": None, "n": 0, "frame": None}  # set by start(); path None = no decision rows


def start(path: Path, knowledge: str | None = None) -> None:
    import cell_knowledge

    RUN.update(path=Path(path), knowledge=cell_knowledge.load(knowledge) if knowledge else None, n=0, frame=None)


def see(frame) -> None:
    """The latest kept top frame: the picture the next decision rows were taken on."""
    RUN["frame"] = frame


def append(path: Path, row: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def emit(stage: str, facts: dict, options: list, chosen, by: str, reason: str, attempt_id: str | None = None):
    """Append one row; returns its decision_id (None when no run was started)."""
    if RUN["path"] is None:
        return None
    import cell_attempts as ca
    import cell_knowledge

    RUN["n"] += 1
    notes = cell_knowledge.select(RUN["knowledge"], {"applies": APPLIES.get(stage, [])})
    append(RUN["path"], {
        "schema": SCHEMA, "decision_id": f"{ca.RUN['run_id']}-d{RUN['n']:03d}",
        "attempt_id": attempt_id or f"{ca.RUN['run_id']}-{ca.RUN['n'] + 1:03d}",  # the attempt row written next
        "stage": stage, "facts": facts, "options": options, "chosen": chosen, "by": by, "reason": reason,
        "frames": [RUN["frame"]] if RUN["frame"] else [], "knowledge_ids": [e["id"] for e in notes],
        "knowledge_sha": RUN["knowledge"] and RUN["knowledge"]["sha"], "params_sha": ca.RUN["params_sha"], "arm_id": ca.RUN["arm_id"],
        "code": Path(__file__).resolve().parents[3].name, "t": round(time.time(), 3)})
    return f"{ca.RUN['run_id']}-d{RUN['n']:03d}"


def target(objects: list, usable: list, refused: list):
    """Which object was chosen and why each other one was not (measured size, catalogue match, tangled, view, reach)."""
    why = {tuple(r["centre_mm"]): r["why"] for r in refused}
    facts = [{"centre_mm": o["centre_mm"], "length_mm": o.get("length_mm"), "width_mm": o.get("width_mm"),
              "catalogue": o.get("object") if o.get("matched") else None, "tangled": bool(o.get("tangled")),
              "split_from": o.get("split_from"), "refusal": why.get(tuple(o["centre_mm"])),
              "in_view": why.get(tuple(o["centre_mm"])) != "not inside the camera view",
              "reachable": not str(why.get(tuple(o["centre_mm"])) or "").startswith("planner")} for o in objects]
    first = usable[0]["object"] if usable else None
    return emit("target", {"objects": facts}, [u["object"]["centre_mm"] for u in usable],
                first and {"centre_mm": first["centre_mm"], "object": first.get("object")}, "rule",
                "nearest usable to the site start, split pieces last" if usable else "; ".join(sorted(set(why.values()))) or "nothing seen")


def bias(region, problem, raw_m):
    chosen = "reuse saved region" if region else ("pivot failed" if problem else "pivot circle")
    return emit("bias", {"target_m": raw_m, "region_bias_mm": region and region["bias_mm"]}, ["reuse saved region", "pivot circle"],
                chosen, "rule", problem or ("a region covers the object" if region else "no region covers the object"))


def closing(offset, ledger: list, object_id):
    return emit("closing_axis", {"object": object_id, "ledger": [dict(c) for c in ledger]}, [c["value"] for c in ledger],
                offset, "measurement" if offset is not None else "rule",
                "best real record in the choices ledger" if offset is not None else "square object: orientation-free")


def after(moved: dict, better, more: bool, monitor=None):
    """Verdict of a transfer that did not place. A stop in transport with the object held (holding true, not at the
    grasp) is its own point, transport_stop: joint, lag and PWM are the facts a rule "fold home, then place from
    home" is learned from. Otherwise: next candidate after a contact or an empty grasp, else stop."""
    if moved["result"] == "placed":
        return None
    steps, at = moved["steps"], moved.get("at")
    again = moved["result"] in ("empty", "contact") and more
    chosen = {"retry_with": better} if again else "stop"
    if any(s.get("holding") for s in steps) and not str(at).endswith("grasp_pick"):
        sensed = next((s for s in reversed(steps) if s.get("state") and s.get("target")), {})
        gaps = [abs(a - b) for a, b in zip(sensed.get("state", [])[:5], sensed.get("target", [])[:5])]
        lag = re.search(r"by ([0-9.]+) units", str(moved.get("error") or ""))
        facts = {"holding": True, "result": moved["result"], "at": at, "error": moved.get("error"),
                 "joint": gaps.index(max(gaps)) + 1 if gaps else None, "lag_units": float(lag.group(1)) if lag else None,
                 "gripper_current_ma": next((s["gripper_current_ma"] for s in steps if s.get("holding")), None),
                 "pwm_last_checked": getattr(monitor, "last_pwm", None), "pwm_caps": getattr(monitor, "caps", None)}
        return emit("transport_stop", facts, ["fold home, then place from home", "re-observe and pick again", "stop"],
                    "re-observe and pick again" if again else "stop", "rule",
                    "no transport rule: the stop falls into the contact retry, which re-observes and cannot see the held object")
    return emit("retry", {"result": moved["result"], "at": at}, ["retry", "stop"], chosen, "measurement" if again else "rule",
                "retreat, then the better ledger candidate" if again else "a fault, a refusal or the last attempt: a person looks")


def note(path: Path, stage: str, text: str, chosen=None, supersedes: str | None = None) -> dict:
    rows = read(path)
    old = next((r for r in rows if r["decision_id"] == supersedes), None) if supersedes else None
    if supersedes and old is None:
        raise SystemExit(f"{supersedes}: no such decision in {path}")
    row = {"schema": SCHEMA, "decision_id": f"person-{len(rows) + 1:03d}", "attempt_id": old and old["attempt_id"],
           "stage": stage, "facts": {}, "options": [], "chosen": text if chosen is None else chosen, "by": "person",
           "reason": text, "supersedes": supersedes, "frames": [], "knowledge_ids": [], "knowledge_sha": None,
           "params_sha": None, "code": None, "t": round(time.time(), 3)}
    append(path, row)
    return row


def read(path) -> list[dict]:
    p = Path(path) if path else None
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p and p.exists() else []


def later(attempt_id):
    run, n = attempt_id.rsplit("-", 1)
    return f"{run}-{int(n) + 1:03d}"


def outcomes(attempts: list, decisions: list) -> dict:
    """attempt_id -> {"result": placed|held|contact|empty|aborted|..., "good": held or placed}."""
    found = {}
    for a in attempts:
        moved = a.get("transfer") or {}
        held = moved.get("result") == "placed" or any(s.get("holding") for s in moved.get("steps", []))
        found[a["attempt_id"]] = {"result": "placed" if a["outcome"] == "placed" else moved.get("result") or a.get("fail_class"),
                                  "held": held, "placed": a["outcome"] == "placed"}
    for d in decisions:  # an aborted attempt writes no attempt row: its safety row is the outcome
        if d["stage"] == "safety" and d["by"] != "person":
            found[d["attempt_id"]] = {"result": "aborted", "held": False, "placed": False}
    return found


def join(decisions: list, attempts: list) -> list[dict]:
    """Each decision with its outcome and label; a superseded row is dropped, its correction takes its place."""
    out, by_id = outcomes(attempts, decisions), {d["decision_id"]: d for d in decisions}
    replaced = {d["supersedes"] for d in decisions if d.get("supersedes")}
    items = []
    for d in decisions:
        if d["decision_id"] in replaced:
            continue
        if d["by"] == "person":
            items.append({"row": d, "outcome": None, "label": "corrected_by_person", "from": by_id.get(d.get("supersedes"))})
            continue
        a = out.get(later(d["attempt_id"]) if d["stage"] == "retry" else d["attempt_id"])  # a retry is judged by the next attempt
        good = None if a is None else (a["placed"] if d["stage"] == "verify" else a["held"] if d["stage"] != "safety" else None)
        items.append({"row": d, "outcome": a and a["result"], "label": "validated_by_outcome" if good else "unvalidated", "from": None})
    return items


def export(decisions: list, attempts: list, knowledge: dict | None) -> list[dict]:
    notes = {e["id"]: e for e in (knowledge or {}).get("entries", []) if e["status"] != "unverified"}
    examples = []
    for it in join(decisions, attempts):
        row, src = it["row"], it["from"] or it["row"]
        examples.append({
            "decision_id": row["decision_id"], "attempt_id": row["attempt_id"], "label": it["label"], "outcome": it["outcome"],
            "input": {"stage": src["stage"], "facts": src["facts"], "options": src["options"],
                      "knowledge": [f"[{k} {notes[k]['status']}] {notes[k]['statement']}" for k in src["knowledge_ids"] if k in notes],
                      "images": src["frames"]},
            "target": row["chosen"], "by": row["by"], "reason": row["reason"]})
    return examples


def context(decisions_path, attempts_path=None, recent: int = 3, chars: int = 900) -> str:
    """Per-stage background for the judge seat: rows, how each choice did, the person's latest corrections."""
    decisions = read(decisions_path)
    if not decisions:
        return ""
    attempts = read(attempts_path or Path(decisions_path).with_name("attempts.jsonl"))
    stats, counts = defaultdict(lambda: [0, 0]), defaultdict(int)
    for it in join(decisions, attempts):
        counts[it["row"]["stage"]] += 1
        if it["outcome"] is not None:
            s = stats[(it["row"]["stage"], json.dumps(it["row"]["chosen"], sort_keys=True))]
            s[0] += 1
            s[1] += it["label"] == "validated_by_outcome"
    parts = [f"{stage}: {n} decisions" + "".join(f"; {c} -> {g}/{t} good" for (st, c), (t, g) in sorted(stats.items()) if st == stage)
             for stage, n in sorted(counts.items())]
    said = [d["reason"] for d in decisions if d["by"] == "person"][-recent:]
    return re.sub(r"\s+", " ", " | ".join(parts) + (" | person said: " + " / ".join(said) if said else ""))[:chars]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["note", "export"])
    ap.add_argument("--decisions", type=Path, required=True)
    ap.add_argument("--attempts", type=Path)
    ap.add_argument("--knowledge")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--context", action="store_true")
    ap.add_argument("--stage")
    ap.add_argument("--text")
    ap.add_argument("--chosen")
    ap.add_argument("--supersedes")
    args = ap.parse_args(argv)
    if args.command == "note":
        if not (args.stage and args.text):
            ap.error("note needs --stage and --text")
        print(note(args.decisions, args.stage, args.text, args.chosen, args.supersedes)["decision_id"])
    elif args.context:
        print(context(args.decisions, args.attempts))
    else:
        import cell_knowledge

        if not args.out:
            ap.error("export needs --out (or --context)")
        examples = export(read(args.decisions), read(args.attempts), cell_knowledge.load(args.knowledge) if args.knowledge else None)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(e, default=str) + "\n" for e in examples), encoding="utf-8")
        print(len(examples), "examples ->", args.out)


if __name__ == "__main__":
    main()
