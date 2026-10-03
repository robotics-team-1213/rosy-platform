"""D-384 R0 replay: LaneKeeper + RoadStateEstimator over recorded D-356 sessions.

  python learning/training/perception/road_replay.py data/perception/raw/<session> --out X:/DevTemp/road-replay/<name>
  python learning/training/perception/road_replay.py <bag_to_video>.mp4 --out ... [--labels data/perception/labels/<session>]

Inputs follow extract.py's two-class rule: a folder is an MCAP session (odometry joined by
stamp), a file a bag_to_video.py video with its sidecar; frame-only input is refused (the
estimator needs odometry). Results stay outside the public repo (D-226).

Metrics and D-384 R0 gates (lane-owner review, 2026-10-01):
  keep / road     on_line, on_paint, none, jump (lane_replay.py definitions); the road target
                  is the estimated lane centre at LOOKAHEAD_M. Gate: road on_line and on_paint
                  <= keep; road jump <= 0.02; straight mean |err| <= 0.08 (|yaw rate| < 0.1 rad/s)
  levels          TRACK/COAST/SLOW/STOP rates
  NIS             mean of applied associations per regime (straight/curve/turning) in [0.5, 4];
                  tail: pre-gate best association per side among the keeper's own lines for
                  that side, 0.5-3 % above 9.21 (side_missing_rate, gated_out_rate reported)
  coast survival  dropouts of 0.05 / 0.10 m injected from TRACK checkpoints; at the first
                  accepted frame after the dropout the coasted state is within 2 cm and 5 deg
                  of the uninterrupted run in >= 95 % of trials
  wall accept     accepted boundaries lying on D-379 wall pixels (<= 1 %), n/a without labels
  switches        lane switches (|dd| > w/2 between accepted frames) per 100 straight frames
                  <= 1; wrong-side lock (TRACK while the keeper's pair centre is > w/2 away) = 0
  determinism     the estimator re-run over the cached inputs reproduces the snapshot hash
Real-session numbers are unvalidated until the lane owner accepts them.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import dataclasses
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[3]
for _p in (REPO / "src" / "runtime" / "sensing",
           REPO / "contracts" / "foundation", REPO / "tools", REPO / "learning" / "training" / "perception" / "dataset"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bag_to_video  # noqa: E402
import extract  # noqa: E402
import lane_replay  # noqa: E402
from control.recording import CAMERA_TOPIC, SHADOW_TOPIC  # noqa: E402
from control.sensing.perception.camera_ground import nominal_ground_plane  # noqa: E402
from control.sensing.perception.lane_keep import LaneKeeper, floor_white_mask  # noqa: E402
from road_replay_metrics import (  # noqa: E402, F401 — re-exported for tests and tools
    _coast_stats,
    _curve_residuals,
    _detector_metrics,
    _gate,
    _keeper_pair_mid,
    _motion,
    _nis_mean_gate,
    _parallel_pair_width,
    _tail_samples,
    _unassociated,
    _unassociated_summary,
    _unassociated_ys,
)
from control.sensing.perception.road_state import (  # noqa: E402
    STOP,
    TRACK,
    IrMeas,
    RoadStateEstimator,
    RoadStateParams,
    boundaries_from_keep,
    decision_point_from_keep,
    offset_from_shadow,
)

HALF = lane_replay.LANE_HALF_WIDTH_M
LOOKAHEAD_M = 0.25
STRAIGHT_MAX_RATE = 0.1        # rad/s
IR_HALF_SPAN_M, IR_MAX_AGE_S = 0.020, 0.2   # half span: URDF nominal (D-397 geometry.yaml)
KEEP_MAX_FRAME_GAP_S = 0.5     # as line_observer_node: a camera gap restarts the keeper
DROPOUTS_M = (0.05, 0.10)
CHECKPOINT_EVERY, DROPOUT_MAX_S = 8, 4.0
NIS_BINS = (0.0, 1.0, 2.0, 4.0, 6.0, 9.21, 16.0, math.inf)
WALL_CLASS = 2


@dataclass
class Frame:
    t: float
    bgr: np.ndarray
    odom: tuple | None = None          # (x, y, yaw)
    shadow: dict | None = None
    ir: dict | None = None             # latest IR_LINE line/observation payload


# ------------------------------------------------------------------ inputs

def _pose_tuple(pose):
    return None if not pose else (float(pose["x"]), float(pose["y"]), float(pose["yaw"]))


def _interp(series, t):
    """Odometry pose at t, linear between the samples around it (yaw wrapped)."""
    times, poses = series
    if not times:
        return None
    j = bisect.bisect_right(times, t)
    if j == 0:
        return poses[0]
    if j == len(times):
        return poses[-1]
    (t0, a), (t1, b) = (times[j - 1], poses[j - 1]), (times[j], poses[j])
    k = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
    turn = math.atan2(math.sin(b[2] - a[2]), math.cos(b[2] - a[2]))
    return (a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1]), a[2] + k * turn)


def _mcap_odom(files):
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    samples = []
    for f in files:
        with open(f, "rb") as fh:
            reader = make_reader(fh, decoder_factories=[DecoderFactory()])
            summary = reader.get_summary()
            topics = None if summary is None else [
                c.topic for c in summary.channels.values() if extract._topic_is(c.topic, "odom")]
            for _, ch, _, msg in reader.iter_decoded_messages(topics=topics):
                if extract._topic_is(ch.topic, "odom"):
                    samples.append((bag_to_video._stamp_ns(msg) / 1e9, _pose_tuple(bag_to_video._pose(msg))))
    samples.sort(key=lambda s: s[0])
    return [s[0] for s in samples], [s[1] for s in samples]


def mcap_frames(session: Path):
    files = extract._mcap_files(session)
    if not files:
        raise SystemExit(f"no .mcap files under {session / 'bag'}")
    odom = _mcap_odom(files)
    shadow = ir = None
    for name, _, schema, msg in bag_to_video._messages(files, camera_only=False):
        if name == CAMERA_TOPIC:
            bgr = bag_to_video._frame(schema, msg)
            if bgr is not None:
                t = bag_to_video._stamp_ns(msg) / 1e9
                yield Frame(t, bgr, _interp(odom, t), shadow, ir)
        elif name == SHADOW_TOPIC:
            shadow = extract._side_value(schema, msg)
        elif name == "line/observation":
            value = extract._side_value(schema, msg)
            if isinstance(value, dict) and value.get("source") == "IR_LINE":
                ir = value


def video_frames(path: Path):
    rows, meta = extract._sidecar(path)
    if rows is None:
        raise SystemExit(f"{path}: no {path.with_suffix('.jsonl').name} sidecar; the estimator needs "
                         "odometry, so frame-only video is not replayed")
    extract._check_sidecar(path, rows, meta)
    for t, bgr, side, _, _ in extract._video_frames(path, rows):
        line = side.get("line/observation")
        yield Frame(float(t), bgr, _pose_tuple(side.get("odom")), side.get(SHADOW_TOPIC),
                    line if isinstance(line, dict) and line.get("source") == "IR_LINE" else None)


def session_frames(source: Path):
    """extract.py's rule: a folder is an MCAP session, a file a bag_to_video video."""
    return mcap_frames(source) if source.is_dir() else video_frames(source)


