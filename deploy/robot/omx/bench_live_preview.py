"""Recording-session preview directories and device-to-viewer bindings."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import time

from bench_live_frames import LIVE_DIR, SAFE_KEY
from omx_devices import role_env

SHM = Path("/dev/shm")


def _device_key(device):
    if isinstance(device, int):
        device = f"/dev/video{device}"
    return os.path.realpath(device) if isinstance(device, str) and device.startswith("/dev/") else None


def camera_labels(robot):
    """Map viewer labels to recorder keys by the configured capture device."""
    from cell_upkeep import viewer_labels

    labels = viewer_labels()
    roles = role_env(Path.home() / ".config/rosy")
    devices = {}
    for key, cfg in (robot.get("cameras") or {}).items():
        device = _device_key(cfg.get("index_or_path")) if isinstance(cfg, dict) else None
        if device and SAFE_KEY.fullmatch(key):
            devices[device] = key if device not in devices else None  # ambiguous binding
    result = {}
    for role, env in roles.items():
        if not role.startswith("camera-"):
            continue
        key = devices.get(_device_key(env.get("ROSY_CAMERA_DEVICE", "").strip("\"'")))
        if key is None:
            continue
        matches = [label for label, topic in labels.items() if topic == env.get("ROSY_CAMERA_TOPIC", "").strip("\"'")]
        for label in matches or [role.removeprefix("camera-")]:
            result[label] = key
    return result


def _fresh(mtime):
    return 0 <= time.time() - mtime <= 2


class SessionPreview:
    def __init__(self, session_folder, robot):
        self.labels = camera_labels(robot)
        try:
            self.folder = Path(tempfile.mkdtemp(prefix="rosy-bench-live-", dir=SHM))
        except OSError:
            self.folder = Path(tempfile.mkdtemp(prefix=".live-", dir=session_folder.resolve()))

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def frame(self, label):
        key = self.labels.get(label)
        if key is not None:
            try:
                with (self.folder / f"{key}.jpg").open("rb") as stream:
                    if _fresh(os.fstat(stream.fileno()).st_mtime):
                        return stream.read()
            except OSError:
                pass  # First frame or cleanup can race the HTTP request.
        return None

    def fresh_cameras(self):
        cameras = {}
        for label, key in self.labels.items():
            try:
                if _fresh((self.folder / f"{key}.jpg").stat().st_mtime):
                    cameras[label] = {"fresh": True, "quality": {}}
            except OSError:
                continue
        return cameras


def open_preview(folder, robot):
    try:
        return SessionPreview(folder, robot)
    except Exception:
        return None  # A broken preview binding or temp directory must leave recording available.


def recorder_env(preview, link_dir=None):
    env = os.environ.copy()
    env.pop(LIVE_DIR, None)
    env.pop("ROSY_LINK_DIR", None)
    if link_dir is not None:  # a linked session (W16): the recorder waits ready between episodes and reads its requests from this folder
        env["ROSY_LINK_DIR"] = str(link_dir)
    if preview is not None:
        env[LIVE_DIR] = str(preview.folder)
    return env
