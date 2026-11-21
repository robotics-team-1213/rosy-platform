"""OMX demonstration admission gate: only intact, correctly named, labelled and declared episodes reach training.

Adds what `native_review.inspect_frames` cannot see (it reads frames by timestamp, so a dropped or duplicated video
frame comes back as its nearest neighbour): camera role names (D-1065), decoded video frames against the joint rows
(1:1 by presentation time), black and frozen camera runs, joint/gripper ranges in the sim contract, the start pose,
the goal label, and per-source provenance (a fixed-layout source may not enter a randomized training set; fixed
h1 demonstrations left an arm unable to reach the container, 2026-11-21). Episode rules reject or send to review;
`gate` writes `gate-receipt.json` with the dataset file hashes, and `check_receipt` is what a training entrypoint
calls before it reads the dataset. Read only: never edits a dataset.

    python learning/curation/omx/data_gate.py gate <dataset> --arm arm_b --source kind=sim,layout=random [--legacy rs=top]
    python learning/curation/omx/data_gate.py check <dataset>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ROLES = ("top", "side", "wrist")  # D-1065 cell A/B roles
LEGACY_TABLE = {"rs": "top"}  # 11-20~21 sim/mix data called the D435 rs (D-1065 §4); a real Purple-SY source passes its own map
GOAL_RE = re.compile(r"from \S+ to (ship-h1r[0-2]-l[0-2]|tray)\.$")
HOME = {"arm_a": (0.023, -1.965, 1.666, 1.618, 1.41), "arm_b": (0.023, -1.967, 1.667, 1.626, 1.399)}  # sim radians
LIMITS = dict(home_review_rad=0.35, black_mean=8.0, black_reject_s=1.0, frozen_diff=0.5, frozen_review_s=3.0,
              min_frames=60, gripper=(0.0, 1.3))
RECEIPT = "gate-receipt.json"
SCHEMA = "rosy.omx-data-gate/1"


def dataset_files(root: Path) -> dict[str, str]:
    files = {}
    for folder in ("meta", "data", "videos"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("dataset links are not accepted")
            if path.is_file():
                with path.open("rb") as stream:
                    files[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return files


def camera_map(features: dict, legacy: dict[str, str]) -> dict[str, str]:
    """observation.images.<name> -> role; refuses names that are neither roles nor in the declared legacy map."""
    out = {}
    for key in features:
        if not key.startswith("observation.images.") or key.endswith("_depth"):
            continue
        name = key.removeprefix("observation.images.")
        role = name if name in ROLES else legacy.get(name)
        if role is None:
            raise ValueError(f"camera {name} is not a role name (D-1065) and has no declared mapping")
        if role in out.values():
            raise ValueError(f"two cameras map to role {role}")
        out[key] = role
    if sorted(out.values()) != sorted(ROLES):
        raise ValueError(f"cameras must cover {list(ROLES)} (D-1065), got {sorted(out.values())}")
    return out


def video_scan(path: Path, t0: float, t1: float, fps: float) -> dict:
    """Decode one episode's span of a video: presentation times, black and frozen runs (seconds)."""
    import av
    import numpy as np
    stamps, black, frozen, run_black, run_frozen, prev = [], 0, 0, 0, 0, None
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        container.seek(int(max(t0 - 1, 0) / stream.time_base), stream=stream, backward=True)
        for frame in container.decode(stream):
            t = float(frame.pts * stream.time_base)
            if t < t0 - 0.5 / fps:
                continue
            if t >= t1 - 0.5 / fps:
                break
            stamps.append(t - t0)
            gray = np.asarray(frame.to_ndarray(format="gray")[::8, ::8], dtype=np.float32)
            run_black = run_black + 1 if gray.mean() <= LIMITS["black_mean"] else 0
            run_frozen = run_frozen + 1 if prev is not None and float(np.abs(gray - prev).mean()) < LIMITS["frozen_diff"] else 0
            black, frozen, prev = max(black, run_black), max(frozen, run_frozen), gray
    return dict(stamps=stamps, black_s=black / fps, frozen_s=frozen / fps)