def load_labels(folder: Path | None) -> dict:
    """{t rounded to ms: mask path} from a D-379 labels folder."""
    if folder is None or not (folder / "labels.jsonl").is_file():
        return {}
    out = {}
    for line in (folder / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[round(float(row["t"]), 3)] = folder / "masks" / f"{int(row['index']):06d}.png"
    return out


# ------------------------------------------------------------------ replay

def derotate(img, roll_deg: float, cx: float, cy: float):
    """The image a roll-free camera would see. The ground model has no roll; the
    calibration (camera_extrinsic.CameraPose.project, feat/camera-extrinsic-autocalib)
    rolls pixels about the principal point: p = c + R(roll) (p0 - c). Replay only."""
    if not roll_deg:
        return img
    r = math.radians(roll_deg)
    m = np.array([[math.cos(r), -math.sin(r), 0.0], [math.sin(r), math.cos(r), 0.0]])
    m[:, 2] = np.array([cx, cy]) - m[:, :2] @ np.array([cx, cy])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def ground_for(pitch_deg: float | None, height_m: float | None = None):
    """(profile, NOMINAL ground) with replay-only pitch (degrees down) and lens height
    overrides on a copy of the profile: calibration candidates, never the robot's."""
    profile, ground = lane_replay._nominal_ground()
    if pitch_deg is None and height_m is None:
        return profile, ground
    profile = dict(profile)
    if pitch_deg is not None:
        profile["pitch_rad"] = math.radians(pitch_deg)
    if height_m is not None:
        profile["height_m"] = float(height_m)
    return profile, nominal_ground_plane(source="NOMINAL", allowed=True, width_px=lane_replay.FRAME_W,
                                         height_px=lane_replay.FRAME_H, profile=profile)


def _measurements(last, frame: Frame, t: float, params: RoadStateParams):
    meas = boundaries_from_keep(last)
    ir = frame.ir
    if params.ir_geometry_measured and ir and ir.get("visible") and isinstance(ir.get("error"), (int, float)) \
            and abs(float(ir.get("stamp", -1e9)) - t) <= IR_MAX_AGE_S:
        meas.append(IrMeas(y=-float(ir["error"]) * IR_HALF_SPAN_M))
    learned = offset_from_shadow(frame.shadow or {}, half_width_m=HALF)
    if learned is not None:
        meas.append(learned)
    return meas


def _road_target(snap):
    """Lane centre at LOOKAHEAD_M (base_link) and its lane-contract error, or None at STOP."""
    if snap["level"] == STOP:
        return None
    y = -(snap["d"] + LOOKAHEAD_M * snap["phi"]) + snap["kappa"] * LOOKAHEAD_M ** 2 / 2
    return y, max(-1.0, min(1.0, -y / HALF))


def _wall_accepts(snap, keeper, ground, mask):
    """(accepted boundaries, those lying on wall pixels) for one labelled frame."""
    accepted = walls = 0
    for c in snap["candidates"]:
        if c.get("label") not in ("R", "L"):
            continue
        accepted += 1
        slope = math.tan(math.radians(c["psi_deg"]))
        hits = total = 0
        for x in np.linspace(0.15, 0.33, 7):
            px = keeper.to_pixel(ground, float(x), c["y"] + (float(x) - c["x"]) * slope)
            if px is None:
                continue
            col, row = int(round(px[0])), int(round(px[1]))
            if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1]:
                total += 1
                hits += int(mask[row, col] == WALL_CLASS)
        walls += int(total > 0 and hits * 2 >= total)
    return accepted, walls


