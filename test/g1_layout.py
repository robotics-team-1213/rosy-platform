"""D-778/D-781 G1 SIM layout support: IK reach audit, swept separation, step timing (pure Python, no ROS).

Test support, not production. It composes the palletizing mixed planner, the OMX analytic IK and
planner (D-402) and the IK reach of ``rosy.integrations.robots.omx.mixed_reach``; the palletizing
process itself never imports the adapter (D-413).

What the numbers mean and do not mean:

- Reach: every compiled pose of a Step (pick, pick approach, carry above pick, place, place approach,
  carry above place, home) must have an in-limit top-down IK solution in that arm's base frame, with
  the simulation profile's nominal limits. Straight segments, timing and collisions are the owner
  planner's job; ``plan_step`` runs that planner too.
- Swept separation: each arm is a chain of capsules over the owner planner's joint samples (shoulder
  -> elbow -> wrist -> TCP -> fingertips, plus the held item from grasp to release). Two Steps that may
  run at the same time (different arms, different zones, neither waits for the other) are compared
  over ALL their samples, ignoring timing: conservative. The radii are generous envelopes of the
  OMX-F links (XL430 body about 28.5 x 34 mm, gripper about 50 mm wide open), not a mesh.
- Timing: phase durations come from the owner planner's trapezoid timing; the makespan model applies
  the Fleet ready rules (depends_on done, arm free, zone free; the shared band one Step at a time).
  It is a schedule model, not a measurement of Gazebo or hardware time.
- Stability: the planner's own static rules re-applied to the final stack. No physics.

``python test/g1_layout.py`` prints the JSON report recorded in docs/validation (no pytest).
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _relative in ("operations/processes/palletizing/src", "middleware/devices/omx/adapter",
                  "integrations/robots/omx/src"):
    if str(ROOT / _relative) not in sys.path:
        sys.path.insert(0, str(ROOT / _relative))

from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose  # noqa: E402
from omx_adapter.manipulation_plan import ExecutionStateSnapshot  # noqa: E402
from omx_adapter.swept_volume import capsules as arm_capsules  # noqa: E402
from omx_adapter.pose_plan import (  # noqa: E402
    AnalyticCellTransferPlanner, CellPlanningProfile, CellTransferPlanRejected, CellTransferRequest)
from rosy.integrations.robots.omx.mixed_reach import IkReach, workcell_bases  # noqa: E402
from rosy.processes.palletizing.mixed_cell import CellPose, Workcell, annulus_reach, workcell_from_dict  # noqa: E402
from rosy.processes.palletizing.mixed_cell_doc import load_mixed_cell  # noqa: E402
from rosy.processes.palletizing.mixed_plan import PlanError, descendants  # noqa: E402
from rosy.processes.palletizing.mixed_planner import plan_mixed  # noqa: E402
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe  # noqa: E402
from rosy.processes.palletizing.mixed_rules import load_problems, support_ok, support_ratio_and_corners  # noqa: E402
from rosy.processes.palletizing.mixed_submission import compile_mixed_cell_job  # noqa: E402

MIXED_FIXTURE = ROOT / "operations/processes/palletizing/test/fixtures/mixed_two_arm"
G1_FIXTURE = ROOT / "test/fixtures/g1_sim"
PROFILE_PATH = ROOT / "deploy/robot/omx/sim/cell_profile.yaml"
SHARED_BAND = "shared_band"
# Capsule radii are omx_adapter.swept_volume's. Sample decimation adds DECIMATE_M.
DECIMATE_M = 0.005
# Required free distance between two concurrent swept volumes after the radii (m). The radii are
# envelopes and every capsule already carries DECIMATE_M, so any positive distance passes; the smallest
# measured value is reported (docs/validation/bimanual-g1-sim-2026-10-17) rather than hidden in a margin.
MIN_CLEARANCE_M = 0.0
POSES = ("pick", "pick_approach", "pick_carry", "place", "place_approach", "place_carry", "home")


def read_documents(recipe_path: Path, cell_path: Path) -> tuple[dict, dict]:
    import yaml
    return (yaml.safe_load(recipe_path.read_text(encoding="utf-8")),
            yaml.safe_load(cell_path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Layout:
    recipe_doc: dict
    cell_doc: dict
    recipe: object
    cell: object
    workcell: Workcell


def load_layout(recipe_path: Path = MIXED_FIXTURE / "recipe.yaml",
                cell_path: Path = G1_FIXTURE / "cell_g1.yaml") -> Layout:
    return layout_from(*read_documents(recipe_path, cell_path))


def layout_from(recipe_doc: dict, cell_doc: dict) -> Layout:
    recipe = load_mixed_recipe(json.dumps(recipe_doc))
    cell = load_mixed_cell(json.dumps(cell_doc))
    return Layout(recipe_doc, cell_doc, recipe, cell, cell.workcell(recipe))


def kinematics_and_profile() -> tuple[OmxKinematics, CellPlanningProfile]:
    kin, profile = OmxKinematics.load(), CellPlanningProfile.load(PROFILE_PATH)
    if profile.kinematics_revision != kin.revision:
        raise RuntimeError("sim profile was reviewed against other kinematics")
    return kin, profile


def ik_reach(workcell: Workcell, kin: OmxKinematics, profile: CellPlanningProfile) -> IkReach:
    return IkReach(workcell_bases(workcell), kin, profile.ik_limits())


def layout_facts(layout: Layout) -> dict:
    """Base separation and the pallet centre's distance from each base (D-778 §2: 0.30-0.35 m, 0.15-0.18 m)."""
    wc, slot = layout.workcell, layout.recipe.pallets[0]
    ox, oy, _ = wc.pallet_origins[slot.id]
    centre = (ox + slot.pallet.length / 2, oy + slot.pallet.width / 2)
    arms = wc.arms
    return {"pallet_m": [slot.pallet.length, slot.pallet.width], "pallet_centre_cell": [round(v, 4) for v in centre],
            "base_separation_m": round(math.dist((arms[0].x, arms[0].y), (arms[-1].x, arms[-1].y)), 4),
            "centre_from_base_m": {a.role: round(math.dist((a.x, a.y), centre), 4) for a in arms},
            "facing": abs(abs(math.remainder(arms[0].yaw - arms[-1].yaw, math.tau)) - math.pi) < 1e-9}


