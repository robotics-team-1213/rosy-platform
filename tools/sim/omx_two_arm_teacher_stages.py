"""Stage-1/Stage-2 handoff generation, pose judging, concurrent scheduler, and video recording helpers for `omx_two_arm_teacher`."""
import json
import math
from pathlib import Path
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
_CELL = str(Path(__file__).resolve().parents[2] / "deploy" / "robot" / "omx")
if _CELL not in sys.path:
    sys.path.append(_CELL)  # appended: only cell_belt_handover is wanted from there
import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import palletizing_gripper as jaw  # noqa: E402
from cell_belt_handover import BeltHandover, Hold  # noqa: E402

FPS = 15
CARRY_SPEED = .05  # m/s; .08 let a 16 g container swing 10 deg in the jaws on the short reach to the near row
OPEN_GAP = dict(belt=.042, ship=.033, temp=.038, outbound=.038)
HOLD_GAP = .030 - jaw.SQUEEZE_M
SERVO_GAIN = 40.  # omx_physics design kp of every joint: about 0.16 s from command to arrival
BELT_MISSING_AFTER_S = 20.  # a placed delivery that still shows nothing at the belt end after this much sim time is `missing`
RECORDED = ("top", "side", "a_wrist", "b_wrist")  # the cell's four cameras (D-960); the world's overview is not one of them
PREFIX = {"arm_a": "a_", "arm_b": "b_"}
parse_choices = sites.parse_choices
VISION_SKEW_CHOICES = dict(temp_lanes="photo-20261110", ship_pose="photo-20261110", belt_pose="photo-20261110",
                           arm_bases="plate-centre", wrist_camera="photo-20261110", physics="twin-kp-20261109")


class Faults:
    """The belt/fault injections a concurrent run must prove itself against (three-arm design, increment C); all off by default."""

    def __init__(self, unknown_p=0., miss="", fail_at="", slow=None, seed=0):
        self.unknown_p, self.miss, self.fail_at = unknown_p, miss, fail_at
        self.slow = dict(slow or {})
        self.rng = np.random.default_rng(seed) if unknown_p else None  # no draws at P=0: seeded runs stay identical


def servo_values(model, ids):
    """The five arm joints' servo and passive constants a seed may change (omx_two_arm_skill.disturb), as the model has them."""
    dofs = model.jnt_dofadr[model.actuator_trnid[ids[:5], 0]]
    return dict(kp=model.actuator_gainprm[ids[:5], 0].copy(), kv=-model.actuator_biasprm[ids[:5], 2], force=model.actuator_forcerange[ids[:5], 1].copy(),
                damping=model.dof_damping[dofs].copy(), frictionloss=model.dof_frictionloss[dofs].copy())


def judge_pose(world, data, cid, site, limits):
    """Container against its target site: position, yaw (180 deg symmetric), height, tilt."""
    s = world.layout.sites[site]
    pos, yaw, tilt = world.pose(data, cid)
    xy = float(np.linalg.norm(pos[:2] - s["xy"])) * 1000
    dyaw = abs(math.degrees(tasks.wrap_pi(yaw - s["yaw"])))
    dz = float(pos[2] - s["z"]) * 1000
    ok = xy <= limits["xy_mm"] and dyaw <= limits["yaw_deg"] and abs(dz) <= limits["z_mm"] and tilt <= limits["tilt_deg"]
    return dict(ok=bool(ok), xy_mm=round(xy, 1), yaw_deg=round(dyaw, 1), z_mm=round(dz, 1), tilt_deg=round(tilt, 1))


class Ctx:
    """What one running step tracks: its arm's contacts, the carried container, the phase, tilts and every container another arm moved
    meanwhile (not a disturbance by this step). The Teacher itself is the context of a sequential step (the policy reads its fields)."""

    def __init__(self, arm):
        self.arm, self.carried, self.phase, self.first, self.tilt, self.held_tilt, self.others = arm, None, "", {}, 0., 0., set()
        self.contacts = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())


