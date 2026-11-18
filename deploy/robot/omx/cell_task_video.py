"""Source-stamped frame series for one supervised OMX attempt; never controls the arm."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import cell_attempts
from cell_auto_pick_plan import save_frame_receipt


class AttemptVideo:
    def __init__(self, cell, work: Path, task_id: str, run_id: str, handoff_lease_id: str, *,
                 interval_s: float = 0.5, max_cycles: int = 300):
        self.cell = cell
        self.folder = work / "video" / f"{run_id}-{uuid.uuid4().hex}"
        self.manifest = self.folder / "frames.jsonl"
        self.task_id, self.run_id, self.handoff_lease_id = task_id, run_id, handoff_lease_id
        self.interval_s, self.max_cycles = interval_s, max_cycles
        self.stop_event = threading.Event()
        self.first_cycle = threading.Event()
        self.thread: threading.Thread | None = None
        self.status = "stopped"
        self.frame_count = {"top": 0, "side": 0}
        self.gap_count = 0

    def _append(self, row: dict) -> None:
        with self.manifest.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def start(self):
        self.folder.mkdir(parents=True, exist_ok=False)
        self.manifest.touch(exist_ok=False)
        self._append({"kind": "start", "task_id": self.task_id, "run_id": self.run_id,
                      "handoff_lease_id": self.handoff_lease_id,
                      "host_time": time.time(), "source_clock": "camera_host_not_exposure"})
        cell_attempts._fsync_directory(self.folder)
        cell_attempts._fsync_directory(self.folder.parent)
        self.thread = threading.Thread(target=self._record, daemon=True)
        self.thread.start()
        if not self.first_cycle.wait(25):
            self.stop()
            raise TimeoutError("source frame series did not start")
        if self.status.startswith("recording_error:"):
            self.stop()
            raise OSError("source frame series failed to start")
        return self

    def _record(self) -> None:
        previous = {}
        try:
            for cycle in range(self.max_cycles):
                for camera in ("top", "side"):
                    try:
                        receipt = self.cell.frame_receipt(camera, previous=previous.get(camera))
                        saved = save_frame_receipt(
                            self.folder / f"{cycle:04d}-{camera}.jpg", receipt)
                        cell_attempts._fsync_directory(self.folder)
                        self._append({"kind": "frame", "camera": camera, "cycle": cycle, **saved})
                        self.frame_count[camera] += 1
                        previous[camera] = receipt
                    except Exception as exc:
                        self.gap_count += 1
                        self.status = "partial"
                        self._append({"kind": "gap", "camera": camera, "cycle": cycle,
                                      "error": type(exc).__name__, "host_time": time.time()})
                self.first_cycle.set()
                if self.stop_event.wait(self.interval_s):
                    break
            else:
                self.status = "limit_reached"
            if not any(self.frame_count.values()):
                self.status = "no_frames"
            elif self.status == "stopped" and (self.gap_count or not all(self.frame_count.values())):
                self.status = "partial"
            self._append({"kind": "end", "status": self.status, "frame_count": self.frame_count,
                          "gap_count": self.gap_count, "host_time": time.time()})
        except Exception as exc:
            self.status = f"recording_error:{type(exc).__name__}"
            self.first_cycle.set()

    def stop(self) -> dict:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=30)
        status = "incomplete" if self.thread is not None and self.thread.is_alive() else self.status
        return {"manifest": str(self.manifest), "status": status,
                "frame_count": dict(self.frame_count), "gap_count": self.gap_count,
                "source_clock": "camera_host_not_exposure"}
