#!/usr/bin/env python3
"""Top-down pick-and-place chunks for chunk_runner.py from Cartesian targets (scripted teacher, v2).

A replayed human demonstration closed the jaws while sweeping the base about 14 degrees, tilted the tool
23-42 degrees off vertical and twisted the wrist 164 degrees on the way (2026-10-25 analysis), so it
missed whenever the box moved. This planner instead goes above the box, descends straight down,
closes while still, lifts straight up, carries high, and does the same in reverse at the place point,
with the tool kept vertical and the wrist yaw changed as little as the 180-degree jaw symmetry allows.

Every frame is solved with the repo's closed-form top-down IK (omx_adapter.kinematics), checked with
FK, and converted to LeRobot normalized units, so chunk_runner plays it under the same caps, clip,
following-error, stall and grasp checks as any taught chunk. Everything tunable lives in the plan file.

  grasp_planner.py <plan.json> <out library.json> [--kinematics-root <dir with omx_adapter>]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # chunk_runner, teach_trajectory
from teach_trajectory import GUARD_UNITS_PER_S, slow, too_fast  # noqa: E402
from motion_profile import retime  # noqa: E402

NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos",
         "gripper.pos"]
TICKS = 4096
TOOL_DOWN_TOL = math.radians(1.0)
POS_TOL = 0.0015     # m between the requested and the FK position of every frame


def rad_to_norm(rad: float, lo: float = 0, hi: float = 4095) -> float:
    """LeRobot body-joint normalization (RANGE_M100_100) of a Dynamixel angle, tick 2048 = 0 rad."""
    raw = (rad + math.pi) * TICKS / (2 * math.pi)
    return (min(max(raw, lo), hi) - lo) / (hi - lo) * 200 - 100


def norm_to_rad(norm: float, lo: float = 0, hi: float = 4095) -> float:
    raw = (norm + 100) / 200 * (hi - lo) + lo
    return raw * 2 * math.pi / TICKS - math.pi


def load_kinematics(root: Path | None):
    root = root or Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter"
    sys.path.insert(0, str(root))
    from omx_adapter.kinematics import IkLimits, OmxKinematics, TopDownPose

    return OmxKinematics.load(root / "config/omx_f_kinematics.yaml"), IkLimits, TopDownPose


class Planner:
    def __init__(self, plan: dict, kinematics_root: Path | None = None):
        self.plan = plan
        self.kin, IkLimits, self.TopDownPose = load_kinematics(kinematics_root)
        lim = plan["limits"]
        self.limits = IkLimits(position_limits={k: tuple(v) for k, v in lim["joints_rad"].items()},
                               workspace_min_m=tuple(lim["workspace_min_m"]),
                               workspace_max_m=tuple(lim["workspace_max_m"]),
                               singularity_radius_m=lim["singularity_radius_m"])
        self.fps = plan["fps"]
        self.kinematics_root = kinematics_root

    def solve(self, x, y, z, yaw_deg, reference_q5):
        result = self.kin.solve_top_down(self.TopDownPose(x, y, z, math.radians(yaw_deg)), self.limits,
                                         reference_q5=reference_q5)
        if not result.ok:
            raise SystemExit(f"IK {result.reason} at ({x:.3f}, {y:.3f}, {z:.3f}) yaw {yaw_deg}: {result.detail}")
        fk = self.kin.fk(result.joints)
        if math.dist((fk.x, fk.y, fk.z), (x, y, z)) > POS_TOL or fk.tool_down_error_rad > TOOL_DOWN_TOL:
            raise SystemExit(f"FK check failed at ({x:.3f}, {y:.3f}, {z:.3f}): {fk}")
        return result.joints

    def line(self, start, end, speed_m_s, yaw_deg, grip, reference_q5):
        """Frames along a straight Cartesian line at `speed_m_s`, one IK solve per frame."""
        n = max(1, math.ceil(math.dist(start, end) / (speed_m_s / self.fps)))
        frames, q5 = [], reference_q5
        for k in range(1, n + 1):
            p = [a + (b - a) * k / n for a, b in zip(start, end)]
            joints = self.solve(*p, yaw_deg, q5)
            q5 = joints[4]
            frames.append([round(rad_to_norm(q), 3) for q in joints] + [grip])
        return frames, q5

    def hold(self, frame, seconds, grip_from=None, grip_to=None):
        n = max(1, round(seconds * self.fps))
        if grip_from is None:
            return [list(frame)] * n
        return [frame[:5] + [round(grip_from + (grip_to - grip_from) * k / n, 3)] for k in range(1, n + 1)]

    def site(self, name, target, grip_in, grip_out, q5):
        """above (one frame, reached by goto) -> descend -> close/open -> lift."""
        p = self.plan
        x, y, z, yaw = target["x"], target["y"], target["z"], target["yaw_deg"]
        above = (x, y, z + p["approach_m"])
        lifted = (x, y, z + p["lift_m"])
        joints = self.solve(*above, yaw, q5)
        pre = [round(rad_to_norm(q), 3) for q in joints] + [grip_in]
        down, q5 = self.line(above, (x, y, z), p["descend_m_s"], yaw, grip_in, joints[4])
        verb = "grasp" if grip_out < grip_in else "release"
        act = self.hold(down[-1], p["grip_s"], grip_in, grip_out) + self.hold(down[-1][:5] + [grip_out], p["settle_s"])
        up, q5 = self.line((x, y, z), lifted, p["lift_m_s"], yaw, grip_out, q5)
        # A joint can turn faster than the Cartesian speed suggests near the wrist; the guard streams at
        # GUARD_UNITS_PER_S, so each chunk is slowed to that from where the previous one ended.
        # the vertical lines ease out of and into rest (the same IK path, a trapezoid speed); the jaws'
        # close/open keeps its own pace
        down = [[round(v, 3) for v in f] for f in retime(down, self.fps, 0.85 * GUARD_UNITS_PER_S, start=pre)]
        act = [[round(v, 3) for v in f] for f in slow(act, self.fps, start=down[-1])]
        up = [[round(v, 3) for v in f] for f in retime(up, self.fps, 0.85 * GUARD_UNITS_PER_S, start=act[-1])]
        return {f"above_{name}": [pre], f"descend_{name}": down, f"{verb}_{name}": act, f"lift_{name}": up}, q5

    def library(self):
        p = self.plan
        home = [round(v, 3) for v in p["home"]] + [p["grip_closed"]]
        chunks, q5 = {}, norm_to_rad(p["home"][4])
        pick, q5 = self.site("pick", p["pick"], p["grip_open"], p["grip_closed"], q5)
        place, q5 = self.site("place", p["place"], p["grip_closed"], p["grip_open"], q5)
        chunks.update(pick)
        chunks.update(place)
        chunks["home"] = [home]
        for name, frames in chunks.items():
            if too_fast(frames, self.fps):
                raise SystemExit(f"{name}: frames move faster than the guard streams ({GUARD_UNITS_PER_S} units/s)")
        return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": self.fps, "chunks": chunks,
                "gripper_closed": p["grip_closed"], "hold_current_ma": p.get("hold_current_ma"),
                "transit": p.get("transit", {}),
                "source": {"planner": "grasp_planner.py top-down v1", "pick": p["pick"], "place": p["place"]}}


    def leg(self, library):
        """One recordable leg from home: travel to above pick, pick, travel to above place, place, travel home.
        Travel uses chunk_runner's rise-turn-descend path, the same one goto and park take."""
        from chunk_runner import transit_path

        c, p = library["chunks"], self.plan
        transit = {NAMES.index(k): float(v) for k, v in p.get("transit", {}).items()} or None
        home = list(p["home"]) + [p["grip_closed"]]
        frames = transit_path(home, c["above_pick"][0], p["grip_closed"], self.fps, transit)
        frames += c["descend_pick"] + c["grasp_pick"] + c["lift_pick"]
        frames += transit_path(frames[-1], c["above_place"][0], p["grip_closed"], self.fps, transit)
        frames += c["descend_place"] + c["release_place"] + c["lift_place"]
        frames += transit_path(frames[-1], home, p["grip_closed"], self.fps, transit)
        return [[round(v, 3) for v in f] for f in frames]

    def cycle_trajectory(self, reset_s: float = 2.0) -> dict:
        """A self-resetting cycle for record_session --replay: A carries pick -> place, B carries it back."""
        from teach_trajectory import compose

        a = self.leg(self.library())
        back = Planner(dict(self.plan, pick=self.plan["place"], place=self.plan["pick"]), self.kinematics_root)
        b = back.leg(back.library())
        source = {"planner": "grasp_planner.py top-down v1", "pick": self.plan["pick"], "place": self.plan["place"]}
        return compose(a + b, self.fps, len(a) / self.fps, len(a + b) / self.fps, reset_s, source)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--kinematics-root", type=Path)
    parser.add_argument("--trajectory", type=Path, help="also write a recordable A/B cycle for record_session --replay")
    args = parser.parse_args(argv)
    library = Planner(json.loads(args.plan.read_text()), args.kinematics_root).library()
    library = {k: v for k, v in library.items() if v is not None}
    args.out.write_text(json.dumps(library))
    print(json.dumps({"out": str(args.out), "chunks": {k: len(v) for k, v in library["chunks"].items()}}))
    if args.trajectory:
        trajectory = Planner(json.loads(args.plan.read_text()), args.kinematics_root).cycle_trajectory()
        args.trajectory.write_text(json.dumps(trajectory))
        print(json.dumps({"trajectory": str(args.trajectory), "segments": trajectory["segments"]}))


if __name__ == "__main__":
    main()
