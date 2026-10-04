"""D-432 explicit, site-scoped development approval; never a runtime motion mode."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .discovery_txt import HOSTNAME

SERVICE_TYPES = frozenset({'_rosy._tcp', '_rosy-fleet._tcp', '_rosy-overhead._tcp',
                           '_rosy-dock._tcp', '_rosy-signal._tcp'})


@dataclass(frozen=True)
class LinkPolicy:
    mode: str = 'paired'
    site_name: str = ''
    expires_at: float = 0
    devices: tuple[tuple[str, str, str], ...] = ()

    @classmethod
    def from_mapping(cls, data, *, deployment='development', now=None):
        if data is None or data == {'mode': 'paired'}:
            return cls()
        if not isinstance(data, dict) or data.get('mode') not in ('paired', 'development'):
            raise ValueError('invalid link mode')
        if data['mode'] == 'paired':
            if set(data) != {'mode'}:
                raise ValueError('paired policy cannot carry development scope')
            return cls()
        if deployment == 'production':
            raise ValueError('production cannot enable development link mode')
        if set(data) != {'mode', 'site_name', 'expires_at', 'devices'}:
            raise ValueError('development policy requires explicit site, expiry and device scope')
        if not isinstance(data['site_name'], str) or not data['site_name'].strip():
            raise ValueError('invalid development site name')
        try:
            expiry = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
            if expiry.tzinfo != timezone.utc:
                raise ValueError()
            deadline = expiry.timestamp()
        except (TypeError, AttributeError, ValueError, OverflowError):
            raise ValueError('invalid development expiry') from None
        if deadline <= (time.time() if now is None else now):
            raise ValueError('development policy has expired')
        rows = data['devices']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
            raise ValueError('development policy requires 1..64 devices')
        bindings = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'device_id', 'service_type', 'tls_host'}:
                raise ValueError('invalid device binding')
            device_id, service_type, host = (row[k] for k in ('device_id', 'service_type', 'tls_host'))
            if (not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 96
                    or not isinstance(service_type, str) or service_type not in SERVICE_TYPES
                    or not isinstance(host, str)
                    or not HOSTNAME.fullmatch(host)):
                raise ValueError('invalid device binding')
            binding = (device_id, service_type, host)
            if any((a == device_id and b == service_type) or (b == service_type and c == host)
                   for a, b, c in bindings):
                raise ValueError('duplicate development device binding')
            bindings.append(binding)
        return cls('development', data['site_name'], deadline, tuple(bindings))

    @classmethod
    def from_file(cls, path, *, deployment='development', now=None):
        raw = Path(path).read_bytes()
        if len(raw) > 32768:
            raise ValueError('development policy too large')
        return cls.from_mapping(json.loads(raw), deployment=deployment, now=now)

    def permits(self, device_id, service_type, tls_host, *, authenticated, now=None):
        return (self.mode == 'development' and authenticated is True
                and (time.time() if now is None else now) < self.expires_at
                and (device_id, service_type, tls_host) in self.devices)
