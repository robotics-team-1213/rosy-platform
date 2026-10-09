"""Measure camera/odom timing and movement in the proven 10/7 MCAP catalog."""

import json
import math
import sys
from pathlib import Path

import numpy as np
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory


def stamp(message):
    return message.header.stamp.sec + message.header.stamp.nanosec * 1e-9


def odom_pose(message):
    point = message.pose.pose.position
    q = message.pose.pose.orientation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                     1 - 2 * (q.y * q.y + q.z * q.z))
    return stamp(message), point.x, point.y, yaw


catalog = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
assert len(catalog) == 207 and {row["source_kind"] for row in catalog} == {"mcap"}
for session in sorted({row["source_session"] for row in catalog}):
    rows = [row for row in catalog if row["source_session"] == session]
    bag = Path(rows[0]["mcap"]["session_dir"]) / "bag" / "bag_0.mcap"
    with bag.open("rb") as stream:
        samples = sorted(odom_pose(message) for _, _, _, message in
                         make_reader(stream, decoder_factories=[DecoderFactory()])
                         .iter_decoded_messages(topics=["/rosy_60/odom"]))
    odom = np.asarray(samples)
    camera = np.asarray([row["mcap"]["frame"]["header_stamp_ns"] * 1e-9 for row in rows])
    assert len(odom) and np.all(np.diff(camera) > 0) and np.all(np.diff(odom[:, 0]) > 0)
    nearest = np.abs(odom[:, 0, None] - camera[None, :]).argmin(axis=0)
    nearest_skew = np.abs(camera - odom[nearest, 0])
    prior = np.searchsorted(odom[:, 0], camera, side="right") - 1
    usable = prior >= 0
    prior_skew = camera[usable] - odom[prior[usable], 0]
    poses = odom[prior[usable]]
    movement = np.hypot(np.diff(poses[:, 1]), np.diff(poses[:, 2]))
    turns = np.abs(np.arctan2(np.sin(np.diff(poses[:, 3])), np.cos(np.diff(poses[:, 3]))))
    print(json.dumps({
        "session": session, "frames": len(rows), "odom_samples": len(samples),
        "nearest_within_0.3_s": int(np.count_nonzero(nearest_skew <= 0.3)),
        "nearest_skew_max_s": round(float(nearest_skew.max()), 4),
        "prior_within_0.3_s": int(np.count_nonzero(prior_skew <= 0.3)),
        "prior_skew_max_s": round(float(prior_skew.max()), 4),
        "prior_skew_p95_s": round(float(np.percentile(prior_skew, 95)), 4),
        "camera_interval_median_s": round(float(np.median(np.diff(camera))), 4),
        "prior_pose_step_max_m": round(float(movement.max()), 4),
        "prior_pose_yaw_step_max_deg": round(float(np.degrees(turns.max())), 2),
    }, sort_keys=True))
