"""Real-to-sim for the two-arm OMX cell: measure the real cell, write a dated snapshot, show what changed, rerun the sims
that read the changed items (D-947: geometry evidence; measured values are named choices, nothing silently overwritten).

  omx_real2sim.py capture --site USER@HOST --out RUN          frames of the cell cameras from the site's view server (read only)
  omx_real2sim.py measure RUN [--prev SNAPSHOT]                each item measured in parallel -> RUN/snapshot.json, RUN/overlay.png
  omx_real2sim.py diff OLD NEW                                 changed items, the sim stages they feed, their sim2real rows
  omx_real2sim.py sim SNAPSHOT --sha SHA --out DIR [--stages ..]   the stages in parallel on the lab PCs (remote_sim.py, never here)
  omx_real2sim.py report DIR                                    Markdown of what ran and passed

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
import functools
import hashlib
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_sites as sites  # noqa: E402

SCHEMA = "rosy.omx-cell-snapshot.v1"
VIEWER = "http://127.0.0.1:8767/frame/{}.jpg"  # rosy-omx-camera-view on the site PC (localhost only)
CAMERAS = ("top", "side", "arm_a_wrist", "arm_b_wrist")
LANE = (.090, .030)          # printed pad = container footprint, m
SIZE_TOL = (.012, .007)      # a blob within this of LANE is a lane
PARTIAL_MIN = .040           # a lane-wide pad at least this long is a lane cut short at one end
CHANGED = (.003, 3.)         # m, deg: a lane moved more than this is a changed item; 3 deg is the pocket's own yaw
                             # tolerance (SCAD yaw_tol_deg), above one plate's frame-to-frame jitter (1.4 deg, 2026-11-09)
STAGGER_S = 45
GAPS = {"temp_plates": "G-17", "ship": "G-18", "camera": "G-19", "belt": "G-30"}  # sim2real registry rows each item reports to (D-480)
PY = "MUJOCO_GL=egl $HOME/rosy-test/venvs/sim-mujoco/bin/python"
SNAP_CHOICES = lambda path: ["--choice", f"cell_snapshot={path}", "--choice", "temp_lanes=snapshot", "--choice", "ship_pose=snapshot",
                                "--choice", "belt_pose=snapshot"]
BELT_MIN_PX = 2000           # the belt strip is about 11,500 px in the 640x480 top frame
SHIP_CHANGED_DEG = 1.        # the hull is 316 mm long: 1 deg moves its ends 2.8 mm
# stage -> (items it reads, role, minutes, command after the python); every stage also reads the camera and arm bases.
# A policy round (omx_two_arm_policy.py round --choice ..) takes the same choices but is a GPU job a person starts.
STAGES = {
    "rehandle": ({"temp_plates", "ship"}, "ai", 40, "tools/sim/omx_two_arm_teacher.py run rehandle --out $OUT/rehandle"),
    "outbound": ({"temp_plates", "ship"}, "ai", 50, "tools/sim/omx_two_arm_plan.py compare --scenario outbound --replay-dir $OUT/outbound/plan {choices} && "
                 "$PY tools/sim/omx_two_arm_teacher.py run plan --plan $OUT/outbound/plan/outbound-two-arm.json --out $OUT/outbound"),
    "matrix-a": ({"temp_plates", "ship"}, "model", 60, "tools/sim/omx_two_arm_matrix.py --arm arm_a --out $OUT/matrix-a"),
    "matrix-b": ({"temp_plates", "ship"}, "model", 60, "tools/sim/omx_two_arm_matrix.py --arm arm_b --out $OUT/matrix-b"),
    "stack": ({"ship", "belt"}, "ai", 40, "tools/sim/omx_two_arm_teacher.py run stack --out $OUT/stack"),
}


class Camera:
    """The sim's pinhole for a surveyed camera (eye, focus, up, f_px at `height` rows), so pixels mean what the sim renders."""

    def __init__(self, cam, size):
        self.h, self.w = size
        self.eye = np.array(cam["eye"], float)
        fwd = np.array(cam["focus"], float) - self.eye
        self.fwd = fwd / np.linalg.norm(fwd)
        up = np.array(cam["up"], float) - self.fwd * (np.array(cam["up"], float) @ self.fwd)
        self.up = up / np.linalg.norm(up)
        self.right = np.cross(self.fwd, self.up)
        self.f = cam["f_px"] * self.h / cam["height"]

    def project(self, p):
        d = np.asarray(p, float) - self.eye
        return self.w / 2 + self.f * (d @ self.right) / (d @ self.fwd), self.h / 2 - self.f * (d @ self.up) / (d @ self.fwd)

    def to_plane(self, uv, z):
        uv = np.asarray(uv, float).reshape(-1, 2)
        d = self.fwd + ((uv[:, :1] - self.w / 2) * self.right - (uv[:, 1:] - self.h / 2) * self.up) / self.f
        return (self.eye + (z - self.eye[2]) / d[:, 2:] * d)[:, :2]


