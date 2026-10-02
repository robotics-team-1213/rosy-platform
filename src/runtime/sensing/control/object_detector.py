"""Subject: the ROS-free core of object_detector_node (D-423 §2).

One camera frame in, at most one DetectionEvidence-shaped packet out:
  - the model comes from a ModelSlot (pointer file, hot swap, keep-previous);
  - inference runs at most max_rate_hz (D-185 CPU budget; 2-3 Hz on a Pi 5);
  - `seq` counts published packets, so a rate-limited frame is not a "missed"
    frame in the D-136 sense; a seq jump still means packets were lost;
  - each detection is ranged from its own box (BoxRanger, region_range rule).

Advisory evidence only (D-137): it goes to vision/detections, which CORE does not
read (CORE's advisory input is detection_evidence), and nothing here commands motion.
"""
from __future__ import annotations

import time

import numpy as np

from .sensing.perception.learned.detector import detection_packet
from .sensing.perception.learned.status import LearnedStatus, rate_limited
from .sensing.perception.region_range import range_boxes, scan_in_camera

TOPIC = 'vision/detections'
STATUS_TOPIC = 'perception/learned/object_det/status'


class BoxRanger:
    """The NOMINAL plane plus the latest scan; ranges pixel boxes for one frame stamp."""

    def __init__(self, ground, *, frame_size, camera_x_m, nose_rad, lidar_x_m, max_age_s,
                 tolerance_m, tolerance_ratio):
        self.frame_size = tuple(frame_size)  # the plane's frame; another size is not ranged
        self.ground, self._camera_x, self._nose, self._lidar_x = ground, camera_x_m, nose_rad, lidar_x_m
        self._max_age, self._tol, self._ratio = max_age_s, tolerance_m, tolerance_ratio
        self._scan = None

    def set_scan(self, ranges, angle_min, angle_increment, range_min, range_max, *, stamp):
        self._scan = (np.asarray(ranges, float), angle_min, angle_increment, range_min, range_max,
                      float(stamp))

    def ranges(self, boxes_xyxy, stamp, frame_size):
        if tuple(frame_size) != self.frame_size:
            return [None] * len(boxes_xyxy)
        points = None
        if self._scan is not None and self._nose is not None and abs(self._scan[5] - stamp) <= self._max_age:
            points = scan_in_camera(*self._scan[:5], nose_rad=self._nose, lidar_x_m=self._lidar_x,
                                    camera_x_m=self._camera_x)
        return range_boxes(boxes_xyxy, self.ground, points, tolerance_m=self._tol,
                           tolerance_ratio=self._ratio)


class ObjectDetectorCore:
    def __init__(self, slot, *, max_rate_hz, camera_fps, ranger=None, clock=time.monotonic):
        self._slot, self._max_rate_hz, self._fps, self.ranger = slot, float(max_rate_hz), float(camera_fps), ranger
        self._status = LearnedStatus(period_s=1.0 / max(self._fps, 0.1))
        self._last_infer = None
        self._seq = 0
        self._error = None
        self._clock = clock

    def on_frame(self, bgr, *, stamp, now=None):
        """The packet for this frame, or None (rate cap, no model, failed inference)."""
        now = self._clock() if now is None else now
        self._status.frame_in(stamp)
        if rate_limited(now, self._last_infer, self._max_rate_hz):
            self._status.frame_rate_limited()
            return None
        model = self._slot.poll()
        if model is None:
            return None
        self._last_infer = now
        try:
            result = model.infer(bgr)
        except Exception as exc:  # reported in status; the node keeps running
            self._error = f'inference: {exc}'
            return None
        self._error = None
        self._status.frame_inferred(result.latency_ms)
        ranges = None
        if self.ranger is not None:
            ranges = self.ranger.ranges([d['bbox_xyxy'] for d in result.detections], stamp,
                                        (bgr.shape[1], bgr.shape[0]))
        packet = detection_packet(result, observed_at=stamp, seq=self._seq,
                                  frame_size=(bgr.shape[1], bgr.shape[0]), fps=self._fps, ranges=ranges)
        self._seq += 1
        return packet

    def status_payload(self):
        model = self._slot.current
        return self._status.payload(model_revision=model.model_revision if model is not None else None,
                                    last_error=self._error or self._slot.last_error)
