"""Record one bag session with `ros2 bag record` (no rclpy import; D-356)."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from datetime import datetime, timezone

from control.recording import (bag_command, can_record, enforce_quota,
                               finish_session, new_session)


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
        subprocess.run(bag_command(folder))
    except KeyboardInterrupt:
        pass
    finally:
        finish_session(folder, datetime.now(timezone.utc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
