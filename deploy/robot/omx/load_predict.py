"""Before motion: the PWM each load-bearing joint will need to hold a plan's poses, from the arm's own field data.

load_model.py fits the model (rosy.omx-load-model.v1, per arm = the follower's USB serial tail) from the follower
motor-health logs at standstill; this module (stdlib, no numpy) applies it to a chunk library and says per chunk
ok / risky / unknown. risky: the predicted hold needs loadcheck.risky_share of the joint's session cap or more
(0.5: the most any logged standstill outside a press ever needed). unknown: a pose in a (lift, elbow, wrist) cell the logs hold fewer than
loadcheck.min_cell standstill samples of, or a pan/roll outside what was seen: the model says nothing there and is
not extrapolated. Poses are LeRobot units (-100..100 over the raw 0..4095 turn, 1.8 deg a unit) as in the library.
A risky plan is refused at `load` (chunk_runner) before any motion; unknown poses are reported and still load unless
loadcheck.refuse_unknown is 1.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cell_params as prm

SCHEMA = "rosy.omx-load-model.v1"
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex")
DEG_PER_UNIT = 1.8
CELL = 5  # units per (lift, elbow, wrist) coverage cell


def angles(pose, signs):
    """Cumulative pitch angles (rad) of lift, lift+elbow and lift+elbow+wrist; signs: the elbow and wrist senses
    the fit chose against the lift's (the library does not say which way a joint's positive turns)."""
    a1 = pose[1] * DEG_PER_UNIT
    a2 = a1 + signs[0] * pose[2] * DEG_PER_UNIT
    return [math.radians(a) for a in (a1, a2, a2 + signs[1] * pose[3] * DEG_PER_UNIT)]


def features(pose, signs):
    """1, then sin/cos of each cumulative angle: a gravity torque is a sum of those terms plus a friction offset."""
    return [1.0] + [f(a) for a in angles(pose, signs) for f in (math.sin, math.cos)]


def cell(pose):
    return ",".join(str(round(pose[i] / CELL)) for i in (1, 2, 3))


_MODEL_CACHE: dict[str, tuple[int, int, dict]] = {}


def load(path):
    p = Path(path)
    try:
        st = p.stat()
        key = str(p)
        cached = _MODEL_CACHE.get(key)
        if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return cached[2]
        model = json.loads(p.read_text(encoding="utf-8-sig"))
        if model.get("schema") != SCHEMA or not isinstance(model.get("arms"), dict):
            raise ValueError(f"not a {SCHEMA} file")
        _MODEL_CACHE[key] = (st.st_mtime_ns, st.st_size, model)
        return model
    except OSError:
        model = json.loads(p.read_text(encoding="utf-8-sig"))
        if model.get("schema") != SCHEMA or not isinstance(model.get("arms"), dict):
            raise ValueError(f"not a {SCHEMA} file")
        return model


def arm_for(model, port):
    """The model's arm whose USB serial tail the follower port carries, else None."""
    return next((a for a in model["arms"] if a in str(port)), None)


def predict(arm, pose):
    x = features(pose, arm["signs"])
    return {j: sum(c * v for c, v in zip(arm["joints"][j]["coef"], x)) for j in BODY[1:]}


def unknown_reason(arm, pose, min_cell):
    c = cell(pose)
    if arm["cells"].get(c, 0) < min_cell:
        return "lift/elbow/wrist " + c + " cell has fewer than " + str(min_cell) + " standstill samples"
    for i, j in ((0, "shoulder_pan"), (4, "wrist_roll")):
        lo, hi = arm["range"][j]
        if not lo - CELL <= pose[i] <= hi + CELL:
            return f"{j} {pose[i]:.1f} outside the logged {lo:.1f}..{hi:.1f}"
    return None


def gravity_pwm(arm, pose, min_cell: int = 5) -> dict[str, float]:
    """Predicted standstill gravity-hold PWM per pitch joint when `pose` lies in a covered cell; else `{}`."""
    if not arm or unknown_reason(arm, pose, min_cell) is not None:
        return {}
    return predict(arm, pose)


def check_chunk(arm, frames, fps, params=None, caps=None):
    """{verdict, joints: {joint: {pwm, at, share}}, unknown: first reason or None} for one chunk. Every pose a
    second apart plus the last frame is judged (a hold is where the arm rests; the path between is not a hold)."""
    share, min_cell = prm.get(params, "loadcheck.risky_share"), prm.get(params, "loadcheck.min_cell")
    idx = sorted(set(range(0, len(frames), max(1, fps))) | {len(frames) - 1})
    worst, unknown = {j: {"pwm": 0.0, "at": 0, "share": 0.0} for j in BODY[1:]}, None
    for k in idx:
        bad = unknown_reason(arm, frames[k], min_cell)
        if bad:
            unknown = unknown or f"frame {k}: {bad}"
            continue  # no prediction where the data has none
        for j, pwm in predict(arm, frames[k]).items():
            spec = arm["joints"][j]
            cap = (caps or {}).get(j) or spec["cap"]
            s = abs(pwm) / cap
            if s > worst[j]["share"]:
                worst[j] = {"pwm": round(pwm), "at": k, "share": round(s, 3)}
    risky = [j for j, w in worst.items() if w["share"] >= share]
    return {"verdict": "risky" if risky else ("unknown" if unknown else "ok"), "risky": risky, "joints": worst,
            "unknown": unknown}


def check(model, port, library, params=None, caps=None):
    """{verdict, chunks}: risky if any chunk is, else unknown if any is, else ok. An arm the model has not seen
    is unknown, never ok."""
    arm = model["arms"].get(arm_for(model, port))
    if arm is None:
        return {"verdict": "unknown", "chunks": {}, "reason": "no load model for this follower's USB serial"}
    chunks = {n: check_chunk(arm, f, library["fps"], params, caps) for n, f in library["chunks"].items()}
    verdicts = {c["verdict"] for c in chunks.values()}
    return {"verdict": next(v for v in ("risky", "unknown", "ok") if v in verdicts), "chunks": chunks}


def refuse(model, port, library, params=None, caps=None, status=lambda row: print(json.dumps(row), flush=True)):
    """The runner's plan check: report the verdict, raise ValueError (the `load` command's refusal) when risky,
    or when unknown and loadcheck.refuse_unknown is 1."""
    out = check(model, port, library, params, caps)
    status({"event": "load_check", "verdict": out["verdict"], "chunks": {
        n: {k: c[k] for k in ("verdict", "risky", "unknown")} | {"worst": c["joints"]} for n, c in out["chunks"].items()
        if c["verdict"] != "ok"}, "reason": out.get("reason")})
    if out["verdict"] == "risky" or (out["verdict"] == "unknown" and prm.get(params, "loadcheck.refuse_unknown")):
        bad = [f"{n} {c['risky'] or c['unknown']}" for n, c in out["chunks"].items() if c["verdict"] == out["verdict"]]
        raise ValueError(f"load check {out['verdict']}: {out.get('reason') or '; '.join(bad)}")
    return out


def plan_check(path, port, params, library, caps=None):
    """chunk_runner's startup: the `plan_check(library)` the Runner applies at every `load`, after refusing the first
    library here (SystemExit, before motion). Both checks use the session's caps; None without a model file."""
    if not path:
        return None
    model = load(path)
    check = lambda lib: refuse(model, port, lib, params, caps)  # noqa: E731
    check.arm = model["arms"].get(arm_for(model, port))
    try:
        check(library)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return check