def run_concurrent_steps(teacher, data, task, here, max_s=900, faults=None):
    """Both arms at once (D-778 L1). Each arm runs its own steps in the given order; a step starts when its `after` steps are done
    and its zones are free. A belt pick is gated by the one-box handover ledger instead of `after_pick`: reserve -> placed (the
    container dropped at the belt end) -> arrived (a reading says occupied) -> grasped -> cleared (a reading says empty); a placed
    delivery that never shows up is `missing` after BELT_MISSING_AFTER_S and stops both arms."""
    L = teacher.layout
    faults = faults or Faults()
    queue = {a: [s for s in task["steps"] if s["arm"] == a] for a in L.arms}
    status, held, running, rows, timing = {}, {}, {}, [], {}
    last = {a: L.sim_arms[a].wait.copy() for a in L.arms}
    frames = 0
    belt = BeltHandover(BELT_MISSING_AFTER_S, clock=lambda: frames / FPS)  # sim time only: the ledger never sees a wall clock
    belt_gen, started, halt, halt_f, halt_wait, placed_t = {}, {}, None, None, 0., 0.
    stall = {a: 0. for a in faults.slow}  # a slowed arm reuses its target for extra frames: stretched segments, progress still measured
    inv = dict(max_cargo_on_belt=0, picks_before_arrival=0, steps_started_after_stop=0)

    def belt_cargo():
        """How many containers stand at the belt end right now, straight from the sim (no injected unknown)."""
        b, n = L.sites["belt"], 0
        for c, _ in L.containers():
            p = teacher.world.pose(data, c)[0]
            if math.hypot(float(p[0]) - b["xy"][0], float(p[1]) - b["xy"][1]) < .045 and abs(float(p[2]) - b["z"]) < .02:
                n += 1
        inv["max_cargo_on_belt"] = max(inv["max_cargo_on_belt"], n)
        return n

    def reading():
        """The synthetic belt reading: occupied/empty from the sim state, `unknown` with the injected seeded probability."""
        if faults.rng is not None and faults.rng.random() < faults.unknown_p:
            return {"occupancy": "unknown", "reason": "injected"}
        return {"occupancy": "occupied" if belt_cargo() else "empty", "reason": "sim"}

    def result(stop_reason):
        if halt is not None:
            inv["steps_started_after_stop"] = sum(f > halt_f for f in started.values())
        extra = dict(belt_events=belt.events, invariants=inv)
        if stop_reason == "belt_missing":
            extra["belt_wait_s"] = round(halt_wait, 1)
        return rows, timing, stop_reason, extra

    while any(queue.values()) or running or belt.state == "picked":  # the last pick still owes its empty reading
        if belt.state == "placed":
            try:
                belt.arrived(belt.generation, belt.cargo, reading())
            except Hold:
                pass
            if belt.check() == "missing":
                halt, halt_f, halt_wait = "belt_missing", frames, frames / FPS - placed_t
        elif belt.state == "picked":
            try:
                belt.cleared(belt.generation, reading())
            except Hold:
                pass
        for arm in L.arms:
            if arm in running or not queue[arm] or halt:
                continue
            s = queue[arm][0]
            pick, place = set(s["zones"][0]), set(s["zones"][1])
            done_after = all(status.get(d) == "done" for d in s.get("after", []))
            free = not any(z in held for z in pick | place)
            if s["from"] == "belt":
                if done_after and belt.state == "empty":
                    try:  # S may load: take the token, report the place, drop the container at the belt end
                        g = belt.reserve(s["container"], reading())
                        belt.placed(g, s["container"])
                        teacher.world.put(data, s["container"], "belt")
                        if s["id"] == faults.miss:  # this delivery never arrives: the container leaves the cell again
                            teacher.world.put(data, s["container"], None, [c for c, _ in L.containers()].index(s["container"]))
                        belt_gen[s["id"]], placed_t = g, frames / FPS
                    except Hold:
                        pass
                if not done_after or not free or belt.state != "at_end" or belt.cargo != s["container"]:
                    continue  # nothing of this step's at the belt end yet (or the token is another step's): the pick gate holds
            elif not done_after or not free or not all(status.get(d) for d in s.get("after_pick", [])):
                continue  # a non-belt step keeps its plan's after_pick
            queue[arm].pop(0)
            started[s["id"]] = frames
            if s["from"] == "belt" and not belt_cargo():
                inv["picks_before_arrival"] += 1  # tripwire: the arm reached for the belt before any container stood there
            held.update({z: s["id"] for z in pick | place})
            ctx = Ctx(arm)
            ctx.step, ctx.here = s, {k: v for k, v in here.items() if k != s["container"]}
            running[arm] = (s, teacher.step_gen(data, s, ctx.here, ctx), ctx, pick - place)
            timing[s["id"]] = dict(arm=arm, start_s=round(frames / FPS, 2))
        if not running:
            heads = [q[0] for q in queue.values() if q]
            # every blocked head waiting on the belt ledger (a delivery in flight, or readings to retry) is waiting, not deadlock
            belt_waiting = all(s["from"] == "belt" and all(status.get(d) == "done" for d in s.get("after", [])) for s in heads)
            if halt or (not heads and belt.state != "picked") or (heads and not belt_waiting):
                return result(halt or f"deadlock: {[s['id'] for s in heads]} cannot start")
        targets = {}
        parking = [a for a, r in running.items() if r[2].phase == "park"]
        for arm, (s, gen, ctx, pick_only) in list(running.items()):
            if ctx.phase == "park" and parking[0] != arm:
                continue
            if stall.get(arm, 0.) >= 1.:
                stall[arm] -= 1.
                targets[arm] = last[arm]
                continue
            try:
                targets[arm] = last[arm] = next(gen)
            except StopIteration as stop:
                rows.append(stop.value)
                print(json.dumps(stop.value), flush=True)
                status[s["id"]] = "done"
                timing[s["id"]]["end_s"] = round(frames / FPS, 2)
                held = {z: i for z, i in held.items() if i != s["id"]}
                here[s["container"]] = s["to"]
                teacher.off_stand(data, s, here)
                del running[arm]
                continue
            if arm in faults.slow:
                stall[arm] += faults.slow[arm] - 1.
            if ctx.phase in ("carry", "lower", "release", "retreat", "park") and not status.get(s["id"]):
                status[s["id"]] = "picked"
                timing[s["id"]]["picked_s"] = round(frames / FPS, 2)
                here.pop(s["container"], None)
                if s["from"] == "belt":
                    belt.grasped(belt_gen[s["id"]], s["container"])
                if s["id"] == faults.fail_at:  # the injected failure: the pick is done, the step is not
                    rows.append(dict(step=s["id"], container=s["container"], arm=arm, source=s["from"], target=s["to"],
                                     result="fail", reason="injected failure right after the pick (--fail-at)"))
                    print(json.dumps(rows[-1]), flush=True)
                    status[s["id"]], timing[s["id"]]["end_s"] = "failed", round(frames / FPS, 2)
                    held = {z: i for z, i in held.items() if i != s["id"]}
                    gen.close()
                    del running[arm]
                    halt, halt_f = f"failed:{s['id']}", frames
                    continue
            if ctx.phase in ("lower", "release", "retreat", "park"):
                held = {z: i for z, i in held.items() if not (i == s["id"] and z in pick_only)}
        ctxs = [r[2] for r in running.values()]
        for c in ctxs:
            c.others |= {o.carried for o in ctxs if o is not c and o.carried}
        teacher.frame(data, {a: targets.get(a, last[a]) for a in L.arms}, " | ".join(r[0]["id"] for r in running.values()) or "wait", ctxs)
        frames += 1
        if frames > max_s * FPS:
            return result(f"timeout after {max_s} s")
    return result(halt)


