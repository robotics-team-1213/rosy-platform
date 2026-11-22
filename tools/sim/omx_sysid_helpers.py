#!/usr/bin/env python3
"""Register conversion, container friction sweep identification, candidate promotion, and next-experiment survey (`omx_sysid.py`).

Single responsibility: non-MuJoCo system identification helpers (`from_registers`, `sweeps`, `windows`,
`one_sweep`, `friction`, `verdict`, `promote`, `survey`) and shared constants for OMX physics fitting.
"""
import datetime as dt
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "deploy/robot/omx")]
import omx_physics as physics  # noqa: E402

SCHEMA = "rosy.omx-sysid-servo.v1"
BODY = physics.JOINTS[:5]
# kp spans the twin's grid (10-80) with room; the first fit on 2026-11-09 ran to 2 and 200, absorbing what the model lacks
BOUNDS = {"kp": (10., 120.), "kv": (.05, 30.), "damping": (.001, 5.), "armature": (1e-4, .1), "frictionloss": (1e-4, .5)}
# Lower bounds that stand for zero: a fit resting there says the term is not needed, not that it is unidentified
ZERO_FLOOR = {"damping", "armature", "frictionloss"}
WORSE_DEG = .1      # a fit may not make any held-out joint worse than this
HOLD = "0/3"        # omx_twin.shard_of: this share of the episode names is held out
EVERY = 2           # use every 2nd 50 Hz grid row in the fit (the hold-out score uses all)
# How each constant is narrowed. Real arm motion is a supervised trial only (D-911): person at the switch.
EXPERIMENTS = {
    "kp": "servo: fit on recorded episodes (no motion); cell_step.py ramps at home if sd stays wide (supervised, D-911)",
    "kv": "servo: fit on recorded episodes; cell_step.py ramps (supervised) separate it from damping",
    "damping": "servo: fit on recorded episodes; cell_step.py ramps (supervised) separate it from kv",
    "armature": "not reachable: the guard streams at most 5 units/s, a true step would be needed",
    "frictionloss": "servo: fit on recorded episodes (slow reversals show it)",
    "force": "not fitted: the guard stops a joint long before its stall torque, so this limit never acts in a real run",
    "zero_offset_deg": "twin fit-camera, then a known pose with a person (G-20)",
    "mass": "declared weight (arm-s-declared-weight), or a scale",
    "friction": "push test with the closed jaws (supervised, PWM against an empty pass), else tilt test by a person",
}

# -- registers ------------------------------------------------------------------------------------------------------------------
# What the real servos are set to, as the MuJoCo position servo (kp, kv, force). The fits above ran kp to their bounds
# (2026-11-09) because the real joints are a Dynamixel PID behind a PWM limit, far softer than the sim's kp 40.
# ROBOTIS e-Manual, X series position mode: PWM = KPP*e + KPI*sum(e) + KPD*de, KPP = P/128, KPI = I/65536, KPD = D/16,
# e in ticks (4096 a turn), the loop at 1 kHz; torque ~ PWM/885 * stall torque, less back-EMF (stall / no-load speed) * w.
MOTORS = {11: "XL430-W250", 12: "XL430-W250", 13: "XL430-W250", 14: "XL330-M288", 15: "XL330-M288"}
STALL = {"XL430-W250": (1.5, 12.0), "XL330-M288": (0.52, 5.0)}  # N·m at V, ROBOTIS e-Manual
STALL_CURRENT = {"XL330-M288": 1470}  # mA at the stall torque; a Current_Limit caps torque in proportion (XL430: no current register)
NO_LOAD = {"XL430-W250": (5.97, 11.1), "XL330-M288": (10.9, 5.0)}  # rad/s at V (57 and 104 rpm)
DEFAULT_GAINS = {"XL430-W250": {"p": 640, "i": 0, "d": 3600}, "XL330-M288": {"p": 400, "i": 0, "d": 0}}  # read back on arm_b 2026-11-08 (register probe)
TICKS_PER_RAD = 4096 / (2 * math.pi)


