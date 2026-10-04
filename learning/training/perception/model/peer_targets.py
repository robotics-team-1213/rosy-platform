"""Locally approved robot roster to current SSH destinations (D-452).

DNS-SD supplies address hints only; SSH authenticates the logical roster name.
No advertisements add robots or alter keys, users, or fallback policy.
"""
from __future__ import annotations

import ipaddress
import re

DNS_NAME = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*'
                      r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
LEGACY = re.compile(r'[A-Za-z0-9._][A-Za-z0-9._-]*')


def validate(robot):
    """Validate local configuration, never materialize policy from an advert."""
    if not isinstance(robot, dict) or not isinstance(robot.get('name'), str) \
            or not LEGACY.fullmatch(robot['name']):
        raise ValueError('robots: invalid logical name')
    if 'expected_hostname' not in robot:
        if not isinstance(robot.get('host'), str) or not LEGACY.fullmatch(robot['host']):
            raise ValueError('robots: approved expected_hostname or legacy host is required')
        if 'mdns_hostname' in robot or 'allow_dns_fallback' in robot:
            raise ValueError('robots: discovery policy requires expected_hostname')
        return
    host = robot['expected_hostname']
    if not isinstance(host, str) or not DNS_NAME.fullmatch(host.lower().rstrip('.')):
        raise ValueError('robots: invalid approved hostname')
    if 'allow_dns_fallback' in robot and not isinstance(robot['allow_dns_fallback'], bool):
        raise ValueError('robots: allow_dns_fallback must be a boolean')
    local = robot.get('mdns_hostname')
    if local is not None:
        from core_common.protocol.discovery_txt import HOSTNAME
        if not isinstance(local, str) or not HOSTNAME.fullmatch(local.lower().rstrip('.')):
            raise ValueError('robots: mdns_hostname must be an approved .local hostname')
        if host.lower().rstrip('.').endswith('.local') and local.lower().rstrip('.') != host.lower().rstrip('.'):
            raise ValueError('robots: conflicting approved LAN hostnames')


def resolve(robot, *, cache=None):
    """Fresh cache snapshot for each operation; no stale destination retention."""
    validate(robot)
    if 'expected_hostname' not in robot:
        return robot['host']  # Explicit migration profile, SSH pins still mandatory.
    from core_common import discover
    from core_common.protocol.discovery_txt import ROBOT, Accepted, classify
    from deliver import SshFailure
    expected = robot['expected_hostname'].lower().rstrip('.')
    local = robot.get('mdns_hostname', expected if expected.endswith('.local') else None)
    if local is None:
        return expected  # Explicit approved DNS target, resolved by strict SSH.
    local = local.lower().rstrip('.')
    rows = (cache or discover.get_shared_cache()).wait(ROBOT, timeout_s=3)
    matches = [r for r in rows if r.host.lower().rstrip('.') == local]
    if len(matches) > 1:
        raise SshFailure('hostkey', 'conflicting robot discovery hints for approved identity')
    if matches:
        row = matches[0]
        accepted = classify(row.service_type, row.host, None, row.port, list(row.txt))
        if not isinstance(accepted, Accepted) or accepted.txt.get('robot_id', robot['name']) != robot['name']:
            raise SshFailure('hostkey', 'invalid robot discovery hint for approved identity')
        addresses = []
        for address in row.addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            # Existing SSH delivery accepts IPv4/DNS names; never substitute SRV
            # port (CORE API) for the independently approved SSH transport port.
            if isinstance(classify(row.service_type, row.host, str(ip), row.port, list(row.txt)), Accepted):
                addresses.append(str(ip))
        if addresses:
            return sorted(set(addresses))[0]
        raise SshFailure('unreachable', 'approved robot hint has no usable SSH address')
    if robot.get('allow_dns_fallback') is True:
        return expected
    raise SshFailure('dns', 'approved robot discovery hint is unavailable')
