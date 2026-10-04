#!/usr/bin/env python3
"""Run on the Ubuntu site host: send one Avahi ROSY scan to Fleet over HTTPS (loopback)."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import re
import selectors
import shlex
import socket
import ssl
import subprocess
import time
from pathlib import Path


HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
TLS_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                      r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
TOKEN = re.compile(r"[\x21-\x7e]+")  # goes into an HTTP header: no CR/LF or control bytes
LOOPBACK = ("127.0.0.1", "::1")
SCAN_PATH = "/api/fleet/discovery/scan"
# Copy of core_common.protocol.discovery_txt for _rosy._tcp (this script cannot import it);
# test/test_site_mdns_bridge.py holds it to test/fixtures/protocol/discovery-txt.v1.json.
TXT = {"product": "rosy", "role": "robot", "proto": "core-v1", "tls": "none"}
SERVICE_TXT = {
    '_rosy._tcp': TXT,
    '_rosy-fleet._tcp': {'product': 'rosy', 'role': 'fleet', 'proto': 'site-v1', 'tls': 'required'},
    '_rosy-overhead._tcp': {'product': 'rosy', 'role': 'overhead-camera', 'proto': 'rosy-overhead/1', 'tls': 'required'},
    '_rosy-dock._tcp': {'product': 'rosy', 'role': 'dock', 'proto': 'rosy-dock/1', 'tls': 'none'},
    '_rosy-signal._tcp': {'product': 'rosy', 'role': 'signal', 'proto': 'rosy-signal/1', 'tls': 'none'},
    '_rosy-model._tcp': {'product': 'rosy', 'role': 'model-host', 'proto': 'ssh/2', 'tls': 'none', 'transport': 'ssh'},
}
MAX_SCAN_BYTES = 1024 * 1024


def parse_services(output: str) -> list[dict]:
    """Canonical six-role public hints; legacy robot rows stay in devices only."""
    services = {}
    for line in output.splitlines():
        columns = line.split(';', 9)
        if len(columns) != 10 or columns[0] != '=' or columns[2] != 'IPv4' or columns[5] != 'local':
            continue
        kind = columns[4]
        if kind not in SERVICE_TXT:
            continue
        try:
            host = columns[6].lower().rstrip('.')
            address = ipaddress.ip_address(columns[7])
            port = int(columns[8])
            pairs = [item.split('=', 1) for item in shlex.split(columns[9]) if '=' in item]
            txt = dict(pairs)
        except (ValueError, TypeError):
            continue
        expected = SERVICE_TXT[kind]
        if (not HOSTNAME.fullmatch(host) or address.version != 4 or not any(address in ipaddress.ip_network(net)
                for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
                or not 1 <= port <= 65535 or len(pairs) != len(txt)
                or any(txt.get(key) != value for key, value in expected.items()
                       if not (kind == '_rosy._tcp' and key == 'tls'))
                or (kind == '_rosy._tcp' and (txt.get('tls') not in ('none', 'required') or txt.get('network') == 'ap'))
                or (kind == '_rosy-overhead._tcp' and txt.get('tls_host', '').lower().rstrip('.') != host)):
            continue
        name = txt.get('name') or re.sub(r'\\(\d{3})', lambda match: chr(int(match[1])), columns[3])
        if not name or len(name) > 96 or any(ord(char) < 32 for char in name):
            continue
        transport = 'ssh' if kind == '_rosy-model._tcp' else ('https' if txt['tls'] == 'required' else 'http')
        row = {'name': name, 'role': expected['role'], 'transport': transport,
               'service_type': kind, 'hostname': host, 'address': str(address), 'port': port}
        services.setdefault((row['role'], host, row['address'], port), row)
    return list(services.values())


def scan_output(*, timeout_s=12) -> str:
    """One host-Avahi scan: total 12s, at most 1MiB output, child always reaped."""
    args = ['avahi-browse', '-a', '-r', '-t', '-p', '-k']
    deadline = time.monotonic() + timeout_s
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    output = bytearray()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(args, timeout_s)
            chunk = os.read(process.stdout.fileno(), min(65536, MAX_SCAN_BYTES - len(output) + 1))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_SCAN_BYTES:
                raise ValueError('Avahi scan exceeds output budget')
        code = process.wait(timeout=max(.001, deadline - time.monotonic()))
        if code:
            raise subprocess.CalledProcessError(code, args)
        return output.decode('utf-8', errors='replace')
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


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
                or (not legacy and any(txt.get(key) != value for key, value in TXT.items() if key != 'tls'))
                or (not legacy and txt.get('tls') not in ('none', 'required'))
                or txt.get("network") != "sta" or not txt.get("name")):
            continue
        row = {"name": txt["name"], "hostname": hostname,
               "address": str(address), "port": port,
               "stage": txt.get("stage", ""), "release": txt.get("release", ""),
               "network": "sta"}
        if not legacy:
            row['transport'] = 'https' if txt['tls'] == 'required' else 'http'
        devices.setdefault((row["name"], row["address"], row["port"]), row)
    return list(devices.values())


def valid_tls_host(name: str) -> bool:
    """A certificate DNS name (e.g. site-pc.local), never an IP literal."""
    try:
        ipaddress.ip_address(name)
        return False
    except ValueError:
        return bool(TLS_HOST.fullmatch(name))


def post_scan(devices: list[dict], *, tls_host: str, port: int, ca_file: Path,
              token: str, services: list[dict] | None = None) -> int:
    """POST to the site proxy on this host's loopback; TLS SNI, name check and Host are tls_host.

    Loopback exists whatever the LAN does, so a changed site subnet or a stale DNS/mDNS
    name cannot take the scanner offline; the site CA still proves it is the site proxy.
    """
    payload = {"devices": devices}
    if services is not None:
        payload['services'] = services
    body = json.dumps(payload).encode("utf-8")
    head = (f"POST {SCAN_PATH} HTTP/1.1\r\nHost: {tls_host}:{port}\r\n"
            f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
    context = ssl.create_default_context(cafile=str(ca_file))
    # Default from Python 3.13; set here so Ubuntu 24.04 (3.12) verifies the same way.
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    raw, error = None, None
    for address in LOOPBACK:  # 127.0.0.1 for a 127.0.0.1/0.0.0.0 bind, ::1 for "::"
        try:
            raw = socket.create_connection((address, port), timeout=5)
            break
        except OSError as failure:
            error = failure
    if raw is None:
        raise ConnectionError(f"site proxy is not listening on loopback port {port}: {error}")
    with raw, context.wrap_socket(raw, server_hostname=tls_host) as secured:
        secured.settimeout(10)
        secured.sendall(head.encode("ascii") + body)
        response = http.client.HTTPResponse(secured)
        response.begin()
        response.read(4096)
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # The unit gets both values from /run/rosy-site/site-public.env (written by
    # site-firewall.py apply from `docker compose config`); the port defaults to 8443 as in Compose.
    parser.add_argument("--tls-host", default=os.environ.get("ROSY_SITE_TLS_HOST", ""),
                        help="site certificate DNS name (default: $ROSY_SITE_TLS_HOST)")
    parser.add_argument("--port", default=os.environ.get("ROSY_SITE_HTTPS_PORT") or "8443",
                        help="published site HTTPS port (default: $ROSY_SITE_HTTPS_PORT or 8443)")
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args()
    tls_host = args.tls_host.strip().lower().rstrip(".")
    if not valid_tls_host(tls_host):
        parser.error("--tls-host must be the DNS name in the site certificate, not an IP")
    if not args.port.isdigit() or not 1 <= int(args.port) <= 65535:
        parser.error("--port must be a TCP port")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if not TOKEN.fullmatch(token):
        parser.error("scanner token file must hold one printable ASCII token without spaces")
    # Avahi failure raises here, before any POST: Fleet keeps the last good scan until
    # its lease expires and then shows the scanner offline.
    output = scan_output()
    devices = parse_avahi(output)
    services = [row for row in parse_services(output) if row['role'] != 'robot']
    if len(devices) + len(services) > 64:
        raise SystemExit("too many ROSY services; refusing scan")
    status = post_scan(devices, tls_host=tls_host, port=int(args.port), ca_file=args.ca_file,
                       token=token, services=services)
    if status != 200:
        raise SystemExit(f"Fleet rejected discovery scan (HTTP {status})")
    print(f"ROSY mDNS scan delivered: {len(devices)} service(s)")


if __name__ == "__main__":
    main()