def step_poses(inputs: dict) -> dict[str, TopDownPose]:
    """The seven base-frame poses one arm's pallet.transfer inputs command (D-402 §6 travel)."""
    src, dst, home = inputs["source_pose_base"], inputs["destination_pose_base"], inputs["home_pose_base"]

    def pose(p, z=None):
        return TopDownPose(p["x_m"], p["y_m"], p["z_m"] if z is None else z, p["yaw_rad"])
    carry = inputs["carry_z_base_m"]
    return {"pick": pose(src), "pick_approach": pose(src, inputs["source_approach_z_base_m"]),
            "pick_carry": pose(src, carry), "place": pose(dst),
            "place_approach": pose(dst, inputs["destination_approach_z_base_m"]),
            "place_carry": pose(dst, carry), "home": pose(home)}


def reach_audit(steps, kin: OmxKinematics, profile: CellPlanningProfile) -> tuple[int, list[dict]]:
    """IK-check every pose of every arm's inputs of every compiled Step. Returns (checked, failures)."""
    limits, checked, failures = profile.ik_limits(), 0, []
    for index, step in enumerate(steps):
        for role, inputs in sorted(step["placement"]["actions"].items()):
            for name, pose in step_poses(inputs).items():
                checked += 1
                result = kin.solve_top_down(pose, limits)
                if not result.ok:
                    failures.append({"step": index, "arm": role, "pose": name, "reason": result.reason,
                                     "detail": result.detail})
    return checked, failures


