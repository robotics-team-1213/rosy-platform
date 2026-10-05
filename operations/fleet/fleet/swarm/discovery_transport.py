"""D-432: resolve locations but authenticate the saved TLS hostname before secrets."""

import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

import httpx

from core_common.discover import get_shared_cache
from core_common.protocol.discovery_txt import ROBOT, Accepted, _lan_ipv4, classify
from fleet.swarm.robots import RobotEndpoint, _endpoint


def tls_context(endpoint: RobotEndpoint) -> ssl.SSLContext | None:
    _endpoint(endpoint.robot_id, endpoint.base_url, endpoint.token, 'robot endpoint',
              endpoint.fleet_pairing_token, endpoint.tls_ca_file, endpoint.discovery, endpoint.link_policy_file)
    if endpoint.tls_ca_file is None:
        return None
    context = ssl.create_default_context(cafile=endpoint.tls_ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def select_robot(endpoint: RobotEndpoint, records) -> tuple[str, int]:
    records = tuple(records)
    host = urlsplit(endpoint.base_url).hostname
    matches = set()
    for record in records:
        if record.host.lower().rstrip('.') != host:
            continue
        for address in record.addresses:
            result = classify(ROBOT, record.host, address, record.port, list(record.txt))
            if (isinstance(result, Accepted) and not result.legacy
                    and result.txt.get('tls') == 'required' and result.txt.get('network') != 'ap'):
                matches.add((address, record.port))
    if not matches:
        raise ValueError('not_discovered: trusted robot name not found')
    # Several addresses in one DNS-SD record can belong to one multi-NIC device;
    # independent records at disjoint locations must not silently win a race.
    rows = [r for r in records if r.host.lower().rstrip('.') == host and r.addresses]
    if len(rows) > 1 and any(set(a.addresses).isdisjoint(b.addresses)
                             for a in rows for b in rows):
        raise ValueError('conflict: robot name is advertised at disjoint locations')
    if len({port for _, port in matches}) != 1:
        raise ValueError('conflict: robot name advertises multiple ports')
    return min(matches, key=lambda item: (ipaddress.ip_address(item[0]).version, item[0]))


def _host_lan(host: str, port: int) -> str:
    """One private LAN IPv4 for a saved name whose DNS-SD browse is empty."""
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError('not_discovered: trusted robot name not found') from None
    found = []
    for info in infos:
        address = info[4][0]
        if _lan_ipv4(address) and address not in found:
            found.append(address)
    if not found:
        raise ValueError('not_discovered: trusted robot name not found')
    if len(found) > 1:
        raise ValueError('conflict: robot name is advertised at disjoint locations')
    return found[0]


async def resolve_robot(endpoint: RobotEndpoint, finder=None) -> tuple[str, int]:
    if endpoint.link_policy_file:
        # Re-read policy for expiry/revocation before each new outbound connection.
        _endpoint(endpoint.robot_id, endpoint.base_url, endpoint.token, 'robot endpoint',
                  endpoint.fleet_pairing_token, endpoint.tls_ca_file, endpoint.discovery,
                  endpoint.link_policy_file)
    finder = finder or get_shared_cache().wait
    records = tuple(await asyncio.wait_for(
        asyncio.to_thread(finder, ROBOT, timeout_s=3.0), timeout=4.0))
    try:
        return select_robot(endpoint, records)
    except ValueError as exc:
        if str(exc) != 'not_discovered: trusted robot name not found':
            raise
        parts = urlsplit(endpoint.base_url)
        host, port = parts.hostname, parts.port
        # A record for this name that fails classification stays a refusal.
        # An empty browse uses host Avahi and keeps the saved HTTPS port.
        if (host is None or port is None
                or any(record.host.lower().rstrip('.') == host for record in records)):
            raise
        return await asyncio.to_thread(_host_lan, host, port), port


class DiscoveryTransport(httpx.AsyncBaseTransport):
    def __init__(self, endpoint: RobotEndpoint, *, finder=None, inner=None):
        self.endpoint = endpoint
        self.finder = finder
        self.inner = inner or httpx.AsyncHTTPTransport(verify=tls_context(endpoint), retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        expected = urlsplit(self.endpoint.base_url)
        if (request.url.scheme != 'https' or request.url.host != expected.hostname
                or request.url.port != (expected.port or 443)):
            raise ValueError('discovery transport refuses a different origin')
        address, port = await resolve_robot(self.endpoint, self.finder)
        # httpcore's sni_hostname extension preserves certificate hostname checks
        # while the TCP destination is the current mDNS IP. No auth reaches HTTP
        # until that TLS handshake succeeds.
        outgoing = httpx.Request(request.method, request.url.copy_with(host=address, port=port),
                                 headers=request.headers, stream=request.stream,
                                 extensions={**request.extensions, 'sni_hostname': expected.hostname})
        return await self.inner.handle_async_request(outgoing)

    async def aclose(self):
        await self.inner.aclose()
