"""Record bag sessions with `ros2 bag record` (no rclpy import; D-356, D-373).

Session mode (default): one run is one session. The compressed front camera is
recorded when it is being published, raw camera/front otherwise (--raw-camera
forces raw).

--snapshot: rosbag2 snapshot mode keeps ~60 s of camera/front/compressed and
the side topics in memory. capture_trigger_node calls /<--node-name>/snapshot;
every dump becomes its own session folder whose session.json carries the
trigger reason and values (see control.recording)."""

from __future__ import annotations

import argparse
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from control.recording import (CAMERA_TOPIC, COMPRESSED_CAMERA_TOPIC, DEFAULT_ROOT,
                               SNAPSHOT_CACHE_PREFIX, adopt_snapshot, bag_command,
                               can_record, closed_snapshot_files, enforce_quota,
                               finish_session, new_session, pending_snapshot_requests,
                               record_topics, snapshot_bag_command, snapshot_files)

QUOTA_POLL_S = 5.0
SNAPSHOT_POLL_S = 1.0  # how soon a dump shows up as a session folder
STOP_TIMEOUT_S = 30
TOPIC_LIST_TIMEOUT_S = 10
DEFAULT_SNAPSHOT_NODE = "rosy_snapshot_recorder"


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


def _topic_listed(name: str) -> bool:
    """True when `ros2 topic list` shows the absolute topic name right now."""
    try:
        out = subprocess.run(["ros2", "topic", "list"], capture_output=True, text=True,
                             timeout=TOPIC_LIST_TIMEOUT_S, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return name in {line.strip() for line in (out or "").splitlines()}


def _supervise(proc, root, quota, poll_s, on_poll=None) -> int:
    """Wait for the recorder; stop it when the quota fills (3) or a check fails (1)."""
    try:
        while True:
            try:
                rc = proc.wait(timeout=poll_s)
                return 1 if rc else 0
            except subprocess.TimeoutExpired:
                if on_poll is not None:
                    on_poll()
                try:
                    full = not can_record(root, quota)
                except Exception as exc:
                    print(f"quota check failed ({exc}); stopping", file=sys.stderr)
                    _stop(proc)
                    return 1
                if full:
                    print("recording quota reached; stopping", file=sys.stderr)
                    _stop(proc)
                    return 3
    except KeyboardInterrupt:
        _stop(proc)
        return 0


def _install_sigterm():
    old_term = old_int = None
    try:
        old_int = signal.getsignal(signal.SIGINT)
        old_term = signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:  # not the main thread
        pass
    return old_term, old_int


def _restore(old_term, old_int) -> None:
    if old_term is not None:
        signal.signal(signal.SIGTERM, old_term)
    if old_int is not None:
        signal.signal(signal.SIGINT, old_int)


def _session_main(args, quota) -> int:
    folder_topic = CAMERA_TOPIC
    if not args.raw_camera:
        ns = args.namespace.strip("/")
        name = f"/{ns}/{COMPRESSED_CAMERA_TOPIC}" if ns else f"/{COMPRESSED_CAMERA_TOPIC}"
        if _topic_listed(name):
            folder_topic = COMPRESSED_CAMERA_TOPIC
    folder = new_session(
        args.root, device=args.device,
        camera_profile_revision=args.camera_profile_revision,
        model_revision=args.model_revision, task_id=args.task_id,
        reason=args.reason, now=datetime.now(timezone.utc),
        topics=record_topics(folder_topic))
    old_term, old_int = _install_sigterm()
    try:
        try:
            proc = subprocess.Popen(bag_command(folder, args.namespace, folder_topic))
        except FileNotFoundError:
            print("ros2 not found on PATH; source the ROS 2 environment",
                  file=sys.stderr)
            return 1
        return _supervise(proc, args.root, quota, QUOTA_POLL_S)
    finally:
        _restore(old_term, old_int)
        finish_session(folder, datetime.now(timezone.utc))


class _Adopter:
    """Closed snapshot files -> session folders, paired with pending requests."""

    def __init__(self, args):
        self.root = Path(args.root)
        self.meta = dict(device=args.device,
                         camera_profile_revision=args.camera_profile_revision,
                         model_revision=args.model_revision)

    def adopt(self, mcap: Path, fallback: str | None = None) -> None:
        pending = pending_snapshot_requests(self.root)
        path, request = pending[0] if pending else (None, None)
        if request is None and fallback is not None:
            request = {"reason": fallback, "values": {}, "requested_at": None}
        folder = adopt_snapshot(self.root, mcap, request, now=datetime.now(timezone.utc),
                                **self.meta)
        if path is not None:
            path.unlink(missing_ok=True)
        reason = request["reason"] if request else "unrequested"
        print(f"snapshot session {folder.name}: {reason}", file=sys.stderr)

    def poll(self, cache: Path) -> None:
        for mcap in closed_snapshot_files(cache):
            self.adopt(mcap)

    def finish(self, cache: Path) -> None:
        """After the recorder exited: its newest file was opened by the last
        split and holds no dump unless a snapshot request is still waiting
        (the recorder died while writing it)."""
        self.poll(cache)
        for mcap in snapshot_files(cache):
            if pending_snapshot_requests(self.root):
                self.adopt(mcap)
            else:
                mcap.unlink()
        for path, request in pending_snapshot_requests(self.root):
            print(f"snapshot request without data dropped: {request['reason']}",
                  file=sys.stderr)
            path.unlink(missing_ok=True)
        shutil.rmtree(cache, ignore_errors=True)

    def recover(self) -> None:
        """A cache left by a crash: keep every non-empty file (never unharvested
        data is deleted), then drop the folder."""
        for cache in sorted(self.root.glob(SNAPSHOT_CACHE_PREFIX + "*")):
            for mcap in snapshot_files(cache):
                if mcap.stat().st_size > 0:
                    self.adopt(mcap, fallback="recovered")
            shutil.rmtree(cache, ignore_errors=True)


def _snapshot_main(args, quota) -> int:
    adopter = _Adopter(args)
    adopter.recover()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cache = Path(args.root) / f"{SNAPSHOT_CACHE_PREFIX}{stamp}"
    old_term, old_int = _install_sigterm()
    try:
        try:
            proc = subprocess.Popen(snapshot_bag_command(cache, args.namespace, args.node_name))
        except FileNotFoundError:
            print("ros2 not found on PATH; source the ROS 2 environment",
                  file=sys.stderr)
            return 1
        return _supervise(proc, args.root, quota, SNAPSHOT_POLL_S,
                          on_poll=lambda: adopter.poll(cache))
    finally:
        _restore(old_term, old_int)
        adopter.finish(cache)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--quota-gib", type=float, default=4)
    p.add_argument("--device", default=socket.gethostname())
    p.add_argument("--reason", help="why this session is recorded (session mode)")
    p.add_argument("--task-id", default="")
    p.add_argument("--camera-profile-revision", default="")
    p.add_argument("--model-revision", default="")
    p.add_argument("--namespace", default="",
                   help="robot namespace prefixed to every recorded topic")
    p.add_argument("--snapshot", action="store_true",
                   help="rosbag2 snapshot mode; each dump becomes one session")
    p.add_argument("--node-name", default=DEFAULT_SNAPSHOT_NODE,
                   help="snapshot recorder node; its service is /<name>/snapshot")
    p.add_argument("--raw-camera", action="store_true",
                   help="session mode: record raw camera/front even when compressed exists")
    args = p.parse_args(argv)
    if not args.snapshot and not args.reason:
        p.error("--reason is required unless --snapshot")

    quota = int(args.quota_gib * 1024 ** 3)
    Path(args.root).mkdir(parents=True, exist_ok=True)
    enforce_quota(args.root, quota)
    if not can_record(args.root, quota):
        print("recording quota full of unharvested sessions; harvest first",
              file=sys.stderr)
        return 2
    if args.snapshot:
        return _snapshot_main(args, quota)
    return _session_main(args, quota)


if __name__ == "__main__":
    sys.exit(main())