def _run_estimator(inputs, params):
    est = RoadStateEstimator(params)
    digest = hashlib.sha256()
    for t, ds, dth, dt, meas, decision in inputs:
        est.predict(ds, dth, dt=dt, stamp=t)
        est.update(meas, t, decision_point=decision)
        digest.update(json.dumps(est.snapshot(), sort_keys=True).encode())
    return digest.hexdigest()


def _dropouts(inputs, rows, checkpoints, dropouts):
    out = {}
    for dropout in dropouts:
        ok = trials = unfinished = 0
        for start, saved in checkpoints.items():
            if start == 0 or rows[start - 1]["level"] != TRACK:
                continue
            est, travel, t0 = copy.deepcopy(saved), 0.0, inputs[start][0]
            for j in range(start, len(inputs)):
                t, ds, dth, dt, meas, decision = inputs[j]
                if t - t0 > DROPOUT_MAX_S:
                    break
                est.predict(ds, dth, dt=dt, stamp=t)
                if travel < dropout:
                    travel += abs(ds)
                    est.update([], t)
                    continue
                prior = est.x.copy()
                est.update(meas, t, decision_point=decision)
                if sum(est.last_frame["accepted"].values()) == 0:
                    continue
                if rows[j]["level"] == TRACK:
                    trials += 1
                    ok += int(abs(prior[0] - rows[j]["d"]) <= 0.02
                              and abs(math.degrees(prior[1] - rows[j]["phi"])) <= 5.0)
                break
            else:
                unfinished += 1
        out[f"{dropout:.2f}"] = {"trials": trials, "survived": ok, "unfinished": unfinished,
                                 "rate": round(ok / trials, 3) if trials else None}
    return out


