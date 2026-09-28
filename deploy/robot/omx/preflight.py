#!/usr/bin/env python3
"""Host-side, fail-closed serial admission for the OMX workstation container."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Callable


def _probe() -> tuple[Callable[[str], str], Callable[[str], os.stat_result], Callable[[str, int], bool]]:
    return os.path.realpath, os.stat, os.access


def _resolve_one(
    label: str,
    selection: str,
    *,
    realpath: Callable[[str], str],
    stat_fn: Callable[[str], os.stat_result],
    access_fn: Callable[[str, int], bool],
) -> str:
    prefix = "/dev/serial/by-id/"
    if not selection.startswith(prefix) or not selection[len(prefix):] or "/" in selection[len(prefix):]:
        raise ValueError(f"{label} must be selected by a single /dev/serial/by-id/ entry")
    resolved = realpath(selection)
    if not resolved.startswith("/dev/") or resolved == "/dev/":
        raise ValueError(f"{label} by-id entry must resolve to a device under /dev")
    try:
        mode = stat_fn(resolved).st_mode
    except OSError as exc:
        raise ValueError(f"{label} device is unavailable: {resolved}") from exc
    if not stat.S_ISCHR(mode):
        raise ValueError(f"{label} target is not a character device: {resolved}")
    if not access_fn(resolved, os.R_OK | os.W_OK):
        raise ValueError(f"{label} device must be accessible for read/write: {resolved}")
    return resolved


def resolve_devices(
    follower: str,
    leader: str,
    *,
    probe: tuple[
        Callable[[str], str], Callable[[str], os.stat_result], Callable[[str, int], bool]
    ] | None = None,
) -> dict[str, str]:
    """Resolve two operator-selected by-id ports and reject ambiguous admission."""
    realpath, stat_fn, access_fn = probe or _probe()
    follower_path = _resolve_one(
        "follower", follower, realpath=realpath, stat_fn=stat_fn, access_fn=access_fn
    )
    leader_path = _resolve_one(
        "leader", leader, realpath=realpath, stat_fn=stat_fn, access_fn=access_fn
    )
    if follower_path == leader_path:
        raise ValueError("follower and leader must resolve to different devices")
    return {"OMX_FOLLOWER_DEVICE": follower_path, "OMX_LEADER_DEVICE": leader_path}


def resolve_host_devices(inventory, host_id: str, *, probe=None) -> dict[str, dict[str, str]]:
    """Resolve all enabled workcells on one host and reject shared real devices."""
    if host_id not in {host.host_id for host in inventory.hosts}:
        raise ValueError(f"unknown host_id: {host_id}")
    resolved_by_workcell = {}
    owners: dict[str, str] = {}
    for workcell in inventory.workcells:
        if workcell.host_id != host_id or not workcell.enabled:
            continue
        try:
            devices = resolve_devices(workcell.follower, workcell.leader, probe=probe)
        except ValueError as exc:
            raise ValueError(f"workcell {workcell.workcell_id}: {exc}") from exc
        for path in devices.values():
            if path in owners:
                raise ValueError(
                    f"device is shared by workcells {owners[path]} and {workcell.workcell_id}"
                )
            owners[path] = workcell.workcell_id
        resolved_by_workcell[workcell.workcell_id] = devices
    return resolved_by_workcell


def render_env(devices: dict[str, str]) -> str:
    return "".join(f"{key}={devices[key]}\n" for key in ("OMX_FOLLOWER_DEVICE", "OMX_LEADER_DEVICE"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--follower", required=True, help="selected /dev/serial/by-id entry")
    parser.add_argument("--leader", required=True, help="selected /dev/serial/by-id entry")
    args = parser.parse_args(argv)
    try:
        print(render_env(resolve_devices(args.follower, args.leader)), end="")
    except ValueError as exc:
        print(f"OMX preflight refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