def from_registers(caps, volts):
    """{jointN: {kp, kv, force}} for joint1-5 from a session's caps (record_session: pwm, p, i per motor ID) and the
    motor-health voltages. An I gain has no MuJoCo position-servo term: it is listed, and the fit's gravity_comp stands
    in for it. The baseline P, I, D were read back on arm_b (2026-11-08 register probe); the 1 kHz loop is ROBOTIS's."""
    out, integral = {}, []
    for j, motor_id in enumerate(sorted(MOTORS)):
        model, cap = MOTORS[motor_id], caps.get(str(motor_id), {})
        gains = dict(DEFAULT_GAINS[model], **{k: cap[k] for k in ("p", "i") if k in cap})
        stall, rated = STALL[model]
        speed, at = NO_LOAD[model]
        v = volts[motor_id]
        per_pwm = stall * v / rated / 885  # N·m per PWM unit
        out[BODY[j]] = {"kp": round(per_pwm * gains["p"] / 128 * TICKS_PER_RAD, 3),
                        "kv": round(stall * v / rated / (speed * v / at) + per_pwm * gains["d"] / 16 * TICKS_PER_RAD / 1000, 4),
                        "force": round(min(per_pwm * cap.get("pwm", 885),  # 2026-11-09: arm_a's wrist at 250 mA holds 0.09, not 0.215
                                           stall * cap["current"] / STALL_CURRENT[model] if "current" in cap and model in STALL_CURRENT else 1e9), 3)}
        if gains["i"]:
            integral.append(BODY[j])
    return out, integral


# -- friction -------------------------------------------------------------------------------------------------------------------
FRICTION_SCHEMA = "rosy.omx-sysid-friction.v1"
PAN = "shoulder_pan"
G = 9.81
DATASHEET_SHARE = .25                # how far the datasheet constant may be off for this servo (back-EMF cancels in the difference)
MIN_SNR, MIN_SAMPLES = 3.0, 8


def sweeps(rows):
    """[(chunk, [(progress 0..1, pan PWM)], pan travel)] for each contiguous slide_push / slide_air segment of a runner trace
    (chunk_runner trace: one row per tick, the 5 Hz PWM sample repeated until the next)."""
    out, seg = [], []
    for r in rows + [{"chunk": None}]:
        if seg and r.get("chunk") != seg[0]["chunk"]:
            if seg[0]["chunk"] in ("slide_push", "slide_air") and len(seg) > 2:
                t0, t1 = seg[0]["t"], seg[-1]["t"]
                samples, last = [], None
                for x in seg:
                    p = (x.get("pwm") or {}).get(PAN)
                    if p is not None and x["pwm"] != last:  # shortcut: no sample time in the trace; a new reading equal in every joint is dropped
                        samples.append(((x["t"] - t0) / (t1 - t0), float(p)))
                    last = x.get("pwm")
                out.append((seg[0]["chunk"], samples, seg[-1]["present"][0] - seg[0]["present"][0]))
            seg = []
        if r.get("chunk") in ("slide_push", "slide_air"):
            seg.append(r)
    return out


def windows(gap_mm, push_mm):
    """(box moving, jaws short of the box) as shares of the sweep, from the push's geometry: contact at gap/push."""
    contact = gap_mm / push_mm
    if not 0 < contact < .6:
        raise SystemExit(f"gap {gap_mm} mm of a {push_mm} mm push leaves no clean window: push further")
    return (contact + .15, .9), (.05, max(.06, .8 * contact))


