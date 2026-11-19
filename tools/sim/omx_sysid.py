#!/usr/bin/env python3
"""Fit the OMX cell's physics constants to what the real arm did, keep a fit only when held-out episodes agree, and say
which constant to measure next: the constant step of the real-sim loop (docs/reference/omx-real-sim-loop.md, 6b).

  servo EP [EP ..] --cell CELL --out DIR [--base design] [--arm arm_b] [--keys kp,damping,frictionloss]
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
  score EP [EP ..] --cell CELL --candidates A,B --out DIR [--gravity-comp]
        Each candidate as it stands (no fit) on the same held-out and all episodes: which one follows the real arm.
  registers --caps CAPS --volts 11=V,..
        The MuJoCo kp, kv, force a session's servo registers stand for (Dynamixel PID behind its PWM limit).
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
from omx_sysid_helpers import (  # noqa: E402
    BODY,
    BOUNDS,
    DATASHEET_SHARE,
    DEFAULT_GAINS,
    EVERY,
    EXPERIMENTS,
    FRICTION_SCHEMA,
    G,
    HOLD,
    MIN_SAMPLES,
    MIN_SNR,
    MOTORS,
    NO_LOAD,
    PAN,
    SCHEMA,
    STALL,
    STALL_CURRENT,
    TICKS_PER_RAD,
    WORSE_DEG,
    ZERO_FLOOR,
    friction,
    from_registers,
    one_sweep,
    promote,
    survey,
    sweeps,
    verdict,
    windows,
)


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
    """arm_a / arm_b / arm_s from an episode's task.json "io" (chunk-io-a / chunk-io-b / chunk-io-s, recorded from 2026-11-08), else None."""
    try:
        io = str(json.loads((Path(folder) / "task.json").read_text()).get("io") or "")
    except (OSError, ValueError):
        return None
    return {"a": "arm_a", "b": "arm_b", "s": "arm_s"}.get(io.rstrip("/")[-1:]) if "chunk-io-" in io else None


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
            self.items.append((f"{f.parent.name}/{f.name}", ticks, cs.norm_to_rad(state[:, :5])))  # unique across days and traces
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


class _Compensated:
    """The cell as omx_twin.track sees it, with gravity compensation only on `joints` (track compensates cell.arm_dof)."""

    def __init__(self, cell, joints):
        self._cell, self.arm_dof = cell, cell.dof[[BODY.index(j) for j in joints]]

    def __getattr__(self, name):
        return getattr(self._cell, name)


def error_deg(cell, episodes, values, gravity_comp, every=1):
    """gravity_comp: False, True (every arm joint) or joint names (the servos holding an I gain, a stand-in for it)."""
    import numpy as np
    import omx_twin as twin
    if isinstance(gravity_comp, (list, tuple)):
        cell, gravity_comp = _Compensated(cell, gravity_comp), bool(gravity_comp)
    set_constants(cell, values)
    kp = [row.get("kp", cell.model.actuator_gainprm[cell.act[j], 0]) for j, row in enumerate(values)]  # unfitted: the candidate's own
    kp_arr = np.array(kp)
    out = []
    for _, ticks, real in episodes:
        sim = twin.track(cell, ticks, kp_arr, gravity_comp)  # sets kp again; the other constants stay as set here
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
        shifted = [x[:i].tolist() + [float(x[i] + self.step)] + x[i + 1:].tolist() for i in range(len(x))]
        tasks = [(unpack(s, self.keys), n, EVERY) for s in shifted for n in self.names]
        parts = list(self.pool.map(_job, tasks))
        k = len(self.names)
        cols = [(np.concatenate(parts[i * k:(i + 1) * k]).ravel() - f0) / self.step for i in range(len(x))]
        return np.stack(cols, 1)


