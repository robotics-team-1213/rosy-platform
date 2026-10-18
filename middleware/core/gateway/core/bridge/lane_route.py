"""Ordered route-prior publication; ROS I/O stays in RosBridge."""

import math
import time
from uuid import uuid4

from core_common.protocol.lane_route_guide import LaneRouteGuide


class RouteGuidePublication:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._source, self._deadline = None, 0.
        self._reset()

    def _reset(self):
        self._epoch, self._seq = uuid4().hex, -1
        self._announced, self._prior = False, None
        self._ros, self._floor = None, None
        self._at = float('-inf')

    def _message(self, prior, now):
        self._seq += 1
        self._prior, self._at = prior, now
        return LaneRouteGuide(v=1, publisher_epoch=self._epoch, seq=self._seq, guide=prior).model_dump()

    def messages(self, prior, ros_now):
        now, out = self._clock(), []
        valid_clock = isinstance(ros_now, (float, int)) and math.isfinite(ros_now)
        if valid_clock:
            if self._ros is not None and ros_now < self._ros:
                self._reset()
            self._ros = ros_now
        if not self._announced:
            out.append(self._message(None, now))
            self._announced = True
        if (prior is not None and valid_clock
                and prior.source_stamp_s <= ros_now < prior.valid_until_s
                and (self._floor is None or prior.source_stamp_s >= self._floor)):
            deadline = now + prior.valid_until_s - ros_now
            self._deadline = min(self._deadline, deadline) if self._source == prior.source_stamp_s else deadline
            self._source = prior.source_stamp_s
            self._floor = prior.source_stamp_s
            if now >= self._deadline:
                prior = None
        else:
            prior = None
        if prior != self._prior or now - self._at >= .2:
            wire = prior
            if prior is not None:
                until = min(prior.valid_until_s, ros_now + (self._deadline - now))
                wire = prior.model_copy(update={'valid_until_s': until}) if until > prior.source_stamp_s else None
            out.append(self._message(wire, now))
            self._prior = prior  # Cadence compares source input, not a shrinking wire budget.
        return out
