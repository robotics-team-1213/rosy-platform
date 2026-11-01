"""Shared motion space for the cell's arms: an arm reserves the corridor it is about to sweep, and a reservation
that overlaps another arm's live one is refused, so that arm holds instead of moving into the other.

Both arms are mapped into the top camera's pixels, so that is the shared frame. A reservation is a 0/1 mask of
that view (`cell_corridor.corridor`) with an expiry; it is released after the move and lapses on its own, so a
process that died cannot block the cell. Changes happen under one file lock (2026-11-01: two arms work at once
since the per-arm session lock; zone locks were the plan's first idea, a corridor is the exact space).

    space = Space(Path("~/rosy-omx/space").expanduser())
    held = space.reserve("arm_a", lane, ttl_s=60)   # {"ok": True} or {"ok": False, "with": "arm_b", "overlap_px": n}
    ...move...
    space.release("arm_a")
"""
from __future__ import annotations

import fcntl
import re
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

MARGIN_PX = 12  # about 1 cm at the pallet in the top view: the arms' links are wider than the gripper corridor


class Space:
    def __init__(self, root: Path, margin_px: int = MARGIN_PX, clock=time.time):
        self.root, self.margin_px, self.clock = Path(root), margin_px, clock
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        with (self.root / "space.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _path(self, arm: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", arm):
            raise ValueError(f"arm id {arm!r} is not a plain name")
        return self.root / f"{arm}.npz"

    def live(self) -> dict:
        """{arm: mask} of the reservations not yet expired."""
        out = {}
        for path in self.root.glob("*.npz"):
            with np.load(path) as data:
                if float(data["expires"]) > self.clock():
                    out[path.stem] = data["mask"].astype(bool)
        return out

    def reserve(self, arm: str, mask, ttl_s: float = 60.0) -> dict:
        import cv2

        path = self._path(arm)
        mask = np.asarray(mask, bool)
        grown = cv2.dilate(mask.astype(np.uint8), np.ones((2 * self.margin_px + 1,) * 2, np.uint8)) > 0
        with self._locked():
            for other, theirs in self.live().items():
                if other == arm:
                    continue
                if theirs.shape != mask.shape:  # not comparable: a different view size is not a free space
                    return {"ok": False, "with": other, "reason": "different view size"}
                overlap = int((grown & theirs).sum())
                if overlap:
                    return {"ok": False, "with": other, "overlap_px": overlap}
            np.savez_compressed(path, mask=mask, expires=self.clock() + ttl_s)
        return {"ok": True}

    def release(self, arm: str) -> None:
        with self._locked():
            self._path(arm).unlink(missing_ok=True)
