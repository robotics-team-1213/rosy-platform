#!/usr/bin/env python3
"""Load review of a real-arm plan before it runs: the torque each body joint needs along the path (gravity, the path's own
acceleration and an optional held payload, by MuJoCo inverse dynamics on the two-arm world) against what the servo can give
(the session's caps through omx_sysid.from_registers). The model share times the joint's MARGIN (how far real PWM ran above
the model on the arm's own traces, 2026-11-09) at or above FLAG is flagged: near the limit means slow down or shorten the
reach, never clearance. The margins come mostly from holds and short moves: refit them with `replay` once clean supervised
reach sessions are traced (docs/validation/omx-load-2026-11-09/result.md).

  omx_load.py check LIBRARY --arm arm_a --caps CAPS --volts 11=11.7,.. [--chunks a,b] [--payload-g 16] [--json OUT]
  omx_load.py replay TRACE --arm arm_a --caps CAPS --volts .. [--json OUT]   model share against the trace's real PWM share (MARGIN)

LIBRARY is a rosy.omx-chunk-library.v1 (what chunk_runner plays); frames are LeRobot units at the library fps. The forces
are datasheet-derived (omx_sysid: about +-25 %); `replay` measures how far they are off on the arm's own traces.
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "deploy/robot/omx")]
import numpy as np  # noqa: E402

FLAG = .5  # load_predict's risky_share: the most any logged standstill outside a press needed
# p99 of real PWM share over model share per joint on seven traces of 2026-11-09 without the 15:08 session (mostly holds)
MARGIN = {"joint1": 4.2, "joint2": 4.2, "joint3": 1.2, "joint4": 1.6, "joint5": 2.4}
G = 9.81
PREFIX = {"arm_a": "a_", "arm_b": "b_"}
BODY = ("joint1", "joint2", "joint3", "joint4", "joint5")


def norm_to_rad(v):
    return (np.asarray(v, float) + 100) / 200 * 4095 * 2 * np.pi / 4096 - np.pi  # grasp_planner.norm_to_rad


class Arm:
    """One arm of the two-arm world as a rigid body chain: inverse dynamics at a pose, velocity and acceleration."""

    def __init__(self, arm):
        import mujoco
        import omx_two_arm_world as tw
        self.mj, self.arm, self.world = mujoco, arm, tw.World()
        m, p = self.world.model, PREFIX[arm]
        # the arm chain alone: no contacts (containers parked at the origin pressed into each other) and no constraint forces
        m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONSTRAINT
        self.qadr = np.array([m.joint(p + j).qposadr[0] for j in BODY])
        self.dof = np.array([m.joint(p + j).dofadr[0] for j in BODY])
        self.data = mujoco.MjData(m)

    def torque(self, q, qd, qdd, payload_kg=0.0):
        """N·m each body joint must give: M qdd + bias (gravity, Coriolis) + the payload's weight at the jaw tip."""
        m, d, mj = self.world.model, self.data, self.mj
        d.qpos[:] = m.qpos0
        d.qvel[:] = 0
        d.qacc[:] = 0
        d.qpos[self.qadr], d.qvel[self.dof], d.qacc[self.dof] = q, qd, qdd
        mj.mj_inverse(m, d)
        tau = d.qfrc_inverse[self.dof].copy()
        if payload_kg:
            tip, _ = self.world.tcp(d, self.arm)
            jacp = np.zeros((3, m.nv))
            mj.mj_jac(m, d, jacp, None, tip, self.world.link5[self.arm])
            tau += jacp[:, self.dof].T @ np.array([0, 0, payload_kg * G])  # holding it up against its weight
        return tau


SMOOTH_S = .2  # measured positions are encoder ticks: differentiate a 0.2 s moving average, not the raw readings


