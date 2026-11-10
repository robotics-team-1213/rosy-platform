"""Experiment: replay real episodes with the arm's body joints driven by a Dynamixel position controller model instead of
MuJoCo's position actuator + ideal gravity compensation. PWM = P/128 e + I/65536 sum(e) + D/16 de (ticks, 1 kHz),
clipped at PWM_Limit; torque = PWM/885 x stall - stall/no-load-speed x w (back-EMF), clipped by Current_Limit (XL330).
  python dxl_replay.py CELL EP_DIR.. [--fit] [--out OUT.json]"""
import math, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path[:0] = ["tools/sim", "deploy/robot/omx"]

TPR = 4096 / (2 * math.pi)
MODEL = ["XL430-W250", "XL430-W250", "XL430-W250", "XL330-M288", "XL330-M288"]
STALL = {"XL430-W250": (1.5, 12.0), "XL330-M288": (0.52, 5.0)}
NOLOAD = {"XL430-W250": (5.97, 11.1), "XL330-M288": (10.9, 5.0)}
VOLTS = [11.7, 11.7, 11.6, 6.1, 6.1]
DEFAULT = {"XL430-W250": dict(p=640, i=0, d=4000), "XL330-M288": dict(p=400, i=0, d=0)}
# arm_b's session caps 11-03..11-07 (caps-arm-b-wrist400-20261103.json): P, I, PWM_Limit, Current_Limit per joint
CAPS = [dict(pwm=300), dict(pwm=600, p=1600), dict(pwm=600, i=50), dict(pwm=300, p=800, i=50, current=400), dict(pwm=300, current=250)]


def servo(d_scale=1.0, p_scale=(1, 1, 1, 1, 1)):
    rows = []
    for j, cap in enumerate(CAPS):
        mdl = MODEL[j]
        g = dict(DEFAULT[mdl], **{k: cap[k] for k in ("p", "i") if k in cap})
        stall = STALL[mdl][0] * VOLTS[j] / STALL[mdl][1]
        w0 = NOLOAD[mdl][0] * VOLTS[j] / NOLOAD[mdl][1]
        tmax = stall * cap.get("current", 1e9) / 1470 if mdl == "XL330-M288" else 1e9
        rows.append(dict(kpp=g["p"] / 128 * p_scale[j], kpi=g["i"] / 65536, kpd=g["d"] / 16 * d_scale, lim=cap["pwm"], stall=stall, bemf=stall / w0, tmax=tmax))
    return rows


def track_dxl(cell, ticks, sv, passive):
    """Sim joint1-5 (rad) on the twin's 50 Hz grid, the body joints torque-driven by the servo model."""
    import mujoco
    import omx_cell_sim as cs
    import omx_twin as twin
    m = cell.model
    for j, a in enumerate(cell.act[:5]):  # torque mode: force = ctrl, our own clamp
        m.actuator_gainprm[a, 0], m.actuator_biasprm[a, :3] = 1.0, 0.0
        m.actuator_forcerange[a] = [-10, 10]
        dof = m.jnt_dofadr[m.joint(f"joint{j + 1}").id]
        m.dof_damping[dof], m.dof_frictionloss[dof] = passive[j]
    data = mujoco.MjData(m)
    data.qpos[cell.qadr] = cs.real_q(ticks[0]["state"])
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]
    m.body_gravcomp[m.body("box").id] = 1
    mujoco.mj_forward(m, data)
    dt = m.opt.timestep
    g, actions = twin.grid(ticks, "action")
    integ = np.zeros(5)
    prev_e = None
    out = np.empty((len(g), 5))
    dofs = np.array([m.jnt_dofadr[m.joint(f"joint{j + 1}").id] for j in range(5)])
    for k in range(len(g)):
        goal = cs.real_q(actions[k])
        data.ctrl[cell.act[5]] = goal[5]
        for _ in range(round(1 / twin.GRID_HZ / dt)):
            q, w = data.qpos[cell.qadr[:5]], data.qvel[dofs]
            e = (goal[:5] - q) * TPR
            integ += e * dt * 1000
            de = (e - prev_e) / (dt * 1000) if prev_e is not None else np.zeros(5)
            prev_e = e
            tau = np.empty(5)
            for j, s in enumerate(sv):
                pwm = np.clip(s["kpp"] * e[j] + s["kpi"] * integ[j] + s["kpd"] * de[j], -s["lim"], s["lim"])
                tau[j] = np.clip(pwm / 885 * s["stall"] - s["bemf"] * w[j], -s["tmax"], s["tmax"])
            data.ctrl[cell.act[:5]] = tau
            mujoco.mj_step(m, data)
        out[k] = data.qpos[cell.qadr[:5]]
    return out


_C = {}


def _init(cell_path, folders):
    import omx_cell_sim as cs
    import omx_sysid as sysid
    _C.update(cell=cs.Cell(cell_path, "registers-20261109"), eps={e[0]: e for e in sysid.Episodes(folders).items})


def _job(task):
    name, d_scale, passive, p_scale = task
    e = _C["eps"][name]
    sim = track_dxl(_C["cell"], e[1], servo(d_scale, p_scale), passive)
    return np.degrees(sim - e[2])


def main():
    import omx_sysid as sysid
    cell, folders = sys.argv[1], [a for a in sys.argv[2:] if not a.startswith("--")]
    eps = sysid.Episodes(folders)
    fit, hold = eps.split()
    passive0 = [(0.0886, 0.046), (0.308, 0.0426), (0.001, 0.0222), (0.823, 0.0001), (0.001, 0.0263)]  # servo-friction-20261109
    with ProcessPoolExecutor(8, initializer=_init, initargs=(cell, folders)) as pool:
        def score(names, d_scale, passive, p_scale=(1, 1, 1, 1, 1)):
            err = np.concatenate(list(pool.map(_job, [(n, d_scale, passive, p_scale) for n in names])))
            return np.sqrt((err ** 2).mean(0)).round(3), err.mean(0).round(3)
        fit_names, hold_names = [e[0] for e in fit], [e[0] for e in hold]
        best = None
        for s430 in (1.0, 1.5, 2.0, 2.5, 3.0):
            for s330 in (0.5, 1.0, 1.5, 2.0):
                ps = (s430, s430, s430, s330, s330)
                r, _ = score(fit_names, 1.0, passive0, ps)
                print(f"fit  XL430 x{s430} XL330 x{s330}: {r.tolist()} mean {r.mean():.3f}", flush=True)
                if best is None or r.mean() < best[0]:
                    best = (r.mean(), ps)
        r1, b1 = score(hold_names, 1.0, passive0, (1, 1, 1, 1, 1))
        r2, b2 = score(hold_names, 1.0, passive0, best[1])
        print(f"HOLD registers x1: {r1.tolist()} mean {r1.mean():.3f} bias {b1.tolist()}")
        print(f"HOLD best {best[1]}: {r2.tolist()} mean {r2.mean():.3f} bias {b2.tolist()}  (servo-friction-20261109 was 0.410)")


if __name__ == "__main__":
    main()
