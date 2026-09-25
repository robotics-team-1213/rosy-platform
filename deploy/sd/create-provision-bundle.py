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
    RELEASE_ID_PATTERN,
    DeviceIdentity,
    create_provision_bundle,
    create_provision_receipt,
)


EXPECTED = {
    "device_uid", "device_name", "model", "release_id", "robot_number",
    "requested_preset", "country_code", "ssid", "wifi_passphrase",
    "fleet_endpoint", "fleet_trust_profile", "pairing_required",
    # D-191: the CORE API credential is read here only to hash it into CORE's record.
    "core_api_token", "core_api_token_id",
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


def load_factory_release(release_root: Path, public_key: Path, release_id: str) -> dict | None:
    """The offline factory-release signature from a signed image release (D-225 2.2).

    Returns None for an image built before D-225 2.2 (no factory-release/<id>),
    whose factory release stays unsigned on the robot as before. Present but
    unsigned, or signed by another key, is refused: the card would otherwise
    carry a signature first boot is certain to throw away.
    """
    if str(REPO_ROOT / "deploy" / "release") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "deploy" / "release"))
    from signing import verify_signature

    if not isinstance(release_id, str) or not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release_id is invalid")
    factory = release_root / "factory-release" / release_id
    if not factory.exists() and not factory.is_symlink():
        return None
    sums = factory / "SHA256SUMS"
    signature = factory / "SHA256SUMS.sig"
    if factory.is_symlink() or not sums.is_file() or not signature.is_file():
        raise ValueError("factory release signature is missing")
    encoded = "".join(signature.read_text(encoding="ascii").split())
    if verify_signature(sums.read_bytes(), encoded, public_key):
        raise ValueError("factory release signature does not verify")
    return {"release_id": release_id, "sha256sums_sig_b64": encoded}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    # D-225 2.2: the verified image release, to carry its factory signature.
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--public-key", type=Path)
    args = parser.parse_args(argv)
    if (args.release_root is None) != (args.public_key is None):
        parser.error("--release-root and --public-key go together")
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
            core_api_token=request["core_api_token"],
            core_api_token_id=request["core_api_token_id"],
            factory_release=(
                load_factory_release(args.release_root, args.public_key, request["release_id"])
                if args.release_root is not None else None),
        )
        _exclusive_json(args.output, bundle, 0o600)
        _exclusive_json(args.receipt, create_provision_receipt(bundle), 0o600)
    except json.JSONDecodeError:
        print("bundle creation refused: JSONDecodeError", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"bundle creation refused: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("BUNDLE_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