# Owner planner trajectories -------------------------------------------------------------------------
def item_geometry(recipe) -> dict[str, dict[str, float]]:
    return {i.sku: {"grasp_width_m": i.width, "grasp_depth_m": i.grasp_depth, "height_m": i.height}
            for i in recipe.items}


def home_state(kin: OmxKinematics, profile: CellPlanningProfile, inputs: dict) -> ExecutionStateSnapshot:
    home = step_poses(inputs)["home"]
    joints = kin.solve_top_down(home, profile.ik_limits()).joints
    positions = dict(zip(ARM_JOINTS, joints))
    positions[profile.gripper_joint] = profile.gripper_open
    return ExecutionStateSnapshot(sequence=1, joint_positions=positions, calibration_revision="g1-sim",
                                  transform_revision="g1-sim", planning_scene_revision=kin.planning_scene_revision,
                                  observed_at_monotonic_s=0.0)


def plan_step(kin: OmxKinematics, profile: CellPlanningProfile, inputs: dict, geometry: dict, *, index: int = 0):
    """The owner's D-402 plan of one arm's Step (raises CellTransferPlanRejected like the owner would)."""
    planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: "c" * 64,
                                          accepted_item_geometry=lambda _r, _i: geometry, monotonic=lambda: 0.0)
    poses = step_poses(inputs)
    request = CellTransferRequest(
        job_id="g1", recipe_sha256="a" * 64, cell_sha256="c" * 64, step_index=index, item="box",
        home=poses["home"], pick=poses["pick"], place=poses["place"],
        pick_approach_z=inputs["source_approach_z_base_m"], place_approach_z=inputs["destination_approach_z_base_m"],
        carry_z=inputs["carry_z_base_m"], grasp_depth_m=geometry["grasp_depth_m"],
        grasp_width_m=geometry["grasp_width_m"])
    return planner.plan_transfer(request, profile, home_state(kin, profile, inputs))


def phase_durations(plan) -> dict[str, float]:
    return {phase.phase_id: phase.points[-1].time_from_start_s for phase in plan.phases}


# Swept volume -------------------------------------------------------------------------------------
def _to_cell(base, point):
    bx, by, byaw = base
    c, s = math.cos(byaw), math.sin(byaw)
    return (bx + c * point[0] - s * point[1], by + s * point[0] + c * point[1], point[2])


def capsules(kin, base, joints, *, fingertip_m: float, item: tuple[float, float] | None) -> list[tuple]:
    """(a, b, radius) capsules of one configuration in the cell frame; ``item`` = (hang, radius)."""
    return [(_to_cell(base, a), _to_cell(base, b), r)
            for a, b, r in arm_capsules(kin, joints, fingertip_m=fingertip_m, item=item)]


def _segment_distance(p1, q1, p2, q2) -> float:
    """Closest distance between segments p1-q1 and p2-q2 (Ericson, Real-Time Collision Detection 5.1.9)."""
    d1 = [q - p for p, q in zip(p1, q1)]
    d2 = [q - p for p, q in zip(p2, q2)]
    r = [a - b for a, b in zip(p1, p2)]
    a, e, f = sum(x * x for x in d1), sum(x * x for x in d2), sum(x * y for x, y in zip(d2, r))
    if a <= 1e-15 and e <= 1e-15:
        return math.dist(p1, p2)
    if a <= 1e-15:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = sum(x * y for x, y in zip(d1, r))
        if e <= 1e-15:
            t, s = 0.0, min(max(-c / a, 0.0), 1.0)
        else:
            b = sum(x * y for x, y in zip(d1, d2))
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-15 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, min(max(-c / a, 0.0), 1.0)
            elif t > 1.0:
                t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    c1 = [p + x * s for p, x in zip(p1, d1)]
    c2 = [p + x * t for p, x in zip(p2, d2)]
    return math.dist(c1, c2)


def _box(caps) -> tuple:
    lo = [min(min(a[i], b[i]) - r for a, b, r in caps) for i in range(3)]
    hi = [max(max(a[i], b[i]) + r for a, b, r in caps) for i in range(3)]
    return lo, hi