def episode_verdicts(root: Path, arm: str, legacy: dict[str, str]) -> tuple[dict, list[dict]]:
    import numpy as np
    import pandas as pd
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    fps = float(info["fps"])
    cams = camera_map(info["features"], legacy)
    episodes = pd.concat([pd.read_parquet(f) for f in sorted((root / "meta/episodes").rglob("*.parquet"))]).sort_values("episode_index")
    data = pd.concat([pd.read_parquet(f) for f in sorted((root / "data").rglob("*.parquet"))]).sort_values("index")
    tasks = pd.read_parquet(root / "meta/tasks.parquet")
    task_text = {int(row.task_index): text for text, row in tasks.iterrows()}
    home = np.asarray(HOME[arm])
    rows = []
    for _, ep in episodes.iterrows():
        index = int(ep.episode_index)
        frames = data[data.episode_index == index].sort_values("frame_index")
        n = len(frames)
        state, action = (np.stack(frames[k].to_numpy()) for k in ("observation.state", "action"))
        reject, review, measured = [], [], {}
        for key, role in cams.items():
            prefix = f"videos/{key}/"
            path = root / info["video_path"].format(video_key=key, chunk_index=int(ep[prefix + "chunk_index"]),
                                                    file_index=int(ep[prefix + "file_index"]))
            scan = video_scan(path, float(ep[prefix + "from_timestamp"]), float(ep[prefix + "to_timestamp"]), fps)
            stamps = scan["stamps"]
            measured[role] = dict(frames=len(stamps), black_s=round(scan["black_s"], 2), frozen_s=round(scan["frozen_s"], 2))
            if len(stamps) != n:
                reject.append(f"{role}: decoded {len(stamps)} frames for {n} rows")
            elif any(abs(t - i / fps) >= 0.5 / fps for i, t in enumerate(stamps)):
                reject.append(f"{role}: frame times do not match the rows one to one")
            if scan["black_s"] >= LIMITS["black_reject_s"]:
                reject.append(f"{role}: black for {scan['black_s']:.1f} s")
            moving = float(np.abs(np.diff(action[:, :5], axis=0)).sum()) > 0.05
            if moving and scan["frozen_s"] >= LIMITS["frozen_review_s"]:
                review.append(f"{role}: unchanged for {scan['frozen_s']:.1f} s while the arm moves")
        if not (np.isfinite(state).all() and np.isfinite(action).all()):
            reject.append("non-finite state or action")
        elif np.abs(np.concatenate([state[:, :5], action[:, :5]])).max() > math.pi + 0.05:
            reject.append("joint outside +-pi: not sim radians")
        lo, hi = LIMITS["gripper"]
        if not (lo <= float(min(state[:, 5].min(), action[:, 5].min())) and float(max(state[:, 5].max(), action[:, 5].max())) <= hi):
            reject.append("gripper outside the sim gripper range")
        start = float(np.abs(state[0, 1:4] - home[1:4]).max()) if n else math.inf
        measured["start_from_home_rad"] = round(start, 3)
        if start > LIMITS["home_review_rad"]:
            review.append(f"start {start:.2f} rad from home (joints 2-4)")
        goal = GOAL_RE.search(task_text.get(int(frames.task_index.iloc[0]), "")) if n else None
        if goal is None:
            reject.append("goal not readable from the task text")
        if n < LIMITS["min_frames"]:
            reject.append(f"{n} frames, under {LIMITS['min_frames']}")
        rows.append(dict(episode_index=index, frames=n, goal=goal.group(1) if goal else None,
                         verdict="reject" if reject else "review" if review else "pass",
                         reject=reject, review=review, measured=measured))
    return dict(fps=fps, cameras=cams), rows


def gate(root, arm: str, source: dict, legacy: dict[str, str] | None = None, training_layout: str = "random") -> dict:
    """Judge every episode and the source declaration; write gate-receipt.json next to meta/."""
    root = Path(root).resolve()
    if arm not in HOME:
        raise ValueError(f"unknown arm {arm}")
    if source.get("kind") not in ("sim", "real") or source.get("layout") not in ("random", "fixed"):
        raise ValueError("source must declare kind=sim|real and layout=random|fixed")
    legacy = dict(LEGACY_TABLE, **(legacy or {}))
    before = dataset_files(root)
    meta, rows = episode_verdicts(root, arm, legacy)
    dataset = []
    if training_layout == "random" and source["layout"] == "fixed":
        dataset.append("fixed-layout source in a randomized training set: evaluation only")
    if dataset_files(root) != before:
        raise ValueError("dataset changed while it was inspected")
    goals = sorted({r["goal"] for r in rows if r["verdict"] == "pass" and r["goal"]})
    receipt = dict(schema=SCHEMA, arm=arm, source=source, legacy_names=legacy, cameras=meta["cameras"], fps=meta["fps"],
                   limits=LIMITS, dataset_reject=dataset, goals_passing=goals,
                   counts={v: sum(r["verdict"] == v for r in rows) for v in ("pass", "review", "reject")},
                   episodes=rows, files=before, approved_reviews=[])
    (root / RECEIPT).write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


def check_receipt(root, receipt_path=None) -> list[int]:
    """The episodes a trainer may read: refuses a missing or stale receipt, a dataset-level reject, or open reviews."""
    root = Path(root).resolve()
    path = Path(receipt_path) if receipt_path else root / RECEIPT
    if not path.is_file():
        raise ValueError(f"no {RECEIPT}: run data_gate.py gate first")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != SCHEMA:
        raise ValueError("unknown gate receipt schema")
    if dataset_files(root) != receipt["files"]:
        raise ValueError("dataset files differ from the gated ones: gate again")
    if receipt["dataset_reject"]:
        raise ValueError("dataset rejected: " + "; ".join(receipt["dataset_reject"]))
    approved = {a["episode_index"] for a in receipt.get("approved_reviews", []) if a.get("reviewer") and a.get("reason")}
    open_reviews = [r["episode_index"] for r in receipt["episodes"] if r["verdict"] == "review" and r["episode_index"] not in approved]
    if open_reviews:
        raise ValueError(f"episodes waiting for review: {open_reviews}")
    return [r["episode_index"] for r in receipt["episodes"]
            if r["verdict"] == "pass" or (r["verdict"] == "review" and r["episode_index"] in approved)]


def _pairs(text: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in text.split(",") if item) if text else {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("dataset"); g.add_argument("--arm", required=True); g.add_argument("--source", required=True)
    g.add_argument("--legacy", default=""); g.add_argument("--training-layout", default="random", choices=("random", "fixed"))
    c = sub.add_parser("check")
    c.add_argument("dataset")
    args = parser.parse_args(argv)
    if args.cmd == "gate":
        r = gate(args.dataset, args.arm, _pairs(args.source), _pairs(args.legacy), args.training_layout)
        print(json.dumps(dict(counts=r["counts"], dataset_reject=r["dataset_reject"]), ensure_ascii=False))
    else:
        print(json.dumps(dict(episodes=check_receipt(args.dataset))))


if __name__ == "__main__":
    main()
