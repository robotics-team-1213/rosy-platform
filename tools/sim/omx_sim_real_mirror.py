"""Real OMX cell <-> two-arm MuJoCo world, read only: the real arms mirrored into the sim, and a sim plan drawn on the real top frame.

mirror: each arm's chunk-io/live.json (`state` = follower units, body -100..100 and gripper 0..100; `target` the same) poses arm_a and
arm_b of `omx_two_arm_world.World` through `cell_act_inputs` (the ACT shadow's own conversion, not a copy). It writes the sim render of
every view next to the real frame (sim_<view>.png, blend_<view>.png) and report.json: per arm the joints in radians, target - state,
the TCP by the MuJoCo world (sim TCP) and by `omx_two_arm_kin` with the real arm's TCP (`real FK`), and their difference in mm.
An arm without a live row is named in `missing` and drawn at its wait pose; nothing is filled in.

preview: a planned chunk (rows of follower units for one arm, or 12 sim radians for both arms as the two-arm policy emits) or world
points (IK targets) are projected with the sim's surveyed top camera onto a real top frame (preview_top.png). Nothing is sent to an arm.

    python tools/sim/omx_sim_real_mirror.py mirror --live arm_a=a/live.json --live arm_b=b/live.json --frame top=top.png --out DIR
    python tools/sim/omx_sim_real_mirror.py mirror ... --follow 0.5         # rewrite DIR every 0.5 s, report rows appended to mirror.jsonl
    python tools/sim/omx_sim_real_mirror.py preview --chunk chunk.json --frame top=top.png --out DIR
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import numpy as np  # noqa: E402
from arm_status_bridge import STALE_S  # noqa: E402
import cell_act_inputs as inputs  # noqa: E402  (to_radians, grip_rule, sim_gripper: the shadow's one conversion)
from omx_real2sim_helpers import Camera  # noqa: E402

VIEWS = {"top": "top", "side": "side", "a_wrist": "a_wrist", "b_wrist": "b_wrist"}  # real frame name -> World camera
PATH_BGR = {"arm_a": (255, 160, 0), "arm_b": (0, 120, 255)}
# the cell layout the real frames match: 2026-11-17 the arm_b jaw tip sat 5.5 mm from FK with it, 27 mm with the Layout defaults
PRESET = "v24-20261114"


def arm_q(units, rule) -> np.ndarray:
    """Six follower values -> the World's joint1..joint5, gripper_joint_1 radians."""
    body = inputs.to_radians(units)
    return np.array([body[j] for j in inputs.JOINTS[:5]] + [inputs.sim_gripper(float(units[5]), rule)])


def read_live(path, now):
    """The runner's live row, or (None, reason). An old row is kept and flagged: the mirror shows it, the report says how old."""
    try:
        row = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"
    if len(row.get("state") or ()) != 6:
        return None, "no six-value state"
    row["age_s"] = round(now - row["t"], 3) if isinstance(row.get("t"), (int, float)) else None
    row["stale"] = row["age_s"] is None or row["age_s"] > STALE_S
    return row, None


def mirror(world, lives: dict, rules: dict, now=None) -> tuple:
    """(MjData posed from the live rows, report). `lives` maps arm -> live.json path."""
    import mujoco

    now = time.time() if now is None else now
    data = world.reset()  # containers parked off the cell: only the arms are mirrored
    report = {"t": round(now, 3), "arms": {}, "missing": {}}
    for arm in inputs.ARMS:
        row, reason = read_live(lives[arm], now) if arm in lives else (None, "no --live given")
        if row is None:
            report["missing"][arm] = reason
            continue
        q = arm_q(row["state"], rules[arm])
        data.qpos[world.q[arm]] = q
        data.qpos[world.mimic[arm]] = -q[5]
        entry = {"age_s": row["age_s"], "stale": row["stale"], "chunk": row.get("chunk"), "fault": row.get("fault"),
                 "state_units": row["state"], "q_rad": q.round(5).tolist()}
        if len(row.get("target") or ()) == 6:
            qt = arm_q(row["target"], rules[arm])
            entry["target_minus_state_rad"] = (qt - q).round(5).tolist()
            fk_t, _ = world.layout.arms[arm]._tcp_and_R(qt)
            entry["target_tcp_m"] = fk_t.round(5).tolist()
        report["arms"][arm] = entry
    mujoco.mj_forward(world.model, data)
    for arm, entry in report["arms"].items():
        sim_tcp, _ = world.tcp(data, arm)
        fk, _ = world.layout.arms[arm]._tcp_and_R(np.array(entry["q_rad"]))
        entry.update(sim_tcp_m=sim_tcp.round(5).tolist(), real_fk_tcp_m=fk.round(5).tolist(),
                     fk_minus_sim_mm=((fk - sim_tcp) * 1000).round(2).tolist())
        if "target_tcp_m" in entry:
            entry["target_minus_state_tcp_mm"] = round(float(np.linalg.norm(np.array(entry["target_tcp_m"]) - fk)) * 1000, 2)
    return data, report


def write_views(world, data, frames: dict, out: Path) -> dict:
    """sim_<view>.png at each real frame's size and blend_<view>.png (half each); views without a real frame render at 480x640."""
    import cv2

    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for view, camera in VIEWS.items():
        real = frames.get(view)
        sim = cv2.cvtColor(world.render(data, camera, size=real.shape[:2] if real is not None else (480, 640)), cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(out / f"sim_{view}.png"), sim)
        written[view] = [f"sim_{view}.png"]
        if real is not None:
            cv2.imwrite(str(out / f"blend_{view}.png"), cv2.addWeighted(real, .5, sim, .5, 0))
            written[view].append(f"blend_{view}.png")
    return written