def _gap(box1, box2) -> float:
    return max(max(box1[0][i] - box2[1][i], box2[0][i] - box1[1][i]) for i in range(3))


@dataclass(frozen=True)
class Sweep:
    """All capsules one arm occupies over one Step (decimated; each radius grows by DECIMATE_M)."""
    label: str
    capsules: tuple
    box: tuple


def sweep(kin, profile, base, plan, *, label: str, hang_radius: tuple[float, float]) -> Sweep:
    fingertip = profile.fingertip_overhang_m
    caps, last = [], None
    for phase in plan.phases:
        holding = phase.phase_id in {"grasp", "transfer"}
        for point in phase.points:
            joints = point.positions[:5]
            pts, _ = kin.link_points(joints, fingertip)
            if last is not None and phase.phase_id == last[1] and max(
                    math.dist(p, q) for p, q in zip(pts, last[0])) < DECIMATE_M:
                continue
            last = (pts, phase.phase_id)
            for a, b, r in capsules(kin, base, joints, fingertip_m=fingertip, item=hang_radius if holding else None):
                caps.append((a, b, r + DECIMATE_M))
    return Sweep(label, tuple(caps), _box(caps))


def home_sweep(kin, profile, base, inputs, *, label: str) -> Sweep:
    joints = home_state(kin, profile, inputs).joint_positions
    caps = capsules(kin, base, [joints[name] for name in ARM_JOINTS], fingertip_m=profile.fingertip_overhang_m,
                    item=None)
    return Sweep(label, tuple(caps), _box(caps))


def clearance(a: Sweep, b: Sweep) -> float:
    """Smallest surface distance between two sweeps (negative = overlap); culls by bounding boxes."""
    if _gap(a.box, b.box) > 0.05:
        return _gap(a.box, b.box)
    best = math.inf
    boxes_b = [(cap, _box([cap])) for cap in b.capsules]
    for cap_a in a.capsules:
        box_a = _box([cap_a])
        for cap_b, box_b in boxes_b:
            if _gap(box_a, box_b) >= best:
                continue
            best = min(best, _segment_distance(cap_a[0], cap_a[1], cap_b[0], cap_b[1]) - cap_a[2] - cap_b[2])
    return best


def concurrent_pairs(job_steps) -> list[tuple[int, int]]:
    """Steps two arms may run at once: different primary arms and zones, neither depends on the other."""
    placements = [s["placement"] for s in job_steps]
    after = descendants([tuple(p["depends_on"]) for p in placements])
    pairs = []
    for i, p in enumerate(placements):
        for j in range(i + 1, len(placements)):
            q = placements[j]
            if p["arm"] != q["arm"] and p["zone"] != q["zone"] and j not in after[i] and i not in after[j]:
                pairs.append((i, j))
    return pairs


def plan_job(layout: Layout, job, kin, profile) -> dict[tuple[int, str], object]:
    """The owner plan of every (step, arm) the Job may send, primary and alternates."""
    skus = [s["sku"] for s in job.job["plan"]["steps"]]
    geometry = item_geometry(layout.recipe)
    return {(i, role): plan_step(kin, profile, inputs, geometry[skus[i]], index=i)
            for i, step in enumerate(job.steps) for role, inputs in step["placement"]["actions"].items()}


