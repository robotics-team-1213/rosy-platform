#!/usr/bin/env python3
"""What a stop looked like, kept on the control PC as one hashed bundle: every camera about once a second for the last few
seconds and one after, the FK jaw-tip crops at the stop, the trace's tail (with the 1 Hz load) and the stop's own status.

2026-11-07: one still per camera after the fold could not tell a contact from a finished descent; a person reading a 1 fps
sequence misread it too, until FK said where the jaw tip was. A finished pick descent is kept the same way as a control,
since a contact can only be told against what met nothing. The bundles stay here (D-516: the model PC pulls them); the
incident report keeps its two stills. Config `evidence` ({} for the defaults) turns it on. Reads cameras and files only.

  incidents/evidence/<UTC stamp>-<arm>-<stop|control>/manifest.json   rosy.omx-stop-evidence.v1, every file with its sha256
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "rosy.omx-stop-evidence.v1"
PERIOD_S, KEEP_S, AFTER_S, TRACE_ROWS, MAX_BUNDLES = 1.0, 4.0, 1.0, 150, 200  # 30 Hz trace: the last 5 s


class Ring:
    """Every camera every period_s into a window of keep_s + AFTER_S; a camera that fails is a gap, never a stop."""

    def __init__(self, frame, cameras, period_s: float = PERIOD_S, keep_s: float = KEEP_S, clock=time.time, sleep=time.sleep):
        self.frame, self.cameras, self.period_s, self.keep_s, self.clock, self.sleep = frame, list(cameras), period_s, keep_s, clock, sleep
        self.frames, self.gaps, self.stopped, self.lock = deque(), deque(), threading.Event(), threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        import cv2

        while not self.stopped.is_set():
            for camera in self.cameras:
                t = self.clock()
                try:
                    ok, jpeg = cv2.imencode(".jpg", self.frame(camera), [cv2.IMWRITE_JPEG_QUALITY, 80])
                    entry = (self.frames, (t, camera, jpeg.tobytes())) if ok else (self.gaps, (t, camera, "not encodable"))
                except Exception as exc:  # the hub drops: say so in the manifest
                    entry = (self.gaps, (t, camera, str(exc)[:120]))
                with self.lock:
                    entry[0].append(entry[1])
                    for kept in (self.frames, self.gaps):
                        while kept and kept[0][0] < t - self.keep_s - AFTER_S:
                            kept.popleft()
            self.sleep(self.period_s)

    def window(self, since: float) -> tuple[list, list]:
        with self.lock:
            return [f for f in self.frames if f[0] >= since], [g for g in self.gaps if g[0] >= since]

    def close(self) -> None:
        self.stopped.set()


def write(folder: Path, kind: str, arm: str, at: float, frames: list, gaps: list, extra: dict, files: dict | None = None) -> Path:
    """One bundle: frames named <camera>-<t from the stop>.jpg, extra files, and the manifest with every file's sha256.
    Only the newest MAX_BUNDLES of a kind stay."""
    stamp, n = f"{datetime.fromtimestamp(at, timezone.utc):%Y%m%dT%H%M%S%fZ}", 0
    folder.mkdir(parents=True, exist_ok=True)
    while True:  # two bundles in one microsecond took one name, and the second was lost (found by its test)
        out = folder / f"{stamp}{f'.{n}' if n else ''}-{arm}-{kind}"
        try:
            out.mkdir()
            break
        except FileExistsError:
            n += 1
    listed = []
    for t, camera, jpeg in frames:
        name = f"{camera}-{t - at:+.1f}.jpg"
        (out / name).write_bytes(jpeg)
        listed.append({"file": name, "camera": camera, "t_rel_s": round(t - at, 2), "sha256": hashlib.sha256(jpeg).hexdigest()})
    for name, data in (files or {}).items():
        (out / name).write_bytes(data)
        listed.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"schema": SCHEMA, "kind": kind, "arm": arm, "at": at, "files": listed,
                "gaps": [{"camera": c, "t_rel_s": round(t - at, 2), "why": why} for t, c, why in gaps], **extra}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    for old in sorted(folder.glob(f"*-{kind}"))[:-MAX_BUNDLES]:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    return out


def trace_tail(arm: str, rows: int = TRACE_ROWS) -> bytes:
    """The newest trace's last rows, as the session script writes it into the working folder (cell_recovery reads the same)."""
    # shortcut: the newest trace in the working folder; upgrade if a run ever starts elsewhere
    traces = sorted(Path(".").glob(f"trace-{arm}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return "\n".join(traces[-1].read_text(errors="replace").splitlines()[-rows:]).encode() if traces else b""
