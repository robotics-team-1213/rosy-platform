#!/usr/bin/env python3
"""Fit the OMX cell's physics constants to what the real arm did, keep a fit only when held-out episodes agree, and say
which constant to measure next: the constant step of the real-sim loop (docs/reference/omx-real-sim-loop.md, 6b).

  servo EP [EP ..] --cell CELL --out DIR [--base design] [--arm arm_b] [--keys kp,kv,damping,frictionloss]
        Replays each real episode's actions open loop in the MuJoCo cell (omx_twin.track, --jobs processes) and fits the chosen constants of
        joint1-5 together (scipy least_squares, joint angle error in degrees). Episodes are split fit/hold by name
        (omx_twin.shard_of, 1 in 3 held out); fit.json has the base and fitted RMS on both, and each constant's sd.
        EP is an episode folder (episode_recorder) or a runner trace of deploy/robot/omx/cell_step.py's per-joint ramps.
        Lab PC only (MuJoCo, D-584). No real motion here: both are recordings.
  friction --run TRACE:MASS_G:RESULT [--run ..] --out DIR
        Container friction from cell_push.py --friction (supervised, D-911): the pan's PWM while the closed jaws sweep the
        box, less the same sweep through air, as torque (datasheet stall torque at the logged voltage) over the radius,
        against the box's weight. Kept only when the difference stands SNR >= 3 above the noise and is against the motion;
        two stack heights must agree within 30 % (friction scales with load). Otherwise a person's tilt test is the fallback.
  promote FIT --name NAME [--evidence PATH] [--base design]
        Appends the fit as candidate NAME to learning/envs/isaac/cell_physics.yaml, only when the held-out RMS is lower
        than the base's and no joint gets worse by more than WORSE_DEG. The base stays (D-947 2); commit the file.
  next  [--json]
        Every constant with how it is known (assumed, fitted with sd) and the experiment that would narrow it, widest first.
"""
import argparse
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
BOUNDS = {"kp": (2., 200.), "kv": (.05, 30.), "damping": (.001, 5.), "armature": (1e-4, .1), "frictionloss": (1e-4, .5)}
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


# -- servo fit ------------------------------------------------------------------------------------------------------------------
def set_constants(cell, values):
    """values[j][key] into the compiled model for body joint j (0..4); kp and kv go on the actuator."""
    m = cell.model
    for j, row in enumerate(values):
        dof, act = m.jnt_dofadr[m.joint(BODY[j]).id], cell.act[j]
        for key, v in row.items():
            if key == "kp":
                m.actuator_gainprm[act, 0], m.actuator_biasprm[act, 1] = v, -v
            elif key == "kv":
                m.actuator_biasprm[act, 2] = -v
            else:
                getattr(m, f"dof_{key}")[dof] = v


def unpack(x, keys):
    return [{k: float(math.exp(x[j * len(keys) + i])) for i, k in enumerate(keys)} for j in range(5)]


def rms(err):
    import numpy as np
    return np.sqrt((err ** 2).mean(0)).round(3).tolist()


def ramp_ticks(rows):
    """A chunk_runner trace of deploy/robot/omx/cell_step.py as episode ticks: present is the state, what was sent the action."""
    return [{"t": r["t"], "state": r["present"], "action": r.get("sent") or r["target"]}
            for r in rows if str(r.get("chunk") or "").startswith("step_j") and r.get("present")]


def recorded_arm(folder):
    """arm_a / arm_b from an episode's task.json "io" (chunk-io-a / chunk-io-b, recorded from 2026-11-08), else None."""
    try:
        io = str(json.loads((Path(folder) / "task.json").read_text()).get("io") or "")
    except (OSError, ValueError):
        return None
    return {"a": "arm_a", "b": "arm_b"}.get(io.rstrip("/")[-1:]) if "chunk-io-" in io else None