def swept_separation(layout: Layout, job, plans, kin, profile) -> list[dict]:
    """Clearance of every concurrent Step pair, and of each Step against the idle other arm at home."""
    bases = workcell_bases(layout.workcell)
    items = {i.sku: i for i in layout.recipe.items}
    skus = [s["sku"] for s in job.job["plan"]["steps"]]

    def hang(index):
        item = items[skus[index]]
        return (item.height - item.grasp_depth, math.hypot(item.length, item.width) / 2)
    sweeps = {(i, s["placement"]["arm"]): sweep(kin, profile, bases[s["placement"]["arm"]],
                                                 plans[(i, s["placement"]["arm"])], label=f"step{i}",
                                                 hang_radius=hang(i))
              for i, s in enumerate(job.steps)}
    homes = {role: home_sweep(kin, profile, bases[role],
                              next(s["placement"]["actions"][role] for s in job.steps
                                   if role in s["placement"]["actions"]), label=f"home-{role}") for role in bases}
    out = []
    for i, j in concurrent_pairs(job.steps):
        a, b = job.steps[i]["placement"]["arm"], job.steps[j]["placement"]["arm"]
        out.append({"pair": [i, j], "arms": [a, b], "zones": [job.steps[i]["placement"]["zone"],
                                                              job.steps[j]["placement"]["zone"]],
                    "clearance_m": round(clearance(sweeps[(i, a)], sweeps[(j, b)]), 4)})
    for (i, role), swept in sweeps.items():
        for other, home in homes.items():
            if other != role:
                out.append({"pair": [i, "home"], "arms": [role, other],
                            "zones": [job.steps[i]["placement"]["zone"], None],
                            "clearance_m": round(clearance(swept, home), 4)})
    return out


# Schedule model -------------------------------------------------------------------------------------
def makespan(job_steps, durations: dict[tuple[int, str], float]) -> dict:
    """Event schedule under the Fleet ready rules (goal confirmation taken as instant)."""
    placements = [s["placement"] for s in job_steps]
    done_at: dict[int, float] = {}
    busy_arm: dict[str, float] = {}
    busy_zone: dict[str, float] = {}
    started: dict[int, tuple[float, float, str]] = {}
    now = 0.0
    while len(done_at) < len(placements):
        progressed = True
        while progressed:
            progressed = False
            for index, placement in enumerate(placements):
                arm, zone = placement["arm"], placement["zone"]
                if index in started or any(done_at.get(d, math.inf) > now for d in placement["depends_on"]):
                    continue
                if busy_arm.get(arm, 0.0) > now or busy_zone.get(zone, 0.0) > now:
                    continue
                end = now + durations[(index, arm)]
                started[index] = (now, end, arm)
                busy_arm[arm] = busy_zone[zone] = end
                done_at[index] = end
                progressed = True
        future = [t for t in [*busy_arm.values(), *done_at.values()] if t > now]
        if not future:
            break
        now = min(future)
    return {"makespan_s": round(max(done_at.values()), 3), "serial_s": round(sum(durations[(i, p["arm"])]
                                                                             for i, p in enumerate(placements)), 3),
            "intervals": {i: [round(a, 3), round(b, 3), arm] for i, (a, b, arm) in sorted(started.items())}}


def one_arm_plan(layout: Layout):
    """The same recipe in a one-arm cell: the left base, the same pallet origin, both stations, no zones.
    Planned with the cell's annulus reach like the two-arm Job; ``report`` audits it with the IK."""
    left = layout.cell_doc["arms"][0]
    plain = {"arms": [{"role": left["role"], "base_in_cell": left["base_in_cell"]}], "zones": [],
             "pallet_origins": {s.id: list(layout.workcell.pallet_origins[s.id]) for s in layout.recipe.pallets},
             "stations": {name: [v["x"], v["y"], v["z"]] for name, v in layout.cell_doc["stations"].items()},
             "approach_clearance_m": layout.cell_doc["approach_clearance_m"]}
    workcell = workcell_from_dict(plain)
    return workcell, plan_mixed(layout.recipe, workcell, annulus_reach(workcell, *layout.cell.reach_m))


