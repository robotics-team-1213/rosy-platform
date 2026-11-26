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

    def __init__(self, frame, cameras, period_s: float = PERIOD_S, keep_s: float = KEEP_S, clock=time.time, sleep=time.sleep, frame_receipt=None):
        self.frame, self.cameras, self.period_s, self.keep_s, self.clock, self.sleep = frame, list(cameras), period_s, keep_s, clock, sleep
        self.frame_receipt = frame_receipt
        self.frames, self.frame_meta, self.gaps, self.stopped, self.lock = deque(), deque(), deque(), threading.Event(), threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def _capture_camera(self, camera: str, last_seq: dict[str, int]):
        if self.frame_receipt is not None:
            rec = self.frame_receipt(camera)
            seq = rec.get("source_seq") if isinstance(rec, dict) else None
            stamp = rec.get("source_stamp") if isinstance(rec, dict) else None
            seq_val = seq if isinstance(seq, int) and not isinstance(seq, bool) else None
            stamp_val = float(stamp) if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None
            if seq_val is not None and last_seq.get(camera) == seq_val:
                return None, None
            raw = rec.get("jpeg_bytes") if isinstance(rec, dict) else None
            if raw is None:
                import cv2

                ok, enc = cv2.imencode(".jpg", rec["image"], [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    return False, "not encodable"
                raw = enc.tobytes()
            if seq_val is not None:
                last_seq[camera] = seq_val
            return bytes(raw), (seq_val, stamp_val)
        import cv2

        ok, jpeg = cv2.imencode(".jpg", self.frame(camera), [cv2.IMWRITE_JPEG_QUALITY, 80])
        return (jpeg.tobytes(), (None, None)) if ok else (False, "not encodable")

    def run(self) -> None:
        last_seq: dict[str, int] = {}
        while not self.stopped.is_set():
            for camera in self.cameras:
                t = self.clock()
                try:
                    data, meta = self._capture_camera(camera, last_seq)
                except Exception as exc:  # the hub drops: say so in the manifest (304 / stale recorded as gap)
                    data, meta = False, str(exc)[:120]
                if data is None:
                    continue
                with self.lock:
                    if data is False:
                        self.gaps.append((t, camera, meta))
                    else:
                        self.frames.append((t, camera, data))
                        self.frame_meta.append((t, camera, meta[0], meta[1]))
                    for kept in (self.frames, self.frame_meta, self.gaps):
                        while kept and kept[0][0] < t - self.keep_s - AFTER_S:
                            kept.popleft()
            if self.sleep is time.sleep:
                self.stopped.wait(self.period_s)
            else:
                self.sleep(self.period_s)

    def window(self, since: float) -> tuple[list, list]:
        with self.lock:
            return [f for f in self.frames if f[0] >= since], [g for g in self.gaps if g[0] >= since]

    def window_with_meta(self, since: float) -> tuple[list[dict], list]:
        with self.lock:
            frames = [
                {"t": t, "camera": cam, "jpeg": jpeg, "source_seq": seq, "source_stamp": stamp}
                for (t, cam, jpeg), (_, _, seq, stamp) in zip(self.frames, self.frame_meta)
                if t >= since
            ]
            gaps = [g for g in self.gaps if g[0] >= since]
        return frames, gaps

    def close(self) -> None:
        """Mandatory once the carry ends (transfer_folded does it): the thread polls until then."""
        self.stopped.set()
        self.thread.join(timeout=2 * self.period_s + 10)  # one camera read may take its 10 s timeout


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
    for n, (t, camera, jpeg) in enumerate(frames):
        name = f"{camera}-{t - at:+.1f}-{n}.jpg"  # the index: two frames in one tenth of a second took one name (review)
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


def trace_tail(arm: str, rows: int = TRACE_ROWS, search_dir: Path | None = None) -> bytes:
    """The newest trace's last rows, as the session script writes it into the working folder (cell_recovery reads the same)."""
    # shortcut: the newest trace in the working folder; upgrade if a run ever starts elsewhere
    base = Path(search_dir) if search_dir is not None else Path(".")
    traces = sorted(base.glob(f"trace-{arm}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return "\n".join(traces[-1].read_text(errors="replace").splitlines()[-rows:]).encode() if traces else b""
