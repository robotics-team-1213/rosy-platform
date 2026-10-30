"""Which ROSY robots are on the lab LAN and what release each runs; read-only.

    python tools/remote/robot_status.py [--via user@host]

Browses ``_rosy._tcp`` with avahi on a lab PC on the robot LAN (``--via``, default the site host,
which runs Fleet's scanner; the model and AI PCs have no avahi-utils) and lists every robot this
PC knows (``lab_hosts.robots()``) and every other robot found, with the release, stage and tls each
advertises. A robot older than the newest one found is BEHIND. The newest published ``payload-*``
release (gh) is printed too: a robot already past it gets no update from the channel. Exit 1 when a
known robot is not found. Nothing on a robot is touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts  # noqa: E402
from core_common.protocol.discovery_txt import parse_txt_pairs  # noqa: E402

REPO = "robotics-team-1213/rosy-platform"
BROWSE = "timeout 8 avahi-browse -rpt _rosy._tcp"


def parse_browse(text: str) -> dict[str, dict]:
    """Resolved IPv4 robot rows of ``avahi-browse -rpt``, keyed by host name without ``.local``."""
    found = {}
    for line in text.splitlines():
        fields = line.split(";", 9)
        if len(fields) != 10 or fields[0] != "=" or fields[2] != "IPv4":
            continue
        txt = dict(parse_txt_pairs(fields[9]))
        # Old robot images advertise no role (discovery_txt LEGACY_ALLOWED).
        if txt.get("role", "robot") != "robot":
            continue
        found[fields[6].removesuffix(".local")] = {
            "address": fields[7], **{key: txt.get(key, "") for key in ("release", "stage", "tls")}}
    return found


def report(known: dict[str, str], found: dict[str, dict]) -> tuple[list[str], bool]:
    """Lines for every known robot, then the unknown ones found; True when a known robot is missing."""
    newest = max((row["release"] for row in found.values()), default="")
    by_address = {row["address"]: name for name, row in found.items()}
    lines, missing, shown = [], False, set()
    for robot_id, address in sorted(known.items()):
        name = address.removesuffix(".local") if address.endswith(".local") else by_address.get(address)
        if name not in found:
            lines.append(f"{robot_id:<6} NOT FOUND ({address})")
            missing = True
            continue
        shown.add(name)
        lines.append(f"{robot_id:<6} {line(name, found[name], newest)}")
    lines += [f"{'?':<6} {line(name, row, newest)} (not in lab_hosts.robots())"
              for name, row in sorted(found.items()) if name not in shown]
    return lines, missing


def line(name: str, row: dict, newest: str) -> str:
    behind = " BEHIND" if row["release"] and row["release"] < newest else ""
    return (f"{name:<18} {row['address']:<15} {row['release'] or '-':<15} {row['stage'] or '-':<12} "
            f"tls={row['tls'] or '-'}{behind}")


def published() -> str:
    """Newest published (not draft or prerelease) payload release id, or why it is unknown."""
    run = subprocess.run(["gh", "release", "list", "--repo", REPO, "--limit", "100", "--exclude-drafts",
                          "--exclude-pre-releases", "--json", "tagName"], capture_output=True, text=True)
    if run.returncode != 0:
        return f"unknown (gh exit {run.returncode})"
    ids = [tag.removeprefix("payload-").removeprefix("v2-") for tag in
           (item["tagName"] for item in json.loads(run.stdout)) if tag.startswith("payload-")]
    return max(ids, default="none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--via", help="ssh target on the robot LAN with avahi-utils (default: site_host)")
    args = parser.parse_args(argv)
    via = args.via or lab_hosts.site_host()
    if not via:
        parser.error("no --via and no site_host in private/lab-hosts.json")
    run = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", via, BROWSE],
                         capture_output=True, text=True, timeout=60)
    if run.returncode not in (0, 124) and not run.stdout:
        hint = "; avahi-utils is not installed there, pass --via <host with it>" if run.returncode == 127 else ""
        detail = run.stderr.strip()[-300:]
        print(f"avahi-browse on {via} failed (exit {run.returncode}): {detail}{hint}", file=sys.stderr)
        return 2
    lines, missing = report(lab_hosts.robots(), parse_browse(run.stdout))
    print(f"via {via}; newest published payload: {published()}")
    print("\n".join(lines) or "no robots known or found")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
