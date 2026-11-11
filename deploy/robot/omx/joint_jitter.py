"""Shaking of an OMX joint, measured from the runner's per-tick trace and the 4 Hz motor-health samples.

Two signals, because they see different frequencies:
- trace rows (ROSY_CHUNK_TRACE, one per control tick, ~30 Hz, LeRobot units): sees tremor up to ~15 Hz. Per joint and
  window it takes e = present - sent, removes its 0.5 s moving mean (lag and slow drift are not shaking) and reports
  the std of what is left, its sign changes per second and the peak-to-peak of `present`, split into windows where
  that joint's command is still (a hold) and where it moves.
- health samples (~4 Hz, raw counts): alias anything above 2 Hz, so they only say "the PWM flips sign / varies at a
  standstill", never how fast. Per joint and window: PWM std and sign changes per second of the PWM around its mean.
The thresholds are cell_params (`jitter.*`), measured with jitter_replay.py over the field logs; rerun it on new logs
before changing them.
"""
import math

import cell_params as prm

MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
WINDOW_S = 2.0         # trace window length
MIN_TICKS = 30         # fewer ticks in a window: not judged
MAX_GAP_S = 0.2        # a pause in the trace ends the window
STILL = 0.3            # units the command may span in a hold (same as joint_push.STILL)
SMOOTH = 15            # ticks of the moving mean removed from present - sent (0.5 s)
DEADBAND = 0.2         # units: sign changes below this are encoder quantisation (1 count = 0.088 deg)
HEALTH_WINDOW = 16     # health samples per window (~4 s)
PWM_DEADBAND = 10      # PWM units: flips below this are noise
H_STILL = 2            # raw counts the command and the present may span in a health hold


def _flips(values, band):
    """Sign changes of `values` that clear +-band, counting only a swing from one side to the other."""
    last, n = 0, 0
    for v in values:
        s = 1 if v > band else -1 if v < -band else 0
        if s and last and s != last:
            n += 1
        last = s or last
    return n


def _residual(sent, present):
    e = [p - s for p, s in zip(present, sent)]
    acc = [0.0]
    for v in e:
        acc.append(acc[-1] + v)
    half = SMOOTH // 2
    out = []
    for i, v in enumerate(e):
        lo, hi = max(0, i - half), min(len(e), i + half + 1)
        out.append(v - (acc[hi] - acc[lo]) / (hi - lo))
    return out


def trace_windows(rows, window_s=WINDOW_S):
    """rows: trace dicts (t, chunk, target, sent, present), oldest first. One dict per window and joint:
    {t, chunk, joint, still, p2p, lag, at (mean present), std, flips_hz}. `sent` falls back to `target` when the runner could not read it."""
    out, buf = [], []
    for r in list(rows) + [None]:
        if buf and (r is None or r["t"] - buf[-1]["t"] > MAX_GAP_S or r["t"] - buf[0]["t"] >= window_s):
            if len(buf) >= MIN_TICKS:
                dur = buf[-1]["t"] - buf[0]["t"]
                for i, joint in enumerate(MOTORS):
                    sent = [(b["sent"] or b["target"])[i] for b in buf]
                    present = [b["present"][i] for b in buf]
                    res = _residual(sent, present)
                    out.append({"t": buf[0]["t"], "chunk": buf[0]["chunk"], "joint": joint,
                                "still": max(sent) - min(sent) < STILL, "p2p": max(present) - min(present),
                                "lag": max(abs(a - b) for a, b in zip(present, sent)), "at": sum(present) / len(present),
                                "std": math.sqrt(sum(v * v for v in res) / len(res)),
                                "flips_hz": _flips(res, DEADBAND) / dur})
            buf = []
        if r is not None and (not buf or r["t"] - buf[-1]["t"] <= MAX_GAP_S):
            buf.append(r)
        elif r is not None:
            buf = [r]
    return out


def health_windows(samples, size=HEALTH_WINDOW):
    """samples: motor-health 'sample' rows (sample_time, motors[6]), oldest first. One dict per standstill window and
    joint: {t, joint, pwm_std, pwm_flips_hz}. A window is `size` consecutive samples less than 1 s apart in which
    the joint's command and present each span at most H_STILL counts."""
    out = []
    for k in range(0, len(samples) - size + 1, size):
        w = samples[k:k + size]
        if any(b["sample_time"] - a["sample_time"] > 1.0 for a, b in zip(w, w[1:])):
            continue
        dur = w[-1]["sample_time"] - w[0]["sample_time"]
        for i, joint in enumerate(MOTORS):
            col = lambda key: [s["motors"][i][key] for s in w]  # noqa: E731
            if max(col("command_raw")) - min(col("command_raw")) > H_STILL or max(col("present_raw")) - min(col("present_raw")) > H_STILL:
                continue
            pwm = col("pwm")
            mean = sum(pwm) / len(pwm)
            dev = [v - mean for v in pwm]
            out.append({"t": w[0]["sample_time"], "joint": joint, "pwm_std": math.sqrt(sum(v * v for v in dev) / len(dev)),
                        "pwm_flips_hz": _flips(dev, PWM_DEADBAND) / dur})
    return out