def isaac_handoff(result, layout, seed=0):
    """Build a Stage-1 (MuJoCo geometry/vision/IK) -> Stage-2 (Isaac PhysX contact/slip/seating) handoff spec."""
    rows = result.get("rows", [])
    vis = [r["vision_pick"] for r in rows if "vision_pick" in r]
    poses = [r["pose"] for r in rows if "pose" in r]
    contacts_clear = all(not r.get("arm_arm_contacts") and not r.get("arm_link_contacts")
                         and not r.get("neighbours_disturbed") for r in rows)
    belt_xy = layout.sites["belt"]["xy"]
    single_cases = []
    for r in rows:
        vp = r.get("vision_pick")
        if vp:
            dx = max(-.025, min(.025, round(vp["seen_xy"][0] - belt_xy[0], 4)))
            dy = max(-.025, min(.025, round(vp["seen_xy"][1] - belt_xy[1], 4)))
            turn = max(-45., min(45., round(vp["seen_yaw_deg"], 1)))
            aim_m = round(min(.025, vp["xy_err_mm"] / 1000), 4)
            task_name = r.get("task") or result.get("task", "two-arm")
            single_cases.append(dict(
                id=f"mujoco-{task_name}-{r['step']}-{r['container']}",
                source=f"mujoco:{task_name}:{r['step']}",
                sim=dict(box=[dx, dy, turn], place="belt", grasp_turn=turn, expect=None, aim=[aim_m, 0.0]),
            ))
    layers = 3 if result.get("steps", 0) > 3 else 1
    cal_keys = ("top_camera", "wrist_camera", "physics", "arm_bases", "belt_pose", "ship_pose", "temp_lanes", "cell_snapshot")
    return dict(
        schema="rosy.omx-mujoco-isaac-handoff.v1",
        task=result.get("task", "two-arm"),
        real2sim_calibration={k: layout.choices.get(k) for k in cal_keys},
        stage_1_mujoco=dict(
            role="geometry_vision_ik_and_collision_screening",
            completed=bool(result.get("completed")),
            steps_pass=result.get("steps_pass", 0),
            steps_total=result.get("steps", 0),
            contacts_clear=contacts_clear,
            worst_vision_xy_mm=max((v["xy_err_mm"] for v in vis), default=0.0),
            worst_vision_yaw_deg=max((v["yaw_err_deg"] for v in vis), default=0.0),
            worst_pose_xy_mm=max((p["xy_mm"] for p in poses), default=0.0),
            worst_pose_yaw_deg=max((p["yaw_deg"] for p in poses), default=0.0),
            worst_ik_error_mm=max((r.get("worst_ik_error_mm", 0.0) for r in rows), default=0.0),
            colours_seen=[v.get("colour") for v in vis if v.get("colour")],
        ),
        stage_2_isaac=dict(
            role="physx_contact_pad_slip_and_seating_confirmation",
            ready=bool(result.get("completed") and contacts_clear),
            two_arm_scenario="omx-map-container-stack",
            two_arm_config=dict(seed=seed, layers=layers, case="nominal-palletizing-v21-ship-surveyed-skew-20261110"),
            single_arm_scenario="arm-s-cell-case",
            single_arm_cases=single_cases,
        ),
    )


