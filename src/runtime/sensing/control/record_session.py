"""Record one bag session with `ros2 bag record` (no rclpy import; D-356)."""

from __future__ import annotations

import argparse
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone

from control.recording import (bag_command, can_record, enforce_quota,
                               finish_session, new_session)

QUOTA_POLL_S = 5.0
STOP_TIMEOUT_S = 30


def _stop(proc) -> None:
    """SIGINT so ros2 bag closes the mcap cleanly; kill only as last resort."""
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _on_sigterm(signum, frame):
    raise KeyboardInterrupt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="/var/lib/rosy/recordings")
    p.add_argument("--quota-gib", type=float, default=4)
    p.add_argument("--device", default=socket.gethostname())
    p.add_argument("--reason", required=True)
    p.add_argument("--task-id", default="")
    p.add_argument("--camera-profile-revision", default="")
    p.add_argument("--model-revision", default="")
    args = p.parse_args(argv)

    quota = int(args.quota_gib * 1024 ** 3)
    enforce_quota(args.root, quota)
    if not can_record(args.root, quota):
        print("recording quota full of unharvested sessions; harvest first",
              file=sys.stderr)
        return 2
    folder = new_session(
        args.root, device=args.device,
        camera_profile_revision=args.camera_profile_revision,
        model_revision=args.model_revision, task_id=args.task_id,
        reason=args.reason, now=datetime.now(timezone.utc))
    try:
        proc = subprocess.Popen(bag_command(folder))
    except FileNotFoundError:
        print("ros2 not found on PATH; source the ROS 2 environment",
              file=sys.stderr)
        finish_session(folder, datetime.now(timezone.utc))
        return 1

    old = None
    try:
        old = signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:  # not the main thread
        pass
    code = 0
    try:
        while True:
            try:
                rc = proc.wait(timeout=QUOTA_POLL_S)
                code = 1 if rc else 0
                break
            except subprocess.TimeoutExpired:
                if not can_record(args.root, quota):
                    print("recording quota reached; stopping", file=sys.stderr)
                    _stop(proc)
                    code = 3
                    break
    except KeyboardInterrupt:
        _stop(proc)
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)
        finish_session(folder, datetime.now(timezone.utc))
    return code


if __name__ == "__main__":
    sys.exit(main())
