#!/usr/bin/env python3
"""Why did it stop? Read the failure from what was recorded, ask the decision model what is left, and keep what is still unknown.

2026-11-07: the first held lift stopped, and "why" stayed a guess for an hour with the answer on disk. The runner's trace
(30 Hz, sent and present per joint) showed the wrist still moving at half the commanded speed. That alone does not mean too
fast: the descents the work record calls real contact keep moving too (0.20-0.75 of the command, free wrist motion 0.33-0.79).
Measurement reads first and says only what it can: a joint that nearly stood still under a moving command was blocked; one that
kept moving is read against the same chunk's runs that met nothing (SEED, learn), and is undetermined without them. On the arm that reading orders the recovery, goes into the incident report (omx_incident) and so to the AI PC's
explanation in Fleet (D-971); the control PC calls no model. Off the arm (this CLI, on a host with the model) the model sees the
same facts, the frames and past rows of the kind, says what they show, picks among HYPOTHESES and says which evidence is missing.
Its answer is text: it cannot overrule the measurement (a disagreement stays an open question) and chooses no action. Two
stages: which kind of stop it was comes from the result's text (cell_diagnose); why an arm stopped (ARM_CAUSES) only from the
measurement, so a model's arm cause is kept as advice and the row stays unknown. A kind that stays unknown
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
SAME_START, SAME_STOP, SLOWER, NOT_FASTER = 1.0, 2.0, 0.85, 1.05
# What a chunk lags with nothing in the way: per chunk and joint, [command peak units/s, largest lag] of runs that ended
# without a guard stop. Seeded with arm_b descend_pick over the bare table (air_descend, 2026-11-07 00:36) and the two
# finished pick descents of that night; every carry adds its finished runs (learn). Lag depends on the chunk, not only on
# speed: at wrist_flex 2-2.5 units/s pick descents lagged at most 0.78, transit moves up to 2.15, so no chunk borrows
# another's. Only runs at least as fast as the stop count, and at least MIN_FREE of them:
# - the stop's lag reached FREE_MARGIN times theirs (1.8: twice was the stop limit itself, the 00:17 stops ended at 1.56): blocked;
# - they lagged SPEED_LIKE of the stop's lag and ran on: with nothing in the way the joint lags that much, so the command
#   outran it: too_fast (2026-11-07 01:34 a held lift ran to its end at 3.80 units/s and lag 2.10; 02:15's stopped at 3.58, 2.25).
SEED = {"descend_pick": {"wrist_flex": [[2.34, 0.64], [2.29, 0.63], [2.34, 0.78]]}}
FREE_MARGIN, FREE_SPEED_SLACK, SPEED_LIKE, MIN_FREE, STOP_LAG, KEEP_RUNS = 1.8, 1.02, 0.9, 2, 1.3, 200
HYPOTHESES = {
    # not "kept moving but slower": that hands the answer to every moving-joint stop, contact included (11-07 comparison)
    "too_fast": "the command outran the joint; nothing was in the way. Check: the same move slower",
    "blocked": "the joint stood still under a moving command: something holds the arm or what it carries. Check: frames at the stop; move the thing clear",
    "snagged": "the held box or a finger caught a neighbour or a rim: the load rose only once it moved. Check: side and wrist frames; a neighbour moved",
    "wrong_position": "the arm came down beside where the box really is. Check: top view against the plan, jaw marks",
    "camera_or_map": "the view or the map was wrong, not the arm. Check: a fresh view, the map's error here",
    "unknown": "none of these fits what is shown: name the evidence that would tell",
}
# Why an arm stopped is the measurement's: in 13 recorded failures no model told contact from speed or a snag, from frames
# after the stop or from the trace, and each guessed differently. Its pick of these stays advice; the row says unknown.
ARM_CAUSES = {"too_fast", "blocked", "snagged"}
# what is shown before the pick: an answer that has to name its evidence first guesses less (seen is the first property)
SCHEMA = {"type": "object", "required": ["seen", "hypothesis", "reason", "missing"],
          "properties": {"seen": {"type": "string"}, "hypothesis": {"type": "string", "enum": list(HYPOTHESES)}, "reason": {"type": "string"},
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


def _lag(r, j):
    return abs(r["present"][j] - r["sent"][j])


def _peak(rows, j) -> float:
    """The command's fastest 5-tick stretch on joint j: the speed a baseline is kept at."""
    return max((abs(b["sent"][j] - a["sent"][j]) / (b["t"] - a["t"]) for a, b in zip(rows, rows[5:]) if b["t"] > a["t"]), default=0.0)


