#!/usr/bin/env python3
"""Why did it stop? Read the failure from what was recorded, ask the decision model what is left, and keep what is still unknown.

2026-11-07: the first held lift stopped, and "why" stayed a guess for an hour with the answer on disk. The runner's trace
(30 Hz, sent and present per joint) showed the wrist still moving at half the commanded speed. That alone does not mean too
fast: the descents the work record calls real contact keep moving too (0.20-0.75 of the command, free wrist motion 0.33-0.79).
Measurement reads first and says only what it can: a joint that nearly stood still under a moving command was blocked; one that
kept moving is undetermined. On the arm that reading orders the recovery, goes into the incident report (omx_incident) and so to the AI PC's
explanation in Fleet (D-971); the control PC calls no model. Off the arm (this CLI, on a host with the model) the model sees the
same facts, the frames and past rows of the kind, picks among HYPOTHESES and says which evidence is missing. Its answer is text:
it cannot overrule the measurement (a disagreement stays an open question) and chooses no action. A kind that stays unknown
twice stops the retries: `repeat_unknown` hands it to a person.

  cell_why.py --kind lift_stall --at lift_pick --trace trace-arm_b-X.jsonl --out why.jsonl [--images a.jpg ...] [--url U --model M]
Standard library only, so it also runs on the host that has the model.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
WINDOW_S, MIN_SPEED, BLOCKED_RATIO, MIN_RISE = 0.5, 0.3, 0.25, 0.3
# a retry of one plan: same start, this much slower, and it stopped within SAME_STOP of the last stop.
# Real pair: 2026-11-06 23:09 -> 23:27, start 0.2 apart, 3.52 -> 2.11 units/s, stop 1.2 apart, a contact by the side view. No opposite pair yet.
SAME_START, SAME_STOP, SLOWER = 1.0, 2.0, 0.85
HYPOTHESES = {
    "too_fast": "the joint kept moving but slower than commanded: the command outran it. Check: the same move slower",
    "blocked": "the joint stood still under a moving command: something holds the arm or what it carries. Check: frames at the stop; move the thing clear",
    "snagged": "the held box or a finger caught a neighbour or a rim: the load rose only once it moved. Check: side and wrist frames; a neighbour moved",
    "wrong_position": "the arm came down beside where the box really is. Check: top view against the plan, jaw marks",
    "camera_or_map": "the view or the map was wrong, not the arm. Check: a fresh view, the map's error here",
    "unknown": "none of these fits what is shown: name the evidence that would tell",
}
SCHEMA = {"type": "object", "required": ["hypothesis", "reason", "missing"],
          "properties": {"hypothesis": {"type": "string", "enum": list(HYPOTHESES)}, "reason": {"type": "string"},
                         "missing": {"type": "array", "items": {"type": "string"}}}}


def chunk_of(result: str) -> str | None:
    """The chunk a run_auto result names: 'stopped: released after a stop at run lift_pick' -> lift_pick."""
    found = re.search(r" at (?:run )?([\w ]+)$", result)
    return found.group(1) if found else None


def last_run(rows: list, chunk: str) -> list:
    """The trace's last unbroken stretch of the chunk."""
    end = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].get("chunk") == chunk), None)
    if end is None:
        return []
    start = end
    while start > 0 and rows[start - 1].get("chunk") == chunk:
        start -= 1
    return rows[start:end + 1]


def read_motion(rows: list) -> dict:
    """The joint that fell behind most in a chunk, and what it did in the last WINDOW_S: did it keep moving?"""
    if len(rows) < 3:
        return {"verdict": "undetermined", "why": "no trace of this chunk"}
    lag = lambda r, j: abs(r["present"][j] - r["sent"][j])  # noqa: E731
    worst = max(range(5), key=lambda j: lag(rows[-1], j))
    tail = [r for r in rows if r["t"] >= rows[-1]["t"] - WINDOW_S]
    span = tail[-1]["t"] - tail[0]["t"] or 1.0
    sent = abs(tail[-1]["sent"][worst] - tail[0]["sent"][worst]) / span
    present = abs(tail[-1]["present"][worst] - tail[0]["present"][worst]) / span
    facts = {"joint": JOINTS[worst], "lag_start": round(lag(rows[0], worst), 2), "lag_end": round(lag(rows[-1], worst), 2),
             "sent_units_s": round(sent, 2), "present_units_s": round(present, 2), "seconds": round(rows[-1]["t"] - rows[0]["t"], 2),
             "other_joints_lag_rise": {JOINTS[j]: round(lag(rows[-1], j) - lag(rows[0], j), 2) for j in range(5) if j != worst},
             "jaws": rows[-1]["present"][5], "start": rows[0]["sent"][:5], "stopped_at": rows[-1]["present"][:5],
             "pwm_end": (rows[-1].get("pwm") or {}).get(JOINTS[worst])}  # no verdict from PWM yet: no contact has been recorded with it
    if sent < MIN_SPEED or facts["lag_end"] - facts["lag_start"] < MIN_RISE:
        return {**facts, "verdict": "undetermined", "why": "the command was not moving, or the lag did not grow"}
    moved = f"{facts['joint']} moved {present:.2f} of {sent:.2f} units/s"
    if present < BLOCKED_RATIO * sent:
        return {**facts, "verdict": "blocked", "why": moved}
    return {**facts, "verdict": "undetermined", "why": f"{moved}: contact and free motion both keep moving like this"}


