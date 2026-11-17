"""Rosy Learning recording producers of the OMX cell (arm_a, arm_b, four cameras) -> a two-arm LeRobot dataset in the sim `collect` format.

Offline and read only: nothing here opens a device, a FIFO or a network socket. Input is the producer directories of
`learning/curation/perception/docs/learning-recording.md` (`<source_root>/<id>/descriptor.json`, `events/<seq>.json` and the camera `events/<seq>.jpg`)
plus the carries to cut out of them, each a time window on the producers' own `host-monotonic` clock with the cell's verdict.
Joint values, gripper and images are converted by `deploy/robot/omx/cell_act_inputs.py` (imported, not copied) and the features are built by
`tools/sim/omx_two_arm_policy_helpers.dataset_features`, the function `collect` uses, so the result mixes with sim data in one round.

Frames are sampled on the sim's grid (`SIM_FPS`, 15) holding each producer's last event at or before the tick. A tick is dropped when a producer has
no event, its latest event is older than `MAX_AGE_S`, or the six events span more than `MAX_SKEW_S`; the counts go into the meta. A carry is kept only
when its verdict is a success and the dropped ticks are few and not in a long run."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for _path in (ROOT / "deploy/robot/omx", ROOT / "tools/sim", Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import cell_act_inputs as inputs  # noqa: E402  the cell's one conversion from follower units to the sim's radians and jaw angle
import omx_two_arm_policy_helpers as helpers  # noqa: E402
from omx_output_paths import in_source_checkout  # noqa: E402

SCHEMA = "rosy.omx-two-arm-real-export/1"
SIM_FPS = 15  # tools/sim/omx_two_arm_world.py FPS (test_two_arm_export reads that source): ACT's chunks are counted in these frames
FOLLOWER_UNITS = "omx-follower-lerobot"  # deploy/robot/omx/cell_record_producer.py UNITS: body -100..100, gripper 0..100
ARM_SCHEMA, CAMERA_SCHEMA = "rosy.passive-owner-sample/1", "rosy.passive-camera-sample/1"
SOURCES = {"arm_a": "arm_a", "arm_b": "arm_b", "top": "cam_top", "side": "cam_side", "a_wrist": "cam_a_wrist", "b_wrist": "cam_b_wrist"}
SUCCESS = ("placed", "success")  # cell_attempts' verified outcome "placed"; a person's Learning verdict "success"
# One grid period is 1/15 = 0.067 s. An event up to two periods old is a producer that missed one beat; three is a stall. The six events of
# one frame may differ by 1.5 periods (a camera one beat behind an arm); two beats apart would show the arms where the pictures were not.
MAX_AGE_S, MAX_SKEW_S = 0.15, 0.10
EPS_S = 1e-6  # float slack when a tick lands on an event's own stamp
MAX_DROP_FRACTION, MAX_GAP_FRAMES, MIN_FRAMES = 0.1, 2, 15  # a carry with more dropped ticks, a longer hole or fewer frames is rejected
ARM_FROZEN = ("owner_id", "source_identity", "session_epoch", "clock_domain", "joint_names", "state_units", "action_units",
              "calibration_revision", "profile_revision", "reference_stage")
CAMERA_FROZEN = ("source_identity", "session_epoch", "clock_domain", "shape", "timestamp_semantics")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Stream:
    """One producer directory: its descriptor and its events in sequence order, read once."""

    def __init__(self, directory, name):
        self.dir, self.name, self.arm = Path(directory), name, name in inputs.ARMS
        self.descriptor = _json(self.dir / "descriptor.json")
        d = self.descriptor
        if self.arm and (d.get("kind") != "arm" or d.get("state_units") != FOLLOWER_UNITS or d.get("action_units") != FOLLOWER_UNITS
                         or list(d.get("joint_names") or []) != list(inputs.JOINTS) or d.get("reference_stage") != "post_guard_accepted"):
            raise ValueError(f"{name}: an arm producer with post-guard accepted references in {FOLLOWER_UNITS} units and joints {inputs.JOINTS} is required")
        if not self.arm and (d.get("kind") != "camera" or d.get("timestamp_semantics") != "host_receive"):
            raise ValueError(f"{name}: a host-receive camera producer is required")
        if not isinstance(d.get("rate_hz"), (int, float)) or d["rate_hz"] < SIM_FPS:
            raise ValueError(f"{name}: producer rate {d.get('rate_hz')} Hz is below the sim's {SIM_FPS} FPS")
        rows = sorted((int(p.stem), p) for p in (self.dir / "events").glob("*.json") if p.stem.isdigit())
        self.seqs, self.times, self.paths = [], [], []
        for seq, path in rows:
            event = _json(path)
            stamp = event.get("reference_timestamp" if self.arm else "timestamp")  # an arm's event is complete at its (later) reference stamp
            if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or (self.times and stamp < self.times[-1]):
                raise ValueError(f"{name}: event {seq} has no finite, non-decreasing timestamp")
            self.seqs.append(seq), self.times.append(float(stamp)), self.paths.append(path)

    def at(self, t):
        """(index, timestamp) of the last event at or before t, or None."""
        i = bisect_right(self.times, t + EPS_S) - 1
        return None if i < 0 else (i, self.times[i])

    def event(self, i):
        """The event with its identity and payload checked against the descriptor; ValueError when it is not trustworthy."""
        event, d = _json(self.paths[i]), self.descriptor
        if event.get("schema") != (ARM_SCHEMA if self.arm else CAMERA_SCHEMA) or event.get("sequence") != self.seqs[i]:
            raise ValueError(f"{self.name} event {self.seqs[i]}: schema or sequence differs")
        if any(event.get(k) != d.get(k) for k in (ARM_FROZEN if self.arm else CAMERA_FROZEN)):
            raise ValueError(f"{self.name} event {self.seqs[i]}: identity differs from the descriptor (producer restart?)")
        if self.arm:
            for key in ("state", "accepted_reference"):
                v = event.get(key)
                if not isinstance(v, list) or len(v) != len(inputs.JOINTS) or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
                    raise ValueError(f"{self.name} event {self.seqs[i]}: {key} is not six finite values")
        else:
            jpeg = self.paths[i].with_suffix(".jpg").read_bytes()
            if hashlib.sha256(jpeg).hexdigest() != event.get("jpeg_sha256"):
                raise ValueError(f"{self.name} event {self.seqs[i]}: JPEG sha256 differs")
            event["_jpeg"] = jpeg
        return event


def to_sim(values, rule) -> list[float]:
    """Six follower values (joint1..5, gripper 0..100) -> the sim's five radians and jaw angle, as the cell's shadow inputs do."""
    body = inputs.to_radians(list(values))
    return [body[name] for name in inputs.JOINTS[:5]] + [inputs.sim_gripper(float(values[5]), rule)]


def decode(jpeg: bytes):
    import cv2

    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)  # BGR, like the cell's own frames
    if image is None:
        raise ValueError("JPEG does not decode")
    return inputs._rgb(image)


def windows_from_attempts(rows, wall_to_monotonic_s, *, arm=None, goal_sites=None, site_map=None):
    """Carry windows from one arm's attempts.jsonl rows (`cell_attempts`): t_start/t_end are wall clock, the producers' stamps are
    `time.monotonic()`, so the caller states the offset (monotonic - wall at one moment on the cell PC). With `goal_sites` (the sim's sorted
    site names) and `site_map` (cell site -> sim site) every window gets `cell_act_inputs.goal`'s site goal of this arm's carry."""
    from types import SimpleNamespace

    binding = SimpleNamespace(goal_size=2 * (1 + 2 * len(goal_sites)), goal_mode="site", goal_sites=tuple(goal_sites)) if goal_sites else None
    out = []
    for row in rows:
        window = {"episode_id": row["attempt_id"], "t_start": row["t_start"] + wall_to_monotonic_s, "t_end": row["t_end"] + wall_to_monotonic_s,
                  "outcome": row.get("outcome")}
        if binding:
            window["goal"] = [float(v) for v in inputs.goal({"site_map": site_map or {}}, binding, arm, row["from"], row["to"])]
        out.append(window)
    return out


def plan(streams, window):
    """(kept ticks as {name: event index}, dropped counts by reason, number of ticks) of one window."""
    ticks = math.floor((window["t_end"] - window["t_start"]) * SIM_FPS + EPS_S) + 1
    kept, dropped = [], Counter()
    for k in range(ticks):
        t, picks, stamps, reason = window["t_start"] + k / SIM_FPS, {}, [], None
        for name, stream in streams.items():
            hit = stream.at(t)
            if hit is None:
                reason = "no_event"
            elif t - hit[1] > MAX_AGE_S + EPS_S:
                reason = "stale"
            else:
                picks[name] = hit[0]
                stamps.append(hit[1])
            if reason:
                break
        if not reason and max(stamps) - min(stamps) > MAX_SKEW_S + EPS_S:
            reason = "skew"
        if not reason:
            try:
                for name, i in picks.items():
                    streams[name].event(i)
            except (OSError, ValueError):
                reason = "bad_event"
        if reason:
            dropped[reason] += 1
        else:
            kept.append((k, picks))
    return kept, dropped, ticks


def _verdict(window, kept, dropped, ticks):
    """Why a carry is not kept, or None."""
    if window.get("outcome") not in SUCCESS:
        return f"outcome {window.get('outcome')!r} is not a success"
    if len(kept) < MIN_FRAMES:
        return f"only {len(kept)} usable frames"
    if sum(dropped.values()) > MAX_DROP_FRACTION * ticks:
        return f"{sum(dropped.values())} of {ticks} ticks dropped ({dict(dropped)})"
    longest = max(b - a - 1 for a, b in zip([-1, *[k for k, _ in kept]], [*[k for k, _ in kept], ticks]))
    return f"a hole of {longest} ticks" if longest > MAX_GAP_FRAMES else None


def export(source_root, windows, output, *, ids=None, rules=None, goal_mode=None, goal_sites=None, repo_id="rosy/omx-two-arm") -> dict:
    """Write the successful carries of `windows` as episodes of a new dataset at `output`; the meta is also `<output>.steps.json`.
    A window is {episode_id, t_start, t_end, outcome[, goal]} on the producers' monotonic clock."""
    output = Path(output).resolve()
    if output.exists() or in_source_checkout(output):
        raise ValueError("export needs a new directory outside the source checkout")
    ids = {**SOURCES, **(ids or {})}
    streams = {name: Stream(Path(source_root) / ids[name], name) for name in SOURCES}
    domains = {s.descriptor.get("clock_domain") for s in streams.values()}
    if len(domains) != 1 or None in domains:
        raise ValueError(f"the six producers must share one clock domain, got {sorted(map(str, domains))}")
    rules = rules or {arm: streams[arm].descriptor.get("grip_rule") for arm in inputs.ARMS}
    if not all(isinstance(r, dict) and {"held_30mm", "gap_mm_per_unit"} <= set(r) for r in rules.values()):
        raise ValueError("each arm needs its gripper rule (descriptor grip_rule or rules=)")
    if not windows:
        raise ValueError("no carry windows given")
    goals = [w.get("goal") for w in windows]
    if any(g is None for g in goals) != all(g is None for g in goals) or len({len(g) for g in goals if g is not None}) > 1:
        raise ValueError("windows must all carry a goal of one size, or none")
    size = len(goals[0]) if goals[0] is not None else None
    if bool(size) != bool(goal_mode) or goal_mode not in (None, *helpers.GOAL_MODES):
        raise ValueError("goal_mode (joints|site) goes with window goals, and only with them")
    features = helpers.dataset_features(inputs.JOINT_NAMES, inputs.VIEWS, size)
    dataset, accepted, rejected = None, [], []
    try:
        for window in windows:
            kept, dropped, ticks = plan(streams, window)
            why = _verdict(window, kept, dropped, ticks)
            if why is None and dataset is None:
                from lerobot.datasets.lerobot_dataset import LeRobotDataset

                dataset = LeRobotDataset.create(repo_id, SIM_FPS, root=output, robot_type="omx_follower_pair", features=features)
            if why is None:
                try:
                    for _, picks in kept:
                        e = {n: streams[n].event(i) for n, i in picks.items()}
                        row = {"observation.state": np.asarray([v for a in inputs.ARMS for v in to_sim(e[a]["state"], rules[a])], np.float32),
                               "action": np.asarray([v for a in inputs.ARMS for v in to_sim(e[a]["accepted_reference"], rules[a])], np.float32),
                               **{f"observation.images.{v}": decode(e[v]["_jpeg"]) for v in inputs.VIEWS}, "task": helpers.PROMPT}
                        if size:
                            row[helpers.GOAL] = np.asarray(window["goal"], np.float32)
                        dataset.add_frame(row)
                except (OSError, ValueError) as error:
                    dataset.clear_episode_buffer()
                    why = f"decode failed ({error})"
            if why is None:
                dataset.save_episode()
                accepted.append({"episode_id": window["episode_id"], "frames": len(kept), "dropped": dict(dropped), "ticks": ticks,
                                 "t_start": window["t_start"], "t_end": window["t_end"]})
            else:
                rejected.append({"episode_id": window["episode_id"], "reason": why})
    finally:
        if dataset is not None:
            dataset.finalize()
    if not accepted and output.exists():
        shutil.rmtree(output, ignore_errors=True)
    meta = {"longest": {}, "spoiled": [], "goal_mode": goal_mode, **({"goal_sites": list(goal_sites)} if goal_sites else {}), "episodes": len(accepted),
            "real": {"schema": SCHEMA, "fps": SIM_FPS, "fps_note": "sim FPS; each producer's latest event at or before the tick is held (no interpolation)",
                     "limits": {"max_age_s": MAX_AGE_S, "max_skew_s": MAX_SKEW_S, "max_drop_fraction": MAX_DROP_FRACTION,
                                "max_gap_frames": MAX_GAP_FRAMES, "min_frames": MIN_FRAMES},
                     "success_outcomes": list(SUCCESS), "accepted": accepted, "rejected": rejected,
                     "dropped_ticks": dict(sum((Counter(a["dropped"]) for a in accepted), Counter())), "clock_domain": domains.pop(), "grip_rules": rules,
                     "sources": {n: {"source_identity": s.descriptor.get("source_identity"), "session_epoch": s.descriptor.get("session_epoch"),
                                     "events": len(s.seqs)} for n, s in streams.items()}}}
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / f"{output.name}.steps.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not accepted:
        raise ValueError(f"no carry was kept: {rejected}")
    return meta


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source_root", type=Path, help="recording source registry with arm_a, arm_b, cam_top, cam_side, cam_a_wrist, cam_b_wrist")
    parser.add_argument("output", type=Path, help="new dataset directory (outside the source checkout)")
    parser.add_argument("--windows", type=Path, help="JSON list of {episode_id, t_start, t_end, outcome[, goal]} on the producers' monotonic clock")
    parser.add_argument("--attempts", type=Path, help="one arm's attempts.jsonl; its rows become the windows (with --arm and --clock-offset)")
    parser.add_argument("--arm", choices=inputs.ARMS)
    parser.add_argument("--clock-offset", type=float, help="monotonic minus wall seconds on the cell PC, for --attempts")
    parser.add_argument("--goal-sites", help="comma-separated sim site names (sorted): give each attempt window its site goal")
    parser.add_argument("--site-map", type=Path, help="JSON {cell site: sim site}, with --goal-sites")
    args = parser.parse_args(argv)
    if bool(args.windows) == bool(args.attempts):
        parser.error("exactly one of --windows and --attempts")
    sites = args.goal_sites.split(",") if args.goal_sites else None
    if args.attempts:
        if args.arm is None or args.clock_offset is None:
            parser.error("--attempts needs --arm and --clock-offset")
        rows = [json.loads(line) for line in args.attempts.read_text(encoding="utf-8").splitlines() if line.strip()]
        windows = windows_from_attempts(rows, args.clock_offset, arm=args.arm, goal_sites=sites, site_map=_json(args.site_map) if args.site_map else None)
    else:
        windows = _json(args.windows)
    meta = export(args.source_root, windows, args.output, goal_mode="site" if sites else ("joints" if windows and windows[0].get("goal") else None),
                  goal_sites=sites)
    print(json.dumps({"episodes": meta["episodes"], "rejected": meta["real"]["rejected"], "dropped_ticks": meta["real"]["dropped_ticks"]}, indent=1))


if __name__ == "__main__":
    main()
