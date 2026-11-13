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
import itertools
import math

import cell_params as prm

MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
MOTORS_BY_DOF = {
    5: MOTORS,
    6: ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll", "gripper"),
    7: ("shoulder_pan", "shoulder_lift", "elbow_roll", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll", "gripper"),
}


def motors_for_frame_len(frame_len: int) -> tuple[str, ...]:
    """Return the `(dof + 1)` joint name tuple (ending with `'gripper'`) for 5-DOF (6), 6-DOF (7), or 7-DOF (8) frames."""
    return MOTORS_BY_DOF.get(max(5, int(frame_len) - 1), MOTORS)
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
    acc = [0.0, *itertools.accumulate(e)]
    half = SMOOTH // 2
    n = len(e)
    return [v - (acc[min(n, i + half + 1)] - acc[max(0, i - half)]) / (min(n, i + half + 1) - max(0, i - half)) for i, v in enumerate(e)]


def _eval_trace_buf(buf):
    n = len(buf)
    dur = buf[-1]["t"] - buf[0]["t"]
    t0, chunk = buf[0]["t"], buf[0]["chunk"]
    sents = [b["sent"] or b["target"] for b in buf]
    presents = [b["present"] for b in buf]
    f_len = len(sents[0])
    joint_names = motors_for_frame_len(f_len)
    half = SMOOTH // 2
    inv_n = 1.0 / n
    inv_dur = 1.0 / dur
    out = []
    for i, joint in enumerate(joint_names[:f_len]):
        sent = [s[i] for s in sents]
        present = [p[i] for p in presents]
        e = [p - s for p, s in zip(present, sent)]
        acc = [0.0, *itertools.accumulate(e)]
        res = [v - (acc[min(n, k + half + 1)] - acc[max(0, k - half)]) / (min(n, k + half + 1) - max(0, k - half)) for k, v in enumerate(e)]
        out.append({
            "t": t0,
            "chunk": chunk,
            "joint": joint,
            "still": max(sent) - min(sent) < STILL,
            "p2p": max(present) - min(present),
            "lag": max(-min(e), max(e)),
            "at": sum(present) * inv_n,
            "std": math.sqrt(sum(v * v for v in res) * inv_n),
            "flips_hz": _flips(res, DEADBAND) * inv_dur,
        })
    return out


def trace_windows(rows, window_s=WINDOW_S):
    """rows: trace dicts (t, chunk, target, sent, present), oldest first. One dict per window and joint:
    {t, chunk, joint, still, p2p, lag, at (mean present), std, flips_hz}. `sent` falls back to `target` when the runner could not read it."""
    out, buf = [], []
    for r in itertools.chain(rows, (None,)):
        if buf and (r is None or r["t"] - buf[-1]["t"] > MAX_GAP_S or r["t"] - buf[0]["t"] >= window_s):
            if len(buf) >= MIN_TICKS:
                out.extend(_eval_trace_buf(buf))
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
    hits = []
    if trace:
        h_std, h_flips = prm.get(params, "jitter.hold_std"), prm.get(params, "jitter.hold_flips_hz")
        m_std, m_flips = prm.get(params, "jitter.move_std"), prm.get(params, "jitter.move_flips_hz")
        for w in trace:
            if w["still"]:
                if w["std"] >= h_std and w["flips_hz"] >= h_flips:
                    hits.append((w["joint"], f"{w['joint']} hold: present swings {w['std']:.2f} units (std) around the command, "
                                             f"{w['flips_hz']:.1f} crossings/s"))
            elif w["std"] >= m_std and w["flips_hz"] >= m_flips:
                hits.append((w["joint"], f"{w['joint']} move: present swings {w['std']:.2f} units (std) around the command, "
                                         f"{w['flips_hz']:.1f} crossings/s"))
    if health:  # the gripper dithers holding a box (std up to 29, 2.8 flips/s): only the trace judges it
        p_std, p_flips = prm.get(params, "jitter.pwm_std"), prm.get(params, "jitter.pwm_flips_hz")
        for w in health:
            if w["joint"] != "gripper" and w["pwm_std"] >= p_std and w["pwm_flips_hz"] >= p_flips:
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
    wins = _eval_trace_buf(buf)
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


SWAY_CHUNKS = ("descend", "lift")  # Z moves only: transits lag the plan on purpose and would read as sway
SWAY_SMOOTH = 5                     # ticks of moving mean: drops the ~0.2 mm tick-step dither, keeps the rock


def tcp_error(target, present):
    """(radial mm, jaw pitch deg) of `present` minus `target`, OMX 5-DoF order. The per-joint judge above misses
    elbow_flex and wrist_flex lagging in opposite directions: each stays under 0.15 unit while the jaw rocks 2-7 mm
    (2026-11-13 traces, arm_s and arm_b)."""
    from omx_adapter.z_profile import _fk_tcp_xyz_mm

    # shortcut: arm_b jaw length (74.1 mm) for every arm, so arm_s (91.9 mm) radial reads ~20% low; pass the arm's
    # jaw length if a threshold ever needs to be exact per arm
    pt, pp = _fk_tcp_xyz_mm(target[:5], unit="norm"), _fk_tcp_xyz_mm(present[:5], unit="norm")
    return math.hypot(pp[0], pp[1]) - math.hypot(pt[0], pt[1]), (sum(present[1:4]) - sum(target[1:4])) * 1.8


def sway_window(rows, params=None):
    """Jaw sway over the latest WINDOW_S of one Z chunk, from rows carrying `tcp` (tcp_error): peak-to-peak of the
    smoothed radial and pitch error and how often the detrended error swings across +-limit/4. Swaying when either
    reaches its jitter.sway_* limit and swings back at least twice. None until MIN_TICKS such rows exist."""
    buf = []
    for r in reversed(rows):
        if "tcp" not in r or (buf and (r["chunk"] != buf[0]["chunk"] or buf[-1]["t"] - r["t"] > MAX_GAP_S
                                       or buf[0]["t"] - r["t"] >= WINDOW_S)):
            break
        buf.append(r)
    if len(buf) < MIN_TICKS:
        return None
    out = {}
    for k, key, flips, limit in ((0, "radial_mm", "radial_flips", prm.get(params, "jitter.sway_mm")),
                                 (1, "pitch_deg", "pitch_flips", prm.get(params, "jitter.sway_deg"))):
        v = [r["tcp"][k] for r in buf[::-1]]
        s = [sum(v[i:i + SWAY_SMOOTH]) / SWAY_SMOOTH for i in range(len(v) - SWAY_SMOOTH + 1)]
        n, mx, my = len(s), (len(s) - 1) / 2, sum(s) / len(s)
        slope = sum((i - mx) * (y - my) for i, y in enumerate(s)) / sum((i - mx) ** 2 for i in range(n))
        # a lag that only grows or shrinks is one bow, not a rock: require the detrended error to swing back
        out[key] = round(max(s) - min(s), 2)
        out[flips] = _flips([y - my - slope * (i - mx) for i, y in enumerate(s)], limit / 4)
        out["swaying"] = out.get("swaying", False) or (out[key] >= limit and out[flips] >= 2)
    return out


def damp_step(ensembler, current: list, next_target: list, lookahead: list, *, vmax=None, fps=None) -> list:
    """Smooth `next_target` through `ensembler` over the upcoming chunk horizon while preserving the final endpoint."""
    if not lookahead:
        ensembler.reset(next_target)
        return list(next_target)
    if getattr(ensembler, "_last", None) is None:
        ensembler.reset(current)
    if vmax is not None:
        ensembler.vmax = vmax
    if fps is not None:
        ensembler.fps = fps
    ensembler.push([list(current), list(next_target), *[list(f) for f in lookahead[:3]]])
    return ensembler.step(next_target)


def blend_to_raw(ensembler, current_target: list[float], raw_target: list[float], remaining: int,
                 vmax: float = 5.0, fps: int = 30) -> list[float]:
    """Ease out the ensemble residual within the per-tick body speed limit."""
    ensembler.push([list(raw_target)])
    smoothed = ensembler.step(current_target)
    alpha = 1.0 / (max(1, remaining) + 1)
    step = vmax / max(1, fps)
    blended = [current + max(-step, min(step, (1 - alpha) * smooth + alpha * raw - current))
               for current, smooth, raw in zip(current_target[:5], smoothed[:5], raw_target[:5])]
    ensembler._smooth = list(blended)
    ensembler._last = blended + list(raw_target[5:])
    return ensembler._last


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
        arm_dof = max(5, len(state) - 1)
        avg = [sum(float(s[j]) for s in states) / len(states) for j in range(arm_dof)] + list(state[arm_dof:])
        return {**status, "state": avg, "samples": len(states)}
    return status


def suppress_tremor(frames: list[list[float]], *, coeff: float = 0.12, vmax: float = 5.0, fps: int = 30,
                    amax: float = 5.0, deadband: float = 0.12, dof: int | None = None) -> list[list[float]]:
    """Filter high-frequency policy/IK tremor (3-10 Hz) across an N-DOF (`dof in {5, 6, 7}`) trajectory chunk
    using a symmetric zero-lag 7-tap period-averaging notch filter plus forward-backward endpoint-pinned velocity
    envelope clamping on arm joints `[:arm_dof]` while preserving the gripper and exact start/end poses."""
    n = len(frames)
    if n <= 2:
        return [list(f) for f in frames]
    arm_dof = int(dof) if dof is not None else max(1, len(frames[0]) - 1)

    # 1. Symmetric zero-lag 7-tap boxcar filter on body joints (exact on linear ramps, >90% attenuation at 4-5 Hz)
    out: list[list[float]] = [list(frames[0])]
    for i in range(1, n - 1):
        row = list(frames[i])
        half = min(3, i, n - 1 - i)
        span = 2 * half + 1
        for j in range(min(arm_dof, len(row))):
            val = sum(float(frames[i + k][j]) for k in range(-half, half + 1)) / span
            if deadband > 0.0 and abs(val - out[-1][j]) < deadband * 0.25:
                val = out[-1][j]
            row[j] = val
        out.append(row)
    out.append(list(frames[-1]))

    # 2. Forward-backward endpoint-pinned velocity envelope bound (honors vmax/fps when chord is feasible)
    if vmax > 0.0 and fps > 0:
        dt = 1.0 / float(fps)
        step_cap = float(vmax) * dt
        for j in range(min(arm_dof, len(out[0]))):
            chord_step = abs(float(out[-1][j]) - float(out[0][j])) / max(1, n - 1)
            eff_cap = max(step_cap, chord_step * 1.05)
            for i in range(1, n - 1):
                lo_f = float(out[i - 1][j]) - eff_cap
                hi_f = float(out[i - 1][j]) + eff_cap
                rem = n - 1 - i
                lo_b = float(out[-1][j]) - rem * eff_cap
                hi_b = float(out[-1][j]) + rem * eff_cap
                lo, hi = max(lo_f, lo_b), min(hi_f, hi_b)
                if lo <= hi:
                    out[i][j] = min(max(float(out[i][j]), lo), hi)
    return out