def blobs(frame):
    """(kind, outline pixels) of dark pads (low value, low saturation) and orange containers in a BGR frame. The outline is
    the filled blob's outside, so the white lane numbers printed on a pad do not bend its axis."""
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {"pad": (hsv[..., 2] < 140) & (hsv[..., 1] < 90),
             "container": (hsv[..., 0] < 22) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)}
    for kind, m in masks.items():
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        for c in cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]:
            if cv2.contourArea(c) >= 150:
                yield kind, c.reshape(-1, 2)


def fold(yaw):
    return (yaw + math.pi / 2) % math.pi - math.pi / 2


def rect(points):
    """Centre (m), long-axis yaw (rad, folded into [-90, 90) deg) and (length, width) m of plane points."""
    import cv2

    (cx, cy), (a, b), ang = cv2.minAreaRect((points * 1000).astype(np.float32))
    return (cx / 1000, cy / 1000), fold(math.radians(ang if a >= b else ang + 90)), (max(a, b) / 1000, min(a, b) / 1000)


def lane_blobs(frame, cam, deck_z, box_h):
    """Every lane-wide blob: dict(kind, xy, yaw, size, partial) on the deck (a container measured on its top face). A pad
    cut short at one end (glare or shade; 73 and 49 mm on 2026-11-09) is `partial`: its yaw and its offset across the lane
    still hold, its centre along the lane does not."""
    out = []
    for kind, px in blobs(frame):
        z = deck_z + (box_h if kind == "container" else 0.)
        xy, yaw, size = rect(cam.to_plane(px, z))
        if abs(size[1] - LANE[1]) > SIZE_TOL[1] or not PARTIAL_MIN <= size[0] <= LANE[0] + SIZE_TOL[0]:
            continue
        partial = size[0] < LANE[0] - SIZE_TOL[0]
        if not partial or kind == "pad":
            out.append(dict(kind=kind, xy=xy, yaw=yaw, size=size, partial=partial))
    return out


def turn(xy, yaw, centre, angle):
    c, s = math.cos(angle), math.sin(angle)
    d = (xy[0] - centre[0], xy[1] - centre[1])
    return (centre[0] + c * d[0] - s * d[1], centre[1] + s * d[0] + c * d[1]), yaw + angle


def axes_meet(a, b):
    """Where two lanes' long axes cross (the fan centre)."""
    (p, t), (q, u) = a, b
    m = np.array([[math.cos(t), -math.cos(u)], [math.sin(t), -math.sin(u)]])
    s = np.linalg.solve(m, np.subtract(q, p))[0]
    return p[0] + s * math.cos(t), p[1] + s * math.sin(t)


