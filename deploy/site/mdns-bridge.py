#!/usr/bin/env python3
"""Run on the Ubuntu site host: send one Avahi ROSY scan to Fleet over HTTPS."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shlex
import ssl
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
# Copy of core_common.protocol.discovery_txt for _rosy._tcp (this script cannot import it);
# test/test_site_mdns_bridge.py holds it to test/fixtures/protocol/discovery-txt.v1.json.
TXT = {"product": "rosy", "role": "robot", "proto": "core-v1", "tls": "none"}


def parse_avahi(output: str) -> list[dict]:
    devices = {}
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (len(columns) != 10 or columns[0] != "=" or columns[2] != "IPv4"
                or columns[4] != "_rosy._tcp" or columns[5] != "local"):
            continue
        hostname = columns[6].lower().rstrip(".")
        if not HOSTNAME.fullmatch(hostname):
            continue
        try:
            address = ipaddress.ip_address(columns[7])
            port = int(columns[8])
            pairs = [item.split("=", 1) for item in shlex.split(columns[9]) if "=" in item]
            txt = dict(pairs)
        except (ValueError, TypeError):
            continue
        # Old images advertise no common keys; they stay visible as legacy (profile line 26).
        legacy = not any(key in txt for key in TXT)
        if (address.version != 4 or not address.is_private or address.is_loopback
                or address.is_link_local or not 1 <= port <= 65535
                or len(pairs) != len(txt)
                or (not legacy and any(txt.get(key) != value for key, value in TXT.items()))
                or txt.get("network") != "sta" or not txt.get("name")):
            continue
        row = {"name": txt["name"], "hostname": hostname,
               "address": str(address), "port": port,
               "stage": txt.get("stage", ""), "release": txt.get("release", ""),
               "network": "sta"}
        devices.setdefault((row["name"], row["address"], row["port"]), row)
    return list(devices.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True,
                        help="site TLS URL ending /api/fleet/discovery/scan")
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "https" or url.path != "/api/fleet/discovery/scan":
        parser.error("--url must be the HTTPS discovery scan endpoint")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if not token:
        parser.error("scanner token file is empty")
    result = subprocess.run(["avahi-browse", "-r", "-t", "-p", "-k", "_rosy._tcp"],
                            capture_output=True, text=True, timeout=12, check=True)
    devices = parse_avahi(result.stdout)
    if len(devices) > 64:
        raise SystemExit("too many ROSY services; refusing scan")
    request = Request(args.url, data=json.dumps({"devices": devices}).encode("utf-8"),
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"}, method="POST")
    with urlopen(request, context=ssl.create_default_context(cafile=str(args.ca_file)),
                 timeout=10) as response:
        if response.status != 200:
            raise SystemExit("Fleet rejected discovery scan")
    print(f"ROSY mDNS scan delivered: {len(devices)} service(s)")


if __name__ == "__main__":
    main()
