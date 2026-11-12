"""Real-to-sim for the two-arm OMX cell: measure the real cell, write a dated snapshot, show what changed, rerun the sims
that read the changed items (D-947: geometry evidence; measured values are named choices, nothing silently overwritten).

  omx_real2sim.py capture --site USER@HOST --out RUN          frames of the cell cameras from the site's view server (read only)
  omx_real2sim.py measure RUN [--prev SNAPSHOT]                each item measured in parallel -> RUN/snapshot.json, RUN/overlay.png
  omx_real2sim.py diff OLD NEW                                 changed items, the sim stages they feed, their sim2real rows
  omx_real2sim.py sim SNAPSHOT --sha SHA --out DIR [--stages ..]   the stages in parallel on the lab PCs (remote_sim.py, never here)
  omx_real2sim.py report DIR                                    Markdown of what ran and passed
  omx_real2sim.py request belt RUN [--store DIR]               a ruler reading for a person (deploy/robot/omx/cell_requests.py)

The snapshot a sim stage reads must be committed at SHA (remote_sim ships commits only): keep the cell's snapshots in
deploy/robot/omx/sim/cell_snapshots/<stamp>.json. Today one item is measured automatically:
  temp_plates  each 3-lane plate's lane centres and yaws: dark lane pads and seated containers in the top frame,
               back-projected through the surveyed top camera onto the deck (containers onto their top); each plate is
               one printed fan (step, radius) placed where most of its visible lanes agree, so a covered lane comes from
               the plate; lane 1 is the smaller-y end of a plate facing its arm (+x), as printed.
  ship         the r08 hull outline (hull.stl, plan view at its deck) fitted to the hull and the containers on it in the
               top frame: stern x, centre y and yaw by overlap (IoU).
  belt         the dark belt strip back-projected at the belt surface: its near end (the stop) and centreline. The 2026-11-09
               frames put it at x .205, y -.037 against the fixture's .158 / .007, and a D435 depth check agreed within a
               few mm in xy; the 11-03 cell file's belt-end site lands on the belt's side rail in the same frame.
The pad size against the printed 90 x 30 mm is the check that the top camera model still holds there. Camera pose, joint
zeros and servo lag stay with omx_twin.py (omx_twin_night.py); the arm bases keep their CHOICES values.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_cell_anchor as anchor  # noqa: E402
from omx_real2sim_helpers import (  # noqa: E402, F401
    BELT_MIN_PX,
    LANE,
    PARTIAL_MIN,
    SIZE_TOL,
    Camera,
    axes_meet,
    blobs,
    fit_plate,
    fit_shape,
    fold,
    hull_outline,
    lane_blobs,
    measure_belt,
    measure_ship,
    measure_temp_plates,
    overlay,
    place,
    plate_lanes,
    rect,
    ship_polygon,
    turn,
)
import omx_two_arm_sites as sites  # noqa: E402

SCHEMA = "rosy.omx-cell-snapshot.v1"
VIEWER = "http://127.0.0.1:8767/frame/{}.jpg"  # rosy-omx-camera-view on the site PC (localhost only)
CAMERAS = ("top", "side", "arm_a_wrist", "arm_b_wrist")
CHANGED = (.003, 3.)         # m, deg: a lane moved more than this is a changed item; 3 deg is the pocket's own yaw
STAGGER_S = 45
GAPS = {"temp_plates": "G-17", "ship": "G-18", "camera": "G-19", "arm_bases": "G-21", "belt": "G-30"}  # sim2real registry rows each item reports to (D-480)
PY = "MUJOCO_GL=egl $HOME/rosy-test/venvs/sim-mujoco/bin/python"
SNAP_CHOICES = lambda path: ["--choice", f"cell_snapshot={path}", "--choice", "temp_lanes=snapshot", "--choice", "ship_pose=snapshot",  # noqa: E731
                             "--choice", "belt_pose=snapshot"]
SHIP_CHANGED_DEG = 1.        # the hull is 316 mm long: 1 deg moves its ends 2.8 mm
BELT_TOLERANCE_MM = 20.      # a tape between two points on a 55 mm step: the candidates differ by about 60 mm (2026-11-09)
STAGES = {
    "rehandle": ({"temp_plates", "ship"}, "ai", 40, "tools/sim/omx_two_arm_teacher.py run rehandle --out $OUT/rehandle"),
    "outbound": ({"temp_plates", "ship"}, "ai", 50, "tools/sim/omx_two_arm_plan.py compare --scenario outbound --replay-dir $OUT/outbound/plan {choices} && "
                 "$PY tools/sim/omx_two_arm_teacher.py run plan --plan $OUT/outbound/plan/outbound-two-arm.json --out $OUT/outbound"),
    "matrix-a": ({"temp_plates", "ship"}, "model", 60, "tools/sim/omx_two_arm_matrix.py --arm arm_a --out $OUT/matrix-a"),
    "matrix-b": ({"temp_plates", "ship"}, "model", 60, "tools/sim/omx_two_arm_matrix.py --arm arm_b --out $OUT/matrix-b"),
    "stack": ({"ship", "belt"}, "ai", 40, "tools/sim/omx_two_arm_teacher.py run stack --out $OUT/stack"),
}


def belt_request(run, layout=None):
    """A ruler reading that tells the snapshot's belt from the fixture's without the camera model: the level distance from
    arm_b's turntable axis to the middle of the belt's width at its stop. (request dict, image path)"""
    import cv2

    run = Path(run)
    snap = json.loads((run / "snapshot.json").read_text(encoding="utf-8"))
    belt = snap["items"].get("belt") or {}
    if "end_x_m" not in belt:
        raise SystemExit(f"{run}/snapshot.json has no measured belt ({belt.get('error', 'item missing')})")
    layout = layout or sites.Layout()
    axis = layout.arms["arm_b"].base[:2]
    points = dict(sim=(sites.BELT_STOP_X, layout.belt_y), camera=(belt["end_x_m"], belt["centre_y_m"]))
    predicted = {name: round(math.dist(axis, xy) * 1000) for name, xy in points.items()}
    frame = cv2.imread(str(run / "frames" / "top.jpg"))
    cam = Camera(layout.fixture["real_cameras"]["top"], frame.shape[:2])
    px = lambda x, y, z: tuple(int(round(v)) for v in cam.project((x, y, z)))  # noqa: E731
    origin = px(*axis, layout.table_z)
    for (name, xy), colour in zip(points.items(), ((0, 200, 0), (0, 0, 255))):
        cv2.line(frame, origin, px(*xy, layout.belt_top), colour, 2)
        cv2.circle(frame, px(*xy, layout.belt_top), 5, colour, -1)
        cv2.putText(frame, f"{name} {predicted[name]} mm", (px(*xy, layout.belt_top)[0] + 6, px(*xy, layout.belt_top)[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, colour, 1)
    cv2.circle(frame, origin, 6, (255, 0, 255), -1)
    image = run / "belt-request.png"
    cv2.imwrite(str(image), frame)
    stamp = (snap.get("taken_at") or "")[:16].replace("-", "").replace(":", "").replace("T", "-") or time.strftime("%Y%m%d-%H%M")
    return dict(
        id=f"belt-end-{stamp}", kind="measure", item="belt", gap=GAPS["belt"],
        question="arm_b 회전축에서 벨트 끝(멈춤 막대) 폭 가운데까지의 수평 거리",
        how=["arm_b 받침 위 회전 관절의 중심(보라 점)에 줄자 끝을 댄다.",
             "벨트가 끝나는 멈춤 막대에서 벨트 폭의 가운데 점까지 줄자를 수평으로 당긴다(벨트는 작업대보다 약 55 mm 낮다).",
             "mm로 읽어 적는다. 팔은 움직이지 않는다."],
        candidates=predicted, unit="mm", tolerance=BELT_TOLERANCE_MM,
        means=dict(sim="시뮬의 설계 벨트(멈춤 x %.3f, 중심 y %.3f)가 맞다: 카메라 모델을 다시 잰다(G-19)." % points["sim"],
                   camera="위 카메라가 잰 벨트(끝 x %.3f, 중심 y %.3f)가 맞다: belt_pose=snapshot을 기본으로 바꿀 수 있다(G-30)." % points["camera"],
                   neither="둘 다 아니다: 다시 재거나 벨트가 옮겨졌는지 본다."),
        source=dict(snapshot_taken_at=snap.get("taken_at"), frames=snap.get("frames"))), image


def measure(run, prev_path=None, camera_moved_ok=False):
    import cv2

    run = Path(run)
    prev = json.loads(Path(prev_path).read_text(encoding="utf-8")) if prev_path else None
    layout = sites.Layout()  # camera, deck and arms; where the plates were comes from prev
    frames = {c: run / "frames" / f"{c}.jpg" for c in CAMERAS if (run / "frames" / f"{c}.jpg").exists()}
    top = cv2.imread(str(frames["top"])) if "top" in frames else None
    if top is None:
        raise SystemExit(f"no readable top frame in {run / 'frames'}")
    anchor.remember(frames["top"])  # this frame is the next snapshot's reference
    camera_motion = dict(checked=False, reason="no previous snapshot")
    ref = prev and anchor.reference(prev.get("frames", {}).get("top", ""))
    if prev and not ref:
        camera_motion["reason"] = "the previous snapshot's top frame is not in the local frame store"
    elif ref:
        m = anchor.motion(cv2.imread(str(ref)), top)
        camera_motion = dict(checked=True, moved=anchor.moved(m), **m) if m else dict(checked=False, reason="too few far-band matches")
        if camera_motion.get("moved") and not camera_moved_ok:
            raise SystemExit(f"top camera moved since the previous snapshot ({m}): re-survey it (G-19, calibration step 3) "
                             "before measuring; --camera-moved-ok measures anyway")
    items = {"temp_plates": lambda: measure_temp_plates(top, layout, prev and prev["items"]["temp_plates"]),
             "ship": lambda: measure_ship(top, layout), "belt": lambda: measure_belt(top, layout)}
    with ThreadPoolExecutor() as pool:  # items are independent; more join here (belt end, arm bases) as they get measurers
        done = {k: pool.submit(f) for k, f in items.items()}
        results = {k: f.result() for k, f in done.items()}
    tp = results["temp_plates"]
    ab = dict(fk={n: dict(xy=[round(v, 4) for v in a.base[:2]], yaw_deg=round(math.degrees(a.yaw), 1)) for n, a in layout.arms.items()},
              plate_centre={n: dict(xy=list(xy), yaw_deg=yaw) for n, (xy, yaw) in sites.ARM_BASES_PLATE_CENTRE.items()})
    snap = dict(schema=SCHEMA, taken_at=json.loads((run / "capture.json").read_text())["taken_at"] if (run / "capture.json").exists() else None,
                frames={c: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for c, p in frames.items()},
                camera=dict(top=layout.fixture["real_cameras"]["top"]), camera_motion=camera_motion,
                items=dict(temp_plates=dict(plates={t: p["lanes"] for t, p in tp["plates"].items() if "lanes" in p},
                                            seen={t: p["seen"] for t, p in tp["plates"].items() if "lanes" in p},
                                            errors={t: p["error"] for t, p in tp["plates"].items() if "error" in p},
                                            shape=tp["shape"], camera_check=tp["camera_check"]),
                           ship=results["ship"], belt=results["belt"], arm_bases=ab))
    (run / "snapshot.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
    cv2.imwrite(str(run / "overlay.png"), overlay(top, layout, tp["plates"], results["ship"], results["belt"]))
    return snap


def diff(old, new):
    """{item: [what changed]} and the stages to rerun."""
    changed = {}
    a, b = old["items"]["temp_plates"]["plates"], new["items"]["temp_plates"]["plates"]
    for tag in sorted(set(a) | set(b)):
        la, lb = {l["lane"]: l for l in a.get(tag, [])}, {l["lane"]: l for l in b.get(tag, [])}
        for n in sorted(set(la) | set(lb)):
            if n not in la or n not in lb:
                changed.setdefault("temp_plates", []).append(f"{tag}-{n} {'gone' if n in la else 'new'}")
                continue
            d = math.dist(la[n]["xy"], lb[n]["xy"])
            dyaw = abs((lb[n]["yaw_deg"] - la[n]["yaw_deg"] + 90) % 180 - 90)
            if d > CHANGED[0] or dyaw > CHANGED[1]:
                changed.setdefault("temp_plates", []).append(f"{tag}-{n} {d * 1000:.0f} mm {dyaw:.1f} deg")
    ba, bb = old["items"].get("belt"), new["items"].get("belt")
    if ba != bb and (not ba or not bb or "error" in ba or "error" in bb):
        changed["belt"] = ["measured" if bb and "error" not in bb else "not measured"]
    elif ba and math.dist((ba["end_x_m"], ba["centre_y_m"]), (bb["end_x_m"], bb["centre_y_m"])) > CHANGED[0]:
        changed["belt"] = [f"{math.dist((ba['end_x_m'], ba['centre_y_m']), (bb['end_x_m'], bb['centre_y_m'])) * 1000:.0f} mm"]
    sa, sb = old["items"].get("ship"), new["items"].get("ship")
    if sa != sb and (not sa or not sb or "error" in sa or "error" in sb):
        changed["ship"] = ["measured" if sb and "error" not in sb else "not measured"]
    elif sa:
        d = math.dist((sa["stern_x_m"], sa["centre_y_m"]), (sb["stern_x_m"], sb["centre_y_m"]))
        if d > CHANGED[0] or abs(sb["yaw_deg"] - sa["yaw_deg"]) > SHIP_CHANGED_DEG:
            changed["ship"] = [f"{d * 1000:.0f} mm {abs(sb['yaw_deg'] - sa['yaw_deg']):.1f} deg"]
    if old.get("camera") != new.get("camera"):
        changed["camera"] = ["top camera model"]
    rerun = sorted(STAGES) if "camera" in changed else sorted(s for s, (items, *_) in STAGES.items() if items & set(changed))
    return changed, rerun


def capture(site, out):
    out = Path(out) / "frames"
    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for cam in CAMERAS:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", site,
                            f"curl -sf -m 10 {shlex.quote(VIEWER.format(cam))}"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8":
            (out / f"{cam}.jpg").write_bytes(r.stdout)
            got[cam] = len(r.stdout)
    if "top" not in got:
        raise SystemExit("no top frame from the view server (is rosy-omx-camera-view running?)")
    meta = dict(taken_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), frames=got)
    (out.parent / "capture.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def stage_body(name, rel, extra=()):
    """The remote shell line of one stage: the snapshot's choices, then `extra` (--choice key=value items), which win
    over them because parse_choices keeps the last value of a key (e.g. physics=<cell_physics.yaml candidate>)."""
    _, _, _, cmd = STAGES[name]
    choices = " ".join(SNAP_CHOICES(rel) + [w for c in extra for w in ("--choice", shlex.quote(c))])
    return f"mkdir -p $OUT/{name} && {PY} {cmd.format(choices=choices).replace('$PY', PY)} {choices}"


def sim(snapshot, sha, out, stages, extra=()):
    """Each stage one remote_sim run, all started at once; remote_sim places them by headroom and caps (D-568)."""
    if not Path(snapshot).resolve().is_relative_to(ROOT):
        raise SystemExit(f"{snapshot} is outside the repo: copy it to deploy/robot/omx/sim/cell_snapshots/ and commit it")
    rel = Path(snapshot).resolve().relative_to(ROOT).as_posix()
    if subprocess.run(["git", "cat-file", "-e", f"{sha}:{rel}"], cwd=ROOT).returncode:
        raise SystemExit(f"{rel} is not in {sha}: commit the snapshot first (remote_sim ships commits only)")
    out = Path(out)
    procs = {}
    for i, name in enumerate(stages):
        if i:
            time.sleep(STAGGER_S)  # remote_sim reserves a host only when it ships: back-to-back starts all pick the same one
        _, role, minutes, _ = STAGES[name]
        body = stage_body(name, rel, extra)
        log = out / name
        log.mkdir(parents=True, exist_ok=True)
        procs[name] = subprocess.Popen([sys.executable, str(ROOT / "tools/remote/remote_sim.py"), "--host", role, "--sha", sha,
                                        "--minutes", str(minutes), "--log-dir", str(log / "remote"), "cmd", "--", body],
                                       cwd=ROOT, stdout=(log / "stdout.txt").open("w"), stderr=subprocess.STDOUT)
    rcs = {n: p.wait() for n, p in procs.items()}
    (out / "sim.json").write_text(json.dumps(dict(snapshot=rel, sha=sha, choices=list(extra), rc=rcs, at=time.strftime("%Y-%m-%dT%H:%M:%S")), indent=1),
                                  encoding="utf-8")
    return rcs


def report(out):
    s = json.loads((Path(out) / "sim.json").read_text(encoding="utf-8"))
    lines = [f"# real-to-sim {s['at']}", "", f"snapshot `{s['snapshot']}` at `{s['sha'][:10]}`"
             + (f", choices {', '.join(f'`{c}`' for c in s['choices'])}" if s.get("choices") else ""), "", "| stage | rc |", "|---|---|"]
    lines += [f"| {n} | {rc} |" for n, rc in s["rc"].items()]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture"); c.add_argument("--site", help="ssh target of the PC serving the cell cameras, default the first omx_hosts entry in private/lab-hosts.json"); c.add_argument("--out", required=True)
    m = sub.add_parser("measure"); m.add_argument("run"); m.add_argument("--prev")
    m.add_argument("--camera-moved-ok", action="store_true", help="measure although the top camera moved since --prev")
    d = sub.add_parser("diff"); d.add_argument("old"); d.add_argument("new")
    s = sub.add_parser("sim"); s.add_argument("snapshot"); s.add_argument("--sha", required=True); s.add_argument("--out", required=True)
    s.add_argument("--stages", help="comma list, default every stage")
    s.add_argument("--choice", action="append", default=[], help="key=value after the snapshot's choices, e.g. physics=<candidate>")
    r = sub.add_parser("report"); r.add_argument("out")
    q = sub.add_parser("request"); q.add_argument("item", choices=["belt"]); q.add_argument("run")
    q.add_argument("--store", help="request store, default cell_requests.store() (ROSY_CELL_REQUESTS)")
    a = p.parse_args(argv)
    if a.cmd == "capture":
        if not a.site:
            sys.path.insert(0, str(ROOT / "tools/remote"))
            import lab_hosts
            a.site = next(iter(lab_hosts.omx_hosts(lab_hosts.load())), "") or p.error("--site, or omx_hosts in private/lab-hosts.json")
        print(json.dumps(capture(a.site, a.out)))
    elif a.cmd == "measure":
        snap = measure(a.run, a.prev, a.camera_moved_ok)
        print(json.dumps(snap["items"], indent=1))
    elif a.cmd == "diff":
        load = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
        changed, rerun = diff(load(a.old), load(a.new))
        print(json.dumps(dict(changed=changed, rerun=rerun, gaps=sorted({GAPS[i] for i in changed})), indent=1))
    elif a.cmd == "sim":
        rcs = sim(a.snapshot, a.sha, a.out, a.stages.split(",") if a.stages else sorted(STAGES), a.choice)
        print(json.dumps(rcs))
        return int(any(rcs.values()))
    elif a.cmd == "request":
        sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
        import cell_requests
        req, image = belt_request(a.run)
        made = cell_requests.open_request(req, image, Path(a.store) if a.store else None)
        print(json.dumps(dict(id=made["id"], candidates=made["candidates"], unit=made["unit"]), ensure_ascii=False))
    else:
        print(report(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