def servo(folders, cell_path, out, base="design", arm="arm_b", keys=("kp", "damping", "frictionloss"), gravity_comp=False,
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
    # sd from the Gauss-Newton covariance, carried from log space: sd(v) ~ v * sd(log v). The residuals are a smooth time
    # series, not independent: scale by sqrt((1 + rho) / (1 - rho)) of their lag-1 autocorrelation (AR(1) effective samples).
    dof = max(1, res.fun.size - res.x.size)
    per_joint = res.fun.reshape(-1, 5)
    rho = float(np.clip(np.mean([np.corrcoef(c[:-1], c[1:])[0, 1] for c in per_joint.T if c.std() > 0] or [0.0]), 0, .99))
    inflate = math.sqrt((1 + rho) / (1 - rho))
    try:
        cov = np.linalg.pinv(res.jac.T @ res.jac) * (2 * res.cost / dof)
        sd_log = np.sqrt(np.clip(np.diag(cov), 0, None)) * inflate
    except np.linalg.LinAlgError:
        sd_log = np.full(res.x.size, np.nan)
    sd = [{k: round(fitted[j][k] * float(sd_log[j * len(keys) + i]), 6) for i, k in enumerate(keys)} for j in range(5)]
    result = dict(schema=SCHEMA, base=base, arm=arm, keys=list(keys), gravity_comp=gravity_comp, cell=str(cell_path),
                  episodes=dict(fit=[e[0] for e in fit], hold=[e[0] for e in hold], untagged=episodes.untagged, other_arm=episodes.other),
                  fitted={j: {k: round(v, 6) for k, v in row.items()} for j, row in zip(BODY, fitted)},
                  bounds={k: BOUNDS[k] for k in keys},
                  sd={j: row for j, row in zip(BODY, sd)}, sd_inflation=round(inflate, 2), rms_deg=score, nfev=int(res.nfev), status=res.message,
                  at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fit.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


_S = {}


def _score_init(cell_path, name, folders, arm, gravity_comp):
    import omx_cell_sim as cs
    _S.update(cell=cs.Cell(cell_path, name), eps={e[0]: e for e in Episodes(folders, arm).items}, grav=gravity_comp)


def _score_job(name):
    c = _S["cell"]
    values = [{k: c.physics.joint("arm_b", j)[k] for k in ("kp",)} for j in BODY]  # every other constant is the model's own
    return error_deg(c, [_S["eps"][name]], values, _S["grav"])


def score(folders, cell_path, names, arm="arm_b", gravity_comp=False, jobs=8):
    """Held-out and all-episode RMS of each named candidate as it stands (no fit): the comparison D-947 2 asks for."""
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor
    episodes = Episodes(folders, arm)
    fit, hold = episodes.split()
    out = {"episodes": {"hold": [e[0] for e in hold], "all": len(episodes.items), "untagged": episodes.untagged},
           "gravity_comp": gravity_comp, "candidates": {}}
    for name in names:
        with ProcessPoolExecutor(jobs, initializer=_score_init, initargs=(cell_path, name, [str(f) for f in folders], arm, gravity_comp)) as pool:
            errs = dict(zip([e[0] for e in episodes.items], pool.map(_score_job, [e[0] for e in episodes.items])))
        out["candidates"][name] = {"hold": rms(np.concatenate([errs[e[0]] for e in hold])),
                                   "all": rms(np.concatenate(list(errs.values())))}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("servo")
    s.add_argument("episodes", nargs="+")
    s.add_argument("--cell", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--base", default="design")
    s.add_argument("--arm", default="arm_b", choices=physics.ARMS)
    s.add_argument("--keys", default="kp,damping,frictionloss")
    s.add_argument("--gravity-comp", nargs="?", const="all", default=None,
                   help="ideal gravity compensation, on every arm joint or on JOINTS (comma list: the I-gain servos, e.g. joint3,joint4)")
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
    sc = sub.add_parser("score")
    sc.add_argument("episodes", nargs="+")
    sc.add_argument("--cell", required=True)
    sc.add_argument("--candidates", default="design", help="comma list of cell_physics.yaml candidates")
    sc.add_argument("--gravity-comp", nargs="?", const="all", default=None, help="as for servo")
    sc.add_argument("--jobs", type=int, default=8)
    sc.add_argument("--out", required=True)
    rg = sub.add_parser("registers")
    rg.add_argument("--caps", required=True, help="a record_session caps.json, or session.json (its caps section)")
    rg.add_argument("--volts", required=True, help="ID=V per motor 11-15, from motor-health voltage_v, e.g. 11=11.7,12=11.7,..")
    n = sub.add_parser("next")
    n.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if getattr(a, "gravity_comp", None) is not None:
        a.gravity_comp = True if a.gravity_comp == "all" else a.gravity_comp.split(",")
    else:
        a.gravity_comp = False
    if a.cmd == "servo":
        r = servo(a.episodes, a.cell, a.out, a.base, a.arm, a.keys.split(","), a.gravity_comp, a.max_nfev, a.jobs)
        print(json.dumps(dict(rms_deg=r["rms_deg"], verdict=verdict(r)), indent=1))
    elif a.cmd == "score":
        r = score(a.episodes, a.cell, a.candidates.split(","), gravity_comp=a.gravity_comp, jobs=a.jobs)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "score.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps(r["candidates"], indent=1))
    elif a.cmd == "registers":
        import yaml
        caps = json.loads(Path(a.caps).read_text())
        if "caps" in caps:  # session.json: {"caps": {"11": {"pwm_limit": .., "p_gain": ..}}}
            caps = {k: {{"pwm_limit": "pwm", "p_gain": "p", "i_gain": "i"}.get(n, n): v for n, v in row.items()} for k, row in caps["caps"].items()}
        joints, integral = from_registers(caps, {int(k): float(v) for k, v in (x.split("=") for x in a.volts.split(","))})
        print(yaml.safe_dump({"joints": joints, "integral_gain": integral}, sort_keys=False))
        runs = []
        for item in a.run:
            trace, grams, result = item.rsplit(":", 2)
            rows = [json.loads(line) for line in Path(trace).read_text(errors="replace").splitlines() if line.strip()]
            info = json.loads(Path(result).read_text())["friction"]
            runs.append((rows, float(grams) / 1000, info["radius_m"], windows(info["gap_mm"], info["push_mm"])))
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


__all__ = [
    "BODY",
    "BOUNDS",
    "DATASHEET_SHARE",
    "DEFAULT_GAINS",
    "EVERY",
    "EXPERIMENTS",
    "Episodes",
    "FRICTION_SCHEMA",
    "G",
    "HERE",
    "HOLD",
    "MIN_SAMPLES",
    "MIN_SNR",
    "MOTORS",
    "NO_LOAD",
    "PAN",
    "Residual",
    "SCHEMA",
    "STALL",
    "STALL_CURRENT",
    "TICKS_PER_RAD",
    "WORSE_DEG",
    "ZERO_FLOOR",
    "error_deg",
    "friction",
    "from_registers",
    "main",
    "one_sweep",
    "promote",
    "ramp_ticks",
    "recorded_arm",
    "rms",
    "score",
    "servo",
    "set_constants",
    "survey",
    "sweeps",
    "unpack",
    "verdict",
    "windows",
]


if __name__ == "__main__":
    raise SystemExit(main())
