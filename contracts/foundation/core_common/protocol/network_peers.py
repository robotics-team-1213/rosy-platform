"""D-452 bounded public peer metadata; no credentials or authority grants."""
from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .discovery_txt import DOCK, FLEET, MODEL, OVERHEAD, ROBOT, SIGNAL, HOSTNAME

ROLE_SERVICES = {
    'robot': (ROBOT, ('http', 'https')),
    'fleet': (FLEET, ('https',)),
    'overhead-camera': (OVERHEAD, ('https',)),
    'dock': (DOCK, ('http',)),
    'signal': (SIGNAL, ('http',)),
    'model-host': (MODEL, ('ssh',)),
}
Role = Literal['robot', 'fleet', 'overhead-camera', 'dock', 'signal', 'model-host', 'pilot', 'cam']


class PeerObservation(BaseModel):
    """An endpoint hint, or an application presence with no inbound listener."""
    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1, max_length=96)
    role: Role
    transport: Literal['http', 'https', 'ssh', 'session']
    service_type: str | None = None
    hostname: str | None = None
    address: str | None = None
    port: int | None = Field(default=None, strict=True, ge=1, le=65535)

    @field_validator('name')
    @classmethod
    def visible_name(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError('peer name contains control characters')
        return value

    @model_validator(mode='after')
    def role_endpoint(self):
        if self.role in ('pilot', 'cam'):
            if self.transport != 'session' or any(value is not None for value in
                    (self.service_type, self.hostname, self.address, self.port)):
                raise ValueError('client presence has no inbound service endpoint')
        else:
            kind, transports = ROLE_SERVICES[self.role]
            if self.service_type != kind or self.transport not in transports:
                raise ValueError('peer role, service type and transport differ')
            directory = getattr(self, 'provenance', None) == 'approved-directory'
            if self.port is None:
                raise ValueError('service requires its approved or resolved port')
            if directory:
                if self.hostname is None and self.address is None:
                    raise ValueError('directory requires its approved DNS or legacy address')
                if self.hostname is not None:
                    try:
                        ipaddress.ip_address(self.hostname)
                    except ValueError:
                        pass
                    else:
                        raise ValueError('literal address belongs in address, not hostname')
                    labels = self.hostname.split('.')
                    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
                    if len(self.hostname) > 253 or len(labels) < 2 or not all(
                            re.fullmatch(label, item) for item in labels):
                        raise ValueError('approved directory hostname must be normalized DNS')
            elif self.hostname is None or not HOSTNAME.fullmatch(self.hostname) or self.address is None:
                raise ValueError('resolved mDNS endpoint requires .local and an address')
            if self.address is not None:
                ip = ipaddress.ip_address(self.address)
                if directory:
                    if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local:
                        raise ValueError('directory address must be a routable unicast hint')
                elif ip.version != 4 or not any(ip in ipaddress.ip_network(net) for net in
                        ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                    raise ValueError('mDNS address must be RFC1918 IPv4')
        return self


class PeerSummary(PeerObservation):
    """Approval and verified readiness come from the endpoint owner, never TXT."""
    peer_id: str | None = Field(default=None, min_length=1, max_length=96)
    provenance: Literal['mdns', 'approved-directory']
    freshness: Literal['fresh', 'expired', 'conflict', 'unavailable']
    approval: Literal['approved', 'unapproved'] = 'unapproved'
    readiness: Literal['unknown', 'verified', 'unreachable'] = 'unknown'

    @model_validator(mode='after')
    def independent_evidence(self):
        if self.provenance == 'approved-directory' and self.approval != 'approved':
            raise ValueError('directory provenance requires an approved identity')
        if self.approval == 'approved' and self.peer_id is None:
            raise ValueError('approval requires a directory identity')
        if self.approval == 'unapproved' and self.peer_id is not None:
            raise ValueError('unapproved hint has no authenticated peer identity')
        if self.readiness == 'verified' and (self.approval != 'approved' or self.freshness != 'fresh'):
            raise ValueError('verified readiness requires fresh approved owner evidence')
        return self


class PeerCatalogue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    peers: list[PeerSummary] = Field(default_factory=list, max_length=64)
    scanner_state: Literal['never_seen', 'online', 'expired'] = 'never_seen'
    scanner_age_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
