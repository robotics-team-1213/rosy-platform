"""Resolve the expected site through mDNS; never derive identity from TXT."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import shlex
import socket
import ssl
import subprocess
from pathlib import Path


SERVICE_TYPE = "_rosy-fleet._tcp"
HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
TXT = {"product": "rosy", "role": "fleet", "proto": "site-v1", "tls": "required"}


def parse_avahi(output: str) -> list[dict]:
    candidates = {}
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (len(columns) != 10 or columns[0] != "=" or columns[2] != "IPv4"
                or columns[4] != SERVICE_TYPE or columns[5] != "local"):
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
        if (address.version != 4 or not address.is_private or address.is_loopback
                or address.is_link_local or not 1 <= port <= 65535
                or len(pairs) != len(txt) or any(txt.get(key) != value for key, value in TXT.items())):
            continue
        row = {"hostname": hostname, "address": str(address), "port": port}
        candidates[(hostname, str(address), port)] = row
    return list(candidates.values())


def probe_health(candidate: dict, expected_hostname: str, ca_file: Path) -> None:
    context = ssl.create_default_context(cafile=str(ca_file))
    with socket.create_connection((candidate["address"], candidate["port"]), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=expected_hostname) as secured:
            secured.settimeout(5)
            secured.sendall((f"GET /healthz HTTP/1.1\r\nHost: {expected_hostname}\r\n"
                             "Connection: close\r\n\r\n").encode("ascii"))
            response = http.client.HTTPResponse(secured)
            response.begin()
            if response.status != 200:
                raise ValueError("Fleet HTTPS health probe failed")
            body = response.read(1025)
            if len(body) > 1024 or json.loads(body) != {"status": "ok"}:
                raise ValueError("unexpected Fleet health response")


def locate_fleet(expected_hostname: str, ca_file: Path, *,
                 runner=subprocess.run, probe=probe_health) -> str:
    """Return a site URL only after a unique DNS-SD result and pinned TLS probe."""
    hostname = expected_hostname.lower().rstrip(".")
    if not HOSTNAME.fullmatch(hostname):
        raise ValueError("expected .local hostname is invalid")
    if not ca_file.is_file():
        raise ValueError("site CA file is missing")
    result = runner(["avahi-browse", "-r", "-t", "-p", "-k", SERVICE_TYPE],
                    capture_output=True, text=True, check=True, timeout=12)
    matches = [item for item in parse_avahi(result.stdout) if item["hostname"] == hostname]
    if not matches:
        raise ValueError("expected Fleet host not found")
    if len(matches) != 1:
        raise ValueError("ambiguous Fleet host advertisement")
    candidate = matches[0]
    probe(candidate, hostname, ca_file)
    return f"https://{hostname}:{candidate['port']}"