def plate_lanes(shape):
    """Lane k (1..3) of a printed fan plate in its own frame: lane 2 at the origin along x, the fan centre at (radius, 0)
    toward its arm, lane k turned about it by (2 - k) * step, so lane 1 is the smaller-y end of a plate facing +x."""
    step, r = math.radians(shape["step_deg"]), shape["radius_m"]
    return {k: turn((0., 0.), 0., (r, 0.), (2 - k) * step) for k in (1, 2, 3)}


def place(local, pose):
    """A plate-frame lane (xy, yaw) at plate pose (x, y, theta)."""
    (x, y), yaw = local
    c, s = math.cos(pose[2]), math.sin(pose[2])
    return (pose[0] + c * x - s * y, pose[1] + s * x + c * y), yaw + pose[2]


def fit_shape(a, b, lanes_apart):
    """Fan step (deg per lane) and radius (m) from two lanes (xy, yaw) `lanes_apart` lanes apart; None when parallel."""
    if abs(fold(b[1] - a[1])) < math.radians(2):
        return None
    centre = axes_meet(a, b)
    return dict(step_deg=round(math.degrees(abs(fold(b[1] - a[1]))) / lanes_apart, 2),
                radius_m=round((math.dist(a[0], centre) + math.dist(b[0], centre)) / 2, 4))


def fit_plate(found, shape, expected, near=.14, tol=(.008, math.radians(4))):
    """Plate pose from its lane blobs: every (whole blob, lane k) pair gives a pose; the one most blobs agree with wins
    (ties: nearest the expected pose). A partial pad agrees when its yaw and its offset across the lane fit and it lies
    within the lane's length; it adds to the yaw, while the position comes from the whole blobs. (pose, {k: blob}) or None."""
    lanes = plate_lanes(shape)
    mine = [b for b in found if math.dist(b["xy"], expected[:2]) < near]

    def pose_from(b, k):
        theta = fold(b["yaw"] - lanes[k][1])
        (x, y), _ = place(lanes[k], (0., 0., theta))
        return b["xy"][0] - x, b["xy"][1] - y, theta

    def agree(pose):
        out = {}
        for b in mine:
            for k in (1, 2, 3):
                xy, yaw = place(lanes[k], pose)
                if k in out or abs(fold(yaw - b["yaw"])) >= tol[1]:
                    continue
                d = np.subtract(b["xy"], xy)
                along, across = abs(d @ (math.cos(yaw), math.sin(yaw))), abs(d @ (-math.sin(yaw), math.cos(yaw)))
                if (across < tol[0] and along < (LANE[0] - b["size"][0]) / 2 + tol[0]) if b["partial"] else math.hypot(*d) < tol[0]:
                    out[k] = b
        return out

    best = None
    for b in (b for b in mine if not b["partial"]):
        for k in (1, 2, 3):
            pose = pose_from(b, k)
            inl = agree(pose)
            key = (len(inl), -math.dist(pose[:2], expected[:2]) - abs(fold(pose[2] - expected[2])) * .05)
            if best is None or key > best[0]:
                best = (key, inl)
    if best is None:
        return None
    turns = [pose_from(b, k)[2] for k, b in best[1].items()]
    theta = math.atan2(np.mean(np.sin(turns)), np.mean(np.cos(turns)))
    spots = []
    for k, b in best[1].items():
        if not b["partial"]:
            (x, y), _ = place(lanes[k], (0., 0., theta))
            spots.append((b["xy"][0] - x, b["xy"][1] - y))
    return (*np.mean(spots, 0).tolist(), theta), best[1]