def one_sweep(rows, mass_kg, radius_m, motor="XL430-W250", volts=11.7, window=(.5, .9), before=(.05, .25)):
    """Friction from the last contact sweep and the air sweep after it: the pan's extra PWM in `window` (box moving) less its
    extra PWM in `before` (jaws not at the box yet), as a torque, over the radius, against the box's weight."""
    import numpy as np
    pairs = sweeps(rows)
    for i in range(len(pairs) - 1, 0, -1):
        if pairs[i][0] == "slide_air" and pairs[i - 1][0] == "slide_push":
            contact, air = pairs[i - 1], pairs[i]
            break
    else:
        raise SystemExit("no slide_push followed by slide_air in the trace: run cell_push.py --friction")
    s_air, p_air = np.array(air[1]).T
    s, p = np.array(contact[1]).T
    delta = p - np.interp(s, s_air, p_air)
    w, b = delta[(s >= window[0]) & (s <= window[1])], delta[(s >= before[0]) & (s <= before[1])]
    if len(w) < 2 or len(b) < 2:
        raise SystemExit(f"too few PWM samples in the windows ({len(w)}, {len(b)}): a longer or slower sweep")
    net = float(w.mean() - b.mean())
    se = float(np.sqrt(w.var(ddof=1) / len(w) + b.var(ddof=1) / len(b)))
    stall, rated = STALL[motor]
    k = stall * volts / rated / 885
    force = abs(net) * k / radius_m
    mu = force / (mass_kg * G)
    snr = abs(net) / se if se else float("inf")
    sd = mu * math.sqrt((1 / snr if snr else 1) ** 2 + DATASHEET_SHARE ** 2)
    agrees = (net > 0) == (contact[2] > 0)  # the extra effort pushes the way the pan turns; the other way is not friction
    ok = agrees and snr >= MIN_SNR and len(w) >= MIN_SAMPLES
    why = (f"PWM {net:+.1f} (se {se:.1f}, SNR {snr:.1f}, {len(w)} samples)"
           + ("" if agrees else ", against the pan's motion: not friction") + ("" if snr >= MIN_SNR else f", SNR under {MIN_SNR}")
           + ("" if len(w) >= MIN_SAMPLES else f", fewer than {MIN_SAMPLES} samples"))
    return dict(mass_kg=mass_kg, radius_m=radius_m, pwm=round(net, 2), se=round(se, 2), snr=round(snr, 2), n=len(w),
                force_n=round(force, 4), mu=round(mu, 3), sd=round(sd, 3), ok=ok, why=why)


def friction(runs, motor="XL430-W250", volts=11.7):
    """runs: [(trace rows, mass kg, radius m[, (window, before)])]. One mu through the origin of force against weight (friction scales with the
    load: two stack heights check that), kept only when every run reads friction clearly."""
    rows = [one_sweep(r, m, rad, motor, volts, *(rest[0] if rest else ())) for r, m, rad, *rest in runs]
    good = [r for r in rows if r["ok"]]
    out = dict(schema=FRICTION_SCHEMA, motor=motor, volts=volts, runs=rows, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    if len(good) < len(rows) or not rows:
        return dict(out, ok=False, why="a run did not read friction clearly; a person's tilt test is the fallback")
    w = [r["mass_kg"] * G for r in good]
    mu = sum(r["force_n"] * x for r, x in zip(good, w)) / sum(x * x for x in w)
    spread = max(abs(r["mu"] - mu) for r in good) / mu
    sd = math.sqrt(sum(r["sd"] ** 2 for r in good)) / len(good) + (spread * mu if len(good) > 1 else 0)
    ok = len(good) == 1 or spread <= .3
    return dict(out, mu=round(mu, 3), sd=round(sd, 3), ok=ok,
                why=f"mu {mu:.3f} +- {sd:.3f} over {len(good)} run(s)" + ("" if ok else f"; runs disagree by {spread:.0%}: not friction alone"))


# -- promote --------------------------------------------------------------------------------------------------------------------
MIN_GRASP_SEEDS = 9  # the G-23 probe size: a 0/9 grasp was what exposed the best-RMS candidate, so fewer rows cannot clear one


MIN_REAL_N = 10  # pooled known real rows: at n=10 a Wilson 95% interval is still about +-0.25 wide, the least that can tell a sim p of .8 from .3
P_CLIP = (.02, .98)  # a sim cell of 0/n or n/n must not give -inf: one real surprise costs ln(1/.02) = 3.9 nats


def _jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.startswith("{")]


