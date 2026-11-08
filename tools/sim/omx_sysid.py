#!/usr/bin/env python3
"""Fit the OMX cell's physics constants to what the real arm did, keep a fit only when held-out episodes agree, and say
which constant to measure next: the constant step of the real-sim loop (docs/reference/omx-real-sim-loop.md, 6b).

  servo EP_DIR [EP_DIR ..] --cell CELL --out DIR [--base design] [--arm arm_b] [--keys kp,kv,damping,frictionloss]
        Replays each real episode's actions open loop in the MuJoCo cell (omx_twin.track, --jobs processes) and fits the chosen constants of
        joint1-5 together (scipy least_squares, joint angle error in degrees). Episodes are split fit/hold by name
        (omx_twin.shard_of, 1 in 3 held out); fit.json has the base and fitted RMS on both, and each constant's sd.
        Lab PC only (MuJoCo, D-584). No real motion: the episodes are recordings.
  promote FIT --name NAME [--evidence PATH]
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
    "kp": "servo: fit on recorded episodes (no motion); step test at a safe pose if sd stays wide (supervised, D-911)",
    "kv": "servo: fit on recorded episodes; step test (supervised) separates it from damping",
    "damping": "servo: fit on recorded episodes; step test (supervised) separates it from kv",
    "armature": "step test (supervised): only fast steps show it",
    "frictionloss": "servo: fit on recorded episodes (slow reversals show it)",
    "force": "assumed servo stall torque; a push test at the guard's PWM limit (supervised)",
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


class Episodes:
    """The real side of the fit: each episode's 50 Hz ticks and its real joint1-5 on the grid (rad)."""

    def __init__(self, folders):
        import omx_cell_sim as cs
        import omx_twin as twin
        self.items = []
        for f in map(Path, folders):
            ticks = twin.read_jsonl(f / "ticks.jsonl")
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
    fit, hold = Episodes(folders).split()
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
                  episodes=dict(fit=[e[0] for e in fit], hold=[e[0] for e in hold]),
                  fitted={j: {k: round(v, 6) for k, v in row.items()} for j, row in zip(BODY, fitted)},
                  sd={j: row for j, row in zip(BODY, sd)}, rms_deg=score, nfev=int(res.nfev), status=res.message,
                  at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fit.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


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


def promote(fit, name, evidence=None, path=physics.FILE):
    import yaml
    ok, why = verdict(fit)
    if not ok:
        raise SystemExit(f"not promoted: {why}")
    doc = physics.load(path)
    if name in doc["candidates"]:
        raise SystemExit(f"candidate {name} exists; pick a new name (candidates are never overwritten)")
    block = {name: dict(base=fit["base"], source="fitted", date=fit["at"][:10],
                        method=f"omx_sysid.py servo, {', '.join(fit['keys'])} of joint1-5 by least squares over "
                               f"{len(fit['episodes']['fit'])} episodes, gravity_comp={fit['gravity_comp']}",
                        evidence=evidence or "", note=why, arms={fit["arm"]: fit["fitted"]}, sd={fit["arm"]: fit["sd"]})}
    text = yaml.safe_dump({"candidates": block}, sort_keys=False, allow_unicode=True).split("\n", 1)[1]  # drop the "candidates:" line
    body = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(body.rstrip("\n") + "\n" + text, encoding="utf-8")  # candidates is the file's last section
    physics.load(path)["candidates"][name]  # the appended block must parse as a candidate
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
    pr = sub.add_parser("promote")
    pr.add_argument("fit")
    pr.add_argument("--name", required=True)
    pr.add_argument("--evidence")
    n = sub.add_parser("next")
    n.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "servo":
        r = servo(a.episodes, a.cell, a.out, a.base, a.arm, a.keys.split(","), a.gravity_comp, a.max_nfev, a.jobs)
        print(json.dumps(dict(rms_deg=r["rms_deg"], verdict=verdict(r)), indent=1))
    elif a.cmd == "promote":
        print(promote(json.loads(Path(a.fit).read_text(encoding="utf-8")), a.name, a.evidence))
    else:
        rows = survey()
        if a.json:
            print(json.dumps([dict(width=w, constant=c, known=k, experiment=e) for w, c, k, e in rows], indent=1))
        else:
            print("| constant | known | width | experiment |\n|---|---|---|---|")
            print("\n".join(f"| {c} | {k} | {'-' if w > 10 else w} | {e} |" for w, c, k, e in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