def plan_points(layout, chunk: dict) -> dict:
    """{arm: N x 3 world TCP points} of a chunk by the real arm's FK, or the given world points."""
    if "points" in chunk:
        return {chunk.get("arm", "plan"): np.asarray(chunk["points"], float).reshape(-1, 3)}
    rows = np.asarray(chunk["rows"], float)
    if rows.shape[1] == 2 * len(inputs.JOINTS):  # the two-arm policy's action: arm_a's six sim radians then arm_b's
        per_arm = {arm: rows[:, k * 6:k * 6 + 5] for k, arm in enumerate(inputs.ARMS)}
    elif rows.shape[1] == len(inputs.JOINTS) and chunk.get("arm") in inputs.ARMS:  # one arm's follower units, as the runner targets
        per_arm = {chunk["arm"]: np.array([[inputs.to_radians(r)[j] for j in inputs.JOINTS[:5]] for r in rows])}
    else:
        raise ValueError(f"rows of {rows.shape[1]} values: give 12 sim radians, or 6 follower units with arm")
    return {arm: np.array([layout.arms[arm]._tcp_and_R(q)[0] for q in qs]) for arm, qs in per_arm.items()}


def preview(layout, chunk: dict, top, out: Path) -> dict:
    """Draw the planned TCP path on the real top frame with the sim's top camera; returns the pixels drawn."""
    import cv2

    out.mkdir(parents=True, exist_ok=True)
    cam = Camera(layout.fixture["real_cameras"]["top"], top.shape[:2])
    image, pixels = top.copy(), {}
    for arm, points in plan_points(layout, chunk).items():
        uv = np.array([cam.project(p) for p in points])
        pixels[arm] = uv.round(1).tolist()
        colour = PATH_BGR.get(arm, (0, 255, 0))
        cv2.polylines(image, [uv.round().astype(np.int32)], False, colour, 2)
        cv2.circle(image, tuple(uv[-1].round().astype(int)), 6, colour, 2)  # where the chunk ends
    cv2.putText(image, "PLAN PREVIEW - not executed", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 2)
    cv2.imwrite(str(out / "preview_top.png"), image)
    return pixels


def _pairs(values, what) -> dict:
    out = {}
    for v in values or ():
        key, _, path = v.partition("=")
        if not path:
            raise SystemExit(f"--{what} wants name=path, got {v!r}")
        out[key] = path
    return out


def _frames(paths: dict) -> dict:
    import cv2

    frames = {}
    for view, path in paths.items():
        if view not in VIEWS:
            raise SystemExit(f"unknown view {view!r}: one of {sorted(VIEWS)}")
        frames[view] = cv2.imread(path)
        if frames[view] is None:
            raise SystemExit(f"cannot read frame {path}")
    return frames


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("mirror")
    m.add_argument("--live", action="append", help="arm_a=PATH or arm_b=PATH of a chunk-io/live.json")
    m.add_argument("--frame", action="append", help="VIEW=PATH of a real frame (top, side, a_wrist, b_wrist)")
    m.add_argument("--arm-cal", default=".", help="work dir holding the arms' arm-cal profiles (absent: cell_arm_cal defaults)")
    m.add_argument("--follow", type=float, help="seconds between refreshes; runs until interrupted")
    m.add_argument("--out", required=True)
    p = sub.add_parser("preview")
    p.add_argument("--chunk", required=True, help='JSON {"rows": [...], "arm": ...} or {"points": [[x, y, z], ...]}')
    p.add_argument("--frame", action="append", required=True, help="top=PATH")
    p.add_argument("--out", required=True)
    for one in (m, p):
        one.add_argument("--preset", default=PRESET, help="omx_two_arm_sites.PRESETS name; '' for the Layout defaults")
    args = parser.parse_args(argv)
    out = Path(args.out)
    import omx_two_arm_world

    world = omx_two_arm_world.World(**({"preset": args.preset} if args.preset else {}))
    if args.command == "preview":
        frames = _frames(_pairs(args.frame, "frame"))
        if "top" not in frames:
            raise SystemExit("preview needs --frame top=PATH")
        pixels = preview(world.layout, json.loads(Path(args.chunk).read_text(encoding="utf-8")), frames["top"], out)
        print(json.dumps({"preview": str(out / "preview_top.png"), "pixels": {a: len(v) for a, v in pixels.items()}}))
        return 0
    lives, frame_paths = _pairs(args.live, "live"), _pairs(args.frame, "frame")
    rules = {arm: inputs.grip_rule({"work_dir": args.arm_cal}, arm) for arm in inputs.ARMS}
    while True:
        data, report = mirror(world, lives, rules)
        report["views"] = write_views(world, data, _frames(frame_paths), out)
        (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        if args.follow is None:
            print(json.dumps({a: e["fk_minus_sim_mm"] for a, e in report["arms"].items()} | {"missing": report["missing"]}))
            return 0
        with (out / "mirror.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(report) + "\n")
        time.sleep(args.follow)


if __name__ == "__main__":
    raise SystemExit(main())
