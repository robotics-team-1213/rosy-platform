"""Conservative ten-second wire-rate samples from the configured robot NIC.

Includes both directions and traffic other than video. Media may shed load;
this sampler never changes NIC settings or throttles control traffic.
"""

from collections import deque
import math
from pathlib import Path
import re


class WireSampler:
    def __init__(self, interface, *, root=Path('/sys/class/net')):
        if (not isinstance(interface, str) or interface in ('.', '..')
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface)):
            raise ValueError('a configured NIC name, not a path, is required')
        self._path = Path(root) / interface / 'statistics'
        self._samples = deque(maxlen=128)
        self._rate = None
        self.window_seconds = 0

    def _unknown(self):
        self._samples.clear()
        self._rate, self.window_seconds = None, 0
        return None

    def sample(self, *, now):
        if type(now) not in (float, int) or not math.isfinite(now) or now < 0:
            return self._unknown()
        try:
            counts = [int((self._path / name).read_text().strip()) for name in ('tx_bytes', 'rx_bytes')]
            if any(value < 0 or value >= 2**64 for value in counts):
                return self._unknown()
        except (OSError, ValueError):
            return self._unknown()
        total = sum(counts)
        if self._samples:
            last_time, last_total = self._samples[-1]
            if now <= last_time or total < last_total:
                self._unknown()
            elif now - last_time < .1:
                return self._rate
        self._samples.append((now, total))
        while len(self._samples) > 2 and self._samples[1][0] <= now - 10:
            self._samples.popleft()
        span = now - self._samples[0][0]
        if span <= 0:
            return None
        self.window_seconds = min(10, span)
        # Include the boundary sample's entire byte delta rather than inventing
        # unobserved sub-sample timing; this overestimates instead of hiding bursts.
        self._rate = 8 * (total - self._samples[0][1]) / self.window_seconds
        return self._rate
