"""Public, operator-provisioned TLS bindings for existing encrypted enrollments."""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import stat
from typing import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import Encoding

from core_common.protocol.discovery_txt import HOSTNAME
from fleet.swarm.robots import RobotEndpoint


class EnrollmentTlsError(ValueError):
    """Public refusal: never include credential or certificate bytes."""


def _public_file(path: str | Path, limit: int) -> bytes:
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise EnrollmentTlsError('TLS config paths must be absolute')
    # Anchored directory descriptors prevent ancestor symlink substitutions on Linux.
    allowed = {0, os.geteuid()} if hasattr(os, 'geteuid') else set()

    def safe(info, directory=False):
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise EnrollmentTlsError('TLS config path type is unsafe')
        if os.name != 'nt':
            sticky_root = directory and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in allowed or (info.st_mode & 0o022 and not sticky_root):
                raise EnrollmentTlsError('TLS config owner or permissions are unsafe')
        if not directory and info.st_nlink != 1:
            raise EnrollmentTlsError('TLS config hardlinks are refused')
    fd = None
    try:
        if os.name == 'nt':
            # Host tests use Windows; deployment owner/mode enforcement is Linux-only.
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise EnrollmentTlsError('TLS config symlinks are refused')
            fd = os.open(path, os.O_RDONLY | os.O_BINARY)
        else:
            fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            safe(os.fstat(fd), True)
            for part in path.parts[1:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
                safe(os.fstat(fd), True)
            next_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        before = os.fstat(fd)
        safe(before)
        if before.st_size > limit:
            raise EnrollmentTlsError('TLS config exceeds its size limit')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(4096, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise EnrollmentTlsError('TLS config changed while reading')
        return bytes(data)
    except OSError:
        raise EnrollmentTlsError('TLS config is missing or unreadable') from None
    finally:
        if fd is not None:
            os.close(fd)


@dataclass(frozen=True)
class EnrolledTlsBinding:
    robot_id: str
    hostname: str
    port: int
    tls_ca_file: str
    tls_ca_sha256: str

    def context(self) -> ssl.SSLContext:
        pem = _public_file(self.tls_ca_file, 16384)
        try:
            certificates = x509.load_pem_x509_certificates(pem)
            if len(certificates) != 1:
                raise ValueError()
            cert = certificates[0]
            if hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest() != self.tls_ca_sha256:
                raise ValueError()
            now = datetime.now(timezone.utc)
            if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
                raise ValueError()
            if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                raise ValueError()
            if not cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
                raise ValueError()
            cert.verify_directly_issued_by(cert)
            context = ssl.create_default_context(cadata=cert.public_bytes(Encoding.PEM).decode('ascii'))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            return context
        except (ValueError, TypeError, x509.ExtensionNotFound, InvalidSignature):
            raise EnrollmentTlsError('configured TLS CA is invalid, expired or changed') from None


class EnrolledTlsBindings:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._approved = self._read()
        for binding in self._approved.values():
            binding.context()

    def _read(self) -> dict[str, EnrolledTlsBinding]:
        try:
            def unique(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            document = json.loads(_public_file(self.path, 65536), object_pairs_hook=unique)
            if (set(document) != {'version', 'robots'} or document['version'] != 'rosy.enrolled-tls/1'
                    or not isinstance(document['robots'], list) or len(document['robots']) > 64):
                raise ValueError()
            bindings = {}
            fields = {'robot_id', 'hostname', 'port', 'tls_ca_file', 'tls_ca_sha256'}
            for row in document['robots']:
                if not isinstance(row, dict) or set(row) != fields:
                    raise ValueError()
                binding = EnrolledTlsBinding(**row)
                if (not isinstance(binding.robot_id, str) or not binding.robot_id
                        or len(binding.robot_id) > 64 or binding.robot_id in bindings
                        or not isinstance(binding.hostname, str) or not HOSTNAME.fullmatch(binding.hostname)
                        or type(binding.port) is not int or not 1 <= binding.port <= 65535
                        or not isinstance(binding.tls_ca_sha256, str) or len(binding.tls_ca_sha256) != 64
                        or any(c not in '0123456789abcdef' for c in binding.tls_ca_sha256)
                        or not isinstance(binding.tls_ca_file, str)):
                    raise ValueError()
                bindings[binding.robot_id] = binding
            return bindings
        except (ValueError, TypeError, KeyError):
            raise EnrollmentTlsError('invalid enrolled TLS binding file') from None

    def validate(self, rows: list[dict]) -> list[str]:
        """Return pending robot_ids: approved (the root-owned file) but not enrolled yet."""
        rows = {row['robot_id']: row for row in rows}
        owners = {}
        for robot_id, row in rows.items():
            name = str(row['hostname']).lower().rstrip('.')
            owners[name if name.endswith('.local') else name + '.local'] = robot_id
        for robot_id, binding in self._approved.items():
            owner = owners.get(binding.hostname)
            # An enrolled binding names its own row; a pending one may not name another robot's row.
            if owner != robot_id and (robot_id in rows or owner is not None):
                raise EnrollmentTlsError('TLS hostname differs from enrolled identity')
        return sorted(self._approved.keys() - rows.keys())

    def claims(self, hostnames: set[str], robot_ids: set[str]) -> bool:
        """True when an approved binding (pending or bound) owns one of these names or ids."""
        names = {name.lower().rstrip('.') for name in hostnames if name}
        names |= {name + '.local' for name in names if not name.endswith('.local')}
        return any(b.hostname in names or b.robot_id in robot_ids for b in self._approved.values())

    def pending(self, rows: list[dict], hostname: str, port: int) -> EnrolledTlsBinding | None:
        """The one unenrolled binding at this hostname:port. Selection only: TLS proves it."""
        enrolled = {row['robot_id'] for row in rows}
        name = hostname.lower().rstrip('.')
        found = [b.robot_id for b in self._approved.values()
                 if b.robot_id not in enrolled and b.hostname == name and b.port == port]
        return self.binding(found[0]) if len(found) == 1 else None

    def binding(self, robot_id: str) -> EnrolledTlsBinding | None:
        original = self._approved.get(robot_id)
        # Once bound in this process, removal or replacement never selects legacy HTTP.
        if self._read() != self._approved:
            raise EnrollmentTlsError('TLS bindings changed; explicit reviewed restart required')
        if original:
            original.context()
        return original

    def endpoint(self, row: dict, access_token: str) -> RobotEndpoint:
        binding = self.binding(row['robot_id'])
        if binding is None:
            return RobotEndpoint(row['robot_id'], 'http://' + row['address'], access_token)
        return RobotEndpoint(row['robot_id'], f'https://{binding.hostname}:{binding.port}', access_token,
                             tls_ca_file=binding.tls_ca_file, discovery=True)

    def markers(self, rows: list[dict]) -> list[dict]:
        pending = self.validate(rows)
        return [dict(robot_id=b.robot_id, origin=f'https://{b.hostname}:{b.port}', ca_sha256=b.tls_ca_sha256)
                for robot_id in self._approved if robot_id not in pending for b in [self.binding(robot_id)]]


class EnrollmentIdentityTransport(httpx.AsyncBaseTransport):
    """Below DiscoveryTransport: authenticate the same selected TLS location before secrets."""

    def __init__(self, endpoint: RobotEndpoint, bindings: EnrolledTlsBindings,
                 inner: httpx.AsyncBaseTransport | None = None):
        self.endpoint, self.bindings = endpoint, bindings
        self.before_send: Callable[[httpx.Request], None] | None = None
        self.context = bindings.binding(endpoint.robot_id).context()
        self.inner = inner or httpx.AsyncHTTPTransport(verify=self.context, retries=0)

    async def identity(self, target: httpx.URL, extensions: dict) -> None:
        binding = self.bindings.binding(self.endpoint.robot_id)
        if binding is None:
            raise EnrollmentTlsError('approved TLS binding is missing')
        probe = httpx.Request('GET', target.copy_with(path='/api/v1/auth/peer-pairing/identity', query=b''),
                              headers={'Host': f'{binding.hostname}:{binding.port}'}, extensions=extensions)
        response = await self.inner.handle_async_request(probe)
        try:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 16384:
                    raise EnrollmentTlsError('TLS identity response exceeds its limit')
            from core_common.protocol.peer_pairing import IdentitySnapshot
            identity = IdentitySnapshot.model_validate_json(bytes(body))
            if response.status_code != 200 or identity.receiver_id != self.endpoint.robot_id:
                raise EnrollmentTlsError('authenticated TLS receiver identity differs')
            if identity.tls_hostname is not None and identity.tls_hostname != binding.hostname:
                raise EnrollmentTlsError('authenticated TLS receiver hostname differs')
            if identity.tls_ca_sha256 is not None and identity.tls_ca_sha256 != binding.tls_ca_sha256:
                raise EnrollmentTlsError('authenticated TLS receiver CA differs')
        except (ValueError, TypeError):
            raise EnrollmentTlsError('authenticated TLS receiver identity unavailable or changed') from None
        finally:
            await response.aclose()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await self.identity(request.url, request.extensions)
        if self.before_send is not None:
            self.before_send(request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()
