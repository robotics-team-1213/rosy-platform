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


def _ignore_signals() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except ValueError:  # not the main thread
            pass


def _stop(proc) -> None:
    """Stop the recorder gracefully; a second signal must not orphan it."""
    _ignore_signals()
    try:
        # A terminal Ctrl-C already reached the whole process group.
        proc.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.send_signal(signal.SIGINT)  # ros2 bag closes the mcap cleanly
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
    old_term = old_int = None
    try:
        old_int = signal.getsignal(signal.SIGINT)
        old_term = signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:  # not the main thread
        pass
    code = 0
    try:
        try:
            proc = subprocess.Popen(bag_command(folder))
        except FileNotFoundError:
            print("ros2 not found on PATH; source the ROS 2 environment",
                  file=sys.stderr)
            return 1
        try:
            while True:
                try:
                    rc = proc.wait(timeout=QUOTA_POLL_S)
                    code = 1 if rc else 0
                    break
                except subprocess.TimeoutExpired:
                    try:
                        full = not can_record(args.root, quota)
                    except Exception as exc:
                        print(f"quota check failed ({exc}); stopping",
                              file=sys.stderr)
                        _stop(proc)
                        code = 1
                        break
                    if full:
                        print("recording quota reached; stopping",
                              file=sys.stderr)
                        _stop(proc)
                        code = 3
                        break
        except KeyboardInterrupt:
            _stop(proc)
    finally:
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)
        if old_int is not None:
            signal.signal(signal.SIGINT, old_int)
        finish_session(folder, datetime.now(timezone.utc))
    return code


if __name__ == "__main__":
    sys.exit(main())
