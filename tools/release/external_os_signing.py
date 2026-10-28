"""Validate exact RAUC inline manifests before operator-local external CMS signing."""
from __future__ import annotations

import configparser
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for relative in ('deploy/robot/pinky_pro/release', 'deploy/robot/pinky_pro/native'):
    sys.path.insert(0, str(ROOT / relative))
from os_update_manifest import COMPATIBLE, _digest, _fields, _integer, release_id
from signing import _openssl


def validate_inline_manifest(raw, expected, images):
    """Bind to authenticated distribution facts and owned-preparer image measurements."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16384:
        raise ValueError('external OS manifest exceeds its bound')
    try:
        identity = release_id(expected['release_id'])
        source = expected['source_revision']
        if not isinstance(source, str) or not re.fullmatch('[0-9a-f]{40}', source):
            raise ValueError('external OS source requires an exact commit')
        factory = expected['native_factory']
        _fields(factory, {'release_id', 'checksums_sha256'})
        release_id(factory['release_id'])
        _digest(factory['checksums_sha256'])
        _integer(expected['boot_abi'], 2, 2)
        schema = expected['state_schema']
        _fields(schema, {'read_min', 'read_max', 'write'})
        for version in schema.values():
            _integer(version, 1, 1)
        _fields(images, {'rootfs.ext4', 'boot.vfat'})
        parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=('=',),
                                           empty_lines_in_values=False)
        parser.optionxform = str
        parser.read_string(raw.decode('ascii'))
        if parser.defaults() or set(parser.sections()) != {'update', 'bundle', 'image.rootfs', 'image.boot', 'meta.rosy'}:
            raise ValueError('unexpected external OS sections')
        if dict(parser['update']) != dict(compatible=COMPATIBLE, version=identity, build=source):
            raise ValueError('external OS release or source differs')
        bundle = dict(parser['bundle'])
        _fields(bundle, {'format', 'verity-hash', 'verity-salt', 'verity-size'})
        if bundle['format'] != 'verity':
            raise ValueError('external OS bundle must use verity')
        for field in ('verity-hash', 'verity-salt'):
            _digest(bundle[field])
        size = bundle['verity-size']
        if not re.fullmatch('[1-9][0-9]*', size) or not 0 < int(size) <= 1024**3 or int(size) % 4096:
            raise ValueError('invalid external OS verity size')
        for slot, filename in (('rootfs', 'rootfs.ext4'), ('boot', 'boot.vfat')):
            item = images[filename]
            _fields(item, {'size_bytes', 'sha256'})
            _integer(item['size_bytes'], 512, 16 * 1024**3 if slot == 'rootfs' else 512 * 1024**2)
            _digest(item['sha256'])
            if item['size_bytes'] % 512:
                raise ValueError('external OS image size is not sector aligned')
            if dict(parser['image.' + slot]) != dict(filename=filename, sha256=item['sha256'], size=str(item['size_bytes'])):
                raise ValueError('external OS image size or digest differs')
        expected_meta = dict(boot_abi='2', state_read_min='1', state_read_max='1', state_write='1',
                             native_factory_release_id=factory['release_id'],
                             native_factory_checksums_sha256=factory['checksums_sha256'])
        if dict(parser['meta.rosy']) != expected_meta:
            raise ValueError('external OS factory or state schema differs')
    except (KeyError, TypeError, UnicodeError, configparser.Error) as error:
        raise ValueError('invalid external OS manifest') from error
    return raw


def _openssl_run(arguments, *, data=None):
    try:
        result = subprocess.run([_openssl(), *map(str, arguments)], input=data, capture_output=True,
                                timeout=60, **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('external OS OpenSSL operation failed') from error
    if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 65536:
        raise ValueError('external OS OpenSSL operation refused')
    return result.stdout


def _local_private_key(path):
    path = Path(path).absolute()
    if path.resolve() != path or path.is_relative_to(ROOT):
        raise ValueError('external OS private key must remain outside source and redirected paths')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('external OS private key requires a private regular file')
    if os.name == 'nt':
        from tools.release.os_tools_vm import _windows_private
        _windows_private(path)
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('external OS private key requires owner-only permissions')
    return path


def _public_certificate(raw):
    if (not isinstance(raw, bytes) or len(raw) > 32768 or not re.fullmatch(
            rb'-----BEGIN CERTIFICATE-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+-----END CERTIFICATE-----\s*', raw)):
        raise ValueError('external OS requires a single public certificate')
    _openssl_run(['x509', '-noout'], data=raw)


def sign_inline_cms(cms, preparer_certificate, expected, images, private_key, certificate, *,
                    certificate_sha256, signer_spki_sha256):
    """Sign owned-guest requests locally using the already approved public build pins."""
    if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
        raise ValueError('external product OS signing must not run in hosted CI')
    if not isinstance(cms, bytes) or not 0 < len(cms) <= 65536:
        raise ValueError('external OS CMS request exceeds its bound')
    _digest(certificate_sha256)
    _digest(signer_spki_sha256)
    _public_certificate(preparer_certificate)
    _public_certificate(certificate)
    if hashlib.sha256(certificate).hexdigest() != certificate_sha256:
        raise ValueError('external OS certificate differs from the approved pin')
    public = _openssl_run(['x509', '-pubkey', '-noout'], data=certificate)
    if b'ASN1 OID: prime256v1' not in _openssl_run(['pkey', '-pubin', '-text', '-noout'], data=public):
        raise ValueError('external OS signer requires ECDSA P-256')
    if hashlib.sha256(_openssl_run(['pkey', '-pubin', '-outform', 'DER'], data=public)).hexdigest() != signer_spki_sha256:
        raise ValueError('external OS signer differs from the approved SPKI pin')
    details = _openssl_run(['x509', '-noout', '-ext', 'extendedKeyUsage,keyUsage,basicConstraints'], data=certificate)
    if any(value not in details for value in (b'Code Signing', b'Digital Signature', b'CA:FALSE')):
        raise ValueError('external OS certificate requires a code-signing leaf')
    # Only public data enters temporary storage; the private key is opened by local OpenSSL.
    with tempfile.TemporaryDirectory(prefix='rosy-external-cms-') as temporary:
        directory = Path(temporary)
        preparer, operator, original = (directory / name for name in ('preparer.pem', 'operator.pem', 'request.cms'))
        preparer.write_bytes(preparer_certificate)
        operator.write_bytes(certificate)
        original.write_bytes(cms)
        raw = _openssl_run(['cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', preparer,
                            '-inform', 'DER', '-in', original])
        validate_inline_manifest(raw, expected, images)
        private_key = _local_private_key(private_key)
        signed = _openssl_run(['cms', '-sign', '-binary', '-signer', operator, '-inkey', private_key,
                               '-nodetach', '-outform', 'DER'], data=raw)
        replacement = directory / 'replacement.cms'
        replacement.write_bytes(signed)
        verified = _openssl_run(['cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', operator,
                                 '-inform', 'DER', '-in', replacement])
        if verified != raw:
            raise ValueError('external OS signature changed its inline manifest')
        return signed
