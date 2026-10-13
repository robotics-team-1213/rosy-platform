"""Which evidence row is live on one keep frame (D-611).

The way-finder still steers. This module only names the source. A fresh learned
lane mask is the paint. The frame the mask is missing uses the glare-reduced
mask at once, and the learned mask must be fresh for LANE_RETURN_FRAMES frames
before it takes the paint back, so the two sources do not trade every frame.

The brightness threshold is not a driving fallback. Crosswalk extent stays in
the keeper (stripes, else the class mask). A stop-line class and an obstacle
box only add a report. The signal row is the HSV observer and never a go.
"""

from __future__ import annotations


#: Fresh learned frames required before paint returns from the glare fallback.
LANE_RETURN_FRAMES = 2


class EvidenceModes:
    """Latch for one line observer. `lane` is none, learned, denoise, or threshold."""

    def __init__(self) -> None:
        self.lane = "none"
        self._return = 0

    def reset(self) -> None:
        self.lane = "none"
        self._return = 0

    def choose_lane(self, *, armed: bool, model_fresh: bool, learned_ok: bool,
                    denoise_ok: bool, unarmed: str = "threshold") -> str:
        """The paint source for this frame. `armed` means a learned model is the
        configured source. An unarmed observer stays on `unarmed` (threshold or denoise)."""
        if not armed:
            self.lane = unarmed
            self._return = 0
            return unarmed
        fresh = bool(model_fresh and learned_ok)
        if fresh and self.lane != "denoise":
            self.lane = "learned"
            self._return = 0
            return "learned"
        if fresh:
            self._return += 1
            if self._return >= LANE_RETURN_FRAMES:
                self.lane = "learned"
                self._return = 0
                return "learned"
            return "denoise" if denoise_ok else "none"
        self._return = 0
        self.lane = "denoise" if denoise_ok else "none"
        return self.lane

    def rows(self, *, crosswalk: bool, stop_line: bool, obstacle: bool) -> dict:
        """The five evidence rows. `obstacle` true adds a hold. It never clears one.
        `signal` is always the HSV observer."""
        return {
            "lane": self.lane,
            "crosswalk": "reported" if crosswalk else "none",
            "stop_line": "class" if self.lane == "learned" and stop_line else "none",
            "obstacle": "hold" if obstacle else "metric",
            "signal": "hsv",
        }
