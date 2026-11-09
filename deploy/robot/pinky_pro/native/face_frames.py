"""Bounded native character frames with cached GIF compatibility."""
from __future__ import annotations

from pathlib import Path
from typing import Callable


class FaceFrames:
    """D-433/D-922: one face frame, with a small temporal pupil/rest state."""

    def __init__(self, directory: Path, *, opener: Callable, convert: Callable,
                 log, skip: int = 1, render: Callable | None = None):
        self._directory, self._open, self._convert = directory, opener, convert
        self._log, self._skip, self._render = log, skip, render
        self._faces: dict[str, dict] = {}
        self._motion_at = None
        self._gaze = self._gaze_start = self._gaze_target = 0.0
        self._rest = self._rest_start = self._rest_target = 0.0
        self._gaze_at = self._rest_at = 0.0

    @property
    def expressive(self) -> bool:
        return self._render is not None

    def frame_count(self, name: str) -> int:
        return len(self._faces.get(name, {}).get("frames", []))

    def next(self, name: str, *, expression: dict | None = None, now: float | None = None):
        if self._render is not None and expression is not None and now is not None:
            gaze, rest = expression["gaze_x"], float(expression["resting"])
            if self._motion_at is None:
                self._motion_at = self._gaze_at = self._rest_at = now
            if gaze != self._gaze_target:
                self._gaze_start, self._gaze_target, self._gaze_at = self._gaze, gaze, now
            if rest != self._rest_target:
                self._rest_start, self._rest_target, self._rest_at = self._rest, rest, now
            self._gaze = self._gaze_start + (gaze - self._gaze_start) * min(1., max(0., (now - self._gaze_at) / .4))
            self._rest = self._rest_start + (rest - self._rest_start) * min(1., max(0., now - self._rest_at))
            phase = ((now - self._motion_at) / (8 if rest else 2) % 1) * 20
            return self._render(name, phase, self._gaze, self._rest)
        entry = self._faces.get(name)
        if entry is None:
            entry = {"frames": [], "image": None, "done": False, "source": 0, "position": -1}
            try:
                entry["image"] = self._open(self._directory / f"{name}.gif")
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}", f"face {name!r} unavailable ({type(exc).__name__})")
                entry["done"] = True
            self._faces[name] = entry
        if not entry["done"]:
            image = entry["image"]
            try:
                image.seek(entry["source"])
                entry["frames"].append(self._convert(image))
                entry["source"] += self._skip
                entry["position"] = len(entry["frames"]) - 1
                return entry["frames"][-1]
            except EOFError:
                pass
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}-frame", f"face {name!r} frame unreadable ({type(exc).__name__})")
            entry["done"] = True
            entry["image"] = None
            if hasattr(image, "close"):
                image.close()
        if not entry["frames"]:
            return None
        entry["position"] = (entry["position"] + 1) % len(entry["frames"])
        return entry["frames"][entry["position"]]