def real_score(trials, real, base, candidate):
    """How well each physics predicts the real attempts. Real rows carry no physics tag (the real arm runs real physics): per
    (carry candidate, tier) cell with real rows, the sim success rate p of `trials` under a physics is scored against the real k of n
    by the binomial log-likelihood k ln p + (n-k) ln(1-p), p clipped to P_CLIP, summed over the cells both physics have trials for.
    UNKNOWN rows and `shadowed` rows (a site's own value won, the offer never ran) are counted apart, never in n. Under MIN_REAL_N pooled
    rows the status is "insufficient" and no score is compared."""
    sim, cells = {}, {}
    for r in trials:
        k = sim.setdefault((r["cand"], r["tier"], r["physics"]), [0, 0])
        k[0] += bool(r["ok"])
        k[1] += 1
    out = dict(unknown=0, shadowed=0)
    for r in real:
        if r["outcome"] in ("unknown", "shadowed"):
            out[r["outcome"]] += 1
        elif r["outcome"] in ("ok", "fail"):
            c = cells.setdefault((r["candidate"], r["tier"]), [0, 0])
            c[0] += r["outcome"] == "ok"
            c[1] += 1
    cells = {c: v for c, v in cells.items() if (*c, base) in sim and (*c, candidate) in sim}  # a cell one physics never ran says nothing about the pair
    n = sum(v[1] for v in cells.values())
    out.update(n=n, min_n=MIN_REAL_N, status="checked" if n >= MIN_REAL_N else "insufficient")
    if out["status"] == "checked":
        def ll(name):
            tot = 0.0
            for (c, t), (k, m) in cells.items():
                p = min(max(sim[(c, t, name)][0] / sim[(c, t, name)][1], P_CLIP[0]), P_CLIP[1])
                tot += k * math.log(p) + (m - k) * math.log(1 - p)
            return round(tot, 4)
        out.update(base_ll=ll(base), candidate_ll=ll(candidate), real_k=sum(v[0] for v in cells.values()))
    return out


def task_from_files(base_stack, stack, grasp, base="design", candidate=None, real=None, sweep=None):
    """The task field of a fit: the teacher `stack` result of the base and of the candidate (their steps_pass/steps) and the
    skill `--skill grasp --servo-lag` rows of the candidate, one json row per line (judge "held": result pass).
    The evidence is bound to the names: the base stack ran physics `base`, the candidate stack and every grasp row ran `candidate`,
    on the same seed, from two different files.
    `real` + `sweep` (optional): omx_carry_sweep ingest's real_outcomes.jsonl (no physics tag needed) and the sweep dir holding
    trials.jsonl, scored by real_score. Real rows only add a refusal in task_gate, they cannot stand in for the sim evidence."""
    if not candidate:
        raise SystemExit("task: name the candidate physics the stack and grasp runs used (--candidate)")
    if Path(base_stack).resolve() == Path(stack).resolve():
        raise SystemExit("task: the base and candidate stack results are one file")
    load = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    rows = _jsonl(grasp)
    b, c = load(base_stack), load(stack)
    phys = lambda d: (d.get("choices") or {}).get("physics", "design")  # noqa: E731
    if phys(b) != base:
        raise SystemExit(f"task: the base stack ran physics {phys(b)}, not {base}")
    if phys(c) != candidate:
        raise SystemExit(f"task: the candidate stack ran physics {phys(c)}, not {candidate}")
    if b.get("seed") != c.get("seed"):
        raise SystemExit(f"task: the stack runs used seeds {b.get('seed')} and {c.get('seed')}")
    other = sorted({str(r.get("physics")) for r in rows if r.get("physics") != candidate})
    if other:
        raise SystemExit(f"task: grasp rows ran physics {', '.join(other)}, not {candidate}")
    pick = lambda d: [d["steps_pass"], d["steps"]]  # noqa: E731
    out = dict(base=base, candidate=candidate, seed=b.get("seed"), stack=dict(base=pick(b), candidate=pick(c)),
                grasp=dict(held=sum(r.get("result") == "pass" for r in rows), total=len(rows)))
    if real:
        if not sweep:
            raise SystemExit("task: --real needs --sweep (the sweep dir with trials.jsonl) to score each physics against the real rows")
        out["real"] = real_score(_jsonl(Path(sweep) / "trials.jsonl"), _jsonl(real), base, candidate)
    return out


