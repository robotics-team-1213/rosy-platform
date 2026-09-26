#!/usr/bin/env python3
"""Advertise a ROSY Fleet site or locate its TLS-verified LAN endpoint."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import shlex
import socket
import ssl
import subprocess
import tempfile
from pathlib import Path


SERVICE_TYPE = "_rosy-fleet._tcp"
HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
TXT = {"product": "rosy", "role": "fleet", "proto": "site-v1", "tls": "required"}


def render_service(port: int) -> str:
    if not 1 <= port <= 65535:
        raise ValueError("invalid site HTTPS port")
    records = "".join(f"    <txt-record>{key}={value}</txt-record>\n"
                      for key, value in TXT.items())
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<service-group>\n'
            '  <name replace-wildcards="yes">ROSY Fleet %h</name>\n'
            '  <service>\n'
            f'    <type>{SERVICE_TYPE}</type>\n'
            f'    <port>{port}</port>\n'
            f'{records}'
            '  </service>\n'
            '</service-group>\n')


def publish_service(output: Path, port: int) -> None:
    """Avahi watches its service directory; replace the complete XML atomically."""
    payload = render_service(port)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                     prefix=".rosy-fleet-", suffix=".tmp",
                                     delete=False) as stream:
        temp = Path(stream.name)
        stream.write(payload)
    try:
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)


def parse_avahi(output: str) -> list[dict]:
    """Accept only resolved LAN records for this version of the site API."""
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


def select_candidate(candidates: list[dict], expected_hostname: str) -> dict:
    if not expected_hostname:
        raise ValueError("expected hostname is required")
    expected = expected_hostname.lower().rstrip(".")
    if not HOSTNAME.fullmatch(expected):
        raise ValueError("expected .local hostname is invalid")
    matches = [item for item in candidates if item["hostname"] == expected]
    if not matches:
        raise ValueError("expected Fleet host not found")
    if len(matches) != 1:
        raise ValueError("ambiguous Fleet host advertisement")
    return matches[0]


def probe_health(address: str, port: int, hostname: str, ca_file: Path) -> None:
    """Connect to resolved IP, but verify the cert against the expected DNS name."""
    context = ssl.create_default_context(cafile=str(ca_file))
    with socket.create_connection((address, port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=hostname) as secured:
            secured.settimeout(5)
            secured.sendall((f"GET /healthz HTTP/1.1\r\nHost: {hostname}\r\n"
                             "Connection: close\r\n\r\n").encode("ascii"))
            response = http.client.HTTPResponse(secured)
            response.begin()
            if response.status != 200:
                raise ValueError("Fleet HTTPS health probe failed")
            body = response.read(1025)
            if len(body) > 1024 or json.loads(body) != {"status": "ok"}:
                raise ValueError("unexpected Fleet health response")


def verify_endpoint(candidate: dict, expected_hostname: str, ca_file: Path) -> str:
    selected = select_candidate([candidate], expected_hostname)
    if not ca_file.is_file():
        raise ValueError("site CA file is missing")
    probe_health(selected["address"], selected["port"], selected["hostname"], ca_file)
    return f"https://{selected['hostname']}:{selected['port']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="install Avahi service XML on the site host")
    publish.add_argument("--port", type=int, required=True)
    publish.add_argument("--output", type=Path,
                         default=Path("/etc/avahi/services/rosy-fleet.service"))
    discover = commands.add_parser("discover", help="list or verify discovered Fleet sites")
    discover.add_argument("--expect-hostname")
    discover.add_argument("--ca-file", type=Path)
    args = parser.parse_args()
    if args.command == "publish":
        publish_service(args.output, args.port)
        return 0
    if bool(args.expect_hostname) != bool(args.ca_file):
        parser.error("--expect-hostname and --ca-file are required together")
    result = subprocess.run(["avahi-browse", "-r", "-t", "-p", "-k", SERVICE_TYPE],
                            capture_output=True, text=True, check=True, timeout=12)
    candidates = parse_avahi(result.stdout)
    if args.expect_hostname:
        selected = select_candidate(candidates, args.expect_hostname)
        print(verify_endpoint(selected, args.expect_hostname, args.ca_file))
    else:
        print(json.dumps(candidates, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
