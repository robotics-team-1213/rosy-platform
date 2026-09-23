#!/usr/bin/env python3
"""Create a one-time SD bundle from one JSON document read on stdin."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deploy.sd.personalization import (
    DeviceIdentity,
    create_provision_bundle,
    create_provision_receipt,
)


EXPECTED = {
    "device_uid", "device_name", "model", "release_id", "robot_number",
    "requested_preset", "country_code", "ssid", "wifi_passphrase",
    "fleet_endpoint", "fleet_trust_profile", "pairing_required",
}
# D-174 F3: per-card operator public keys; absent keeps the pre-F3 bundle shape.
OPTIONAL = {"operator_ssh_keys", "ap_password"}


def _exclusive_json(path: Path, payload: dict, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.chmod(path, mode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("request is too large")
        request = json.loads(raw.lstrip("\ufeff"))
        if not isinstance(request, dict) or set(request) - OPTIONAL != EXPECTED:
            raise ValueError("request fields are invalid")
        identity = DeviceIdentity(
            device_uid=request["device_uid"],
            device_name=request["device_name"],
            hostname=request["device_name"],
            model=request["model"],
        )
        bundle = create_provision_bundle(
            identity=identity,
            release_id=request["release_id"],
            robot_number=request["robot_number"],
            requested_preset=request["requested_preset"],
            country_code=request["country_code"],
            ssid=request["ssid"],
            wifi_passphrase=request["wifi_passphrase"],
            fleet_endpoint=request["fleet_endpoint"],
            fleet_trust_profile=request["fleet_trust_profile"],
            pairing_required=request["pairing_required"],
            operator_ssh_keys=request.get("operator_ssh_keys"),
            ap_password=request.get("ap_password"),
        )
        _exclusive_json(args.output, bundle, 0o600)
        _exclusive_json(args.receipt, create_provision_receipt(bundle), 0o600)
    except json.JSONDecodeError:
        print("bundle creation refused: JSONDecodeError", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"bundle creation refused: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("BUNDLE_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
