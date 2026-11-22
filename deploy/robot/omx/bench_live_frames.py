"""Publish a sampled preview from the recorder's in-memory observations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from threading import Event, Thread
import time

LIVE_DIR = "ROSY_BENCH_LIVE_DIR"
SAFE_KEY = re.compile(r"[a-zA-Z0-9_.-]+")


class LiveFrames:
    def __init__(self, folder):
        self.folder = folder
        self.latest = None
        self.timestamps = {}
        self.stopped = Event()
        Thread(target=self._run, name="bench-live-frames", daemon=True).start()

    def offer(self, observation):
        # LeRobot supplies a new dict per tick. Keep only its reference.
        self.latest = observation

    def close(self):
        self.stopped.set()

    def _run(self):
        previous = None
        while not self.stopped.wait(0.1):
            observation = self.latest
            if observation is not None and observation is not previous:
                previous = observation
                try:
                    self._encode(observation)
                except Exception:
                    pass  # Preview failure cannot stop the recorder.

    def _encode(self, observation):
        try:
            import cv2
        except ImportError:
            cv2 = None

        timestamp = time.time()
        updated = False
        for key, array in observation.items():
            shape = getattr(array, "shape", ())
            if not SAFE_KEY.fullmatch(key) or len(shape) != 3 or shape[2] != 3 or str(array.dtype) != "uint8":
                continue
            tmp = self.folder / f"{key}.jpg.tmp"
            try:
                if cv2 is not None:
                    h, w = shape[0], shape[1]
                    frame = array
                    if max(h, w) > 640:
                        if w >= h:
                            w2, h2 = 640, max(1, int(round(h * 640 / w)))
                        else:
                            h2, w2 = 640, max(1, int(round(w * 640 / h)))
                        frame = cv2.resize(frame, (w2, h2), interpolation=cv2.INTER_AREA)
                    ok, encoded = cv2.imencode(
                        ".jpg",
                        cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 70],
                    )
                    if not ok:
                        raise RuntimeError("cv2.imencode failed")
                    tmp.write_bytes(encoded.tobytes())
                else:
                    from PIL import Image

                    image = Image.fromarray(array)
                    image.thumbnail((640, 640))
                    image.save(tmp, "JPEG", quality=70)
                os.utime(tmp, (timestamp, timestamp))
                os.replace(tmp, self.folder / f"{key}.jpg")
                self.timestamps[key] = timestamp
                updated = True
            except Exception:
                tmp.unlink(missing_ok=True)
                continue  # One camera may fail while the others keep publishing.
        if updated:
            tmp = self.folder / "meta.json.tmp"
            tmp.write_text(json.dumps(self.timestamps), encoding="utf-8")
            os.replace(tmp, self.folder / "meta.json")


def start_live_frames():
    folder = os.environ.get(LIVE_DIR)
    if folder:
        try:
            return LiveFrames(Path(folder))
        except Exception:
            pass  # Thread startup is optional too.
    return None


def offer_preview(preview, values):
    if preview is not None:
        try:
            preview.offer(values)
        except Exception:
            pass


def preview_reset_loop(preview, kwargs):
    # LeRobot's between-episode loop reads observations without building dataset frames.
    processor = kwargs.get("robot_observation_processor")
    if preview is None or kwargs.get("dataset") is not None or processor is None:
        return

    def process(values):
        observation = processor(values)
        offer_preview(preview, observation)
        return observation

    kwargs["robot_observation_processor"] = process
