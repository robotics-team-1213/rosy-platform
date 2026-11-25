"""One local diagnostic report for a completed AMCL injection check."""
from __future__ import annotations

import math

from .sensing.loc_candidates import base_from_sensor


class VerificationTrace:
    def __init__(self, check, injection):
        self.check = check
        self.injection = injection
        self.scan_stamp = None
        self.scan_error = None
        self.sample = None

    def scan(self, stamp):
        self.scan_stamp = stamp
        self.scan_error = None

    def fit(self, stamp, now, sensor_pose, frame, fit, breakdown):
        self.sample = {
            "scan_stamp": stamp,
            "scan_age_s": now - stamp,
            "sensor_pose": sensor_pose,
            "sensor_frame": frame,
            "fit": fit if fit is not None and math.isfinite(fit) else None,
        }
        if breakdown is not None:
            self.sample.update(raw_fit=breakdown.raw_score, wall_pierced=breakdown.miss_wall_pierced,
                               beams=breakdown.total, agreement_rejection=breakdown.rejected_reason)

    def report(self, now, mount=None):
        measured_base_pose = (base_from_sensor(self.sample["sensor_pose"], mount)
                              if mount is not None and self.sample is not None else None)
        check = self.check
        requested = self.injection.pose
        return {
            "request_id": self.injection.request_id,
            "source": self.injection.source,
            "result": check.result,
            "reason": check.reason,
            "elapsed_s": now - check.started_s,
            "fit_gap_s": now - check.last_s,
            "minimum_fit": check.min_fit,
            "maximum_fit_gap_s": check.max_gap_s,
            "requested_base_pose": requested,
            "measured_base_pose": measured_base_pose,
            "position_error_m": (None if measured_base_pose is None
                                 else math.dist(requested[:2], measured_base_pose[:2])),
            "yaw_error_rad": (None if measured_base_pose is None
                              else math.remainder(measured_base_pose[2] - requested[2], 2 * math.pi)),
            "latest_scan_stamp": self.scan_stamp,
            "latest_scan_age_s": None if self.scan_stamp is None else now - self.scan_stamp,
            "latest_scan_error": self.scan_error,
            "last_fit": self.sample,
        }
