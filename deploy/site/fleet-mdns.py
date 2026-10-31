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
# Copy of core_common.protocol.discovery_txt for _rosy-fleet._tcp (this script cannot import it);
# test/test_site_fleet_mdns.py holds it to test/fixtures/protocol/discovery-txt.v1.json.
HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
TXT = {"product": "rosy", "role": "fleet", "proto": "site-v1", "tls": "required"}
OVERHEAD_TXT = {
    "product": "rosy", "role": "overhead-camera", "proto": "rosy-overhead/1",
    "tls": "required",
}
PAIR_TXT = ("pair", "rosy-pair/1")   # D-341 14: only when Fleet runs with --pairing-ca


def render_service(port: int, *, role: str = "fleet", tls_host: str | None = None,
                   pair: bool = False, camera_peer: bool = False) -> str:
    if not 1 <= port <= 65535:
        raise ValueError("invalid site HTTPS port")
    if pair and role != "overhead":
        raise ValueError("pair applies only to the overhead role")
    if camera_peer and not pair:
        raise ValueError('camera peer capability requires configured overhead pairing')
    if role == "fleet":
        service_type, service_name, metadata = SERVICE_TYPE, "ROSY Fleet %h", TXT
    elif role == "overhead":
        if not isinstance(tls_host, str) or not HOSTNAME.fullmatch(tls_host.lower().rstrip(".")):
            raise ValueError("overhead service needs a .local TLS hostname")
        service_type, service_name = "_rosy-overhead._tcp", "ROSY Vision %h"
        metadata = {**OVERHEAD_TXT, "tls_host": tls_host.lower().rstrip(".")}
        if pair:
            metadata[PAIR_TXT[0]] = PAIR_TXT[1]
        if camera_peer:
            metadata['peer'] = 'rosy.camera-peer/1'  # Capability hint, never readiness or trust.
    else:
        raise ValueError("unknown site mDNS role")
    records = "".join(f"    <txt-record>{key}={value}</txt-record>\n"
                      for key, value in metadata.items())
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<service-group>\n'
            f'  <name replace-wildcards="yes">{service_name}</name>\n'
            '  <service>\n'
            f'    <type>{service_type}</type>\n'
            f'    <port>{port}</port>\n'
            f'{records}'
            '  </service>\n'
            '</service-group>\n')


def publish_service(output: Path, port: int, *, role: str = "fleet",
                    tls_host: str | None = None, pair: bool = False, camera_peer: bool = False) -> None:
    """Avahi watches its service directory; replace the complete XML atomically."""
    payload = render_service(port, role=role, tls_host=tls_host, pair=pair, camera_peer=camera_peer)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                     prefix=".rosy-fleet-", suffix=".tmp",
                                     delete=False) as stream:
        temp = Path(stream.name)
        stream.write(payload)
    try:
        # DNS-SD XML contains public metadata. Avahi drops root privileges;
        # NamedTemporaryFile's 0600 default otherwise hides the new service.
        # Set permissions before rename, including under a restrictive umask.
        temp.chmod(0o644)
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)


def parse_txt_pairs(text: str) -> list[tuple[str, str]]:
    """Avahi's parsable ``"k=v" "k=v"`` column as ordered pairs; duplicates stay."""
    try:
        items = shlex.split(text)
    except ValueError:
        return []
    return [tuple(item.split("=", 1)) for item in items if "=" in item]


def _lan_ipv4(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return False
    return (ip.version == 4 and ip.is_private and not ip.is_loopback
            and not ip.is_link_local and not ip.is_multicast and not ip.is_unspecified)


def classify_fleet(host: str | None, address: str | None, port: object,
                   txt: list[tuple[str, str]]) -> str | None:
    """core_common classify() for _rosy-fleet._tcp: None if accepted, else the reason."""
    if host is not None and not HOSTNAME.fullmatch(host.strip().lower().rstrip(".")):
        return "bad_host"
    if address is not None and not _lan_ipv4(address):
        return "bad_address"
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return "bad_port"
    keys = [key for key, _ in txt]
    if len(keys) != len(set(keys)):
        return "duplicate_key"
    values = dict(txt)
    for key, expected in TXT.items():
        if key not in values:
            return "missing_key"
        if values[key] != expected:
            return "value_mismatch"
    return None


def parse_avahi(output: str) -> list[dict]:
    """Accept only resolved LAN records for this version of the site API."""
    candidates = {}
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (len(columns) != 10 or columns[0] != "=" or columns[2] != "IPv4"
                or columns[4] != SERVICE_TYPE or columns[5] != "local"):
            continue
        try:
            port = int(columns[8])
        except ValueError:
            continue
        if classify_fleet(columns[6], columns[7], port, parse_txt_pairs(columns[9])) is not None:
            continue
        hostname = columns[6].strip().lower().rstrip(".")
        row = {"hostname": hostname, "address": columns[7], "port": port}
        candidates[(hostname, columns[7], port)] = row
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


HEALTH_MAX_BYTES = 1024


def check_health_body(body: bytes) -> None:
    """Accept {"status":"ok"} and the D-370 extended shape; ignore unknown keys.

    A present ``role`` must match the role Fleet advertises in its DNS-SD TXT.
    """
    try:
        payload = json.loads(body) if len(body) <= HEALTH_MAX_BYTES else None
    except ValueError:
        payload = None
    if (not isinstance(payload, dict) or payload.get("status") != "ok"
            or ("role" in payload and payload["role"] != TXT["role"])):
        raise ValueError("unexpected Fleet health response")


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
            check_health_body(response.read(HEALTH_MAX_BYTES + 1))


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
    publish.add_argument("--role", choices=("fleet", "overhead"), default="fleet")
    publish.add_argument("--tls-host", help="certificate hostname for the overhead WSS endpoint")
    publish.add_argument("--pair", nargs="?", const="1", default="0", choices=("0", "1", ""),
                         help="overhead only: add TXT pair=rosy-pair/1 (D-341); off by default. "
                              "--pair or --pair=1 turns it on; --pair=0 and --pair= leave it off, "
                              "so a unit can pass --pair=${ROSY_SITE_PAIRING}")
    publish.add_argument("--output", type=Path)
    publish.add_argument('--camera-peer', default='0', choices=('0','1',''),
                         help='capability hint from resolved signed-site configuration; not readiness or trust')
    discover = commands.add_parser("discover", help="list or verify discovered Fleet sites")
    discover.add_argument("--expect-hostname")
    discover.add_argument("--ca-file", type=Path)
    args = parser.parse_args()
    if args.command == "publish":
        if args.role == "overhead" and not args.tls_host:
            parser.error("--tls-host is required for --role overhead")
        if args.pair == "1" and args.role != "overhead":
            parser.error("--pair applies only to --role overhead")
        if args.camera_peer == '1' and args.pair != '1':
            parser.error('--camera-peer requires configured overhead pairing')
        output = args.output or Path(f"/etc/avahi/services/rosy-{args.role}.service")
        publish_service(output, args.port, role=args.role, tls_host=args.tls_host,
                        pair=args.pair == "1", camera_peer=args.camera_peer == '1')
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
