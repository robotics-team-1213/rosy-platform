"""Analyse recorded calibration runs: wheel odometry, LiDAR mount yaw, camera extrinsics.

    analyze_session.py SESSION_DIR [SESSION_DIR ...] [--out DIR] [--lidar-yaw-deg D]
                       [--straights-only NAME ...]

SESSION_DIR is a D-356 recording (session.json + bag/*.mcap) with scan, odom,
joint_states, cmd_vel and camera/front. Runs are grouped per robot
(session.json "device"); each robot gets <out>/<device>/candidate.json and
report.md. Per run it fits (sensing/odometry_fit.py, perception/camera_extrinsic.py):

  wheel_radius, wheel_separation  LiDAR ICP motion vs joint_states wheel angles
  per-wheel radii, gains          left/right scale, actual/commanded per command speed
  lidar_yaw_offset check          direction of LiDAR travel on straight runs
  camera pitch/roll/height        LiDAR walls vs image edges (moving frames,
                                  motion-compensated), at the motion-measured yaw

and across runs the mean, the repeat spread and a 95 % interval (Student t).
The candidate is never applied: docs/adr/D-47-core-sensor-adapter-calibration-binding.md
(addendum 2026-10-01) says how an operator applies it. Nothing here touches a robot.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools" / "perception" / "dataset"))
sys.path.insert(0, str(REPO / "src" / "runtime" / "sensing"))
sys.path.insert(0, str(REPO / "src" / "contracts" / "foundation"))

import autolabel as A  # noqa: E402
from core_common.calibration_store import CalibrationStore  # noqa: E402
from geometry import Lidar, PoseSeries, robot_lidar_yaw_deg  # noqa: E402
from control.sensing import odometry_fit as OF  # noqa: E402
from control.sensing.perception import camera_extrinsic as CE  # noqa: E402

PROFILE_PATH = REPO / "src" / "products" / "pinky_pro" / "profile" / "config" / "camera_nominal.yaml"
BRINGUP_PARAMS = REPO / "src" / "products" / "pinky_pro" / "bringup" / "config" / "rosy_params.yaml"
LIDAR_X_M = CE.LIDAR_X_OFFSET_M
METHOD = "tools/calibration/analyze_session.py/1 (ICP point-to-line, wheel LS, wall-edge camera fit)"
WHEEL_SIGNS = (1.0, -1.0)      # Pinky Pro: the right encoder counts backwards (bringup.py)
SCAN_EVERY = 3                 # every 3rd scan (~0.3 s) inside a segment
PAD_BEFORE_S, PAD_AFTER_S = 0.3, 1.0   # rest before a segment, coast after it
CAMERA_FRAMES = 24
CAMERA_EVERY_S = 2.0
# Student t, two-sided 95 %, by degrees of freedom.
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23}


def t95(dof):
    return T95.get(dof, 1.96) if dof > 0 else math.inf


def load_profile(path=PROFILE_PATH):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def nominal_wheels(path=BRINGUP_PARAMS):
    p = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["bringup"]["ros__parameters"]
    return float(p["wheel_radius"]), float(p["wheel_separation"])


def load(session: Path):
    """odom (log, x, y, yaw unwrapped), scans, wheel joints (log, left, right), cmds, session.json."""
    files = A._mcap_files(session)
    if not files:
        raise FileNotFoundError(f"no .mcap under {session / 'bag'}")
    odom, scans, joints, cmds = [], [], [], []
    for topic, log, m in A._iter(files, ("odom", "scan", "joint_states", "cmd_vel")):
        if topic == "odom":
            p = m.pose.pose.position
            odom.append((log, A._stamp(m), p.x, p.y, A._yaw(m.pose.pose.orientation)))
        elif topic == "scan":
            scans.append((log, A._stamp(m), (np.asarray(m.ranges, np.float32), m.angle_min, m.angle_increment,
                                              m.range_min, m.range_max), m.time_increment))
        elif topic == "joint_states":
            names = list(m.name)  # a URDF publisher may share the topic with zeros
            if "left_wheel_joint" in names and "right_wheel_joint" in names:
                joints.append((log, m.position[names.index("left_wheel_joint")],
                               m.position[names.index("right_wheel_joint")]))
        else:
            cmds.append((log, m.linear.x, m.angular.z))
    od = np.array(odom)
    od[:, 4] = np.unwrap(od[:, 4])
    sj = session / "session.json"
    meta = json.loads(sj.read_text(encoding="utf-8")) if sj.is_file() else {}
    return {"files": files, "odom": od, "scans": scans, "joints": np.array(joints), "cmds": sorted(cmds),
            "meta": meta}


def _kind(seg):
    if abs(seg["linear"]) > OF.COMMAND_EPS and abs(seg["angular"]) <= OF.COMMAND_EPS:
        return "straight"
    if abs(seg["angular"]) > OF.COMMAND_EPS and abs(seg["linear"]) <= OF.COMMAND_EPS:
        return "pivot"
    return None


def odometry_records(data, yaw_rad, straights_only=False):
    od, jt = data["odom"], data["joints"]
    sl = np.array([s[0] for s in data["scans"]])
    out = []
    for seg in OF.command_segments(data["cmds"]):
        kind = _kind(seg)
        if kind is None or (straights_only and kind != "straight"):
            continue
        idx = np.nonzero((sl >= seg["t0"] - PAD_BEFORE_S) & (sl <= seg["t1"] + PAD_AFTER_S))[0]
        idx = np.unique(np.concatenate([idx[::SCAN_EVERY], idx[-1:]])) if len(idx) else idx
        if len(idx) < 3 or len(jt) == 0:
            continue
        guess = [(float(np.interp(sl[i], od[:, 0], od[:, 2])), float(np.interp(sl[i], od[:, 0], od[:, 3])),
                  float(np.interp(sl[i], od[:, 0], od[:, 4]))) for i in idx]
        # Seeded by the LiDAR's own previous increment, never by odometry: the
        # odometry is what is being calibrated and may be scaled or mirrored.
        motion = OF.lidar_motion([data["scans"][i][2] for i in idx], None, yaw_rad, LIDAR_X_M)
        if "error" in motion:
            out.append({"kind": kind, "error": motion["error"], "t0": seg["t0"]})
            continue
        j0 = jt[np.argmin(abs(jt[:, 0] - sl[idx[0]])), 1:]
        j1 = jt[np.argmin(abs(jt[:, 0] - sl[idx[-1]])), 1:]
        rec = OF.segment_record(kind, j0, j1, motion, (seg["linear"], seg["angular"]),
                                seg["t1"] - seg["t0"], wheel_signs=(1.0, 1.0))
        odo = OF.between(guess[0], guess[-1])
        rec.update(t0=seg["t0"], duration_s=seg["t1"] - seg["t0"], command=[seg["linear"], seg["angular"]],
                   odom_ds=odo[0], odom_dth=guess[-1][2] - guess[0][2])
        out.append(rec)
    return out


def wheel_signs(records):
    """Forward sign of each raw wheel joint, from straights (LiDAR travel is absolute).

    Pinky Pro bringup: left counts forward, right backwards -> (1, -1)."""
    signs = []
    for side in ("phi_l", "phi_r"):
        votes = [np.sign(r[side] * r["ds"]) for r in records
                 if "error" not in r and r["kind"] == "straight" and abs(r["ds"]) >= OF.STRAIGHT_MIN_M]
        signs.append(float(np.sign(np.sum(votes))) if votes and np.sum(votes) != 0 else WHEEL_SIGNS[len(signs)])
    return tuple(signs)


def apply_signs(records, signs):
    for r in records:
        if "error" not in r:
            r["phi_l"], r["phi_r"] = signs[0] * r["phi_l"], signs[1] * r["phi_r"]
    return records


def sign_checks(records, flow):
    """Absolute rotation sign per pivot: command, LiDAR, odometry, camera image flow.

    A CCW (left) pivot moves the scene rightwards in the image (+u)."""
    rows = []
    for r in records:
        if "error" in r or r["kind"] != "pivot":
            continue
        row = {"t0": r["t0"], "command": float(np.sign(r["command"][1])), "lidar": float(np.sign(r["dth"])),
               "odom": float(np.sign(r["odom_dth"]))}
        u = flow.get(r["t0"])
        if u is not None:
            row["camera_flow_px"] = u
            row["camera"] = float(np.sign(u))
        rows.append(row)
    agree = lambda key: all(x.get(key) == x["lidar"] for x in rows if key in x)  # noqa: E731
    return {"pivots": rows, "odom_matches_lidar": agree("odom"), "command_matches_lidar": agree("command"),
            "camera_matches_lidar": agree("camera") if any("camera" in x for x in rows) else None}


def image_flow(data, records, every_s=0.5, max_pairs=20):
    """Summed horizontal image shift (px, phase correlation) over each pivot, keyed by segment t0."""
    import cv2
    wins = [(r["t0"], r["t0"] + r["duration_s"]) for r in records if "error" not in r and r["kind"] == "pivot"]
    out, prev, last, count = {}, {}, {}, {}
    for t, bgr, log in A.mcap_frames(data["files"]):
        for t0, t1 in wins:
            if not t0 <= log <= t1 or count.get(t0, 0) >= max_pairs or log - last.get(t0, -1e9) < every_s:
                continue
            gray = np.float32(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
            if t0 in prev:
                (dx, _dy), _resp = cv2.phaseCorrelate(prev[t0], gray)
                out[t0] = out.get(t0, 0.0) + float(dx)
                count[t0] = count.get(t0, 0) + 1
            prev[t0], last[t0] = gray, log
    return out


def camera_fit(data, yaw_deg, profile):
    """Pitch/roll/height from moving frames (every CAMERA_EVERY_S), motion-compensated scans."""
    od = data["odom"]
    poses = PoseSeries(od[:, 1], od[:, 2], od[:, 3], od[:, 4])
    scans = A.Scans()
    for log, stamp, scan, tinc in data["scans"]:
        ranges, amin, ainc, rmin, rmax = scan
        scans.add_raw(stamp, ranges, amin, ainc, tinc, rmin, rmax, log)
    lidar = Lidar(forward_deg=yaw_deg, x_offset_m=LIDAR_X_M)
    samples, raw, base, last = [], [], None, None
    for t, bgr, key in A.mcap_frames(data["files"]):
        if last is not None and t - last < CAMERA_EVERY_S:
            continue
        pose, (j, dt) = poses.at(t), scans.select(t, key)
        if pose is None or j is None or abs(dt) > 0.15:
            continue
        last = t
        base = base or CE.CameraPose.from_profile(profile, bgr.shape[1], bgr.shape[0])
        grad = CE.vertical_gradient(CE.to_gray(bgr))
        xy = A.scan_points_at(lidar, poses, (scans.t[j], scans.msgs[j]), pose, CE.MAX_RANGE_M)
        samples.append((xy[xy[:, 0] > CE.MIN_AHEAD_M] if len(xy) else xy, grad))
        ranges, amin, ainc, _tinc, rmin, rmax = scans.msgs[j]
        raw.append(((ranges, amin, ainc, rmin, rmax), grad))
        if len(samples) >= CAMERA_FRAMES:
            break
    if base is None:
        return {"error": "no camera frame with a scan"}
    fit = CE.fit_camera_extrinsic(base, samples)
    if "error" in fit:
        return fit
    fitted = base.replace(pitch_rad=fit["pitch_rad"], roll_rad=fit["roll_rad"], height_m=fit["height_m"])
    fit["yaw_check"] = CE.yaw_check(fitted, raw, math.radians(yaw_deg), x_offset_m=LIDAR_X_M)
    fit["frames"] = len(samples)
    return fit


def analyse_run(session: Path, yaw_cfg_deg, profile, straights_only=False, camera=True):
    data = load(session)
    r0, b0 = nominal_wheels()
    recs = odometry_records(data, math.radians(yaw_cfg_deg), straights_only)
    yaw_motion = (OF.summarize([r for r in recs if "error" not in r], r0, b0, math.radians(yaw_cfg_deg))
                  .get("lidar_yaw_from_motion") or {}).get("mean_deg")
    if yaw_motion is not None and abs(yaw_motion - yaw_cfg_deg) > 1.0:
        # The mount yaw is an estimate, not the configured value: redo the base
        # motions (pivot translation, per-wheel radii) at the measured yaw.
        recs = odometry_records(data, math.radians(yaw_motion), straights_only)
    signs = wheel_signs(recs)
    apply_signs(recs, signs)
    good = [r for r in recs if "error" not in r]
    summary = OF.summarize(good, r0, b0, math.radians(yaw_cfg_deg))
    summary["wheel_signs"] = {"forward_sign_left_right": list(signs), "pinky_default": list(WHEEL_SIGNS),
                              "matches_default": tuple(signs) == WHEEL_SIGNS}
    summary["rotation_sign"] = sign_checks(good, image_flow(data, good) if camera else {})
    run = {"session": session.name, "device": data["meta"].get("device", session.name.split("_")[-1]),
           "straights_only": straights_only, "records": recs, "odometry": summary,
           "lidar_yaw_used_deg": yaw_motion if yaw_motion is not None else yaw_cfg_deg}
    if camera:
        run["camera"] = camera_fit(data, yaw_motion if yaw_motion is not None else yaw_cfg_deg, profile)
        run["camera"]["lidar_yaw_used_deg"] = yaw_motion if yaw_motion is not None else yaw_cfg_deg
    return run


def _stats(values):
    v = np.asarray([x for x in values if x is not None], float)
    if v.size == 0:
        return None
    out = {"n": int(v.size), "mean": float(v.mean()), "values": [float(x) for x in v]}
    if v.size > 1:
        sd = float(v.std(ddof=1))
        out.update(sd=sd, spread=float(v.max() - v.min()), ci95=float(t95(v.size - 1) * sd / math.sqrt(v.size)))
    return out


def gains_by_speed(runs):
    """Actual/commanded gain grouped by (kind, |command|)."""
    table = {}
    for run in runs:
        for r in run["records"]:
            if "error" in r:
                continue
            lin, ang = r["command"]
            if r["kind"] == "pivot" and "angular_gain" in r:
                key = f"pivot {abs(ang):.2f} rad/s {'left' if ang > 0 else 'right'}"
                table.setdefault(key, []).append(r["angular_gain"])
            elif r["kind"] == "straight" and "linear_gain" in r:
                key = f"straight {abs(lin):.3f} m/s {'fwd' if lin > 0 else 'rev'}"
                table.setdefault(key, []).append(r["linear_gain"])
    return {k: _stats(v) for k, v in sorted(table.items())}


def combine(device, runs, yaw_cfg_deg, profile):
    """Across-run candidate for one robot."""
    odo = [r["odometry"] for r in runs]
    full = [r for r in runs if not r["straights_only"]]

    def pick(key, rs=odo):
        return _stats([o.get(key) for o in rs])

    within_r = [o.get("wheel_radius_se") for o in odo if o.get("wheel_radius_se")]
    within_b = [r["odometry"].get("wheel_separation_se") for r in full if r["odometry"].get("wheel_separation_se")]
    yaw = _stats([(o.get("lidar_yaw_from_motion") or {}).get("mean_deg") for o in odo])
    # Only runs whose camera fit passed its own gates (margin, wall points, not on a bound).
    cams = [r["camera"] for r in runs if "camera" in r and "error" not in r["camera"]
            and r["camera"].get("recommended")]
    cam = {k: _stats([math.degrees(c[k]) if k.endswith("_rad") else c[k] for c in cams])
           for k in ("pitch_rad", "roll_rad", "height_m")} if cams else None
    candidate = {
        "schema": "rosy.calibration.candidate/1",
        "robot": device,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "applied": False,
        "sessions": [r["session"] for r in runs],
        "odometry": {
            "wheel_radius": pick("wheel_radius"), "wheel_radius_within_run_se": within_r,
            "wheel_separation": pick("wheel_separation", [r["odometry"] for r in full]),
            "wheel_separation_within_run_se": within_b,
            "right_to_left_ratio": pick("right_to_left_ratio", [r["odometry"] for r in full]),
            "nominal": dict(zip(("wheel_radius", "wheel_separation"), nominal_wheels())),
            "gains": gains_by_speed(runs),
        },
        "lidar_yaw_offset_check": {"configured_deg": yaw_cfg_deg, "from_motion_deg": yaw,
                                   "camera": [c.get("yaw_check") for c in cams]},
    }
    if cams:
        best = max(cams, key=lambda c: c["wall_points"])
        mean_fit = dict(best, pitch_rad=math.radians(cam["pitch_rad"]["mean"]),
                        roll_rad=math.radians(cam["roll_rad"]["mean"]), height_m=cam["height_m"]["mean"])
        candidate["camera"] = CE.candidate_profile(
            profile, mean_fit, revision=f"camera-extrinsic-{device}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
            source="tools/calibration/analyze_session.py: " + ", ".join(r["session"] for r in runs))
        candidate["camera"]["across_runs"] = cam
    return candidate


def report(candidate, runs):
    o = candidate["odometry"]

    def fmt(s, scale=1.0, unit="", nd=5):
        if not s:
            return "n/a"
        text = f"{s['mean'] * scale:.{nd}f}{unit}"
        if "ci95" in s:
            text += f" 짹 {s['ci95'] * scale:.{nd}f} (95 %, n={s['n']}, spread {s['spread'] * scale:.{nd}f})"
        return text
    lines = [f"# Calibration candidate ??{candidate['robot']}", "",
             f"Sessions: {', '.join(candidate['sessions'])}. Not applied.", "",
             "| quantity | value |", "|---|---|",
             f"| wheel_radius (m) | {fmt(o['wheel_radius'])} |",
             f"| wheel_separation (m) | {fmt(o['wheel_separation'])} |",
             f"| right/left wheel scale | {fmt(o['right_to_left_ratio'], nd=4)} |",
             f"| lidar yaw from motion (deg) | {fmt(candidate['lidar_yaw_offset_check']['from_motion_deg'], nd=2)} "
             f"(configured {candidate['lidar_yaw_offset_check']['configured_deg']:.2f}) |"]
    cam = (candidate.get("camera") or {}).get("across_runs")
    if cam:
        lines += [f"| camera pitch (deg) | {fmt(cam['pitch_rad'], nd=2)} |",
                  f"| camera roll (deg) | {fmt(cam['roll_rad'], nd=2)} |",
                  f"| camera height (m) | {fmt(cam['height_m'], nd=4)} |"]
    lines += ["", "## Gains (actual / commanded)", "", "| command | gain |", "|---|---|"]
    lines += [f"| {k} | {fmt(v, nd=3)} |" for k, v in o["gains"].items()]
    lines += ["", "## Runs", ""]
    for run in runs:
        od = run["odometry"]
        cam = run.get("camera", {})
        lines.append(f"- {run['session']}: r={od.get('wheel_radius'):.5f}"
                     f" (se {od.get('wheel_radius_se') or 0:.5f}), b="
                     + (f"{od['wheel_separation']:.5f} (se {od.get('wheel_separation_se') or 0:.5f})"
                        if od.get("wheel_separation") else "n/a")
                     + f", yaw {(od.get('lidar_yaw_from_motion') or {}).get('mean_deg')}"
                     + (f", camera pitch {math.degrees(cam['pitch_rad']):.2f} roll {math.degrees(cam['roll_rad']):.2f}"
                        f" h {cam['height_m']:.4f} ({cam['height_source']}, score {cam['score']})"
                        if "pitch_rad" in cam else f", camera: {cam.get('error', 'skipped')}"))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "calibration",
                    help="reports go to <out>/<robot>/reports/<utc>/ (data/ is gitignored)")
    ap.add_argument("--store", type=Path, default=REPO / "data" / "calibration",
                    help="PC mirror of the calibration store; each run adds candidate records")
    ap.add_argument("--lidar-yaw-deg", type=float, default=None,
                    help="configured LiDAR yaw; default: lidar_yaw_offset in robot.yaml")
    ap.add_argument("--straights-only", nargs="*", default=[],
                    help="session names whose pivots are not usable (interrupted runs)")
    ap.add_argument("--no-camera", action="store_true")
    args = ap.parse_args(argv)
    yaw_cfg = args.lidar_yaw_deg if args.lidar_yaw_deg is not None else robot_lidar_yaw_deg()
    profile = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    runs = []
    for s in args.sessions:
        print(f"analysing {s.name} ...", flush=True)
        runs.append(analyse_run(s, yaw_cfg, profile, s.name in args.straights_only, not args.no_camera))
    store = CalibrationStore(args.store)
    for device in sorted({r["device"] for r in runs}):
        mine = [r for r in runs if r["device"] == device]
        cand = combine(device, mine, yaw_cfg, profile)
        cand["store_records"] = store_candidates(store, device, cand)
        out = args.out / device / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out.mkdir(parents=True, exist_ok=True)
        (out / "candidate.json").write_text(json.dumps(cand, indent=1, default=float), encoding="utf-8")
        (out / "runs.json").write_text(json.dumps(mine, indent=1, default=float), encoding="utf-8")
        (out / "report.md").write_text(report(cand, mine), encoding="utf-8")
        print(report(cand, mine))
        print(f"written {out}; store records {cand['store_records']}")
    return 0


def store_candidates(store, device, cand):
    """One new candidate record per kind (never accepted here; D-47 addendum)."""
    ids = {}
    sessions = cand["sessions"]
    o = cand["odometry"]
    if o["wheel_radius"] and o["wheel_separation"]:
        ids["wheel_odometry"] = store.add(
            device, "wheel_odometry",
            {"wheel_radius": o["wheel_radius"]["mean"], "wheel_separation": o["wheel_separation"]["mean"]},
            sessions=sessions, method=METHOD,
            intervals={k: [o[k]["mean"] - o[k].get("ci95", math.nan), o[k]["mean"] + o[k].get("ci95", math.nan)]
                       for k in ("wheel_radius", "wheel_separation") if "ci95" in o[k]},
            extra={"right_to_left_ratio": o["right_to_left_ratio"], "gains": o["gains"]})
    yaw = cand["lidar_yaw_offset_check"]["from_motion_deg"]
    if yaw:
        ids["lidar_mount"] = store.add(
            device, "lidar_mount", {"lidar_yaw_offset": math.radians(yaw["mean"])}, sessions=sessions,
            method=METHOD, intervals={"lidar_yaw_offset_deg": [yaw["mean"] - yaw.get("ci95", math.nan),
                                                                yaw["mean"] + yaw.get("ci95", math.nan)]}
            if "ci95" in yaw else {}, extra={"configured_deg": cand["lidar_yaw_offset_check"]["configured_deg"]})
    cam = cand.get("camera")
    if cam:
        keys = ("width", "height", "fx", "cx", "cy", "pitch_rad", "height_m", "x_offset_m", "roll_rad", "max_range_m")
        ids["camera_profile"] = store.add(
            device, "camera_profile", {k: cam[k] for k in keys if k in cam}, sessions=sessions, method=METHOD,
            intervals={"across_runs": cam.get("across_runs"), "uncertainty": cam.get("uncertainty")},
            extra={"height_source": cam.get("height_source"), "recommended": cam.get("recommended")})
    return ids


if __name__ == "__main__":
    sys.exit(main())