def task_gate(task):
    """(ok, why): the candidate passes the stack steps at least as often as the base (and some), and holds the grasp probe in every
    seed of at least MIN_GRASP_SEEDS. A small joint RMS alone proved nothing: servo-friction-20261109 had the best RMS and grasped 0/9 (G-23)."""
    if not task:
        return False, "no task result: run omx_sysid.py task (stack pass vs base + servo-lag grasp probe); RMS alone cannot promote"
    (bp, bn), (cp, cn) = task["stack"]["base"], task["stack"]["candidate"]
    held, total = task["grasp"]["held"], task["grasp"]["total"]
    if bn != cn or not cn:
        return False, f"stack runs differ in size (base {bp}/{bn}, candidate {cp}/{cn})"
    if cp < bp or not cp:
        return False, f"task worse: stack pass {bp}/{bn} -> {cp}/{cn}"
    if total < MIN_GRASP_SEEDS or held < total:
        return False, f"task worse: servo-lag grasp held {held}/{total} (needs every one of at least {MIN_GRASP_SEEDS} seeds)"
    ok = f"stack pass {bp}/{bn} -> {cp}/{cn}, grasp held {held}/{total}"
    real = task.get("real")
    if not real:
        return True, ok
    extra = f" (unknown {real.get('unknown', 0)}, shadowed {real.get('shadowed', 0)} not counted)"
    if real.get("status") != "checked":  # neutral: too few rows to refuse or to confirm
        return True, f"{ok}; insufficient real evidence (n={real.get('n', 0)} < {real.get('min_n', MIN_REAL_N)}), real check neutral{extra}"
    if real["candidate_ll"] < real["base_ll"]:  # real outcomes only refuse; a real success never lifts a sim shortfall (checked above)
        return False, f"real outcomes worse: sim predicts them with log-likelihood {real['candidate_ll']} vs base {real['base_ll']} over n={real['n']}{extra}"
    return True, f"{ok}; real log-likelihood {real['candidate_ll']} vs base {real['base_ll']} over n={real['n']}, not refused{extra}"


def verdict(fit):
    """(ok, why): the task gate (task_gate), no constant on its fit bound (an edge value is not identified: it soaks up what the model lacks; a
    passive term at its zero floor is fine, it is just not needed), the
    held-out mean lower than the base's and no joint worse by more than WORSE_DEG."""
    bounds = fit.get("bounds") or BOUNDS
    edge = [f"{j} {k} {v:g}" for j, row in fit["fitted"].items() for k, v in row.items()
            if k in bounds and (v >= bounds[k][1] / 1.01 or (v <= bounds[k][0] * 1.01 and k not in ZERO_FLOOR))]
    if edge:
        return False, f"on a fit bound, not identified: {', '.join(edge)}"
    base, new = fit["rms_deg"]["base"]["hold"], fit["rms_deg"]["fitted"]["hold"]
    worse = [f"joint{j + 1} {b:.2f}->{n:.2f}" for j, (b, n) in enumerate(zip(base, new)) if n - b > WORSE_DEG]
    mb, mn = sum(base) / len(base), sum(new) / len(new)
    if worse:
        return False, f"held-out worse: {', '.join(worse)}"
    if len(fit['episodes']['hold']) < 2:
        return False, 'a held-out score needs at least two episodes'
    if mn >= mb:
        return False, f"held-out mean {mb:.3f} -> {mn:.3f} deg: no better than {fit['base']}"
    ok, why = task_gate(fit.get("task"))
    if not ok:
        return False, why
    return True, f"held-out mean {mb:.3f} -> {mn:.3f} deg over {len(fit['episodes']['hold'])} episodes; {why}"