def measure_temp_plates(frame, layout, prev=None):
    """Lanes of both plates, one fitted printed plate each (fit_plate). The plate shape (fan step and radius) is the previous
    snapshot's, else fitted from a plate showing two clean pads (within 3 mm of 90 x 30) about two lanes apart."""
    cam = Camera(layout.fixture["real_cameras"]["top"], frame.shape[:2])
    box_h = sites.CONTAINER[layout.choices["ship_source"]][2]
    found = lane_blobs(frame, cam, layout.deck_z, box_h)
    # where to look: the previous snapshot's lane 2, else (no snapshot, or a plate it could not measure) the layout's
    expected = {t: (*layout.sites[f"tmp-{t}-2"]["xy"], fold(layout.sites[f"tmp-{t}-2"]["yaw"])) for t in "ab"}
    for t, ls in (prev or {}).get("plates", {}).items():
        expected[t] = (*ls[1]["xy"], math.radians(ls[1]["yaw_deg"]))
    shape = prev and prev.get("shape")
    for t in ("" if shape else "ab"):
        clean = sorted((b for b in found if b["kind"] == "pad" and math.dist(b["xy"], expected[t][:2]) < .14
                        and np.abs(np.subtract(b["size"], LANE)).max() < .003), key=lambda b: b["xy"][1])
        if len(clean) >= 2:
            a, b = clean[0], clean[-1]
            shape = fit_shape((a["xy"], a["yaw"]), (b["xy"], b["yaw"]), 2 if math.dist(a["xy"], b["xy"]) > .075 else 1)
            if shape:
                shape["from"] = f"plate {t}, two clean pads"
                break
    if not shape:
        return dict(plates={t: dict(error="no plate shape: no previous snapshot and no plate with two clean pads") for t in "ab"},
                    shape=None, camera_check=None)
    plates, sizes = {}, []
    for t in "ab":
        fit = fit_plate(found, shape, expected[t])
        if not fit:
            plates[t] = dict(error="no lane-sized blob near the plate")
            continue
        pose, seen = fit
        lanes = []
        for k, local in plate_lanes(shape).items():
            xy, yaw = place(local, pose)
            b = seen.get(k)
            lanes.append(dict(lane=k, xy=[round(v, 4) for v in xy], yaw_deg=round(math.degrees(fold(yaw)), 1),
                              source=(b["kind"] + (" (partial)" if b["partial"] else "")) if b else "plate-fit", residual_mm=round(math.dist(xy, b["xy"]) * 1000, 1) if b else None))
        plates[t] = dict(lanes=lanes, seen=len(seen))
        sizes += [b["size"] for b in seen.values() if b["kind"] == "pad" and not b["partial"]]
    scale = None
    if sizes:
        err = np.abs(np.array(sizes) - LANE).max(0)
        scale = dict(pads=len(sizes), worst_mm=[round(float(e) * 1000, 1) for e in err])
    return dict(plates=plates, shape=shape, camera_check=scale)


@functools.lru_cache(maxsize=1)
def hull_outline():
    """Plan-view outline (ship mm, x stern to bow, y to port) and deck height (mm) of the r08 hull mesh."""
    import cv2

    data = (sites.SHIP_ASSETS / "hull.stl").read_bytes()
    n = int.from_bytes(data[80:84], "little")
    v = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))["v"].reshape(-1, 3)
    return cv2.convexHull(v[:, :2].astype(np.float32)).reshape(-1, 2), float(v[:, 2].max())


def ship_polygon(cam, layout, pose):
    """Image polygon of the hull deck at (stern x, centre y, yaw rad); the bow points -x as omx_two_arm_sites.r08_to_fixture."""
    outline, deck = hull_outline()
    c, s = math.cos(pose[2]), math.sin(pose[2])
    return np.array([cam.project((pose[0] - c * x / 1000 + s * y / 1000, pose[1] - s * x / 1000 - c * y / 1000, layout.table_z + deck / 1000))
                     for x, y in outline])


