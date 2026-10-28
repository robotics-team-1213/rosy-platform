"""Admit source-expiring route priors and ordered invalidation from one CORE."""

import math
import time

from core_common.protocol.lane_route_guide import LaneRouteGuide


def subscribe_route_guide(node, message_type):
    """Bind the sole route-guide topic to ordered admission using node source time."""
    node.create_subscription(message_type, 'line/lane_guide',
                             lambda message: node._lane_guide.receive(message.data, node._stamp()), 10)


class LaneRouteGuideInput:
    def __init__(self, clock=time.monotonic):
        self._epoch, self._seq, self._guide = None, -1, None
        self._retired = set()
        self._frame = None
        self._clock, self._disabled = clock, False
        self._source_stamp, self._deadline = None, 0.
        self.generation = 0

    def receive(self, raw, now_s):
        previous, epoch = self._guide, self._epoch
        self._receive(raw, now_s)
        if (previous is not None and self._guide is None) or epoch != self._epoch:
            self.generation += 1

    def _receive(self, raw, now_s):
        if self._disabled:
            return
        try:
            message = LaneRouteGuide.model_validate_json(raw)
        except ValueError:
            self._guide = None
            return
        if type(now_s) not in (int, float) or not math.isfinite(now_s):
            self._guide = None
            return
        epoch = message.publisher_epoch
        if epoch in self._retired:
            return
        if self._epoch is not None and epoch != self._epoch:
            # A new CORE announces itself with a clear. Never let queued data
            # silently replace a live publisher or revive a retired publisher.
            self._guide = None
            if len(self._retired) >= 64:
                self._disabled = True
                return
            if message.guide is not None:
                return
            self._retired.add(self._epoch)
            self._seq, self._frame = -1, None
            self._source_stamp, self._deadline = None, 0.
        self._epoch = epoch
        if message.seq <= self._seq:
            return
        self._seq, self._guide = message.seq, None
        guide = message.guide
        if guide is not None and guide.source_stamp_s <= now_s < guide.valid_until_s:
            if self._source_stamp is not None and guide.source_stamp_s < self._source_stamp:
                return
            deadline = self._clock() + guide.valid_until_s - now_s
            # Repeated publications of one source sample cannot restart a local
            # budget while ROS time pauses. Keep this across clears/expiry too.
            self._deadline = min(self._deadline, deadline) if self._source_stamp == guide.source_stamp_s else deadline
            self._source_stamp = guide.source_stamp_s
            self._guide = guide

    def for_frame(self, stamp_s):
        if (type(stamp_s) not in (int, float) or not math.isfinite(stamp_s)
                or (self._frame is not None and stamp_s < self._frame)):
            self._guide = None
            return None
        self._frame = stamp_s
        guide = self._guide
        if (guide is None or self._clock() >= self._deadline
                or not guide.source_stamp_s <= stamp_s < guide.valid_until_s):
            self._guide = None
            return None
        return guide