def _load(rows, j) -> dict:
    """Joint j's current and PWM at the run's last health reading, and its largest current in the run; {} without one."""
    loads = [r["load"] for r in rows if r.get("load")]
    if not loads:
        return {}
    return {"current_ma_end": loads[-1]["current_ma"][j], "pwm_load_end": loads[-1]["pwm"][j],
            "current_ma_peak": max(abs(load["current_ma"][j]) for load in loads)}


def free_runs(rows: list) -> dict:
    """chunk -> joint -> [[peak, largest lag, start t, largest current or None]] of the trace's runs that ended with every
    joint under STOP_LAG. The current is kept for a load baseline once stops carry it too."""
    out, start = {}, 0
    for i in range(1, len(rows) + 1):
        if i < len(rows) and rows[i].get("chunk") == rows[start].get("chunk"):
            continue
        run, start = rows[start:i], i
        if not run[0].get("chunk") or len(run) < 10 or max(_lag(run[-1], j) for j in range(5)) >= STOP_LAG:
            continue
        for j in (1, 2, 3):  # the pitch joints; the guard stops on them
            peak = _peak(run, j)
            if peak >= MIN_SPEED:
                out.setdefault(run[0]["chunk"], {}).setdefault(JOINTS[j], []).append(
                    [round(peak, 2), round(max(_lag(r, j) for r in run), 2), round(run[0]["t"], 2), _load(run, j).get("current_ma_peak")])
    return out


def learn(rows: list, path: Path) -> dict:
    """Add the trace's finished runs to the baseline file (once each, by start t) and return SEED with it."""
    kept = json.loads(path.read_text()) if path.exists() else {}
    for chunk, joints in free_runs(rows).items():
        for joint, runs in joints.items():
            have = kept.setdefault(chunk, {}).setdefault(joint, [])
            have += [r for r in runs if r[2] not in {h[2] for h in have}]
            # shortcut: the newest KEEP_RUNS per chunk and joint (2 days gave 170 transit runs); keep the fastest instead
            # if old fast runs start to matter
            del have[:-KEEP_RUNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept))
    return {c: {j: SEED.get(c, {}).get(j, []) + kept.get(c, {}).get(j, []) for j in set(SEED.get(c, {})) | set(kept.get(c, {}))}
            for c in set(SEED) | set(kept)}