# Stack quality ----------------------------------------------------------------------------------------
def stack_report(recipe, placements) -> dict:
    """Fill rate and the planner's static rules re-applied to the final stack (no physics)."""
    slot = recipe.pallets[0]
    volume = sum(p.lx * p.ly * p.h for p in placements)
    floor = sum(p.lx * p.ly for p in placements if p.z <= 1e-9)
    violations = [p.index for j, p in enumerate(placements) if p.z > 1e-9
                  and not support_ok(*support_ratio_and_corners(p, list(placements[:j])))]
    return {"items": len(placements), "skus": sorted({p.sku for p in placements}),
            "fill_rate_volume": round(volume / (slot.pallet.length * slot.pallet.width
                                                * slot.pallet.max_stack_height), 4),
            "floor_coverage": round(floor / (slot.pallet.length * slot.pallet.width), 4),
            "stack_height_m": round(max(p.top for p in placements), 4),
            "support_violations": violations, "load_violations": [p.index for p in load_problems(list(placements))]}


def barrier_skews(job, plans) -> list[dict]:
    """For Steps compiled for two arms: arrival skew at both_grasped (after grasp) and placed_before_push
    (after transfer), as the difference of the two arms' planned phase times (send skew excluded)."""
    out = []
    for i, step in enumerate(job.steps):
        roles = sorted(step["placement"]["actions"])
        if len(roles) < 2:
            continue
        times = {role: phase_durations(plans[(i, role)]) for role in roles}
        grasped = [times[r]["approach"] + times[r]["grasp"] for r in roles]
        placed = [g + times[r]["transfer"] for g, r in zip(grasped, roles)]
        out.append({"step": i, "arms": roles, "after_grasp_s": [round(v, 3) for v in grasped],
                    "skew_after_grasp_s": round(abs(grasped[0] - grasped[1]), 3),
                    "skew_after_transfer_s": round(abs(placed[0] - placed[1]), 3)})
    return out


def variant_cell(cell_doc: dict, *, separation_m: float, home_x_m: float) -> dict:
    """The two-arm cell with another base separation (pallet and an 0.08 m shared band kept centred)
    and another taught home x (both arms, base frame)."""
    out = json.loads(json.dumps(cell_doc))
    mid = separation_m / 2
    out["arms"][1]["base_in_cell"]["x"] = separation_m
    for arm in out["arms"]:
        arm["home"]["x"] = home_x_m
    out["pallet_frames"]["pallet_a"]["x"] = round(mid - 0.10, 6)
    zones = {zone["zone_id"]: zone for zone in out["zones"]}
    zones["left_half"]["x_max"] = zones["shared_band"]["x_min"] = round(mid - 0.04, 6)
    zones["shared_band"]["x_max"] = zones["right_half"]["x_min"] = round(mid + 0.04, 6)
    zones["right_half"]["x_max"] = round(separation_m + 0.17, 6)
    out["stations"]["infeed_right"]["x"] = separation_m
    return out


def separation_only(recipe_doc: dict, cell_doc: dict) -> dict:
    """Reach failures and the smallest swept clearance of one layout (the variant sweep)."""
    layout = layout_from(recipe_doc, cell_doc)
    kin, profile = kinematics_and_profile()
    job = compile_mixed_cell_job(layout.recipe, layout.cell)
    _, failures = reach_audit(job.steps, kin, profile)
    pairs = swept_separation(layout, job, plan_job(layout, job, kin, profile), kin, profile)
    worst = min(pairs, key=lambda item: item["clearance_m"])
    return {"reach_failures": len(failures), "min_clearance_m": worst["clearance_m"], "worst_pair": worst}


