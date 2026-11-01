#!/usr/bin/env python3
"""Raw episodes from chunk_runner runs, converted to a LeRobot dataset after the session.

The runner owns the arm loop: anything slow inside a tick (a bus read once stalled it past the guard's 0.5 s bound,
2026-10-25) can turn torque off. So the runner only appends (t, state, action) per tick, and a camera thread copies
the viewer's JPEG bytes to disk; video encoding happens later in `convert`, with no arm attached.

  episode dir:  task.json {task, cameras: {name: url}}  ->  ticks.jsonl, <camera>/<seq>.jpg + <camera>.jsonl, result.json
  convert:      episode_recorder.py convert <episodes root> <dataset root> --repo-id local/<name> [--fps 30]
"""
from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
import urllib.request
from pathlib import Path

NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]


class Cameras(threading.Thread):
    """Polls each camera URL; while an episode is open, every new frame is written with its time."""

    def __init__(self, urls: dict, folder: Path, period_s: float = 1 / 30, fetch=None):
        super().__init__(daemon=True)
        self.urls, self.folder, self.period_s, self.stop_event = urls, folder, period_s, threading.Event()
        self.fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=1).read())
        self.counts = {name: 0 for name in urls}
        self.errors = {name: None for name in urls}  # last fetch error: a stopped camera service answers 503

    def run(self):
        last = {}
        while not self.stop_event.is_set():
            for name, url in self.urls.items():
                try:
                    data = self.fetch(url)
                except OSError as exc:
                    self.errors[name] = str(exc)[:120]
                    continue
                if data == last.get(name):  # the viewer serves the same frame until a new one arrives
                    continue
                last[name], t = data, time.time()
                seq = self.counts[name]
                (self.folder / name).mkdir(parents=True, exist_ok=True)
                (self.folder / name / f"{seq:06d}.jpg").write_bytes(data)
                with (self.folder / f"{name}.jsonl").open("a") as f:
                    f.write(json.dumps({"seq": seq, "t": t}) + "\n")
                self.counts[name] = seq + 1
            self.stop_event.wait(self.period_s)


class Recorder:
    """`episode start <dir>` / `episode save` / `episode drop` in the runner; tick() appends one row per tick."""

    def __init__(self, cameras_factory=None):
        # cameras_factory None: no camera thread in this process. The runner holds the arm loop; a camera thread there
        # (HTTP fetch + JPEG writes at 30 Hz) stalled it past the guard's 0.5 s effort sample and dropped the arm
        # (2026-10-29). The pipeline process records the frames (CameraSession).
        self.folder, self.cameras, self.rows, self.factory = None, None, None, cameras_factory

    @property
    def active(self) -> bool:
        return self.folder is not None

    def command(self, words: list) -> dict:
        if words[:1] == ["start"] and len(words) == 2:
            if self.active:
                raise ValueError(f"episode {self.folder} is still open")
            folder = Path(words[1])
            task = json.loads((folder / "task.json").read_text())
            self.folder, self.rows = folder, (folder / "ticks.jsonl").open("a")
            if self.factory is not None:
                self.cameras = self.factory(task.get("cameras", {}), folder)
                self.cameras.start()
            return {"episode": str(folder)}
        if words in (["save"], ["drop"]) or words[:1] == ["fail"]:
            if not self.active:
                raise ValueError("no open episode")
            counts, errors = (dict(self.cameras.counts), dict(self.cameras.errors)) if self.cameras else ({}, {})
            folder = self.close()
            if words == ["drop"]:  # nothing worth keeping (no motion happened)
                shutil.rmtree(folder, ignore_errors=True)
                return {"episode": str(folder), "kept": False}
            if words[0] == "fail":  # a failed carry is kept as a labelled failure: learning needs the misses too
                result = {"kept": False, "outcome": "failed", "why": " ".join(words[1:]) or "unspecified",
                          "closed": time.time(), "frames": counts}
                (folder / "result.json").write_text(json.dumps(result))
                return {"episode": str(folder), **{k: v for k, v in result.items() if k != "closed"}}
            # an episode without frames from every camera is not training data (2026-10-28: the camera services were
            # stopped by another recording session and every frame request answered 503)
            missing = sorted(name for name, n in counts.items() if n == 0)
            result = {"kept": not missing, "outcome": "success" if not missing else "no frames", "closed": time.time(), "frames": counts}
            if missing:
                result["why"] = {name: errors[name] or "no frame" for name in missing}
            (folder / "result.json").write_text(json.dumps(result))
            return {"episode": str(folder), **{k: v for k, v in result.items() if k != "closed"}}
        raise ValueError("episode start <dir> | episode save | episode fail <why> | episode drop")

    def tick(self, state, action) -> None:
        if self.active:
            self.rows.write(json.dumps({"t": time.time(), "state": [round(v, 3) for v in state],
                                        "action": [round(v, 3) for v in action]}) + "\n")

    def close(self) -> Path:
        folder = self.folder
        if self.cameras is not None:
            self.cameras.stop_event.set()
            self.cameras.join(timeout=2)
        self.rows.close()
        self.folder = self.cameras = self.rows = None
        return folder


