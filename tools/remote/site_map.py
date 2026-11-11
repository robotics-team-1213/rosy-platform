"""One private site map: which PC runs what, with which arm boards, and how it is managed.

The map lives in ``private/site-map.yaml`` on the main checkout (``ROSY_SITE_MAP`` overrides), beside
``lab-hosts.json``, because it holds real addresses and board serials (D-226). Tools read it here instead of
rediscovering the site. ``check`` compares each host's OpenRB boards with the map, read-only:

    python tools/remote/site_map.py show
    python tools/remote/site_map.py check            # exit 1 on a missing or unmapped board
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_hosts import main_checkout  # noqa: E402

SCHEMA = "rosy.site-map/1"
OPENRB = re.compile(r"usb-ROBOTIS_OpenRB-150_([0-9A-F]{32})-if00")


def map_file() -> Path:
    override = os.environ.get("ROSY_SITE_MAP", "").strip()
    return Path(override) if override else main_checkout() / "private" / "site-map.yaml"


def load(path: Path | None = None) -> dict:
    path = path or map_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("hosts"), dict):
        raise SystemExit(f"{path}: expected schema {SCHEMA} with a hosts mapping")
    return data


def boards(host: dict) -> dict[str, str]:
    """Board serial -> '<arm>.<role>' for one host's arms."""
    found = {}
    for arm, roles in (host.get("arms") or {}).items():
        for role in ("follower", "leader"):
            serial = ((roles or {}).get(role) or {}).get("board")
            if serial:
                if serial in found:
                    raise SystemExit(f"board {serial} is mapped twice: {found[serial]} and {arm}.{role}")
                found[serial] = f"{arm}.{role}"
    return found


def board_findings(host: dict, present: set[str]) -> list[str]:
    mapped = boards(host)
    return ([f"missing {mapped[s]} board {s}" for s in sorted(set(mapped) - present)]
            + [f"unmapped board {s}" for s in sorted(present - set(mapped))])


def present_boards(ssh: str) -> set[str]:
    ssh_target = ssh.split()[0]
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_target,
                          "ls /dev/serial/by-id 2>/dev/null"], capture_output=True, text=True, timeout=30)
    if out.returncode not in (0, 2):
        raise RuntimeError(out.stderr.strip() or f"ssh {ssh_target} failed")
    return set(OPENRB.findall(out.stdout))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("show", "check"))
    args = parser.parse_args(argv)
    site = load()
    if args.command == "show":
        print(json.dumps(site, indent=1, ensure_ascii=False, default=str))
        return 0
    failed = False
    for name, host in site["hosts"].items():
        if not host.get("arms"):
            continue
        try:
            findings = board_findings(host, present_boards(str(host["ssh"])))
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            findings = [f"unreachable: {error}"]
        failed |= bool(findings)
        print(f"{name}: " + ("; ".join(findings) if findings else f"{len(boards(host))} boards match"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
