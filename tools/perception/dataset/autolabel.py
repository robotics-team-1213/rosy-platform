"""D-379: automatic labels for a recorded session (LiDAR walls, driven floor).

    autolabel.py <session_dir> [--out data/perception/labels/<session>]
                 [--overlays X:/DevTemp/d379-labels/<session>] [--keep-v2 DIR]
    autolabel.py --video teleop_x.mp4 [--sidecar teleop_x.jsonl] ...

<session_dir> is a D-356 recording (session.json + bag/*.mcap). A teleop video
from bag_to_video.py plus its per-frame sidecar jsonl works too (odometry from
the sidecar; no LiDAR unless the sidecar carries a "scan" side value).

Writes <out>/frames/NNNNNN.jpg (camera frame), masks/NNNNNN.png (class ids,
labels.CLASSES), conf/NNNNNN.png (confidence x255), labels.jsonl (per frame:
sources, versions, disagreements, rule comparison) and meta.json (parameters,
totals). Nothing here goes into git: data/ is gitignored.
"""
from __future__ import annotations

import argparse
import bisect
import dataclasses
import hashlib
import importlib
import json
import math
import sys
import types
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src" / "runtime" / "sensing"))

import labels as L  # noqa: E402
from frames import FrameSelector  # noqa: E402
from geometry import Camera, Lidar, PoseSeries, to_frame  # noqa: E402

DATA = HERE.parents[2] / "data" / "perception"
MAX_SCAN_DT_S = 0.2
JPEG_Q = 95


def _topic_is(topic: str, name: str) -> bool:
    topic = topic.lstrip("/")
    return topic == name or topic.endswith("/" + name)


def _stamp(msg) -> float:
    return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9