def measure_ship(frame, layout):
    """Where the r08 hull stands: its outline fitted to the hull and the containers on it by overlap, a coarse grid around the
    layout's ship then a finer climb. The hull is light blue (saturation 70-160, value 200+: the grey floor and white plates are
    outside); the containers are orange (hue under 18: the yellow table is 21)."""
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (90, 70, 200), (110, 160, 255)) | cv2.inRange(hsv, (0, 120, 150), (17, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return dict(error="no hull-coloured area in the top frame")
    blob = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    blob = cv2.drawContours(np.zeros_like(blob), cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, 1, -1)
    cam = Camera(layout.fixture["real_cameras"]["top"], frame.shape[:2])

    def iou(pose):
        hull = cv2.fillPoly(np.zeros_like(blob), [np.round(ship_polygon(cam, layout, pose)).astype(np.int32)], 1)
        return (hull & blob).sum() / max((hull | blob).sum(), 1)

    x0, y0 = layout.choices["ship_stern_x_m"], layout.choices["ship_centre_y_m"]
    best = max(((x, y, 0.) for x in np.arange(x0 - .06, x0 + .06, .004) for y in np.arange(y0 - .05, y0 + .05, .004)), key=iou)
    for step in (.002, .001, .0005):
        while True:
            near = max(((best[0] + a * step, best[1] + b * step, best[2] + c * step * 2) for a in (-1, 0, 1) for b in (-1, 0, 1)
                        for c in (-1, 0, 1)), key=iou)
            if iou(near) <= iou(best):
                break
            best = near
    return dict(stern_x_m=round(float(best[0]), 4), centre_y_m=round(float(best[1]), 4), yaw_deg=round(math.degrees(best[2]), 2),
                iou=round(float(iou(best)), 3), model="r08")


def measure_belt(frame, layout):
    """The belt's near end (x where the strip starts, its 1st percentile) and centreline (median y beyond 20 mm from the end),
    from the largest dark strip whose back-projection at the belt surface lies along the fixture's belt line."""
    import cv2

    cam = Camera(layout.fixture["real_cameras"]["top"], frame.shape[:2])
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    dark = cv2.morphologyEx(((hsv[..., 2] < 95) & (hsv[..., 1] < 110)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark)
    best = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < BELT_MIN_PX:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = cam.to_plane(np.stack([xs, ys], 1), layout.belt_top)
        if abs(np.median(pts[:, 1]) - layout.belt_y) < .06 and np.median(pts[:, 0]) > layout.belt_stop_x - .02 and (best is None or len(pts) > len(best)):
            best = pts
    if best is None:
        return dict(error="no dark strip along the belt line")
    end = float(np.percentile(best[:, 0], 1))
    far = best[best[:, 0] > end + .02]
    width = float(np.percentile(far[:, 1], 98) - np.percentile(far[:, 1], 2))
    return dict(end_x_m=round(end, 4), centre_y_m=round(float(np.median(far[:, 1])), 4), width_m=round(width, 4))


def overlay(frame, layout, plates, ship=None, belt=None):
    import cv2

    cam = Camera(layout.fixture["real_cameras"]["top"], frame.shape[:2])
    img = frame.copy()
    for tag, plate in plates.items():
        for lane in plate.get("lanes", []):
            (x, y), t = lane["xy"], math.radians(lane["yaw_deg"])
            pts = [cam.project((x + a * LANE[0] / 2 * math.cos(t) - b * LANE[1] / 2 * math.sin(t),
                                y + a * LANE[0] / 2 * math.sin(t) + b * LANE[1] / 2 * math.cos(t), layout.deck_z))
                   for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            colour = (0, 255, 0) if lane["source"] != "plate-fit" else (0, 200, 255)
            cv2.polylines(img, [np.array(pts, np.int32)], True, colour, 1)
            cv2.putText(img, f"{tag}-{lane['lane']}", tuple(int(v) for v in cam.project((x, y, layout.deck_z))),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, colour, 1)
    for arm in layout.arms.values():
        cv2.circle(img, tuple(int(v) for v in cam.project(arm.base)), 4, (0, 0, 255), -1)
    if belt and "error" not in belt:
        ends = [cam.project((belt["end_x_m"], belt["centre_y_m"] + s * belt["width_m"] / 2, layout.belt_top)) for s in (-1, 1)]
        cv2.line(img, tuple(int(v) for v in ends[0]), tuple(int(v) for v in ends[1]), (0, 0, 255), 2)
    if ship and "error" not in ship:
        pose = (ship["stern_x_m"], ship["centre_y_m"], math.radians(ship["yaw_deg"]))
        cv2.polylines(img, [np.round(ship_polygon(cam, layout, pose)).astype(np.int32)], True, (255, 0, 255), 1)
    return img


def measure(run, prev_path=None):
    import cv2

    run = Path(run)
    prev = json.loads(Path(prev_path).read_text(encoding="utf-8")) if prev_path else None
    layout = sites.Layout()  # camera, deck and arms; where the plates were comes from prev
    frames = {c: run / "frames" / f"{c}.jpg" for c in CAMERAS if (run / "frames" / f"{c}.jpg").exists()}
    top = cv2.imread(str(frames["top"])) if "top" in frames else None
    if top is None:
        raise SystemExit(f"no readable top frame in {run / 'frames'}")
    items = {"temp_plates": lambda: measure_temp_plates(top, layout, prev and prev["items"]["temp_plates"]),
             "ship": lambda: measure_ship(top, layout),
             "belt": lambda: measure_belt(top, layout)}
    with ThreadPoolExecutor() as pool:  # items are independent; more join here (belt end, arm bases) as they get measurers
        done = {k: pool.submit(f) for k, f in items.items()}
        results = {k: f.result() for k, f in done.items()}
    tp = results["temp_plates"]
    snap = dict(schema=SCHEMA, taken_at=json.loads((run / "capture.json").read_text())["taken_at"] if (run / "capture.json").exists() else None,
                frames={c: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for c, p in frames.items()},
                camera=dict(top=layout.fixture["real_cameras"]["top"]),
                items=dict(temp_plates=dict(plates={t: p["lanes"] for t, p in tp["plates"].items() if "lanes" in p},
                                            seen={t: p["seen"] for t, p in tp["plates"].items() if "lanes" in p},
                                            errors={t: p["error"] for t, p in tp["plates"].items() if "error" in p},
                                            shape=tp["shape"], camera_check=tp["camera_check"]),
                           ship=results["ship"], belt=results["belt"]))
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
    d = sub.add_parser("diff"); d.add_argument("old"); d.add_argument("new")
    s = sub.add_parser("sim"); s.add_argument("snapshot"); s.add_argument("--sha", required=True); s.add_argument("--out", required=True)
    s.add_argument("--stages", help="comma list, default every stage")
    s.add_argument("--choice", action="append", default=[], help="key=value after the snapshot's choices, e.g. physics=<candidate>")
    r = sub.add_parser("report"); r.add_argument("out")
    a = p.parse_args(argv)
    if a.cmd == "capture":
        if not a.site:
            sys.path.insert(0, str(ROOT / "tools/remote"))
            import lab_hosts
            # the cameras hang off the OMX owner's PC (rosy-omx-camera-view); site_host is the Fleet site, which may be another PC
            a.site = next(iter(lab_hosts.omx_hosts(lab_hosts.load())), "") or p.error("--site, or omx_hosts in private/lab-hosts.json")
        print(json.dumps(capture(a.site, a.out)))
    elif a.cmd == "measure":
        snap = measure(a.run, a.prev)
        print(json.dumps(snap["items"], indent=1))
    elif a.cmd == "diff":
        load = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))
        changed, rerun = diff(load(a.old), load(a.new))
        print(json.dumps(dict(changed=changed, rerun=rerun, gaps=sorted({GAPS[i] for i in changed})), indent=1))
    elif a.cmd == "sim":
        rcs = sim(a.snapshot, a.sha, a.out, a.stages.split(",") if a.stages else sorted(STAGES), a.choice)
        print(json.dumps(rcs))
        return int(any(rcs.values()))
    else:
        print(report(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
