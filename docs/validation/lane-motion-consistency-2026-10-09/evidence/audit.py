"""Read-only camera-window cmd/odom consistency audit for original MCAP bags."""

import argparse
import bisect
import hashlib
import json
import math
import statistics
from pathlib import Path

from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory

WINDOW_S = 0.5


def stamp(header):
    return header.stamp.sec + header.stamp.nanosec * 1e-9


def audit(session):
    files = sorted((session / "bag").glob("bag_*.mcap"),
                   key=lambda path: int(path.stem.split("_")[-1]))
    if not files:
        raise ValueError(f"no MCAP bags in {session}")
    cmd, odom, camera = [], [], []
    scan_count = 0
    header_log_skews = []
    namespaces = set()
    hashes = {}
    for path in files:
        with path.open("rb") as raw:
            hashes[path.name] = hashlib.file_digest(raw, "sha256").hexdigest()
            raw.seek(0)
            for _, channel, message, value in make_reader(
                    raw, decoder_factories=[DecoderFactory()]).iter_decoded_messages():
                topic = channel.topic
                if topic.endswith(("/cmd_vel", "/odom", "/camera/front/compressed", "/scan")):
                    namespaces.add(topic.split("/")[1])
                if topic.endswith("/cmd_vel"):
                    cmd.append((message.log_time * 1e-9, value.linear.x, value.angular.z))
                elif topic.endswith("/odom"):
                    pose = value.pose.pose
                    q = pose.orientation
                    header_log_skews.append(message.log_time * 1e-9 - stamp(value.header))
                    odom.append((stamp(value.header), pose.position.x, pose.position.y,
                                 2.0 * math.atan2(q.z, q.w)))
                elif topic.endswith("/camera/front/compressed"):
                    header_log_skews.append(message.log_time * 1e-9 - stamp(value.header))
                    camera.append(stamp(value.header))
                elif topic.endswith("/scan"):
                    scan_count += 1
    if len(namespaces) != 1 or not cmd or not odom or not camera:
        raise ValueError(f"one robot with cmd, odom and camera required: {session}")
    cmd.sort()
    odom.sort()
    camera.sort()
    cmd_times, odom_times = [row[0] for row in cmd], [row[0] for row in odom]
    active = suspect = eligible = 0
    min_translation = None
    for start in camera:
        c = cmd[bisect.bisect_left(cmd_times, start):bisect.bisect_left(cmd_times, start + WINDOW_S)]
        o = odom[bisect.bisect_left(odom_times, start):bisect.bisect_left(odom_times, start + WINDOW_S)]
        if len(c) < 3 or len(o) < 3:
            continue
        eligible += 1
        linear = statistics.median(abs(row[1]) for row in c)
        angular = statistics.median(abs(row[2]) for row in c)
        if linear < 0.02 and angular < 0.1:
            continue
        active += 1
        translation = math.hypot(o[-1][1] - o[0][1], o[-1][2] - o[0][2])
        rotation = abs(math.remainder(o[-1][3] - o[0][3], 2.0 * math.pi))
        min_translation = translation if min_translation is None else min(min_translation, translation)
        if translation < 0.003 and rotation < 0.015:
            suspect += 1
    return {"session": session.name, "bags_sha256": hashes,
            "camera": len(camera), "cmd_vel": len(cmd), "odom": len(odom), "scan": scan_count,
            "eligible_windows": eligible, "active_windows": active,
            "no_progress_proxy_windows": suspect,
            "min_active_translation_m": min_translation,
            "max_header_log_skew_s": max(map(abs, header_log_skews), default=None),
            "max_odom_gap_s": max((b - a for a, b in zip(odom_times, odom_times[1:])),
                                  default=None)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([audit(path) for path in args.sessions], indent=2))