def _yaw(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _mcap_files(session: Path):
    import re

    def key(p):
        m = re.search(r"(\d+)(?=\.mcap$)", p.name)
        return (int(m.group(1)) if m else -1, p.name)
    return sorted((session / "bag").glob("*.mcap"), key=key)


def _iter(files, names):
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            try:
                channels = reader.get_summary().channels.values()
                topics = [c.topic for c in channels if any(_topic_is(c.topic, n) for n in names)]
            except Exception:  # no summary (truncated file): filter while reading
                topics = None
            try:
                for _schema, ch, message, msg in reader.iter_decoded_messages(topics=topics):
                    name = next((n for n in names if _topic_is(ch.topic, n)), None)
                    if name is not None:
                        yield name, message.log_time / 1e9, msg
            except Exception as exc:  # truncated tail of the last split
                print(f"warning: {f.name}: stopped reading ({exc})", file=sys.stderr)


class Scans:
    """LaserScans by header stamp (scan start)."""

    def __init__(self):
        self.t, self.msgs = [], []

    def add(self, t, msg):
        self.add_raw(t, msg.ranges, msg.angle_min, msg.angle_increment, msg.time_increment,
                     msg.range_min, msg.range_max)

    def add_raw(self, t, ranges, angle_min, angle_increment, time_increment, range_min, range_max):
        self.t.append(float(t))
        self.msgs.append((np.asarray(ranges, dtype=np.float32), float(angle_min),
                          float(angle_increment), float(time_increment),
                          float(range_min), float(range_max)))

    def nearest(self, t):
        if not self.t:
            return None, None
        i = bisect.bisect_left(self.t, t)
        j = min((k for k in (i - 1, i) if 0 <= k < len(self.t)), key=lambda k: abs(self.t[k] - t))
        return j, self.t[j] - t


def read_mcap_side(files):
    """First pass: odometry and scans."""
    ot, ox, oy, oa, scans = [], [], [], [], Scans()
    for name, _log, msg in _iter(files, ("odom", "scan")):
        if name == "odom":
            p = msg.pose.pose.position
            ot.append(_stamp(msg)); ox.append(p.x); oy.append(p.y); oa.append(_yaw(msg.pose.pose.orientation))
        else:
            scans.add(_stamp(msg), msg)
    return PoseSeries(ot, ox, oy, oa), scans


def mcap_frames(files):
    """Second pass: (stamp, bgr) camera frames, raw or JPEG."""
    from extract import image_to_bgr
    for name, _log, msg in _iter(files, ("camera/front", "camera/front/compressed")):
        if name == "camera/front/compressed":
            bgr = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
        else:
            try:
                bgr = image_to_bgr(msg.encoding, msg.width, msg.height, msg.step, bytes(msg.data))
            except ValueError:
                continue
        if bgr is not None:
            yield _stamp(msg), bgr


def read_sidecar(video: Path, sidecar: Path):
    """bag_to_video.py output -> (PoseSeries, frame iterator factory, Scans or None).

    Odometry is the sidecar's per-frame "odom" side value; scans come from the
    sibling <stem>.scan.npz (row i = scan nearest frame i) when it exists. The npz
    has no time_increment, so scans are motion-compensated at their stamp only.
    """
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
    t, x, y, a = [], [], [], []
    for r in rows:
        odom = (r.get("side") or {}).get("odom")
        if isinstance(odom, dict) and all(k in odom for k in ("x", "y", "yaw")):
            t.append(r["t"]); x.append(odom["x"]); y.append(odom["y"]); a.append(odom["yaw"])

    def frames():
        cap = cv2.VideoCapture(str(video))
        try:
            for r in rows:
                ok, bgr = cap.read()
                if not ok:
                    break
                yield r["t"], bgr
        finally:
            cap.release()
    scans = None
    npz = sidecar.with_name(sidecar.name[: -len(".jsonl")] + ".scan.npz")
    if npz.is_file():
        with np.load(npz) as z:  # NpzFile re-reads a key on every access
            d = {k: z[k] for k in z.files}
        scans, seen = Scans(), set()
        for i in np.argsort(d["scan_stamp_ns"]):
            s = int(d["scan_stamp_ns"][i])
            if s == 0 or s in seen or np.isnan(d["ranges"][i].astype(np.float32)).all():
                continue
            seen.add(s)
            scans.add_raw(s / 1e9, d["ranges"][i], d["angle_min"], d["angle_increment"], 0.0,
                          d["range_min"], d["range_max"])
    return PoseSeries(t, x, y, a), frames, scans


def scan_points_at(lidar: Lidar, odom: PoseSeries, scan, frame_pose, max_range):
    """Scan returns moved into the base frame at the frame time (per-return pose)."""
    t0, (ranges, amin, ainc, tinc, rmin, rmax) = scan
    xy, r, idx = lidar.points(ranges, amin, ainc, max(rmin, L.MIN_RANGE_M), rmax, max_range)
    if xy.size == 0:
        return xy
    times = t0 + idx * tinc
    px = np.interp(times, odom.t, odom.x)
    py = np.interp(times, odom.t, odom.y)
    pa = np.interp(times, odom.t, odom.yaw)
    c, s = np.cos(pa), np.sin(pa)
    world = np.column_stack([px + c * xy[:, 0] - s * xy[:, 1], py + s * xy[:, 0] + c * xy[:, 1]])
    return to_frame((0.0, 0.0, 0.0), frame_pose, world)


def load_rules(keep_v2: Path | None):
    """{name: fn(bgr, horizon_row) -> 0/1 mask}: the rules we compare against."""
    from control.sensing.perception.lane_keep import floor_white_mask

    def device_line(bgr, horizon):  # D-378 E1: the device 'line' mode's bright mask
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = (hsv[..., 2] >= 180) & (hsv[..., 1] <= 60)
        m[: int(math.ceil(horizon))] = False
        return m
    rules = {"line_v180": device_line, "keep_main": floor_white_mask}
    if keep_v2 is not None:
        pkg = types.ModuleType("keepv2_rules")
        pkg.__path__ = [str(keep_v2)]
        sys.modules["keepv2_rules"] = pkg
        rules["keep_v2"] = importlib.import_module("keepv2_rules.lane_keep").floor_white_mask
    return rules


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def video_session(video: Path) -> tuple[str | None, dict | None]:
    """(session name, session.json) from bag_to_video.py's <stem>.json, as extract.py reads it.

    The session name, not the video stem, keeps a converted session and its bag in
    one split."""
    meta = video.with_suffix(".json")
    if not meta.is_file():
        return None, None
    doc = json.loads(meta.read_text(encoding="utf-8"))
    return (doc.get("source") or {}).get("session"), doc.get("session")


def check_out(out: Path, session: str, force: bool) -> str | None:
    """Why labels may not be written to out, or None when they may.

    Never silently replace earlier labels, and never, even with force, the labels of
    a different session."""
    meta = out / "meta.json"
    if not (out / "labels.jsonl").exists() and not meta.exists():
        return None
    if meta.is_file():
        other = json.loads(meta.read_text(encoding="utf-8")).get("session")
        if other != session:
            return f"{out} holds labels of session {other!r}, not {session!r}"
    return None if force else f"{out} already holds labels (use --force to replace them)"


def calibrate_pitch(frames, odom: PoseSeries, scans: Scans, lidar=Lidar(), every_s=4.0,
                    max_samples=80, max_range=1.6):
    """Fit the camera pitch to the session's LiDAR walls (labels.fit_pitch)."""
    samples, cam, last = [], None, None
    for t, bgr in frames:
        if last is not None and t - last < every_s:
            continue
        pose = odom.at(t)
        j, dt = scans.nearest(t)
        if pose is None or j is None or abs(dt) > 0.1:
            continue
        last = t
        cam = cam or Camera.from_profile(width=bgr.shape[1], height=bgr.shape[0])
        xy = scan_points_at(lidar, odom, (scans.t[j], scans.msgs[j]), pose, max_range)
        samples.append((xy[xy[:, 0] > 0.3] if len(xy) else xy, L.edge_image(bgr)))
        if len(samples) >= max_samples:
            break
    if cam is None:
        return None, {"pitch_source": "profile", "why": "no frame with a scan"}
    return L.choose_pitch(cam, samples)


def label_session(frames, odom: PoseSeries, scans: Scans | None, out: Path, *, session: str,
                  cam: Camera | None = None, lidar=Lidar(), rules=None, overlays: Path | None = None,
                  overlay_every: int = 5, min_interval=0.5, max_hamming=4, max_range=4.0,
                  traj_window_s=40.0, max_frames=None, pitch_rad=None):
    rules = rules or {}
    for sub in ("frames", "masks", "conf"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    if overlays:
        overlays.mkdir(parents=True, exist_ok=True)
    sel = FrameSelector(min_interval, max_hamming)
    totals = {"frames": 0, "lidar": 0, "trajectory": 0, "conflict": 0, "no_pose": 0,
              "rules": {n: {} for n in rules}}
    n = 0
    with open(out / "labels.jsonl", "w", encoding="utf-8") as rows:
        for t, bgr in frames:
            if max_frames is not None and n >= max_frames:
                break
            if not sel.accept(t, bgr):
                continue
            if cam is None:
                cam = Camera.from_profile(width=bgr.shape[1], height=bgr.shape[0])
                if pitch_rad is not None:
                    cam = dataclasses.replace(cam, pitch_rad=pitch_rad)
            pose = odom.at(t)
            rec = {"index": n, "t": t, "session": session, "version": L.LABEL_VERSION}
            wall = floor = dist = band = None
            if pose is None:
                totals["no_pose"] += 1
            else:
                if scans is not None and scans.t:
                    j, dt = scans.nearest(t)
                    if abs(dt) <= MAX_SCAN_DT_S:
                        xy = scan_points_at(lidar, odom, (scans.t[j], scans.msgs[j]), pose, max_range)
                        wall, floor, _contact, dist = L.wall_label(cam, xy)
                        rec["lidar"] = {"scan_dt_s": round(dt, 4), "returns": int(len(xy))}
                    else:
                        rec["lidar"] = {"scan_dt_s": round(dt, 4), "skipped": "no scan near the frame"}
                ft = odom.window(t, t + traj_window_s)
                band, travel = L.trajectory_band(cam, pose, ft[1:])
                rec["trajectory"] = {"travel_m": round(travel, 3), "used": band is not None}
            masks = {name: fn(bgr, cam.horizon_row).astype(bool) for name, fn in rules.items()}
            cls, conf, info = L.combine(bgr, wall=wall, floor=floor, band=band, rules=masks, wall_dist=dist)
            rec.update(info)
            name = f"{n:06d}"
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            (out / "frames" / f"{name}.jpg").write_bytes(buf.tobytes())
            cv2.imwrite(str(out / "masks" / f"{name}.png"), cls)
            cv2.imwrite(str(out / "conf" / f"{name}.png"), conf)
            rows.write(json.dumps(rec) + "\n")
            totals["frames"] += 1
            totals["lidar"] += wall is not None
            totals["trajectory"] += band is not None
            totals["conflict"] += bool(rec["conflict"])
            for rname, st in rec["rules"].items():
                agg = totals["rules"][rname]
                for k, v in st.items():
                    agg[k] = agg.get(k, 0) + v
            if overlays and (n % overlay_every == 0):
                _write_overlay(overlays / f"{name}.jpg", bgr, cls, masks, rec)
            n += 1
    for agg in totals["rules"].values():
        agg.update(confusion(agg))
    return totals


def confusion(agg) -> dict:
    """Headline numbers for one rule over many frames."""
    def ratio(a, b):
        return None if not b else round(a / b, 4)
    judged = agg.get("on_wall", 0) + agg.get("on_floor", 0) + agg.get("on_lane", 0)
    return {"paint_on_wall_share": ratio(agg.get("on_wall", 0), judged),
            "paint_on_wall_core_share": ratio(agg.get("on_wall_core", 0), judged),
            "wall_marked_paint_rate": ratio(agg.get("on_wall", 0), agg.get("wall_px", 0)),
            "lane_recall": ratio(agg.get("on_lane", 0), agg.get("lane_px", 0))}


def _write_overlay(path, bgr, cls, masks, rec):
    panels = [bgr, L.overlay(bgr, cls)]
    for name, m in masks.items():
        p = bgr.copy()
        p[m & (cls == L.WALL)] = (0, 0, 255)       # rule paint on a LiDAR wall: red
        p[m & (cls != L.WALL)] = (255, 255, 0)     # rule paint elsewhere: cyan
        cv2.putText(p, name, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        panels.append(p)
    tag = "+".join(rec["sources"]) or "none"
    cv2.putText(panels[1], f"{rec['index']} {tag}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (0, 255, 255), 1)
    cv2.imwrite(str(path), np.hstack(panels), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", type=Path)
    ap.add_argument("--video", type=Path)
    ap.add_argument("--sidecar", type=Path)
    ap.add_argument("--session-name", help="session id for a --video input without <stem>.json")
    ap.add_argument("--force", action="store_true", help="replace this session's earlier labels")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--overlays", type=Path)
    ap.add_argument("--overlay-every", type=int, default=5)
    ap.add_argument("--keep-v2", type=Path, help="folder with keep v2 lane_keep.py, lane.py, lane_bev.py")
    ap.add_argument("--min-interval", type=float, default=0.5)
    ap.add_argument("--lidar-mirrored", action="store_true")
    ap.add_argument("--max-frames", type=int)
    ap.add_argument("--pitch-deg", type=float,
                    help="camera pitch; default: fit to the session's LiDAR walls, else the profile")
    args = ap.parse_args(argv)
    if (args.session is None) == (args.video is None):
        ap.error("give a session folder or --video")
    rules = load_rules(args.keep_v2)
    if args.session is not None:
        files = _mcap_files(args.session)
        if not files:
            print(f"no .mcap under {args.session / 'bag'}", file=sys.stderr)
            return 1
        session = args.session.name
        odom, scans = read_mcap_side(files)
        make_frames = lambda: mcap_frames(files)  # noqa: E731
        source = {"kind": "mcap", "files": [str(f) for f in files]}
    else:
        sidecar = args.sidecar or args.video.with_suffix(".jsonl")
        session, session_json = video_session(args.video)
        if args.session_name and session and args.session_name != session:
            ap.error(f"--session-name {args.session_name} differs from {session} in the video metadata")
        session = session or args.session_name
        if not session:
            ap.error(f"{args.video.with_suffix('.json')} has no source.session: give --session-name")
        odom, make_frames, scans = read_sidecar(args.video, sidecar)
        source = {"kind": "video+sidecar", "video": str(args.video), "sidecar": str(sidecar),
                  "sha256": {"video": _sha(args.video), "sidecar": _sha(sidecar)}}
    lidar = Lidar(mirrored=args.lidar_mirrored)
    pitch, camera = None, {"pitch_source": "profile"}
    if args.pitch_deg is not None:
        pitch, camera = math.radians(args.pitch_deg), {"pitch_source": "argument",
                                                       "pitch_deg": args.pitch_deg}
    elif scans is not None and scans.t:
        pitch, camera = calibrate_pitch(make_frames(), odom, scans, lidar)
        print(f"camera pitch ({camera['pitch_source']}): {camera}")
    out = args.out or DATA / "labels" / session
    refusal = check_out(out, session, args.force)
    if refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return 1
    totals = label_session(make_frames(), odom, scans, out, session=session, pitch_rad=pitch,
                           lidar=lidar, rules=rules,
                           overlays=args.overlays, overlay_every=args.overlay_every,
                           min_interval=args.min_interval, max_frames=args.max_frames)
    meta = {"schema": "rosy.perception.autolabel/1", "version": L.LABEL_VERSION, "session": session,
            "source": source, "camera": camera, "classes": L.CLASSES, "ignore_index": L.IGNORE_INDEX,
            "odom_samples": len(odom), "scans": 0 if scans is None else len(scans.t),
            "params": {k: getattr(L, k) for k in (
                "CONTACT_MARGIN_PX", "RANGE_SIGMA_M", "MAX_MARGIN_PX", "GAP_FILL_PX", "SEGMENT_GAP_M", "SEGMENT_GAP_PER_M", "PAINT_MIN_CONTRAST",
                "PAINT_HEADROOM", "PAINT_MAX_SATURATION", "FOOTPRINT_HALF_WIDTH_M",
                "TRAJ_MAX_DISTANCE_M", "TRAJ_MAX_TURN_RAD", "TRAJ_MIN_TRAVEL_M", "CONFLICT_PX")}
            | {"lidar_mirrored": args.lidar_mirrored, "max_scan_dt_s": MAX_SCAN_DT_S,
               "rules": sorted(rules)},
            "totals": totals}
    sj = args.session / "session.json" if args.session else None
    if sj is not None and sj.is_file():
        meta["session_json"] = json.loads(sj.read_text(encoding="utf-8"))
    elif args.video is not None and session_json:
        meta["session_json"] = session_json
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(totals, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
