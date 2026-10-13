"""Frame selection: time spacing plus perceptual-hash de-duplication."""
import cv2
import numpy as np


def dhash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


class FrameSelector:
    def __init__(self, min_interval_s: float = 0.5, max_hamming: int = 4):
        self.min_interval_s = min_interval_s
        self.max_hamming = max_hamming
        self._t = None
        self._hash = None

    def accept(self, t: float, bgr: np.ndarray) -> bool:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        h = dhash(gray)
        if self._t is not None:
            if t - self._t < self.min_interval_s:
                return False
            if bin(h ^ self._hash).count("1") <= self.max_hamming:
                return False
        self._t, self._hash = t, h
        return True