def report(recipe_doc: dict, cell_doc: dict) -> dict:
    layout = layout_from(recipe_doc, cell_doc)
    kin, profile = kinematics_and_profile()
    job = compile_mixed_cell_job(layout.recipe, layout.cell)
    checked, failures = reach_audit(job.steps, kin, profile)
    try:
        ik_plan = plan_mixed(layout.recipe, layout.workcell, ik_reach(layout.workcell, kin, profile))
        replan = {"same_plan_as_annulus": ik_plan.digest == job.job["plan_digest"]}
    except PlanError as exc:
        replan = {"refused": list(exc.problems)}
    plans = plan_job(layout, job, kin, profile)
    durations = {key: sum(phase_durations(plan).values()) for key, plan in plans.items()}
    separation = swept_separation(layout, job, plans, kin, profile)
    one_cell, one_plan = one_arm_plan(layout)
    geometry = item_geometry(layout.recipe)
    one_inputs = _one_arm_inputs(layout, one_cell, one_plan)
    one_checked, one_failures = reach_audit([{"placement": {"actions": {"left": inputs}}} for _, inputs in one_inputs],
                                            kin, profile)
    one_durations = [sum(phase_durations(plan_step(kin, profile, inputs, geometry[step.sku],
                                                   index=step.index)).values()) for step, inputs in one_inputs]
    two = makespan(job.steps, durations)
    return {"recipe": layout.recipe.name, "layout": layout_facts(layout),
            "reach": {"checked_poses": checked, "failures": failures, "ik_replan": replan},
            "swept_separation": {"min_clearance_m": min(item["clearance_m"] for item in separation),
                                 "required_m": MIN_CLEARANCE_M, "pairs": separation},
            "phase_time_s": {f"{i}:{role}": round(v, 3) for (i, role), v in sorted(durations.items())},
            "two_arm": two, "one_arm": {"steps": len(one_durations), "serial_s": round(sum(one_durations), 3),
                        "reach_checked_poses": one_checked, "reach_failures": one_failures},
            "speedup_vs_one_arm": round(sum(one_durations) / two["makespan_s"], 3),
            "stack_two_arm": stack_report(layout.recipe, job_placements(layout)),
            "stack_one_arm": stack_report(layout.recipe, one_plan.placements),
            "barrier_skews": barrier_skews(job, plans)}


def job_placements(layout: Layout):
    return plan_mixed(layout.recipe, layout.workcell, layout.cell.reach(layout.workcell)).placements


def _one_arm_inputs(layout: Layout, workcell, plan):
    from rosy.processes.palletizing.mixed_submission import step_placements
    home = tuple(layout.cell_doc["arms"][0]["home"][k] for k in ("x", "y", "z", "yaw"))
    steps = step_placements(layout.recipe, workcell, plan, {workcell.arms[0].role: home})
    return [(step, s["placement"]["actions"][workcell.arms[0].role]) for step, s in zip(plan.steps, steps)]


def main() -> dict:
    two, _ = read_documents(MIXED_FIXTURE / "recipe.yaml", MIXED_FIXTURE / "cell.yaml")
    four, _ = read_documents(G1_FIXTURE / "recipe_4sku.yaml", MIXED_FIXTURE / "cell.yaml")
    _, fixture_cell = read_documents(MIXED_FIXTURE / "recipe.yaml", MIXED_FIXTURE / "cell.yaml")
    _, g1_cell = read_documents(MIXED_FIXTURE / "recipe.yaml", G1_FIXTURE / "cell_g1.yaml")
    variants = {f"sep{sep:.2f}_home{home:.2f}_{name}": separation_only(recipe, variant_cell(
        g1_cell, separation_m=sep, home_x_m=home)) for sep in (0.30, 0.33, 0.35) for home in (0.08, 0.12)
        for name, recipe in (("2sku", two), ("4sku", four))}
    return {"fixture_cell_2sku": report(two, fixture_cell), "g1_cell_2sku": report(two, g1_cell),
            "g1_cell_4sku": report(four, g1_cell), "layout_variants": variants}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, sort_keys=True, default=str))


__all__ = ["CellPose", "CellTransferPlanRejected", "G1_FIXTURE", "MIXED_FIXTURE", "MIN_CLEARANCE_M", "PROFILE_PATH",
           "barrier_skews", "concurrent_pairs", "ik_reach", "kinematics_and_profile", "layout_facts", "layout_from",
           "load_layout", "makespan", "one_arm_plan", "plan_job", "plan_step", "reach_audit", "read_documents",
           "report", "separation_only", "stack_report", "swept_separation", "variant_cell"]
