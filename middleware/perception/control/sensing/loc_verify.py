"""Subject: the 3 s scan/map check after every pose injection (D-395 §7).

Every injected pose, whatever its source (candidate, overhead, homing_ref,
human), must earn LOCALIZED the same way: after a settle time for AMCL, the
scan/map fit stays at or above `min_fit` on fresh scans for `hold_s`. One low
fit or a scan gap fails it at once, because a held-but-wrong pose is the
dangerous outcome and a retry is cheap.

Limit: on a 180-degree symmetric map the mirror fits exactly as well as the
truth, so this check cannot reject a mirror injection. Arbitration must, and
loc_state requires a scan-asymmetric cue before LOCALIZED.
"""
from __future__ import annotations

import math

PENDING, PASSED, FAILED = 'pending', 'passed', 'failed'


class InjectionCheck:
    def __init__(self, started_s, hold_s=3., settle_s=.5, min_fit=.85, max_gap_s=.5):
        self.started_s = float(started_s)
        self.hold_s, self.settle_s = float(hold_s), float(settle_s)
        self.min_fit, self.max_gap_s = float(min_fit), float(max_gap_s)
        self.last_s = self.started_s
        self.result, self.reason = PENDING, None

    def observe(self, now_s, fit=None):
        """Feed one fresh-scan fit (or None for a tick without a scan); returns the result."""
        if self.result != PENDING:
            return self.result
        # A gap fails the check whether or not this tick brings a scan: one fit
        # after a long silence must not stand in for the whole hold.
        if now_s - self.last_s > self.max_gap_s:
            return self._fail('stale_scan')
        if fit is not None and math.isfinite(fit):
            if now_s >= self.started_s + self.settle_s and fit < self.min_fit:
                return self._fail('fit_low')
            self.last_s = now_s
        if self.last_s >= self.started_s + self.settle_s + self.hold_s:
            self.result = PASSED
        return self.result

    def _fail(self, reason):
        self.result, self.reason = FAILED, reason
        return self.result
