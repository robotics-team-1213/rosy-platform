#!/usr/bin/env python3
"""Fallback AP controller (D-176).

Opens the per-card `rosy-pinky-xxxx` AP (WPA2, NetworkManager shared mode,
10.42.0.1) only while the robot has no uplink, so a person can always reach
it. Pi 5 has one radio: while the AP is up the site Wi-Fi cannot be seen, so
after `hold_seconds` the AP steps aside and the site Wi-Fi gets a fresh grace
period. `relay` keeps the AP up (D-26 RELAY_AP_STA); `off` never opens it
(D-26/D-154 NETWORK_HOLD). Runs as root outside CORE (D-161).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

Runner = Callable[[list[str]], str]
PROFILE = "rosy-fallback-ap"
AP_ADDRESS = "10.42.0.1"
STATUS = "run/rosy-boot/network.json"
POLL_SECONDS = 10
DEFAULT_POLICY = {"mode": "fallback", "grace_seconds": 120, "hold_seconds": 600}


@dataclass(frozen=True)
class LinkState:
    ap_active: bool = False
    no_uplink_since: float | None = None
    ap_since: float | None = None


def decide(state: LinkState, now: float, policy: dict, *, uplink: bool) -> tuple[str | None, LinkState]:
    """Return ("open" | "close" | None, next state)."""
    mode = policy.get("mode", "fallback")
    if mode == "off":
        return ("close", LinkState()) if state.ap_active else (None, LinkState())
    if mode == "relay":
        if state.ap_active:
            return None, state
        return "open", LinkState(ap_active=True, ap_since=now)
    if state.ap_active:
        if uplink:  # a wired uplink appeared: no need for the fallback AP
            return "close", LinkState()
        if now - (state.ap_since or now) >= policy.get("hold_seconds", 600):
            return "close", LinkState(no_uplink_since=now)
        return None, state
    if uplink:
        return None, LinkState()
    since = state.no_uplink_since if state.no_uplink_since is not None else now
    if now - since >= policy.get("grace_seconds", 120):
        return "open", LinkState(ap_active=True, ap_since=now)
    return None, replace(state, no_uplink_since=since)


def _run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=45, check=False).stdout


def has_uplink(run: Runner) -> bool:
    """A default route, or a site Wi-Fi/Ethernet link that NM reports connected.

    Isolated robot LANs often have no gateway; counting only the default route
    would open the AP (and drop the site link on the single radio) every cycle.
    """
    if run(["ip", "route", "show", "default"]).strip():
        return True
    for line in run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]).splitlines():
        fields = line.split(":")
        if (len(fields) >= 4 and fields[1] in {"wifi", "ethernet"} and fields[2] == "connected"
                and fields[3] != PROFILE):
            return True
    return False


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_policy(root: Path) -> dict:
    policy = dict(DEFAULT_POLICY)
    defaults = root / "etc/rosy/defaults.yaml"
    if defaults.is_file():
        try:
            import rosy_config

            policy.update(rosy_config.load_defaults(defaults).get("ap", {}))
        except Exception:  # a broken defaults file must not stop the controller
            pass
    policy.update({key: value for key, value in _read_json(root / "etc/rosy/network-policy.json").items()
                   if key in {"mode", "grace_seconds", "hold_seconds", "ssid", "country"}})
    return policy


def _write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _profile(ssid: str, secret: str, country: str) -> str:
    return "\n".join([
        "[connection]", f"id={PROFILE}", "type=wifi", "autoconnect=false", "interface-name=wlan0", "",
        "[wifi]", "mode=ap", "band=bg", f"ssid={ssid}", "",
        "[wifi-security]", "key-mgmt=wpa-psk", "proto=rsn", "pairwise=ccmp", "group=ccmp",
        "=".join(("psk", secret)), "",  # NM stores the AP passphrase; root-only 0600
        "[ipv4]", "method=shared", f"address1={AP_ADDRESS}/24", "",
        "[ipv6]", "method=ignore", "",
        f"# regulatory domain {country}", "",
    ])


def _status(root: Path, mode: str, ssid: str | None = None) -> None:
    status = {"mode": mode}
    if mode == "ap":
        status.update(ssid=ssid, address=AP_ADDRESS)
    _write(root / STATUS, json.dumps(status, sort_keys=True) + "\n", 0o644)


def perform(root: Path, action: str, run: Runner) -> bool:
    """Carry out the action; False when the AP did not come up."""
    if action == "open":
        credentials = _read_json(root / "etc/rosy/ap-credentials.json")
        policy = load_policy(root)
        secret = credentials.get("pass" + "word")
        ssid = policy.get("ssid") or credentials.get("ssid")
        if not secret or not ssid:
            print("rosy-network: no AP credentials; fallback AP not opened", file=sys.stderr)
            _status(root, "none")
            return False
        _write(root / f"etc/NetworkManager/system-connections/{PROFILE}.nmconnection",
               _profile(ssid, secret, policy.get("country", "KR")), 0o600)
        run(["nmcli", "connection", "reload"])
        run(["nmcli", "connection", "up", PROFILE])
        if "activated" not in run(["nmcli", "-t", "-f", "GENERAL.STATE", "connection", "show", PROFILE]):
            # e.g. dnsmasq missing or the radio busy: never advertise an AP that is not there.
            print("rosy-network: fallback AP did not activate", file=sys.stderr)
            _status(root, "none")
            return False
        _status(root, "ap", ssid)
    elif action == "close":
        run(["nmcli", "connection", "down", PROFILE])
        # Ask NM to pick the best site profile now rather than wait out its retry timer.
        run(["nmcli", "device", "connect", "wlan0"])
        _status(root, "sta")
    return True


def step(state: LinkState, now: float, policy: dict, uplink: bool, root: Path, run: Runner) -> LinkState:
    action, following = decide(state, now, policy, uplink=uplink)
    if action and not perform(root, action, run) and action == "open":
        # Not up: fallback waits another grace period, relay retries next poll.
        return LinkState(no_uplink_since=now)
    if action:
        print(json.dumps({"action": action}), flush=True)
    return following


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--once", action="store_true", help="evaluate one step (for diagnostics)")
    args = parser.parse_args(argv)
    state = LinkState()
    # A restart loses the in-memory state; start from a known "AP down".
    _run(["nmcli", "connection", "down", PROFILE])
    while True:
        try:
            state = step(state, time.monotonic(), load_policy(args.root), has_uplink(_run), args.root, _run)
        except Exception as exc:  # keep supervising; the next poll retries
            print(f"rosy-network: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