def read_motion(rows: list, free: dict | None = None) -> dict:
    """The joint that fell behind most in a chunk, and what it did in the last WINDOW_S: did it keep moving? Read against
    `free` (learn; SEED when none): what the same chunk lagged on the same joint with nothing in the way."""
    if len(rows) < 3:
        return {"verdict": "undetermined", "why": "no trace of this chunk"}
    lag = _lag
    worst = max(range(5), key=lambda j: lag(rows[-1], j))
    tail = [r for r in rows if r["t"] >= rows[-1]["t"] - WINDOW_S]
    span = tail[-1]["t"] - tail[0]["t"] or 1.0
    sent = abs(tail[-1]["sent"][worst] - tail[0]["sent"][worst]) / span
    present = abs(tail[-1]["present"][worst] - tail[0]["present"][worst]) / span
    facts = {"joint": JOINTS[worst], "lag_start": round(lag(rows[0], worst), 2), "lag_end": round(lag(rows[-1], worst), 2),
             "sent_units_s": round(sent, 2), "present_units_s": round(present, 2), "seconds": round(rows[-1]["t"] - rows[0]["t"], 2),
             "other_joints_lag_rise": {JOINTS[j]: round(lag(rows[-1], j) - lag(rows[0], j), 2) for j in range(5) if j != worst},
             "jaws": rows[-1]["present"][5], "start": rows[0]["sent"][:5], "stopped_at": rows[-1]["present"][:5],
             "pwm_end": (rows[-1].get("pwm") or {}).get(JOINTS[worst]),
             # chunk_runner's 1 Hz health reading (load); no verdict from it yet: no contact has been recorded with it
             **_load(rows, worst)}
    # a run that did not end on lag is no stop to explain: a finished descent's last half second, its arm already at the
    # target while the command eased in, read blocked, and a baseline would read its small lag too_fast
    if sent < MIN_SPEED or facts["lag_end"] - facts["lag_start"] < MIN_RISE or facts["lag_end"] < STOP_LAG:
        return {**facts, "verdict": "undetermined", "why": "the command was not moving, or the lag did not grow to a stop"}
    moved = f"{facts['joint']} moved {present:.2f} of {sent:.2f} units/s"
    if present < BLOCKED_RATIO * sent:
        return {**facts, "verdict": "blocked", "why": moved}
    facts["peak_units_s"] = round(_peak(rows, worst), 2)
    runs = [r for r in (free or SEED).get(rows[-1].get("chunk"), {}).get(facts["joint"], [])
            if r[0] * FREE_SPEED_SLACK >= facts["peak_units_s"]]  # as fast as this one or faster
    if len(runs) >= MIN_FREE:
        most = max(r[1] for r in runs)
        said = f"{moved}; {len(runs)} runs of this chunk as fast, with nothing in the way, lagged at most {most}"
        if facts["lag_end"] >= FREE_MARGIN * most:
            return {**facts, "verdict": "blocked", "why": said}
        if most >= SPEED_LIKE * facts["lag_end"]:
            return {**facts, "verdict": "too_fast", "why": f"{said} and ran on"}
    return {**facts, "verdict": "undetermined", "why": f"{moved}: contact and free motion both keep moving like this"}


def read_repeat(motion: dict, earlier: list) -> dict:
    """What the speed ratio cannot tell, a retry can: slower, or from another start at no higher speed, yet stopped at the same
    place, so speed is excluded.
    shortcut: a load limit at that pose reads as blocked too; the push it chooses ends at a person if the top view shows no change."""
    if motion["verdict"] != "undetermined" or not earlier or "start" not in motion or "start" not in (earlier[-1].get("motion") or {}):
        return motion
    before = earlier[-1]["motion"]
    gap = lambda a, b: max(abs(x - y) for x, y in zip(a, b))  # noqa: E731
    stood = motion["sent_units_s"] >= MIN_SPEED and motion["lag_end"] - motion["lag_start"] >= MIN_RISE
    if not stood or gap(motion["stopped_at"], before["stopped_at"]) > SAME_STOP:
        return motion
    if gap(motion["start"], before["start"]) <= SAME_START and motion["sent_units_s"] <= SLOWER * before["sent_units_s"]:
        return {**motion, "verdict": "blocked", "why": f"slower ({before['sent_units_s']} -> {motion['sent_units_s']} units/s), stopped at the same place"}
    # A lag that outgrows the command builds with time from the chunk's start, so another start moves the stop with it.
    # Real pair: 2026-11-07 00:17 -> 01:15, start 2.8 apart (FK z 31 -> 43 mm), 1.98 -> 2.07 units/s, stop 0.3 apart (z 15.5 mm).
    if gap(motion["start"], before["start"]) > SAME_START and motion["sent_units_s"] <= NOT_FASTER * before["sent_units_s"]:
        return {**motion, "verdict": "blocked", "why": "started elsewhere at no higher speed, stopped at the same place"}
    return motion


def past_rows(path: Path, kind: str) -> list:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == kind]