def derivatives(q, fps, smooth_s=0.0):
    """Velocity and acceleration of a frame sequence (rad) at fps, central differences, after a moving average of smooth_s."""
    n = max(1, int(round(smooth_s * fps)))
    if n > 1 and len(q) > n:
        kernel = np.ones(n) / n
        q = np.stack([np.convolve(np.pad(c, (n // 2, n - 1 - n // 2), mode="edge"), kernel, mode="valid") for c in q.T], 1)
    dt = 1 / fps
    qd = np.gradient(q, dt, axis=0)
    return qd, np.gradient(qd, dt, axis=0)


def load_caps(caps_path):
    """{motor ID: {pwm, p, i, ..}} from a record_session caps.json or a session.json's caps section."""
    caps = json.loads(Path(caps_path).read_text())
    if "caps" in caps:
        caps = {k: {{"pwm_limit": "pwm", "p_gain": "p", "i_gain": "i"}.get(n, n): v for n, v in row.items()} for k, row in caps["caps"].items()}
    return caps


def caps_force(caps, volts):
    import omx_sysid as sysid
    joints, _ = sysid.from_registers(caps, volts)
    return np.array([joints[j]["force"] for j in BODY])


def review(arm, frames, fps, cap, payload_kg=0.0, names=None, margin=MARGIN):
    """Per frame each joint's model share of its cap and that share times its margin; the frames whose margined share
    reaches FLAG."""
    q = norm_to_rad(np.asarray(frames)[:, :5])
    qd, qdd = derivatives(q, fps) if len(q) > 2 else (np.zeros_like(q), np.zeros_like(q))
    share = np.array([np.abs(arm.torque(q[k], qd[k], qdd[k], payload_kg)) / cap for k in range(len(q))])
    margined = share * np.array([margin[j] for j in BODY])
    flags = [dict(frame=int(k), chunk=(names[k] if names else None), joint=BODY[j], share=round(float(share[k, j]), 2),
                  with_margin=round(float(margined[k, j]), 2)) for k, j in zip(*np.nonzero(margined >= FLAG))]
    return dict(worst=dict(zip(BODY, share.max(0).round(2).tolist())), worst_with_margin=dict(zip(BODY, margined.max(0).round(2).tolist())),
                flags=flags[:50], n_flags=len(flags), ok=not flags)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "replay"):
        s = sub.add_parser(name)
        s.add_argument("path")
        s.add_argument("--arm", required=True, choices=sorted(PREFIX))
        s.add_argument("--caps", required=True)
        s.add_argument("--volts", required=True)
        s.add_argument("--json")
        s.add_argument("--payload-g", type=float, default=0.0, help="held at the jaw tip (a container, a calibration board)")
        if name == "check":
            s.add_argument("--chunks", help="comma list in run order, default every chunk but home")
    a = p.parse_args(argv)
    volts = {int(k): float(v) for k, v in (x.split("=") for x in a.volts.split(","))}
    caps = load_caps(a.caps)
    cap, arm = caps_force(caps, volts), Arm(a.arm)
    if a.cmd == "check":
        lib = json.loads(Path(a.path).read_text())
        order = a.chunks.split(",") if a.chunks else [c for c in lib["chunks"] if c != "home"]
        frames, names = [], []
        for c in order:
            frames += lib["chunks"][c]
            names += [c] * len(lib["chunks"][c])
        out = dict(review(arm, frames, lib["fps"], cap, a.payload_g / 1000, names), cap_nm=dict(zip(BODY, cap.round(3).tolist())))
    else:
        rows = [json.loads(line) for line in Path(a.path).read_text(errors="replace").splitlines() if line.strip()]
        rows = [r for r in rows if r.get("present") and r.get("pwm")]
        t = np.array([r["t"] for r in rows])
        fps = 1 / np.median(np.diff(t))
        names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
        q = norm_to_rad(np.array([r["present"] for r in rows])[:, :5])
        qd, qdd = derivatives(q, fps, SMOOTH_S)
        share = np.array([np.abs(arm.torque(q[k], qd[k], qdd[k], a.payload_g / 1000)) / cap for k in range(len(q))])
        real = np.array([[abs(r["pwm"].get(n, 0)) for n in names] for r in rows]) / np.array(
            [caps.get(str(i), {}).get("pwm", 885) for i in range(11, 16)])
        moving = np.abs(qd).max(1) > np.radians(1)
        out = dict(predicted_worst=dict(zip(BODY, share.max(0).round(2).tolist())), real_worst=dict(zip(BODY, real.max(0).round(2).tolist())),
                   fps=round(float(fps), 1),
                   corr={n: round(float(np.corrcoef(share[:, j], real[:, j])[0, 1]), 2) for j, n in enumerate(BODY) if real[:, j].std() > 0},
                   real_over_pred_moving={n: round(float(np.median(real[moving, j] / np.maximum(share[moving, j], .02))), 2) for j, n in enumerate(BODY)},
                   real_over_pred_p99={n: round(float(np.percentile(real[moving, j] / np.maximum(share[moving, j], .02), 99)), 2) for j, n in enumerate(BODY)})
    text = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(text)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
