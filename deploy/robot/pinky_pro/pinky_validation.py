"""Build an operator-facing verdict from stationary Pinky evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"name": name, "outcome": "GO" if passed else "HOLD", "detail": detail}


def build_summary(
    connection: dict[str, Any],
    readback: dict[str, Any] | None,
    *,
    expected_robot_number: int,
    expected_revision: str,
    api_port: int = 8080,
) -> dict[str, Any]:
    """Join existing read-only evidence without widening its acceptance scope."""

    network = connection.get("network") if isinstance(connection.get("network"), dict) else {}
    readback_available = isinstance(readback, dict)
    readback_data = readback if readback_available else {}
    identity = readback_data.get("identity") if isinstance(readback_data.get("identity"), dict) else {}
    activation = readback_data.get("activation") if isinstance(readback_data.get("activation"), dict) else {}
    artifact = readback_data.get("artifact") if isinstance(readback_data.get("artifact"), dict) else {}
    gates = readback_data.get("gates") if isinstance(readback_data.get("gates"), dict) else {}

    actual_robot_number = str(identity.get("robot_number") or "")
    actual_revision = str(artifact.get("git_revision") or "").lower()
    expected_revision = expected_revision.lower()
    expected_domain = str(40 + expected_robot_number)
    expected_namespace = f"rosy_{expected_robot_number:02d}"
    checks = [
        _check(
            "connection_schema",
            connection.get("schema_version") == 1,
            f"expected=1 actual={connection.get('schema_version', 'missing')}",
        ),
        _check(
            "readback_schema",
            readback_data.get("schema_version") == 1,
            f"expected=1 actual={readback_data.get('schema_version', 'missing')}",
        ),
        _check(
            "lan_peer",
            connection.get("outcome") == "GO",
            "Windows peer reached SSH, API, and dashboard.",
        ),
        _check(
            "device_runtime",
            gates.get("device_runtime") == "GO",
            "Signed ARM64 artifact, CORE, and ROS graph readback.",
        ),
        _check(
            "robot_identity",
            actual_robot_number == str(expected_robot_number),
            f"expected={expected_robot_number} actual={actual_robot_number or 'missing'}",
        ),
        _check(
            "derived_identity",
            str(identity.get("ros_domain_id") or "") == expected_domain
            and str(identity.get("namespace") or "") == expected_namespace,
            (
                f"expected_domain={expected_domain} actual_domain="
                f"{identity.get('ros_domain_id') or 'missing'} "
                f"expected_namespace={expected_namespace} actual_namespace="
                f"{identity.get('namespace') or 'missing'}"
            ),
        ),
        _check(
            "source_revision",
            actual_revision == expected_revision,
            f"expected={expected_revision} actual={actual_revision or 'missing'}",
        ),
        _check(
            "core_only_quarantine",
            identity.get("runtime_mode") == "core" and activation.get("runtime_mode") == "core",
            "Stationary preflight requires both configured and activated mode to be core.",
        ),
        _check(
            "field_hold_preserved",
            gates.get("field") == "HOLD",
            "Stationary evidence must not authorize field motion.",
        ),
    ]
    outcome = "GO" if all(item["outcome"] == "GO" for item in checks) else "HOLD"
    failed_checks = [item["name"] for item in checks if item["outcome"] == "HOLD"]
    address = str(network.get("address") or "")

    return {
        "schema_version": 1,
        "scope": "STATIONARY_DEVICE_PREFLIGHT",
        "outcome": outcome,
        "motion_authorized": False,
        "device_readback_available": readback_available,
        "next_gate": "G3_SENSOR_ONLY" if outcome == "GO" else "REMEDIATE_HOLD",
        "failed_checks": failed_checks,
        "operator_message": (
            "GO: inspect sensors at G3; motors remain disabled."
            if outcome == "GO"
            else "HOLD: fix the named checks; do not enable motors."
        ),
        "dashboard_url": f"http://{address}:{api_port}/dashboard" if address else None,
        "device": readback_data.get("device", {}),
        "identity": identity,
        "checks": checks,
    }


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", type=Path, required=True)
    parser.add_argument("--readback", type=Path)
    parser.add_argument("--expected-robot-number", type=int, choices=range(1, 102), required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--api-port", type=int, choices=range(1, 65536), default=8080)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    expected_revision = args.expected_revision.lower()
    if not _REVISION.fullmatch(expected_revision):
        parser.error("--expected-revision must be a full 40-character git revision")
    if args.output.exists():
        print(f"refusing to replace existing evidence: {args.output}", file=sys.stderr)
        return 64
    try:
        summary = build_summary(
            _load_object(args.connection),
            _load_object(args.readback) if args.readback else None,
            expected_robot_number=args.expected_robot_number,
            expected_revision=expected_revision,
            api_port=args.api_port,
        )
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation evidence error: {exc}", file=sys.stderr)
        return 64

    print(summary["operator_message"])
    return 0 if summary["outcome"] == "GO" else 2


if __name__ == "__main__":
    sys.exit(main())