def open_video_writer(world, out: Path, task_name: str, video_skip: int = 1):
    """Open an H.264 4-camera grid video writer (`(writer_hook, close_fn)`)."""
    video_path = str(out / f"{task_name}{'-short' if video_skip > 1 else ''}.mp4")
    from PIL import Image, ImageDraw
    try:
        import av
        container = av.open(video_path, "w")
        stream = container.add_stream("h264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = 1280, 960, "yuv420p"
        encode_rgb = lambda arr: container.mux(stream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")))  # noqa: E731
        close_video = lambda: (container.mux(stream.encode(None)), container.close())  # noqa: E731
    except ImportError:
        import subprocess
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x960",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", video_path],
            stdin=subprocess.PIPE,
        )
        encode_rgb = lambda arr: ff.stdin.write(arr.tobytes())  # noqa: E731
        close_video = lambda: (ff.stdin.close(), ff.wait())  # noqa: E731

    count = [0]

    def writer(data, label):
        count[0] += 1
        if count[0] % video_skip:
            return
        frame = Image.fromarray(np.vstack([np.hstack([world.render(data, view) for view in row]) for row in (RECORDED[:2], RECORDED[2:])]))
        ImageDraw.Draw(frame).text((8, 8), f"{task_name} {label}", fill=(255, 255, 0))
        encode_rgb(np.asarray(frame))

    return writer, close_video