def shaking(trace=(), health=(), params=None):
    """(joint, reason) for every trace/health window above the jitter.* thresholds, in input order."""
    g = lambda name: prm.get(params, f"jitter.{name}")  # noqa: E731
    hits = []
    for w in trace:
        kind = "hold" if w["still"] else "move"
        if w["std"] >= g(f"{kind}_std") and w["flips_hz"] >= g(f"{kind}_flips_hz"):
            hits.append((w["joint"], f"{w['joint']} {kind}: present swings {w['std']:.2f} units (std) around the command, "
                                     f"{w['flips_hz']:.1f} crossings/s"))
    for w in health:  # the gripper dithers holding a box (std up to 29, 2.8 flips/s): only the trace judges it
        if w["joint"] != "gripper" and w["pwm_std"] >= g("pwm_std") and w["pwm_flips_hz"] >= g("pwm_flips_hz"):
            hits.append((w["joint"], f"{w['joint']} hold: PWM std {w['pwm_std']:.0f}, {w['pwm_flips_hz']:.1f} sign changes/s"))
    return hits


def live_window(rows, params=None) -> dict:
    """Real-time rolling jitter check over the latest contiguous tick window (>= MIN_TICKS)."""
    buf: list = []
    for r in reversed(rows):
        if buf and buf[-1]["t"] - r["t"] > MAX_GAP_S:
            break
        buf.append(r)
        if buf[0]["t"] - r["t"] >= WINDOW_S:
            break
    if len(buf) < MIN_TICKS:
        return {"shaking": False, "max_std": 0.0, "max_flips_hz": 0.0, "max_p2p": 0.0, "flagged": []}
    buf.reverse()
    wins = trace_windows(buf, window_s=buf[-1]["t"] - buf[0]["t"] + 1e-6)
    if not wins:
        return {"shaking": False, "max_std": 0.0, "max_flips_hz": 0.0, "max_p2p": 0.0, "flagged": []}
    hits = shaking(trace=wins, params=params)
    body = [w for w in wins if w["joint"] != "gripper"] or wins
    return {
        "shaking": bool(hits),
        "max_std": round(max(w["std"] for w in body), 3),
        "max_flips_hz": round(max(w["flips_hz"] for w in body), 2),
        "max_p2p": round(max(w["p2p"] for w in body), 3),
        "flagged": [{"joint": j, "reason": reason} for j, reason in hits],
    }


def damp_step(ensembler, current: list, next_target: list, lookahead: list) -> list:
    """Smooth `next_target` through `ensembler` over the upcoming chunk horizon while preserving the final endpoint."""
    if not lookahead:
        ensembler.reset(next_target)
        return list(next_target)
    if getattr(ensembler, "_last", None) is None:
        ensembler.reset(current)
    ensembler.push([list(current), list(next_target), *[list(f) for f in lookahead[:3]]])
    return ensembler.step(next_target)


def settled_state(cell, params=None) -> dict:
    """Read `cell.act('state')`, averaging `reach.samples` (or 3 when `jitter.shaking` is True) samples on `state[:5]`."""
    status = cell.act("state")
    state = status.get("state") if isinstance(status, dict) else None
    if not isinstance(state, (list, tuple)) or len(state) < 5 or not isinstance(state[0], (int, float)):
        return status
    samples = int(prm.get(params, "reach.samples", 1))
    if samples < 3 and (status.get("jitter") or {}).get("shaking"):
        samples = 3
    if samples <= 1:
        return status
    states = [list(state)]
    for _ in range(samples - 1):
        nxt = (cell.act("state") or {}).get("state")
        if isinstance(nxt, (list, tuple)) and len(nxt) >= 5 and isinstance(nxt[0], (int, float)):
            states.append(list(nxt))
    if len(states) > 1:
        avg = [sum(float(s[j]) for s in states) / len(states) for j in range(5)] + list(state[5:])
        return {**status, "state": avg, "samples": len(states)}
    return status


def suppress_tremor(frames: list[list[float]], *, coeff: float = 0.12, vmax: float = 5.0, fps: int = 30,
                    amax: float = 5.0, deadband: float = 0.12) -> list[list[float]]:
    """Filter high-frequency policy/IK tremor (3-10 Hz) across a trajectory chunk using a symmetric zero-lag
    7-tap period-averaging notch filter while preserving the exact start and end poses."""
    n = len(frames)
    if n <= 2:
        return [list(f) for f in frames]

    # Symmetric zero-lag 7-tap boxcar filter on body joints (exact on linear ramps, >90% attenuation at 4-5 Hz)
    out: list[list[float]] = [list(frames[0])]
    for i in range(1, n - 1):
        row = list(frames[i])
        half = min(3, i, n - 1 - i)
        span = 2 * half + 1
        for j in range(min(5, len(row))):
            val = sum(float(frames[i + k][j]) for k in range(-half, half + 1)) / span
            if deadband > 0.0 and abs(val - out[-1][j]) < deadband * 0.25:
                val = out[-1][j]
            row[j] = val
        out.append(row)
    out.append(list(frames[-1]))
    return out