class CameraSession:
    """Frames for one episode, captured in the caller's process (the pipeline), never in the arm runner."""

    def __init__(self, folder: Path, urls: dict, factory=Cameras):
        self.folder, self.cams = Path(folder), factory(urls, Path(folder))
        self.cams.start()

    def finish(self) -> dict:
        """Stop, then record the frame counts in result.json; a camera with no frame makes the episode not kept."""
        self.cams.stop_event.set()
        self.cams.join(timeout=3)
        path = self.folder / "result.json"
        result = json.loads(path.read_text()) if path.exists() else {}
        result["frames"] = dict(self.cams.counts)
        missing = sorted(n for n, k in self.cams.counts.items() if k == 0)
        if missing and result.get("kept"):
            result.update(kept=False, outcome="no frames", why={n: self.cams.errors.get(n) or "no frame" for n in missing})
        if path.parent.exists():
            path.write_text(json.dumps(result))
        return result


def aligned(ticks: list, frames: dict) -> list:
    """Each tick with the latest frame of every camera taken at or before it; ticks before a camera's first frame
    are dropped (a policy must not learn from a missing image)."""
    out, idx = [], {name: 0 for name in frames}
    for row in ticks:
        picked = {}
        for name, rows in frames.items():
            i = idx[name]
            while i + 1 < len(rows) and rows[i + 1]["t"] <= row["t"]:
                i += 1
            idx[name] = i
            if not rows or rows[i]["t"] > row["t"]:
                break
            picked[name] = rows[i]["seq"]
        else:
            out.append((row, picked))
    return out


def convert(episodes: Path, root: Path, repo_id: str, fps: int, image_names: dict, outcome: str = "success") -> int:
    import cv2
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    def chosen(result: dict) -> bool:  # successes and labelled failures go to separate datasets, never one
        has_frames = all(n > 0 for n in result.get("frames", {}).values()) if "frames" in result else result.get("kept")
        return result.get("outcome", "success" if result.get("kept") else None) == outcome and has_frames

    kept = sorted(p.parent for p in episodes.glob("*/result.json") if chosen(json.loads(p.read_text())))
    # shapes are tuples: LeRobot compares a frame's array shape to them (a list [6] failed every frame, 2026-10-28)
    features = {"action": {"dtype": "float32", "shape": (6,), "names": NAMES},
                "observation.state": {"dtype": "float32", "shape": (6,), "names": NAMES}}
    for feature in image_names.values():
        features[f"observation.images.{feature}"] = {"dtype": "video", "shape": (480, 640, 3),
                                                     "names": ["height", "width", "channels"]}
    ds = LeRobotDataset.create(repo_id, fps, features, root=root, robot_type="omx_follower", use_videos=True,
                               image_writer_threads=4)
    for folder in kept:
        task = json.loads((folder / "task.json").read_text())["task"]
        ticks = [json.loads(line) for line in (folder / "ticks.jsonl").read_text().splitlines() if line]
        frames = {name: [json.loads(line) for line in (folder / f"{name}.jsonl").read_text().splitlines() if line]
                  for name in image_names}
        for row, seqs in aligned(ticks, frames):
            frame = {"observation.state": np.asarray(row["state"], np.float32),
                     "action": np.asarray(row["action"], np.float32), "task": task}
            for name, feature in image_names.items():
                img = cv2.imread(str(folder / name / f"{seqs[name]:06d}.jpg"))
                frame[f"observation.images.{feature}"] = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            ds.add_frame(frame)
        ds.save_episode()
    ds.finalize()
    return len(kept)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("episodes", type=Path)
    c.add_argument("root", type=Path)
    c.add_argument("--repo-id", required=True)
    c.add_argument("--fps", type=int, default=30)
    c.add_argument("--images", default="top=top,front=front", help="camera=feature pairs (the teleop dataset's names)")
    c.add_argument("--outcome", default="success", choices=["success", "failed"], help="which episodes go in this dataset")
    args = ap.parse_args(argv)
    names = dict(pair.split("=") for pair in args.images.split(","))
    print(convert(args.episodes, args.root, args.repo_id, args.fps, names, args.outcome), "episodes")


if __name__ == "__main__":
    main()
