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
REACH_MARGIN_M = 0.008  # wrist distance kept inside l1 + l2 at the travel end points of a site
MIN_STANDOFF_M = 0.02   # the shortest approach / lift a site may shrink to
MAX_JOINT_STEP_RAD = 0.25  # between two frames; the sim profile's max_waypoint_joint_step_rad
# shortcut: the gripper housing's reach past the tool axis is an estimate, not a measurement; measure it on the
# cell and replace (2026-10-27: a TCP-only keep-out let the wrist and gripper hit the wall behind the belt).
# It is the keep-out radius of the wrist-TCP capsule; the other links use swept_volume.LINK_RADIUS_M.
BODY_MARGIN_M = 0.035


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

    def reach_margin(self, x, y, z, yaw_deg) -> float:
        """How far inside l1 + l2 the wrist stands for a top-down TCP at (x, y, z): negative is out of reach."""
        k = self.kin
        wx, wy, wz = k.wrist_point(self.TopDownPose(x, y, z, math.radians(yaw_deg)))
        r = math.hypot(wx - k.base_xy[0], wy - k.base_xy[1]) - k.shoulder_offset_m
        return k.l1 + k.l2 - math.hypot(r, wz - k.shoulder_height_m)

    def standoff(self, x, y, z, yaw_deg, wanted: float) -> float:
        """The travel end point's height over the target: ``wanted``, shortened in 1 cm steps to at least
        MIN_STANDOFF_M while the wrist would stand within REACH_MARGIN_M of full stretch. Moving and touching
        are two jobs: travel ends where the arm still has margin, the touch is a short straight line from there
        (2026-10-26: a container 0.24 m out was graspable top-down; only its 7 cm lift point was out of reach)."""
        s = wanted
        while s > MIN_STANDOFF_M and not self.fits(x, y, z + s, yaw_deg):
            s = max(MIN_STANDOFF_M, round(s - 0.01, 3))
        return s

    def fits(self, x, y, z, yaw_deg) -> bool:
        """Reach margin kept and every joint inside its limit. A higher top-down point bends the wrist further: arm
        S's wrist stops at 1.89 rad (2026-10-27), so its lifts shorten here instead of failing at the guard."""
        if self.reach_margin(x, y, z, yaw_deg) < REACH_MARGIN_M:
            return False
        return self.kin.solve_top_down(self.TopDownPose(x, y, z, math.radians(yaw_deg)), self.limits).ok

    def line(self, start, end, speed_m_s, yaw_deg, grip, reference_q5):
        """Frames along a straight Cartesian line at `speed_m_s` and the q5 it ends at: the kinematics' shared
        line (one IK solve and FK check per frame, a yaw-twin flip refused), the same one the sim planner uses."""
        n = max(1, math.ceil(math.dist(start, end) / (speed_m_s / self.fps)))
        try:
            path = self.kin.solve_line(self.solve(*start, yaw_deg, reference_q5),
                                       self.TopDownPose(*start, math.radians(yaw_deg)), end, self.limits,
                                       count=n, max_joint_step_rad=MAX_JOINT_STEP_RAD)
        except ValueError as exc:
            raise SystemExit(f"IK line {start} -> {end}: {exc}") from None
        return [[round(rad_to_norm(q), 3) for q in joints] + [grip] for joints in path], path[-1][4]

    def hold(self, frame, seconds, grip_from=None, grip_to=None):
        n = max(1, round(seconds * self.fps))
        if grip_from is None:
            return [list(frame)] * n
        return [frame[:5] + [round(grip_from + (grip_to - grip_from) * k / n, 3)] for k in range(1, n + 1)]

    def site(self, name, target, grip_in, grip_out, q5):
        """above (one frame, reached by goto) -> descend -> close/open -> lift."""
        p = self.plan
        x, y, z, yaw = target["x"], target["y"], target["z"], target["yaw_deg"]
        above = (x, y, z + self.standoff(x, y, z, yaw, p["approach_m"]))
        # after a release the jaws rise clear before the park closes them: 3 cm let the fingertips take the box back
        # (2026-10-28); the pick's lift can stay low for the shoulder. Either lift shrinks inside the wrist limit.
        rise = p.get("release_lift_m", p["lift_m"]) if grip_out > grip_in else p["lift_m"]
        lifted = (x, y, z + self.standoff(x, y, z, yaw, rise))
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
        transit = self.keep_out(chunks)
        return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": self.fps, "chunks": chunks,
                "gripper_closed": p["grip_closed"], "hold_current_ma": p.get("hold_current_ma"),
                "transit": transit,
                "transit_speed": p.get("transit_speed", 0.85),
                "source": {"planner": "grasp_planner.py top-down v1", "pick": p["pick"], "place": p["place"],
                           "transit": "taught" if transit == p.get("transit", {}) else "pulled in for keep_out",
                           "reach": {site: {"approach_m": round(self.height(chunks[f"above_{site}"][0]) - p[site]["z"], 3),
                               "margin_m": round(self.reach_margin(p[site]["x"], p[site]["y"], p[site]["z"],
                                                                   p[site]["yaw_deg"]), 4)}
                                     for site in ("pick", "place")}}}

    def height(self, frame) -> float:
        return self.kin.fk([norm_to_rad(v) for v in frame[:5]]).z

    def keep_out(self, chunks) -> dict:
        """``keep_out`` {"x_max_m": ...} in the plan: no link capsule (shoulder to fingertips) past that line, in
        the chunks and on the travel between them (chunk_runner's rise-turn-descend path), e.g. the wall behind
        the S cell's belt. Returns the transit the travel uses: the plan's taught one, or when its travel crosses
        the line the first passing tool-down transit pulled toward the base (taught and computed compete)."""
        taught = self.plan.get("transit", {})
        bound = (self.plan.get("keep_out") or {}).get("x_max_m")
        if bound is None:
            return taught
        for name, frames in chunks.items():
            worst = max(self.body_x(f) for f in frames)
            if worst > bound:
                raise SystemExit(f"{name}: a link (elbow, wrist or gripper) reaches x {worst:.3f} m "
                                 f"past keep_out x_max {bound} m")
        first = None
        for transit in [taught, *self.pulled_in_transits(taught)]:
            worst = max(self.body_x(f) for f in self.travel(chunks, transit))
            if worst <= bound:
                return transit
            first = first if first is not None else worst
        raise SystemExit(f"travel: a link (elbow, wrist or gripper) reaches x {first:.3f} m past keep_out x_max "
                         f"{bound} m with the taught transit, and no pulled-in transit stays inside")

    def travel(self, chunks, transit: dict) -> list:
        """The frames goto and park would play between the chunks with this transit."""
        from chunk_runner import transit_path

        p = self.plan
        index = {NAMES.index(k): float(v) for k, v in transit.items()} or None
        home = list(p["home"]) + [p["grip_closed"]]
        return (transit_path(home, chunks["above_pick"][0], p["grip_closed"], self.fps, index)
                + transit_path(chunks["lift_pick"][-1], chunks["above_place"][0], p["grip_closed"], self.fps, index)
                + transit_path(chunks["lift_place"][-1], home, p["grip_closed"], self.fps, index))

    def pulled_in_transits(self, taught: dict) -> list[dict]:
        """Tool-down transits 1 cm apart from the taught one's reach toward the base, the TCP no lower than the
        taught transit's lowest link point (turning low scraped the jaws on the table, 2026-10-24)."""
        from omx_adapter.chunk_library import TRANSIT

        index = {NAMES.index(k): float(v) for k, v in taught.items()} or TRANSIT
        points, _ = self.kin.link_points([0.0] + [norm_to_rad(index.get(i, 0.0)) for i in (1, 2, 3)] + [0.0])
        floor = min(z for _, _, z in points)
        bx, by = self.kin.base_xy
        radius = round(math.hypot(points[-1][0] - bx, points[-1][1] - by) - 0.01, 3)
        out = []
        while radius >= self.limits.singularity_radius_m:
            result = self.kin.solve_top_down(self.TopDownPose(bx + radius, by, floor, 0.0), self.limits)
            if result.ok:
                out.append({NAMES[i]: round(rad_to_norm(result.joints[i]), 3) for i in (1, 2, 3)})
            radius = round(radius - 0.01, 3)
        return out

    def body_x(self, frame) -> float:
        """Largest x any link capsule reaches: shoulder-elbow, elbow-wrist, and wrist-TCP at the housing margin."""
        from omx_adapter.swept_volume import capsules

        caps = capsules(self.kin, [norm_to_rad(v) for v in frame[:5]], fingertip_m=0.0,
                        gripper_radius_m=BODY_MARGIN_M)
        return max(max(a[0], b[0]) + r for a, b, r in caps)

    def leg(self, library):
        """One recordable leg from home: travel to above pick, pick, travel to above place, place, travel home.
        Travel uses chunk_runner's rise-turn-descend path, the same one goto and park take."""
        from chunk_runner import transit_path

        c, p = library["chunks"], self.plan
        transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
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
