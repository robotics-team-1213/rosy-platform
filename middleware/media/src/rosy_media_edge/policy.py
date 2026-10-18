"""D-789 feedback policy; callers provide a ten-second measured wire rate."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MediaDecision:
    enabled: bool
    fps: int
    bitrate: int
    reset_idr: bool = False
    reason: str = 'fresh'


class MediaPolicy:
    LEVELS = ((15, 800_000), (10, 550_000), (5, 300_000))

    def __init__(self):
        self._level, self._healthy = 0, 0

    def update(self, *, demand_age_s, queue_age_ms, loss_fraction, wire_bps):
        values = (demand_age_s, queue_age_ms, loss_fraction, wire_bps)
        valid = all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in values)
        if not valid or loss_fraction > 1:
            return MediaDecision(False, 5, 300_000, reason='invalid_feedback')
        if demand_age_s > 5:
            return MediaDecision(False, 5, 300_000, reason='demand_stale')
        if queue_age_ms > 200:
            return MediaDecision(False, 5, 300_000, reset_idr=True, reason='encoded_queue_old')
        if wire_bps > 8_000_000 / 6:
            self._level, self._healthy = 2, 0
            return MediaDecision(False, 5, 300_000, reason='wire_budget')
        level = 2 if loss_fraction > .05 else 1 if loss_fraction > .03 else 0
        if level:
            self._level, self._healthy = max(self._level, level), 0
        else:
            self._healthy += 1
            if self._healthy >= 10:
                self._level, self._healthy = max(0, self._level - 1), 0
        fps, bitrate = self.LEVELS[self._level]
        return MediaDecision(True, fps, bitrate)
