"""Read-only storage gate before network services can use cached device state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_firstboot import FirstBootState
from os_state_layout import COMMON, TLS_PENDING, _object, _path, _read


def admit_storage(root: Path, *, require_no_pending: bool = False) -> dict:
    shared = FirstBootState.admit(root)
    if shared is None:
        return {"schema_version": 1, "phase": "LEGACY"}
    phase = shared.validate_storage_state()
    if require_no_pending and _path(Path(root), TLS_PENDING).exists():
        raise ValueError("TLS transaction pending")
    return {"schema_version": 1, "phase": phase, "slot": shared.layout["slot"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--no-pending-maintenance", action="store_true")
    parser.add_argument("--tailnet", action="store_true")
    parser.add_argument("--projected", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.projected:
            from os_state_ready import publish_ready
            report = publish_ready(args.root)
        else:
            report = (admit_tailnet(args.root, bind_machine=True) if args.tailnet else
                      admit_storage(args.root, require_no_pending=args.no_pending_maintenance))
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_STATE_HOLD"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


def admit_tailnet(root: Path, *, bind_machine: bool = False) -> dict:
    from os_state_io import SERIAL, _json_atomic
    from os_state_config import common_lock

    root = Path(root).absolute()
    with common_lock(root) as shared:
        if shared is None:
            return {"schema_version": 1, "phase": "LEGACY"}
        if not shared.current.exists():
            raise ValueError("tailnet requires a committed device identity")
        _, manifest, values = shared._generation()
        live = _read(root / "proc/device-tree/serial-number", 128, root.stat().st_uid).decode("ascii").strip("\0\r\n ").lower()
        if not SERIAL.fullmatch(live) or live != manifest["hardware_serial"]:
            raise ValueError("tailnet hardware binding differs")
        expected = dict(schema_version=1, state_schema=1, device_uid=manifest["device_uid"], hardware_serial=live)
        binding = _path(root, COMMON + "/tailscale/machine-binding.json")
        if binding.exists():
            info = binding.stat()
            if info.st_mode & 0o7777 != 0o600 or info.st_nlink != 1:
                raise ValueError("tailnet binding permissions differ")
            if _object(_read(binding, 4096, root.stat().st_uid), set(expected)) != expected:
                raise ValueError("tailnet machine identity belongs to another device")
        elif not bind_machine:
            raise ValueError("tailnet machine binding is missing")
        else:
            if any((root / "var/lib/tailscale").iterdir()):
                raise ValueError("unbound tailnet state cannot be adopted")
            _json_atomic(binding, expected, 0o600)
        identity = json.loads(values["etc/rosy/device-identity.json"])
        return {"schema_version": 1, "phase": "TAILNET_BOUND", "slot": shared.layout["slot"],
                "hostname": identity["hostname"]}


if __name__ == "__main__":
    raise SystemExit(main())