def promote(fit, name, evidence=None, path=physics.FILE, base="design"):
    """Append `fit` as candidate NAME. A servo fit keeps its own base; a friction reading sits on `base`."""
    import yaml
    friction_fit = fit.get("schema") == FRICTION_SCHEMA
    ok, why = verdict(fit) if not friction_fit else ((fit["ok"], fit["why"]) if not fit["ok"] else task_gate(fit.get("task")))
    if not ok:
        raise SystemExit(f"not promoted: {why}")
    bound = fit.get("task") or {}  # the task evidence ran this candidate on this base
    if bound.get("candidate") != name or bound.get("base") != (base if friction_fit else fit["base"]):
        raise SystemExit(f"not promoted: the task result was run for {bound.get('base')} -> {bound.get('candidate')}, not {fit.get('base', base)} -> {name}")
    doc = physics.load(path)
    if name in doc["candidates"]:
        raise SystemExit(f"candidate {name} exists; pick a new name (candidates are never overwritten)")
    if friction_fit:
        runs = ", ".join(f"{r['mass_kg'] * 1000:.0f} g" for r in fit["runs"])
        block = dict(base=base, source="fitted", date=fit["at"][:10],
                     method=f"omx_sysid.py friction, cell_push --friction pan sweep against an air sweep ({runs}), {fit['motor']} at {fit['volts']} V",
                     evidence=evidence or "", note=why + "; priority 1 also sets the jaw-to-box friction in the sim (not measured)",
                     container={"friction": [fit["mu"], .005, .0001], "priority": 1},
                     sd={"container": {"friction": fit["sd"]}})
    else:
        block = dict(base=fit["base"], source="fitted", date=fit["at"][:10],
                     method=f"omx_sysid.py servo, {', '.join(fit['keys'])} of joint1-5 by least squares over "
                            f"{len(fit['episodes']['fit'])} episodes, gravity_comp={fit['gravity_comp']}",
                     evidence=evidence or "", note=why, arms={fit["arm"]: fit["fitted"]}, sd={fit["arm"]: fit["sd"]},
                     gravity_hold="all" if fit["gravity_comp"] is True else list(fit["gravity_comp"] or []))  # the world replays it as fitted
    physics.Physics(name, dict(doc, candidates={**doc["candidates"], name: block}))  # resolves (its base exists) before any write
    text = yaml.safe_dump({"candidates": {name: block}}, sort_keys=False, allow_unicode=True).split("\n", 1)[1]  # drop "candidates:"
    body = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(body.rstrip("\n") + "\n" + text, encoding="utf-8")  # candidates is the file's last section
    physics.Physics(name, physics.load(path))  # and the appended text parses back to it
    return why


# -- next -----------------------------------------------------------------------------------------------------------------------
def survey(doc=None):
    """[(width, constant, how known, experiment)]: assumed constants first, then fitted ones by relative 2-sd width."""
    doc = doc or physics.load()
    r = physics.ranges(doc)
    fitted = {}
    for name, c in doc["candidates"].items():
        if c.get("source") in physics.MEASURED:
            layers = [(arm, joints) for arm, joints in c.get("arms", {}).items()] + [(arm, c.get("joints", {})) for arm in physics.ARMS]
            for arm, joints in layers:  # `joints` holds for every arm
                for j, row in joints.items():
                    for k in row:
                        fitted.setdefault((arm, j, k), []).append(name)
    rows = []
    for arm, joints in r["arms"].items():
        for j, keys in joints.items():
            for k, span in keys.items():
                by = fitted.get((arm, j, k))
                mid = (span["low"] + span["high"]) / 2 or 1.0
                width = 11.0 if not by else (span["high"] - span["low"]) / abs(mid)  # assumed beats any fitted width
                rows.append((round(width, 3), f"{arm}.{j}.{k}", f"measured ({', '.join(sorted(set(by)))})" if by else "assumed", EXPERIMENTS[k]))
    for k in r["container"]:
        known = [c.get("source") for c in doc["candidates"].values() if k in c.get("container", {})]
        rows.append((11.0 if set(known) <= {"assumed"} else 0.0, f"container.{k}", "assumed" if set(known) <= {"assumed"} else "fitted",
                     EXPERIMENTS[k]))
    return sorted(rows, key=lambda row: -row[0])


__all__ = [
    "BODY",
    "BOUNDS",
    "DATASHEET_SHARE",
    "DEFAULT_GAINS",
    "EVERY",
    "EXPERIMENTS",
    "FRICTION_SCHEMA",
    "G",
    "HERE",
    "HOLD",
    "MIN_SAMPLES",
    "MIN_SNR",
    "MIN_GRASP_SEEDS",
    "MOTORS",
    "NO_LOAD",
    "PAN",
    "SCHEMA",
    "STALL",
    "STALL_CURRENT",
    "TICKS_PER_RAD",
    "WORSE_DEG",
    "ZERO_FLOOR",
    "friction",
    "from_registers",
    "one_sweep",
    "promote",
    "survey",
    "sweeps",
    "verdict",
    "windows",
]
