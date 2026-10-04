"""Resolve the expected site through mDNS; never derive identity from TXT."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import ipaddress
import re
from urllib.parse import urlsplit
from pathlib import Path

from core_common.discover import get_shared_cache

from core_common.protocol.discovery_txt import (
    FLEET as SERVICE_TYPE, HOSTNAME, REQUIRED, Accepted, classify, parse_txt_pairs,
)

HEALTH_MAX_BYTES = 1024


class DiscoveryConflict(ValueError):
    """A competing identity requires an operator, rather than automatic retries."""


class DiscoveryUnavailable(ValueError):
    """The approved peer is temporarily absent."""


def directory_candidate(url, hostname):
    """Local approved routing policy; TLS identity remains the pinned hostname."""
    if not isinstance(url, str) or any(ord(c) <= 32 for c in url):
        raise ValueError('approved directory URL must be a WSS URL')
    parsed = urlsplit(url)
    if (parsed.scheme != 'wss' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path != '/ws/robots'
            or '?' in url or '#' in url or parsed.netloc.endswith(':')
            or not 1 <= (parsed.port or 443) <= 65535):
        raise ValueError('approved directory URL requires wss and canonical /ws/robots')
    if parsed.port == 0:
        raise ValueError('approved directory port is invalid')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
        if len(parsed.hostname) > 253 or not all(re.fullmatch(label, item)
                                               for item in parsed.hostname.split('.')):
            raise ValueError('approved directory hostname is invalid')
    else:
        if address.is_unspecified or address.is_multicast or '%' in parsed.hostname:
            raise ValueError('approved directory address is invalid')
    return {'hostname': hostname, 'address': parsed.hostname, 'port': parsed.port or 443}


def approved_profile(fleet_cfg):
    discovery = fleet_cfg.get('discovery')
    if discovery is None or discovery == {}:
        return None
    if not isinstance(discovery, dict):
        raise ValueError('fleet.discovery must be a mapping')
    hostname, ca_file = discovery.get('expected_hostname'), discovery.get('ca_file')
    if not isinstance(hostname, str) or not HOSTNAME.fullmatch(hostname.lower().rstrip('.')):
        raise ValueError('fleet.discovery requires an approved .local hostname')
    if not isinstance(ca_file, str) or not Path(ca_file).is_absolute():
        raise ValueError('fleet.discovery requires an absolute site CA path')
    profile = {'expected_hostname': hostname.lower().rstrip('.'), 'ca_file': ca_file}
    allow = discovery.get('allow_dns_fallback', False)
    if not isinstance(allow, bool):
        raise ValueError('fleet.discovery.allow_dns_fallback must be a boolean')
    url = discovery.get('approved_directory_url')
    if allow:
        directory_candidate(url, profile['expected_hostname'])
        profile['approved_directory_url'] = url
    elif url is not None:
        raise ValueError('approved directory URL requires explicit allow_dns_fallback')
    return profile


class FleetLocation(str):
    def __new__(cls, hostname, address, port):
        value = str.__new__(cls, f'https://{hostname}:{port}')
        value.address = address
        value.port = port
        return value


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
                 runner=None, probe=probe_health, cache=None, approved_directory_url=None) -> str:
    """Return a site URL only after a unique DNS-SD result and pinned TLS probe."""
    hostname = expected_hostname.lower().rstrip(".")
    if not HOSTNAME.fullmatch(hostname):
        raise ValueError("expected .local hostname is invalid")
    if not ca_file.is_file():
        raise ValueError("site CA file is missing")
    directory = (directory_candidate(approved_directory_url, hostname)
                 if approved_directory_url is not None else None)
    if runner is not None:
        # Compatibility for scripts/tests injecting the legacy Avahi adapter.
        result = runner(["avahi-browse", "-r", "-t", "-p", "-k", SERVICE_TYPE],
                        capture_output=True, text=True, check=True, timeout=12)
        candidates = parse_avahi(result.stdout)
        # Invalid matching advertisements are not absence. In particular, a
        # forged plaintext hint cannot trigger a different connection route.
        for line in result.stdout.splitlines():
            fields = line.split(';', 9)
            if len(fields) > 6 and fields[0] == '=' and fields[4] == SERVICE_TYPE \
                    and fields[6].lower().rstrip('.') == hostname:
                try:
                    valid = len(fields) == 10 and isinstance(classify(
                        SERVICE_TYPE, fields[6], fields[7], int(fields[8]),
                        parse_txt_pairs(fields[9])), Accepted)
                except ValueError:
                    valid = False
                if not valid:
                    raise DiscoveryConflict('expected Fleet host not found: invalid advertisement')
    else:
        candidates = []
        records = (cache or get_shared_cache()).wait(SERVICE_TYPE, timeout_s=3)
        same_host = [r for r in records if r.host.lower().rstrip('.') == hostname]
        for row in same_host:
            if not row.addresses or not isinstance(classify(
                    SERVICE_TYPE, row.host, None, row.port, list(row.txt)), Accepted) \
                    or not any(isinstance(classify(SERVICE_TYPE, row.host, address,
                        row.port, list(row.txt)), Accepted) for address in row.addresses):
                raise DiscoveryConflict('expected Fleet host not found: invalid advertisement')
        if any(set(a.addresses).isdisjoint(b.addresses) for a in same_host for b in same_host):
            raise DiscoveryConflict('ambiguous Fleet host advertisement')
        for item in records:
            for address in item.addresses:
                result = classify(SERVICE_TYPE, item.host, address, item.port, list(item.txt))
                if isinstance(result, Accepted):
                    row = {"hostname": result.host, "address": address, "port": item.port}
                    if row not in candidates:
                        candidates.append(row)
    matches = [item for item in candidates if item["hostname"] == hostname]
    if not matches:
        if directory is None:
            raise DiscoveryUnavailable("expected Fleet host not found")
        probe(directory, hostname, ca_file)
        return FleetLocation(hostname, directory['address'], directory['port'])
    if (runner is not None and len(matches) != 1) or len({row['port'] for row in matches}) != 1:
        raise DiscoveryConflict("ambiguous Fleet host advertisement")
    candidate = min(matches, key=lambda row: row['address'])
    probe(candidate, hostname, ca_file)
    return FleetLocation(hostname, candidate['address'], candidate['port'])