class Episodes:
    """The real side of the fit: each episode folder's ticks (episode_recorder) or a cell_step runner trace file, and its
    real joint1-5 on the 50 Hz grid (rad). A folder recorded on the other arm is left out; ones that do not say which arm
    (before 2026-11-08) are kept and listed in `untagged`."""

    def __init__(self, folders, arm="arm_b"):
        import omx_cell_sim as cs
        import omx_twin as twin
        self.items, self.untagged, self.other = [], [], []
        for f in map(Path, folders):
            if f.is_dir():
                who = recorded_arm(f)
                if who and who != arm:
                    self.other.append(f.name)
                    continue
                if who is None:
                    self.untagged.append(f.name)
            ticks = twin.read_jsonl(f / "ticks.jsonl") if f.is_dir() else ramp_ticks(twin.read_jsonl(f))
            if len(ticks) <= 50:
                continue  # omx_twin.replay skips these too
            _, state = twin.grid(ticks, "state")
            self.items.append((f.name, ticks, cs.norm_to_rad(state[:, :5])))
        if not self.items:
            raise SystemExit("no episode with more than 50 ticks")

    def split(self):
        import omx_twin as twin
        hold = [e for e in self.items if twin.shard_of(e[0], HOLD)]
        fit = [e for e in self.items if not twin.shard_of(e[0], HOLD)]
        if not fit or not hold:  # too few names for a 1-in-3 split: hold the last one out
            fit, hold = self.items[:-1], self.items[-1:]
        if not fit:
            raise SystemExit("a held-out score needs at least two episodes")
        return fit, hold


def error_deg(cell, episodes, values, gravity_comp, every=1):
    import numpy as np
    import omx_twin as twin
    set_constants(cell, values)
    kp = [row["kp"] for row in values]
    out = []
    for _, ticks, real in episodes:
        sim = twin.track(cell, ticks, np.array(kp), gravity_comp)  # sets kp again; the other constants stay as set here
        out.append(np.degrees(sim - real)[::every])
    return np.concatenate(out)


_W = {}  # one worker's cell and episodes, built once per process


def _init(cell_path, base, folders, gravity_comp):
    import omx_cell_sim as cs
    _W.update(cell=cs.Cell(cell_path, base), eps={e[0]: e for e in Episodes(folders).items}, grav=gravity_comp)


def _job(task):
    values, name, every = task
    return error_deg(_W["cell"], [_W["eps"][name]], values, _W["grav"], every)


class Residual:
    """least_squares' fun and jac over a process pool: every (episode) replay, and every (constant, episode) replay of the
    forward-difference Jacobian, is one job. The last fun value is reused by jac at the same x."""

    def __init__(self, pool, names, keys, step=.05):
        self.pool, self.names, self.keys, self.step, self.last = pool, names, keys, step, (None, None)

    def errors(self, values, every=EVERY):
        import numpy as np
        return np.concatenate(list(self.pool.map(_job, [(values, n, every) for n in self.names])))

    def fun(self, x):
        f = self.errors(unpack(x, self.keys)).ravel()
        self.last = (x.copy(), f)
        return f

    def jac(self, x):
        import numpy as np
        f0 = self.last[1] if self.last[0] is not None and np.array_equal(self.last[0], x) else self.fun(x)
        shifted = [x + self.step * np.eye(len(x))[i] for i in range(len(x))]
        tasks = [(unpack(s, self.keys), n, EVERY) for s in shifted for n in self.names]
        parts = list(self.pool.map(_job, tasks))
        k = len(self.names)
        cols = [(np.concatenate(parts[i * k:(i + 1) * k]).ravel() - f0) / self.step for i in range(len(x))]
        return np.stack(cols, 1)