def read_repeat(motion: dict, earlier: list) -> dict:
    """What the speed ratio cannot tell, a retry can: slower, yet stopped at the same place, so speed is excluded.
    shortcut: a load limit at that pose reads as blocked too; the push it chooses ends at a person if the top view shows no change."""
    if motion["verdict"] != "undetermined" or not earlier or "start" not in motion or "start" not in (earlier[-1].get("motion") or {}):
        return motion
    before = earlier[-1]["motion"]
    gap = lambda a, b: max(abs(x - y) for x, y in zip(a, b))  # noqa: E731
    stood = motion["sent_units_s"] >= MIN_SPEED and motion["lag_end"] - motion["lag_start"] >= MIN_RISE
    if (stood and gap(motion["start"], before["start"]) <= SAME_START and gap(motion["stopped_at"], before["stopped_at"]) <= SAME_STOP
            and motion["sent_units_s"] <= SLOWER * before["sent_units_s"]):
        return {**motion, "verdict": "blocked", "why": f"slower ({before['sent_units_s']} -> {motion['sent_units_s']} units/s), stopped at the same place"}
    return motion


def past_rows(path: Path, kind: str) -> list:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == kind]


def explain(kind: str, result: str, trace: list, images: list, backend, path: Path, chunk: str | None = None, since: float = 0.0) -> dict:
    """One row in why.jsonl: measured verdict, the model's pick and missing evidence, and the final `hypothesis`. `repeat_unknown`
    counts only rows since `since`: an unknown of last week is an open question, not this carry's second try."""
    chunk = chunk or chunk_of(result)
    motion = read_motion(last_run(trace, chunk)) if chunk else {"verdict": "undetermined", "why": "no chunk named"}
    past = past_rows(path, kind)
    motion = read_repeat(motion, [r for r in past if r.get("chunk") == chunk and r["t"] >= since])
    row = {"t": time.time(), "kind": kind, "result": result, "chunk": chunk, "motion": motion, "model": None, "missing": []}
    if backend is not None:
        prompt = (f"A robot arm's attempt failed: {result!r} (kind {kind}). Measured from its 30 Hz trace: {json.dumps(motion)}. Past results "
                  f"of this kind: {json.dumps([{k: r.get(k) for k in ('hypothesis', 'missing')} for r in past[-5:]])}. Images, if any, are "
                  f"the cameras at or after the stop. Which explains it best? {json.dumps(HYPOTHESES)} Say what evidence is missing to be sure.")
        try:
            answer = backend(prompt, images, SCHEMA)
            if answer.get("hypothesis") not in HYPOTHESES:
                raise ValueError(f"answered {answer.get('hypothesis')!r}")
            row["model"] = {"hypothesis": answer["hypothesis"], "reason": str(answer.get("reason", ""))[:400]}
            row["missing"] = [str(m)[:160] for m in answer.get("missing", [])][:6]
        except Exception as exc:  # the model is advice: without it the measurement stands
            row["model"] = {"hypothesis": None, "reason": f"model unavailable: {str(exc)[:120]}"}
    picked = (row["model"] or {}).get("hypothesis")
    measured = motion["verdict"] if motion["verdict"] != "undetermined" else None
    row["hypothesis"] = measured or picked or "unknown"
    row["by"] = "measurement" if measured else ("model" if picked and picked != "unknown" else "nobody")
    row["disagree"] = bool(measured and picked and picked not in (measured, "unknown"))
    row["repeat_unknown"] = row["hypothesis"] == "unknown" and any(r.get("hypothesis") == "unknown" and r["t"] >= since for r in past)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def open_questions(path: Path) -> dict:
    """Kind -> how often its cause stayed unknown or the model disagreed, and the evidence asked for."""
    out = {}
    for line in (path.read_text().splitlines() if path.exists() else []):
        row = json.loads(line)
        if row.get("hypothesis") == "unknown" or row.get("disagree"):
            q = out.setdefault(row["kind"], {"times": 0, "missing": [], "last": None})
            q["times"] += 1
            q["last"] = row["result"]
            q["missing"] = sorted(set(q["missing"]) | set(row.get("missing", [])))
    return out


def flushing_trace(file):
    """One JSON line per tick, on disk once a chunk ends: cell_why reads a stop while the session is still alive."""
    last = [None]

    def write(row):
        file.write(json.dumps(row, default=float) + "\n")  # a motor read may be numpy: a trace line must not stop the tick
        if row["chunk"] != last[0]:
            file.flush()
        last[0] = row["chunk"]
    return write


def read_trace(path: Path) -> list:
    """The rows that can be read: a live session's last line may be cut, and a tick without a full command has no `sent`."""
    rows = []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("sent") and row.get("present"):
            rows.append(row)
    return rows


def ollama(url: str, model: str, timeout: int = 180):
    """Bound here rather than through judge_seat, whose imports this host may not have; the same request."""
    import urllib.request

    def ask(prompt, images, schema):
        body = {"model": model, "stream": False, "format": schema, "options": {"temperature": 0, "seed": 42},
                "messages": [{"role": "user", "content": prompt, "images": list(images)}]}
        request = urllib.request.Request(f"{url}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(json.loads(reply.read())["message"]["content"])
    return ask


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", required=True)
    ap.add_argument("--at", help="the chunk that stopped")
    ap.add_argument("--result", default="")
    ap.add_argument("--trace", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--images", nargs="*", type=Path, default=[])
    ap.add_argument("--url")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    args = ap.parse_args(argv)
    images = [base64.b64encode(p.read_bytes()).decode() for p in args.images]
    row = explain(args.kind, args.result, read_trace(args.trace), images, ollama(args.url, args.model) if args.url else None, args.out, args.at)
    print(json.dumps({"why": row, "open": open_questions(args.out)}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