def explain(kind: str, result: str, trace: list, images: list, backend, path: Path, chunk: str | None = None, since: float = 0.0,
            free: dict | None = None) -> dict:
    """One row in why.jsonl: measured verdict, the model's pick and missing evidence, and the final `hypothesis`. `repeat_unknown`
    counts only rows since `since`: an unknown of last week is an open question, not this carry's second try."""
    chunk = chunk or chunk_of(result)
    motion = read_motion(last_run(trace, chunk), free) if chunk else {"verdict": "undetermined", "why": "no chunk named"}
    past = past_rows(path, kind)
    motion = read_repeat(motion, [r for r in past if r.get("chunk") == chunk and r["t"] >= since])
    row = {"t": time.time(), "kind": kind, "result": result, "chunk": chunk, "motion": motion, "model": None, "missing": []}
    if backend is not None:
        prompt = (f"A robot arm's attempt failed: {result!r} (kind {kind}). Measured from its 30 Hz trace: {json.dumps(motion)}. Past results "
                  f"of this kind: {json.dumps([{k: r.get(k) for k in ('hypothesis', 'missing')} for r in past[-5:]])}. Images, if any, are "
                  f"the cameras at or after the stop. First say what the record and images show. Then which explains it best? "
                  f"{json.dumps(HYPOTHESES)} Frames after a stop rarely show contact: without a frame at the moment or a repeat, "
                  "choose unknown over too_fast, blocked or snagged. Say what evidence is missing to be sure.")
        try:
            answer = backend(prompt, images, SCHEMA)
            if answer.get("hypothesis") not in HYPOTHESES:
                raise ValueError(f"answered {answer.get('hypothesis')!r}")
            row["model"] = {"hypothesis": answer["hypothesis"], "reason": str(answer.get("reason", ""))[:400], "seen": str(answer.get("seen", ""))[:400]}
            row["missing"] = [str(m)[:160] for m in answer.get("missing", [])][:6]
        except Exception as exc:  # the model is advice: without it the measurement stands
            row["model"] = {"hypothesis": None, "reason": f"model unavailable: {str(exc)[:120]}"}
    said = (row["model"] or {}).get("hypothesis")
    picked = None if said in ARM_CAUSES else said  # an arm cause stays advice in row["model"]
    measured = motion["verdict"] if motion["verdict"] != "undetermined" else None
    row["hypothesis"] = measured or picked or "unknown"
    row["by"] = "measurement" if measured else ("model" if picked and picked != "unknown" else "nobody")
    row["disagree"] = bool(measured and said and said not in (measured, "unknown"))
    row["repeat_unknown"] = row["hypothesis"] == "unknown" and any(r.get("hypothesis") == "unknown" and r["t"] >= since for r in past)
    # Something measured at this place explains the earlier stops there that stayed unknown: they leave the open questions.
    # Real: 23:09 unknown, 23:27 blocked 1.3 apart; 00:17 unknown, 01:15 blocked 0.3 apart. Recovery is not changed by it.
    row["settles"] = [r["t"] for r in past if measured == "blocked" and r.get("hypothesis") == "unknown" and r.get("chunk") == chunk
                      and "stopped_at" in (r.get("motion") or {}) and "stopped_at" in motion
                      and max(abs(a - b) for a, b in zip(r["motion"]["stopped_at"], motion["stopped_at"])) <= SAME_STOP]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def open_questions(path: Path) -> dict:
    """Kind -> how often its cause stayed unknown or the model disagreed, and the evidence asked for."""
    out = {}
    rows = [json.loads(line) for line in (path.read_text().splitlines() if path.exists() else [])]
    settled = {t for row in rows for t in row.get("settles", [])}
    for row in rows:
        if row["t"] in settled:
            continue
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
    ap.add_argument("--free", type=Path, help="the baseline file: the trace's finished runs are added, then read against")
    args = ap.parse_args(argv)
    images = [base64.b64encode(p.read_bytes()).decode() for p in args.images]
    trace = read_trace(args.trace)
    row = explain(args.kind, args.result, trace, images, ollama(args.url, args.model) if args.url else None, args.out, args.at,
                  free=learn(trace, args.free) if args.free else None)
    print(json.dumps({"why": row, "open": open_questions(args.out)}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
