"""Resolve the expected site through mDNS; never derive identity from TXT."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from pathlib import Path

from core_common.discover import get_shared_cache

from core_common.protocol.discovery_txt import (
    FLEET as SERVICE_TYPE, HOSTNAME, REQUIRED, Accepted, classify, parse_txt_pairs,
)

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
            or ("role" in payload and payload["role"] != REQUIRED[SERVICE_TYPE]["role"])):
        raise ValueError("unexpected Fleet health response")


def parse_avahi(output: str) -> list[dict]:
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
        result = classify(SERVICE_TYPE, columns[6], columns[7], port,
                          parse_txt_pairs(columns[9]))
        if not isinstance(result, Accepted):
            continue
        row = {"hostname": result.host, "address": columns[7], "port": port}
        candidates[(result.host, columns[7], port)] = row
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
            check_health_body(response.read(HEALTH_MAX_BYTES + 1))


def locate_fleet(expected_hostname: str, ca_file: Path, *,
                 runner=None, probe=probe_health, cache=None) -> str:
    """Return a site URL only after a unique DNS-SD result and pinned TLS probe."""
    hostname = expected_hostname.lower().rstrip(".")
    if not HOSTNAME.fullmatch(hostname):
        raise ValueError("expected .local hostname is invalid")
    if not ca_file.is_file():
        raise ValueError("site CA file is missing")
    if runner is not None:
        # Compatibility for scripts/tests injecting the legacy Avahi adapter.
        result = runner(["avahi-browse", "-r", "-t", "-p", "-k", SERVICE_TYPE],
                        capture_output=True, text=True, check=True, timeout=12)
        candidates = parse_avahi(result.stdout)
    else:
        candidates = []
        for item in (cache or get_shared_cache()).wait(SERVICE_TYPE, timeout_s=3):
            for address in item.addresses:
                result = classify(SERVICE_TYPE, item.host, address, item.port, list(item.txt))
                if isinstance(result, Accepted):
                    row = {"hostname": result.host, "address": address, "port": item.port}
                    if row not in candidates:
                        candidates.append(row)
    matches = [item for item in candidates if item["hostname"] == hostname]
    if not matches:
        raise ValueError("expected Fleet host not found")
    if len(matches) != 1:
        raise ValueError("ambiguous Fleet host advertisement")
    candidate = matches[0]
    probe(candidate, hostname, ca_file)
    return f"https://{hostname}:{candidate['port']}"
