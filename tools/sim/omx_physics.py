#!/usr/bin/env python3
"""OMX cell physics constants from learning/envs/isaac/cell_physics.yaml: one candidate per name, the ranges training samples.

  omx_physics.py show [NAME]      the resolved constants of a candidate (default design)
  omx_physics.py ranges           {low, high} per arm, joint and constant, plus container mass and friction (omx_two_arm_skill)
The MuJoCo cells call joint() and container() with the candidate named by --choice physics=<name> (D-947 2).
"""
import argparse
import json
from pathlib import Path

import yaml

FILE = Path(__file__).resolve().parents[2] / "learning/envs/isaac/cell_physics.yaml"
ARMS = ("arm_a", "arm_b")
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
MEASURED = ("fitted", "registers")  # read off the real arm: fitted to its recordings, or its servo settings
KEYS = ("kp", "kv", "damping", "armature", "frictionloss", "force", "zero_offset_deg")


def load(path=FILE):
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != "rosy.cell-physics/1":
        raise ValueError(f"{path}: not a rosy.cell-physics/1 file")
    return doc


class Physics:
    """One resolved candidate: its `base` chain first, then its own joints (all arms) and arms (one arm) on top."""

    def __init__(self, name="design", doc=None):
        self.doc = doc or load()
        if name not in self.doc["candidates"]:
            raise ValueError(f"no physics candidate {name!r}; have {sorted(self.doc['candidates'])}")
        self.name, self.chain = name, []
        seen = name
        while seen:
            if seen in self.chain:
                raise ValueError(f"physics candidate {name!r}: base loop at {seen!r}")
            if seen not in self.doc["candidates"]:
                raise ValueError(f"no physics candidate {seen!r} (the base of {name!r})")
            self.chain.insert(0, seen)
            seen = self.doc["candidates"][seen].get("base")

    def joint(self, arm, joint):
        out = {}
        for name in self.chain:
            c = self.doc["candidates"][name]
            for layer in (c.get("joints", {}), c.get("arms", {}).get(arm, {})):
                out.update(layer.get("default", {}))
                out.update(layer.get(joint, {}))
        return out

    def gravity_hold(self):
        """Which arm joints the sim holds against gravity: "all" (the cells' ideal compensation, the default) or joint names.
        It stands in for a servo I gain the MuJoCo position servo lacks, so it belongs with the gains (registers: joint3, joint4)."""
        hold = "all"
        for name in self.chain:
            hold = self.doc["candidates"][name].get("gravity_hold", hold)
        return hold

    def hold_dofs(self, model, prefix=""):
        """The dof addresses of gravity_hold() in a compiled model (prefix: the two-arm world's a_ / b_)."""
        import numpy as np
        hold = self.gravity_hold()
        names = (*JOINTS, "gripper_joint_2") if hold == "all" else hold
        return np.array([model.joint(prefix + n).dofadr[0] for n in names], dtype=int)

    def container(self):
        out = {}
        for name in self.chain:
            out.update(self.doc["candidates"][name].get("container", {}))
        return out


def apply_joint(joint, c):
    """An MjSpec joint's passive dynamics from one resolved joint row."""
    joint.damping, joint.armature, joint.frictionloss = c["damping"], c["armature"], c["frictionloss"]


def add_actuator(spec, name, c):
    """The position servo both cells use: kp on the error, kv on the velocity, clipped at force."""
    import mujoco
    spec.add_actuator(name=name, target=name, trntype=mujoco.mjtTrn.mjTRN_JOINT, gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                      gainprm=[c["kp"]] + [0] * 9, biastype=mujoco.mjtBias.mjBIAS_AFFINE, biasprm=[0, -c["kp"], -c["kv"]] + [0] * 7,
                      forcelimited=mujoco.mjtLimited.mjLIMITED_TRUE, forcerange=[-c["force"], c["force"]])


def ranges(doc=None):
    """{low, high} per constant: the spread of every candidate's value, widened by 2 sd where a fit gave its uncertainty
    (a candidate's `sd`, same shape as its `arms`). Design alone gives low == high. `measured` says a fitted candidate
    sets the constant itself: false means not measured (a sampler keeps its own width there), not known exactly."""
    doc = doc or load()
    cands = {n: Physics(n, doc) for n in doc["candidates"]}
    out = {"source": FILE.name, "candidates": sorted(cands), "arms": {}, "container": {}}
    fitted = [c for c in doc["candidates"].values() if c.get("source") in MEASURED]
    for arm in ARMS:
        for j in JOINTS:
            for k in KEYS:
                values = [0.0] if k == "zero_offset_deg" else []  # no offset is a candidate too
                for n, p in cands.items():
                    v = p.joint(arm, j).get(k)
                    if v is None:
                        continue
                    sd = doc["candidates"][n].get("sd", {}).get(arm, {}).get(j, {}).get(k, 0.0)
                    values += [v - 2 * sd, v + 2 * sd]
                if len(values) > 1 or k != "zero_offset_deg":
                    measured = any(k in c.get("arms", {}).get(arm, {}).get(j, {}) or k in c.get("joints", {}).get(j, {}) for c in fitted)
                    out["arms"].setdefault(arm, {}).setdefault(j, {})[k] = {"low": max(min(values), 0.0) if k != "zero_offset_deg" else min(values),
                                                                            "high": max(values), "measured": measured}
    for k, pick in (("mass", lambda v: v), ("friction", lambda v: v[0])):
        values = []
        for n, p in cands.items():
            if k in p.container():
                sd = doc["candidates"][n].get("sd", {}).get("container", {}).get(k, 0.0)
                values += [pick(p.container()[k]) - 2 * sd, pick(p.container()[k]) + 2 * sd]
        out["container"][k] = {"low": max(min(values), 0.0), "high": max(values),
                               "measured": any(k in c.get("container", {}) for c in fitted)}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("name", nargs="?", default="design")
    sub.add_parser("ranges")
    a = p.parse_args(argv)
    if a.cmd == "show":
        ph = Physics(a.name)
        print(json.dumps({"chain": ph.chain, "container": ph.container(),
                          "arms": {arm: {j: ph.joint(arm, j) for j in JOINTS} for arm in ARMS}}, indent=1))
    else:
        print(json.dumps(ranges(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
