from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading
import time
import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))


def test_attempt_video_keeps_source_frames_and_records_gaps(tmp_path):
    video = importlib.import_module("cell_task_video")
    captured = threading.Event()

    class Camera:
        def __init__(self):
            self.seq = {"top": 0, "side": 0}

        def frame_receipt(self, role, *, previous=None):
            if role == "side":
                raise TimeoutError("side camera unavailable")
            self.seq[role] += 1
            raw = b"\xff\xd8" + str(self.seq[role]).encode()
            captured.set()
            return {"camera": role, "jpeg_bytes": raw,
                    "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_seq": self.seq[role], "source_stamp": time.time()}

    recording = video.AttemptVideo(Camera(), tmp_path, "task-1", "run-1", "lease-1",
                                   interval_s=0.01, max_cycles=20)
    recording.start()
    assert recording.status == "partial"
    assert captured.wait(2)
    result = recording.stop()
    rows = [json.loads(line) for line in Path(result["manifest"]).read_text().splitlines()]
    assert rows[0]["task_id"] == "task-1" and rows[0]["run_id"] == "run-1"
    assert rows[0]["handoff_lease_id"] == "lease-1"
    frames = [row for row in rows if row.get("kind") == "frame"]
    assert frames and frames[0]["camera"] == "top"
    assert Path(frames[0]["path"]).read_bytes() == b"\xff\xd81"
    assert any(row.get("kind") == "gap" and row.get("camera") == "side" for row in rows)
    assert result["status"] == "partial"


def test_attempt_video_with_no_valid_frames_is_not_complete(tmp_path):
    video = importlib.import_module("cell_task_video")

    class Camera:
        def frame_receipt(self, role, *, previous=None):
            raise TimeoutError("camera unavailable")

    recording = video.AttemptVideo(Camera(), tmp_path, "task-2", "run-2", "lease-2",
                                   interval_s=0, max_cycles=1)
    recording.start()
    recording.thread.join(timeout=2)
    result = recording.stop()
    assert result["status"] == "no_frames"
    assert result["frame_count"] == {"top": 0, "side": 0}


def test_recorder_start_rejects_failed_first_cycle(tmp_path):
    video = importlib.import_module("cell_task_video")

    class Broken(video.AttemptVideo):
        def _record(self):
            self.status = "recording_error:OSError"
            self.first_cycle.set()

    recording = Broken(object(), tmp_path, "task-3", "run-3", "lease-3")
    with pytest.raises(OSError, match="source frame series"):
        recording.start()
