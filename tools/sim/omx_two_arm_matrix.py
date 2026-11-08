#!/usr/bin/env python3
"""Feasibility matrix of the two-arm cell (MuJoCo, geometry only, D-947): can arm X take container C out of the full block, and put it back?

For every container, both arms and both jaw branches (the grip turned 180 deg), the state is the full block minus what lies above C.
Two single steps run from that nominal state: extract (C to the arm's own temporary lane) and restore (back to C's cell). A step is feasible
when its pose, neighbours, arm links and pads all pass the strict judge. Run on the AI PC:

    MUJOCO_GL=egl python tools/sim/omx_two_arm_matrix.py --arm arm_a --branch best --out DIR
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_two_arm_sites as sites  # noqa: E402


def cases(layout):
    """(container, ship site, uncovered state) for every container of the stack plan: the block without what lies above."""
    full = {c: s for c, s, _ in layout.plan_order()}
    out = []
    for c, site in full.items():
        s = layout.sites[site]
        above = {k for k, v in full.items() if layout.sites[v]["stack"] == s["stack"] and layout.sites[v]["layer"] > s["layer"]}
        out.append((c, site, {k: v for k, v in full.items() if k not in above}))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--arm", required=True, choices=sorted(sites.ARMS))
    p.add_argument("--branch", default="best", choices=["best", "other"])
    p.add_argument("--out", required=True)
    p.add_argument("--choice", action="append")
    a = p.parse_args(argv)
    import omx_two_arm_teacher as teacher
    import omx_two_arm_world as world_mod
    layout = sites.Layout(**teacher.parse_choices(a.choice))
    world = world_mod.World(layout)
    t = teacher.Teacher(world)
    tag = "a" if a.arm == "arm_a" else "b"
    rows = []
    for c, site, state in cases(layout):
        lane = f"tmp-{tag}-2"
        for op, src, dst, here in (("extract", site, lane, state), ("restore", lane, site, {**{k: v for k, v in state.items() if k != c}, c: lane})):
            step = dict(id=f"{c}-{op}", container=c, arm=a.arm, **{"from": src}, to=dst)
            row = t.run_single(here, step, a.branch)
            row.update(op=op, branch=a.branch)
            rows.append(row)
            print(c, a.arm, a.branch, op, row["result"], row.get("reason", ""), row.get("arm_link_contacts", ""), row.get("neighbours_disturbed", ""), flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"matrix-{a.arm}-{a.branch}.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
