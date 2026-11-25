#!/usr/bin/env python3
"""Arm B native lease control socket, before motor enrollment (no hardware access).

Run as the dedicated native owner using --config <installed root-owned JSON>.
Read-only status exposes a per-process session ID to the configured CORE uid.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys

from native_policy_fence import NativePolicyFence


def _trusted_parents(path, owners):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute installed path required")
    for directory in (path, *path.parents):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o022:
            raise PermissionError("untrusted installed directory")


def load_config(path):
    _trusted_parents(path.parent, {0})
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 8192:
        raise PermissionError("trusted root-owned owner enrollment required")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or set(cfg) != {"arm_id", "socket", "journal", "core_uid", "socket_gid", "pins"}:
        raise ValueError("invalid owner configuration")
    owner = os.geteuid()
    if (cfg["arm_id"] != "arm_b" or owner == 0 or type(cfg["core_uid"]) is not int
            or cfg["core_uid"] <= 0 or cfg["core_uid"] == owner or type(cfg["socket_gid"]) is not int
            or cfg["socket_gid"] <= 0):
        raise ValueError("distinct dedicated native and CORE principals required for B")
    address, journal = Path(cfg["socket"]), Path(cfg["journal"])
    if not address.is_relative_to("/run") or not journal.is_relative_to("/var/lib"):
        raise ValueError("use a service RuntimeDirectory socket and persistent StateDirectory journal")
    for target in (address, journal):
        _trusted_parents(target.parent, {0, owner})
        if target.parent.stat().st_uid != owner:
            raise PermissionError("native owner must control the endpoint and journal directories")
    if (address == journal or journal.parent.stat().st_mode & 0o077
            or address.parent.stat().st_gid != cfg["socket_gid"]
            or not address.parent.stat().st_mode & stat.S_IXGRP):
        raise PermissionError("shared traversable socket directory and private journal directory required")
    if journal.exists() or journal.is_symlink():
        row = journal.lstat()
        if not stat.S_ISREG(row.st_mode) or row.st_uid != owner or row.st_mode & 0o077:
            raise PermissionError("untrusted lease journal")
    return cfg


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate request key")
        obj[key] = value
    return obj


def handle(conn, cfg, fence):
    peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", peer)
    if uid != cfg["core_uid"]:
        return {"accepted": False, "reason": "core_peer_required"}
    with conn.makefile("rb") as reader:
        line = reader.readline(8193)
    if len(line) > 8192 or not line.endswith(b"\n"):
        raise ValueError("incomplete or oversized request")
    request = json.loads(line, object_pairs_hook=_unique)
    if not isinstance(request, dict):
        raise ValueError("object required")
    op = request.get("op")
    if op == "status" and set(request) == {"op"}:
        return {"ready": False, "arm_id": cfg["arm_id"], "owner_session_id": fence.owner_session_id,
                "reason": "native_motor_writer_not_enrolled", **fence.status()}
    if op == "hold" and set(request) == {"op", "reason"}:
        fence.hold("core_hold")
        return {"accepted": False, "reason": "motor_hold_unconfirmed"}
    if op == "lease" and set(request) == {"op", "owner_session_id", "not_after_monotonic_ns", "grant"}:
        # No existing native motor owner enforces grants through torque-on, writes and teardown.
        # Refuse before consuming the approval or any episode tombstone.
        return {"accepted": False, "reason": "native_motor_writer_not_enrolled"}
    raise ValueError("unknown native control request")


def serve(cfg):
    os.umask(0o077)
    address = Path(cfg["socket"])
    fence = NativePolicyFence(cfg["pins"], cfg["journal"])
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(address))  # An existing endpoint belongs to its current owner.
            identity = address.lstat()
            try:
                os.chown(address, -1, cfg["socket_gid"])
                address.chmod(0o660)
                server.listen(8)
                while True:
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(.25)
                        try:
                            response = handle(conn, cfg, fence)
                        except (ValueError, OSError, RecursionError):
                            response = {"accepted": False, "reason": "invalid_control_request"}
                        try:
                            conn.sendall(json.dumps(response, allow_nan=False).encode() + b"\n")
                        except OSError:
                            pass
            finally:
                if address.exists() and os.path.samestat(identity, address.lstat()):
                    address.unlink()
    finally:
        fence.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    serve(load_config(args.config))


if __name__ == "__main__":
    main()