def replay(frames, *, labels: dict | None = None, dropouts=DROPOUTS_M,
           params: RoadStateParams | None = None, pitch_deg: float | None = None,
           lidar_forward_deg: float = 180.0, height_m: float | None = None,
           roll_deg: float = 0.0) -> tuple[dict, list]:
    params = params or RoadStateParams(lane_width_m=2 * HALF)
    profile, ground = ground_for(pitch_deg, height_m)
    keeper = LaneKeeper(camera_x_offset_m=float(profile["x_offset_m"]))
    est = RoadStateEstimator(params)
    labels = labels or {}
    rows, inputs, checkpoints, nis = [], [], {}, []
    nis_candidates, nis_tail, tail_frames, tail_gated, side_missing, side_slots = [], [], 0, 0, 0, 0
    residual = {"left": [], "right": []}
    unassociated = []
    nis_state = {"straight": [], "curve": [], "turning": [], "stationary": []}
    prev_pose = prev_t = None
    wall_accepted = wall_hits = labelled = 0
    keeper_digest = hashlib.sha256()
    headings, pairs = [], 0
    straight_heading = {"left": [], "right": []}
    pair_widths = []
    for i, frame in enumerate(frames):
        img = frame.bgr
        if img.shape[:2] != (lane_replay.FRAME_H, lane_replay.FRAME_W):
            img = cv2.resize(img, (lane_replay.FRAME_W, lane_replay.FRAME_H), interpolation=cv2.INTER_AREA)
        img = derotate(img, roll_deg, ground.principal_x, ground.principal_y)
        t = frame.t
        if prev_t is None or not 0.0 <= t - prev_t <= KEEP_MAX_FRAME_GAP_S:
            keeper.reset()
        obs = keeper.update(img, ground, lane_half_width_m=HALF)
        keeper_digest.update(json.dumps(keeper.last, sort_keys=True, default=float).encode())
        ds = dth = 0.0
        if frame.odom is not None and prev_pose is not None:
            dx, dy = frame.odom[0] - prev_pose[0], frame.odom[1] - prev_pose[1]
            ds = dx * math.cos(prev_pose[2]) + dy * math.sin(prev_pose[2])
            dth = math.atan2(math.sin(frame.odom[2] - prev_pose[2]), math.cos(frame.odom[2] - prev_pose[2]))
        dt = 0.0 if prev_t is None else max(0.0, t - prev_t)
        prev_pose, prev_t = frame.odom or prev_pose, t
        meas = _measurements(keeper.last, frame, t, params)
        decision = decision_point_from_keep(keeper.last)
        headings += [float(b["heading_deg"]) for b in keeper.last.get("boundaries", [])]
        pairs += keeper.last.get("strategy") == "both"
        pair_widths += _parallel_pair_width(keeper.last)
        if i % CHECKPOINT_EVERY == 0:
            checkpoints[i] = copy.deepcopy(est)
        est.predict(ds, dth, dt=dt, stamp=t)
        est.update(meas, t, decision_point=decision)
        snap = est.snapshot()
        inputs.append((t, ds, dth, dt, meas, decision))
        if _motion(ds, dth, dt) == "straight":
            for b in keeper.last.get("boundaries", []):
                if b.get("side") in straight_heading:
                    straight_heading[b["side"]].append(float(b["heading_deg"]))
        mask = lane_replay.white_mask(img)
        floor = floor_white_mask(img, ground.horizon_row)
        row = {"t": t, "level": snap["level"], "d": snap["d"], "phi": snap["phi"], "w": snap["w"],
               "hypothesis": (snap["hypothesis"] or {}).get("labels"),
               "accepted": sum(snap["accepted"].values()), "strategy": keeper.last.get("strategy"),
               "calibration_suspect": snap["calibration_suspect"],
               "consistent_reason": snap["consistent_reason"], "decision_point": decision,
               "straight": dt > 0 and abs(dth / dt) < STRAIGHT_MAX_RATE, "keep": None, "road": None,
               "motion": _motion(ds, dth, dt)}
        if obs is not None:
            point = keeper.last.get("target_px") or (img.shape[1] / 2 * (1 + obs.error), img.shape[0] * 0.835)
            row["keep"] = {"err": round(float(obs.error), 4),
                           "on_line": lane_replay.target_on_line(mask, obs.error),
                           "on_paint": lane_replay.target_on_paint(floor, point)}
        target = _road_target(snap)
        if target is not None:
            px = keeper.to_pixel(ground, LOOKAHEAD_M, target[0])
            row["road"] = {"err": round(target[1], 4),
                           "on_line": lane_replay.target_on_line(mask, target[1]),
                           "on_paint": px is not None and lane_replay.target_on_paint(floor, px)}
        accepted = snap["accepted"]
        row["applied_update"] = bool((accepted["boundaries"] and not snap["deduplicated"])
                                     or accepted["ir"] or accepted["learned"])
        unassociated += _unassociated_ys(snap["level"], snap["candidates"])
        scored = [c for c in snap["candidates"] if isinstance(c.get("nis"), dict)]
        if snap["level"] != STOP:
            nis_candidates += [min(c["nis"].values()) for c in scored]
        if row["applied_update"] and snap["level"] not in (STOP, "COAST"):
            # tail: only where an update was applied (NIS is undefined in COAST)
            samples, missing = _tail_samples(scored)
            nis_tail += [nis_value for _, nis_value, _ in samples]
            side_missing += missing
            side_slots += 2
            tail_frames += 1
            if samples:
                tail_gated += min(samples, key=lambda x: x[1])[2]
            for c in scored:
                if c.get("label") in ("R", "L") and not snap["deduplicated"]:   # applied innovations
                    nis.append(c["nis"][c["label"]])
                    nis_state[row["motion"]].append(nis[-1])
                    if row["motion"] == "straight" and c.get("nu"):
                        residual["left" if c["label"] == "L" else "right"].append(c["nu"])
        mid_keep = _keeper_pair_mid(keeper.last.get("boundaries", []))
        if row["strategy"] == "both" and snap["level"] == TRACK and mid_keep is not None:
            mid_est = -snap["d"] - 0.22 * snap["phi"] + snap["kappa"] * 0.22 ** 2 / 2
            row["wrong_side"] = abs(mid_keep - mid_est) > HALF
        path = labels.get(round(t, 3))
        if path is not None and path.is_file():
            labelled += 1
            a, w = _wall_accepts(snap, keeper, ground, cv2.imread(str(path), cv2.IMREAD_UNCHANGED))
            wall_accepted, wall_hits = wall_accepted + a, wall_hits + w
        rows.append(row)
    n = len(rows)
    levels = {lv: round(sum(r["level"] == lv for r in rows) / max(1, n), 3)
              for lv in ("TRACK", "COAST", "SLOW", "STOP")}
    accepted = [r for r in rows if r["accepted"]]
    switches = sum(1 for a, b in zip(accepted, accepted[1:])
                   if b["straight"] and abs(b["d"] - a["d"]) > HALF)
    straight_frames = sum(r["straight"] for r in rows)
    d_jumps = sum(1 for a, b in zip(rows, rows[1:]) if a["level"] != STOP and b["level"] != STOP
                  and abs(b["d"] - a["d"]) > 0.02)
    nis_arr = np.asarray(nis, float)
    hist, _ = np.histogram(nis_arr, bins=NIS_BINS) if nis else (np.zeros(len(NIS_BINS) - 1), None)
    keep_m, road_m = _detector_metrics(rows, "keep"), _detector_metrics(rows, "road")
    baseline = _run_estimator(inputs, params)
    again = _run_estimator(inputs, params)
    survival = _dropouts(inputs, rows, checkpoints, dropouts)
    nis_mean = round(float(nis_arr.mean()), 3) if nis else None
    nis_above = round(float((nis_arr > 9.21).mean()), 4) if nis else None
    wall_rate = round(wall_hits / wall_accepted, 4) if wall_accepted else None
    switch_rate = round(100.0 * switches / straight_frames, 3) if straight_frames else None
    wrong = sum(bool(r.get("wrong_side")) for r in rows)
    metrics = {
        "frames": n, "keep": keep_m, "road": road_m, "levels": levels,
        "nis_candidates": {"n": len(nis_candidates),
                           "mean": round(float(np.mean(nis_candidates)), 3) if nis_candidates else None},
        "nis": {"basis": "associated", "n": len(nis), "mean": nis_mean, "above_9_21": nis_above,
                "by_state": {k: {"n": len(v), "mean": round(float(np.mean(v)), 3) if v else None,
                                 "above_9_21": round(float(np.mean(np.asarray(v) > 9.21)), 4) if v else None}
                             for k, v in nis_state.items()},
                "bins": [b if math.isfinite(b) else "inf" for b in NIS_BINS],
                "hist": [int(h) for h in hist]},
        "d_jump_rate": round(d_jumps / max(1, n - 1), 4),
        "coast_survival": survival,
        "wall_false_accept": {"labelled_frames": labelled, "accepted": wall_accepted,
                              "on_wall": wall_hits, "rate": wall_rate},
        "hypothesis_switches_per_100_straight": switch_rate, "wrong_side_lock": wrong,
        "rejects": est.snapshot()["rejects"],
        "reacq_counts": est.snapshot()["reacq_counts"],
        "keeper": {"pairs_rate": round(pairs / max(1, n), 4),
                   "median_heading_deg": round(float(np.median(headings)), 2) if headings else None,
                   "median_abs_heading_deg": round(float(np.median(np.abs(headings))), 2) if headings else None,
                   "boundaries": len(headings),
                   "pair_width_m": {"n": len(pair_widths),
                                    "median": round(float(np.median(pair_widths)), 4) if pair_widths else None,
                                    "ratio_to_map": round(float(np.median(pair_widths)) / params.lane_width_m, 4)
                                    if pair_widths else None},
                   # signed heading on straight motion: equal offsets both sides = camera
                   # yaw; opposite offsets = roll/pitch (lane owner, 2026-10-01)
                   "straight_heading_deg": {
                       side: None if not v else {"n": len(v), "median": round(float(np.median(v)), 2),
                                                 "p25": round(float(np.percentile(v, 25)), 2),
                                                 "p75": round(float(np.percentile(v, 75)), 2)}
                       for side, v in straight_heading.items()}},
        "setup": {"pitch_deg": pitch_deg, "height_m": height_m, "roll_deg": roll_deg,
                  "lidar_forward_deg": lidar_forward_deg,
                  "lidar_wall_veto": params.lidar_wall_veto,
                  "ir_geometry_measured": params.ir_geometry_measured, "mode": params.mode},
        "calibration_suspect_frames": sum(r["calibration_suspect"] for r in rows),
        "deterministic": baseline == again, "estimator_sha256": baseline,
        "keeper_sha256": keeper_digest.hexdigest(),
    }
    metrics["determinism"] = {"scope": "estimator re-run over the cached keeper outputs in one run; "
                                        "compare keeper_sha256 across two runs for the full pipeline",
                               "estimator_sha256": baseline, "keeper_sha256": metrics["keeper_sha256"]}
    metrics["calibration_suspect_run"] = metrics["calibration_suspect_frames"] > 0
    metrics["params"] = dataclasses.asdict(params)
    metrics["curve_residuals"] = _curve_residuals(nis_state)
    tail = np.asarray(nis_tail, float)
    metrics["coast"] = _coast_stats(rows)
    metrics["unassociated_keeper_lines"] = _unassociated_summary(unassociated)
    metrics["nis"]["tail"] = {"basis": "pre_gate_best_association_keeper_side", "n": len(nis_tail),
                              "frames": tail_frames, "scope": "applied-update frames, COAST excluded",
                              "side_missing_rate": round(side_missing / side_slots, 4) if side_slots else None,
                              "above_9_21": round(float((tail > 9.21).mean()), 4) if len(tail) else None,
                              "gated_out_rate": round(tail_gated / tail_frames, 4) if tail_frames else None}
    metrics["extrinsic_residual"] = {
        "note": "median innovation per side on straights, for the calibration record; not absorbed into R",
        **{side: {"n": len(v),
                  "median_nu_y_m": round(float(np.median([x["y"] for x in v])), 4) if v else None,
                  "median_nu_psi_deg": round(float(np.median([x["psi_deg"] for x in v])), 3) if v else None}
           for side, v in residual.items()}}

    def worse(key):
        a, b = road_m[key], keep_m[key]
        return None if a is None or b is None else a <= b
    rates = [v["rate"] for v in survival.values() if v["rate"] is not None]
    metrics["gates"] = {
        "on_line_le_keep": {"value": road_m["on_line_rate"], "pass": worse("on_line_rate")},
        "on_paint_le_keep": {"value": road_m["on_paint_rate"], "pass": worse("on_paint_rate")},
        "jump": _gate(road_m["jump_rate"], lambda v: v <= 0.02),
        "straight_mean_abs_err": _gate(road_m["straight_mean_abs_err"], lambda v: v <= 0.08),
        "nis_mean_by_regime": _nis_mean_gate(metrics["nis"]["by_state"]),
        "nis_above_9_21": _gate(metrics["nis"]["tail"]["above_9_21"], lambda v: 0.005 <= v <= 0.03),
        "coast_survival": _gate(min(rates) if rates else None, lambda v: v >= 0.95),
        "wall_false_accept": _gate(wall_rate, lambda v: v <= 0.01),
        "hypothesis_switches": _gate(switch_rate, lambda v: v <= 1.0),
        "wrong_side_lock": _gate(wrong, lambda v: v == 0),
        "deterministic_estimator": _gate(metrics["deterministic"], bool),
    }
    return metrics, rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="session folder (bag/*.mcap) or bag_to_video mp4 with its sidecar")
    parser.add_argument("--out", required=True)
    parser.add_argument("--labels", help="D-379 labels folder (labels.jsonl + masks/) for wall false-accept")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--pitch-deg", type=float, default=None,
                        help="camera pitch override (the D-379 real-frame fit is 11.8)")
    parser.add_argument("--height-m", type=float, default=None, help="lens height override (m)")
    parser.add_argument("--roll-deg", type=float, default=0.0,
                        help="camera roll (calibration convention); frames are derotated before the keeper")
    parser.add_argument("--lidar-forward-deg", type=float, default=180.0,
                        help="LiDAR scan angle of the nose; recorded only while the wall veto is off")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if REPO in out.parents or out == REPO:
        raise SystemExit("--out must be outside the public repo (D-226)")
    frames = session_frames(Path(args.source))
    if args.max_frames:
        frames = (f for i, f in zip(range(args.max_frames), frames))
    metrics, rows = replay(frames, labels=load_labels(Path(args.labels) if args.labels else None),
                           pitch_deg=args.pitch_deg, lidar_forward_deg=args.lidar_forward_deg,
                           height_m=args.height_m, roll_deg=args.roll_deg)
    metrics["source"] = str(args.source)
    metrics["validated"] = False
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    with open(out / "frames.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=float) + "\n")
    print(json.dumps(metrics, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