def servo(folders, cell_path, out, base="design", arm="arm_b", keys=("kp", "kv", "damping", "frictionloss"), gravity_comp=False,
          max_nfev=60, jobs=8):
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor
    from scipy.optimize import least_squares
    keys = tuple(keys)
    unknown = set(keys) - set(BOUNDS)
    if unknown:
        raise SystemExit(f"cannot fit {sorted(unknown)}; fit keys are {sorted(BOUNDS)}")
    if arm != "arm_b":
        raise SystemExit("omx_cell_sim models arm_b only; arm_a's episodes need the two-arm world")
    phys = physics.Physics(base)
    start = [{k: phys.joint(arm, j)[k] for k in keys} for j in BODY]
    episodes = Episodes(folders, arm)
    fit, hold = episodes.split()
    x0 = np.log([max(row[k], BOUNDS[k][0]) for row in start for k in keys])
    lo = np.log([BOUNDS[k][0] for _ in BODY for k in keys])
    hi = np.log([BOUNDS[k][1] for _ in BODY for k in keys])
    with ProcessPoolExecutor(jobs, initializer=_init, initargs=(cell_path, base, [str(f) for f in folders], gravity_comp)) as pool:
        r_fit = Residual(pool, [e[0] for e in fit], keys)
        r_hold = Residual(pool, [e[0] for e in hold], keys)
        res = least_squares(r_fit.fun, np.clip(x0, lo, hi), jac=r_fit.jac, bounds=(lo, hi), max_nfev=max_nfev, x_scale="jac")
        fitted = unpack(res.x, keys)
        score = {name: {"fit": rms(r_fit.errors(v, 1)), "hold": rms(r_hold.errors(v, 1))} for name, v in (("base", start), ("fitted", fitted))}
    # sd from the Gauss-Newton covariance, carried from log space: sd(v) ~ v * sd(log v)
    dof = max(1, res.fun.size - res.x.size)
    try:
        cov = np.linalg.pinv(res.jac.T @ res.jac) * (2 * res.cost / dof)
        sd_log = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        sd_log = np.full(res.x.size, np.nan)
    sd = [{k: round(fitted[j][k] * float(sd_log[j * len(keys) + i]), 6) for i, k in enumerate(keys)} for j in range(5)]
    result = dict(schema=SCHEMA, base=base, arm=arm, keys=list(keys), gravity_comp=gravity_comp, cell=str(cell_path),
                  episodes=dict(fit=[e[0] for e in fit], hold=[e[0] for e in hold], untagged=episodes.untagged, other_arm=episodes.other),
                  fitted={j: {k: round(v, 6) for k, v in row.items()} for j, row in zip(BODY, fitted)},
                  sd={j: row for j, row in zip(BODY, sd)}, rms_deg=score, nfev=int(res.nfev), status=res.message,
                  at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fit.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# -- friction -------------------------------------------------------------------------------------------------------------------
FRICTION_SCHEMA = "rosy.omx-sysid-friction.v1"
PAN = "shoulder_pan"
G = 9.81
STALL = {"XL430-W250": (1.5, 12.0)}  # N·m at V, ROBOTIS e-Manual; torque per PWM unit = stall * V/V_rated / 885
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
                    if p is not None and x["pwm"] != last:
                        samples.append(((x["t"] - t0) / (t1 - t0), float(p)))
                    last = x.get("pwm")
                out.append((seg[0]["chunk"], samples, seg[-1]["present"][0] - seg[0]["present"][0]))
            seg = []
        if r.get("chunk") in ("slide_push", "slide_air"):
            seg.append(r)
    return out


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
    """runs: [(trace rows, mass kg, radius m)]. One mu through the origin of force against weight (friction scales with the
    load: two stack heights check that), kept only when every run reads friction clearly."""
    rows = [one_sweep(r, m, rad, motor, volts) for r, m, rad in runs]
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
def verdict(fit):
    """(ok, why): held-out mean lower than the base's and no joint worse by more than WORSE_DEG."""
    base, new = fit["rms_deg"]["base"]["hold"], fit["rms_deg"]["fitted"]["hold"]
    worse = [f"joint{j + 1} {b:.2f}->{n:.2f}" for j, (b, n) in enumerate(zip(base, new)) if n - b > WORSE_DEG]
    mb, mn = sum(base) / len(base), sum(new) / len(new)
    if worse:
        return False, f"held-out worse: {', '.join(worse)}"
    if mn >= mb:
        return False, f"held-out mean {mb:.3f} -> {mn:.3f} deg: no better than {fit['base']}"
    return True, f"held-out mean {mb:.3f} -> {mn:.3f} deg over {len(fit['episodes']['hold'])} episodes"


def promote(fit, name, evidence=None, path=physics.FILE, base="design"):
    """Append `fit` as candidate NAME. A servo fit keeps its own base; a friction reading sits on `base`."""
    import yaml
    friction_fit = fit.get("schema") == FRICTION_SCHEMA
    ok, why = (fit["ok"], fit["why"]) if friction_fit else verdict(fit)
    if not ok:
        raise SystemExit(f"not promoted: {why}")
    doc = physics.load(path)
    if name in doc["candidates"]:
        raise SystemExit(f"candidate {name} exists; pick a new name (candidates are never overwritten)")
    if friction_fit:
        runs = ", ".join(f"{r['mass_kg'] * 1000:.0f} g" for r in fit["runs"])
        block = dict(base=base, source="fitted", date=fit["at"][:10],
                     method=f"omx_sysid.py friction, cell_push --friction pan sweep against an air sweep ({runs}), {fit['motor']} at {fit['volts']} V",
                     evidence=evidence or "", note=why, container={"friction": [fit["mu"], .005, .0001], "priority": 1},
                     sd={"container": {"friction": fit["sd"]}})
    else:
        block = dict(base=fit["base"], source="fitted", date=fit["at"][:10],
                     method=f"omx_sysid.py servo, {', '.join(fit['keys'])} of joint1-5 by least squares over "
                            f"{len(fit['episodes']['fit'])} episodes, gravity_comp={fit['gravity_comp']}",
                     evidence=evidence or "", note=why, arms={fit["arm"]: fit["fitted"]}, sd={fit["arm"]: fit["sd"]})
    text = yaml.safe_dump({"candidates": {name: block}}, sort_keys=False, allow_unicode=True).split("\n", 1)[1]  # drop "candidates:"
    body = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(body.rstrip("\n") + "\n" + text, encoding="utf-8")  # candidates is the file's last section
    physics.Physics(name, physics.load(path))  # the appended block must resolve as a candidate
    return why


# -- next -----------------------------------------------------------------------------------------------------------------------
def survey(doc=None):
    """[(width, constant, how known, experiment)]: assumed constants first, then fitted ones by relative 2-sd width."""
    doc = doc or physics.load()
    r = physics.ranges(doc)
    fitted = {}
    for name, c in doc["candidates"].items():
        if c.get("source") == "fitted":
            for arm, joints in c.get("arms", {}).items():
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
                rows.append((round(width, 3), f"{arm}.{j}.{k}", f"fitted ({', '.join(by)})" if by else "assumed", EXPERIMENTS[k]))
    for k in r["container"]:
        known = [c.get("source") for c in doc["candidates"].values() if k in c.get("container", {})]
        rows.append((11.0 if set(known) <= {"assumed"} else 0.0, f"container.{k}", "assumed" if set(known) <= {"assumed"} else "fitted",
                     EXPERIMENTS[k]))
    return sorted(rows, key=lambda row: -row[0])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("servo")
    s.add_argument("episodes", nargs="+")
    s.add_argument("--cell", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--base", default="design")
    s.add_argument("--arm", default="arm_b", choices=physics.ARMS)
    s.add_argument("--keys", default="kp,kv,damping,frictionloss")
    s.add_argument("--gravity-comp", action="store_true", help="the sim's ideal gravity compensation (omx_twin tries both)")
    s.add_argument("--max-nfev", type=int, default=60)
    s.add_argument("--jobs", type=int, default=8, help="replay processes (each holds one MuJoCo cell)")
    fr = sub.add_parser("friction")
    fr.add_argument("--run", action="append", required=True, metavar="TRACE:MASS_G:RESULT",
                    help="a runner trace with a cell_push --friction sweep, the pushed stack's mass in grams, and that push's result.json")
    fr.add_argument("--volts", type=float, default=11.7, help="servo supply, motor-health voltage_v")
    fr.add_argument("--out", required=True)
    pr = sub.add_parser("promote")
    pr.add_argument("fit")
    pr.add_argument("--name", required=True)
    pr.add_argument("--evidence")
    pr.add_argument("--base", default="design", help="for a friction fit: the candidate it sits on")
    n = sub.add_parser("next")
    n.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "servo":
        r = servo(a.episodes, a.cell, a.out, a.base, a.arm, a.keys.split(","), a.gravity_comp, a.max_nfev, a.jobs)
        print(json.dumps(dict(rms_deg=r["rms_deg"], verdict=verdict(r)), indent=1))
    elif a.cmd == "friction":
        runs = []
        for item in a.run:
            trace, grams, result = item.rsplit(":", 2)
            rows = [json.loads(line) for line in Path(trace).read_text(errors="replace").splitlines() if line.strip()]
            runs.append((rows, float(grams) / 1000, json.loads(Path(result).read_text())["friction"]["radius_m"]))
        r = friction(runs, volts=a.volts)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "friction.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps({k: r.get(k) for k in ("mu", "sd", "ok", "why")}, indent=1))
        return 0 if r["ok"] else 1
    elif a.cmd == "promote":
        print(promote(json.loads(Path(a.fit).read_text(encoding="utf-8")), a.name, a.evidence, base=a.base))
    else:
        rows = survey()
        if a.json:
            print(json.dumps([dict(width=w, constant=c, known=k, experiment=e) for w, c, k, e in rows], indent=1))
        else:
            groups = {}  # one line per arm, constant and how it is known, its joints listed together
            for w, c, k, e in rows:
                head, _, key = c.rpartition(".")
                arm, _, joint = head.partition(".")
                g = groups.setdefault((arm, key, k), [w, [], e])
                g[0], g[1] = max(g[0], w), g[1] + ([joint] if joint else [])
            print("| constant | joints | known | width | experiment |\n|---|---|---|---|---|")
            print("\n".join(f"| {arm}.{key} | {', '.join(j) or '-'} | {k} | {'-' if w > 10 else w} | {e} |"
                            for (arm, key, k), (w, j, e) in sorted(groups.items(), key=lambda g: -g[1][0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
