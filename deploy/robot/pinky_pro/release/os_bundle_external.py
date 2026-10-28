"""Keyless Linux preparation/finalization; product private keys never enter this process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
import os_bundle as bundle
from tools.release.external_os_signing import validate_inline_manifest

FILES = {'prepared.raucb', 'preparer.pem', 'manifest.cms', 'manifest.bin', 'request.json'}
REQUEST_FIELDS = {'schema_version', 'kind', 'inputs', 'images', 'prepared_bundle', 'manifest_sha256',
                  'certificate_sha256', 'cms_signer_spki_sha256'}


def _workspace(output, rauc):
    output = Path(output).absolute()
    bundle.ab._offline_directory(output.parent)
    if output.exists() or output.is_symlink() or '..' in output.parts:
        raise ValueError('external OS output must be a new directory')
    if bundle._command([rauc, '--version']).strip() != b'rauc 1.11.3':
        raise ValueError('unsupported external OS RAUC version')
    return output, Path(tempfile.mkdtemp(prefix='.os-external-', dir=output.parent))


def _config(work, certificate):
    path = work / 'system.conf'
    path.write_text(f'[system]\ncompatible={bundle.COMPATIBLE}\nbootloader=noop\nbundle-formats=verity\n'
                    f'[keyring]\npath={certificate}\ncheck-purpose=codesign\n'
                    'use-bundle-signing-time=false\nallow-partial-chain=false\n', encoding='ascii')
    return path


def _record(path):
    return dict(size_bytes=path.stat().st_size, sha256=bundle.sha256_file(path))


def _copy_bundle(source, target, expected):
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != source.parent.stat().st_uid:
        raise ValueError('external OS bundle is not a private regular file')
    total, digest = 0, hashlib.sha256()
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as incoming, target.open('xb') as outgoing:
        if (os.fstat(incoming.fileno()).st_dev, os.fstat(incoming.fileno()).st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('external OS bundle changed before capture')
        while raw := incoming.read(min(bundle.CHUNK, expected['size_bytes'] - total + 1)):
            total += len(raw)
            if total > expected['size_bytes']:
                raise ValueError('external OS bundle exceeds its prepared size')
            digest.update(raw)
            outgoing.write(raw)
    if dict(size_bytes=total, sha256=digest.hexdigest()) != expected:
        raise ValueError('external OS bundle differs from its prepared digest')


def prepare(dist, output, public, certificate, *, rauc='/usr/bin/rauc'):
    """Export only a temporary-signed bundle and public signing request, never its key."""
    value = bundle.read_inputs(Path(dist), Path(public))
    raw_cert = bundle._read(Path(certificate), 32768, Path(certificate).parent.stat().st_uid)
    spki = bundle.validate_certificate(raw_cert)
    output, work = _workspace(output, rauc)
    preserve = False
    try:
        needed = 2 * sum(item['size_bytes'] for item in value['images'].values()) + 512 * 1024**2
        if shutil.disk_usage(work).free < needed:
            raise ValueError('insufficient disk for keyless OS preparation')
        images, exported = work / 'images', work / 'export'
        images.mkdir()
        exported.mkdir()
        for name, item in value['images'].items():
            bundle.decompress(Path(dist) / 'os-bundle-inputs' / item['filename'], item, images / name)
        try:
            bundle.prepare_root(images, value, Path(dist), Path(public), raw_cert)
        except RuntimeError:
            preserve = True
            raise
        measured = {name: _record(images / name) for name in ('rootfs.ext4', 'boot.vfat')}
        (images / 'manifest.raucm').write_text(bundle._manifest(value), encoding='ascii')
        temporary_key, preparer = work / 'temporary.key.pem', exported / 'preparer.pem'
        bundle._command(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
            '-nodes', '-sha256', '-days', '1', '-subj', '/CN=ROSY Disposable Bundle Preparer',
            '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'keyUsage=critical,digitalSignature',
            '-addext', 'extendedKeyUsage=codeSigning', '-keyout', temporary_key, '-out', preparer])
        config = _config(work, preparer)
        prepared = exported / 'prepared.raucb'
        bundle._command([rauc, '--conf', config, '--cert', preparer, '--key', temporary_key,
                         '--mksquashfs-args=-processors 1', 'bundle', images, prepared], timeout=8 * 3600)
        cms = exported / 'manifest.cms'
        bundle._command([rauc, '--conf', config, 'extract-signature', '--keyring', preparer, prepared, cms])
        inline = bundle._command(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any',
                                  '-CAfile', preparer, '-inform', 'DER', '-in', cms])
        validate_inline_manifest(inline, value, measured)
        (exported / 'manifest.bin').write_bytes(inline)
        request = dict(schema_version=1, kind='os-signing-request', inputs=value, images=measured,
                       prepared_bundle=_record(prepared), manifest_sha256=hashlib.sha256(inline).hexdigest(),
                       certificate_sha256=hashlib.sha256(raw_cert).hexdigest(), cms_signer_spki_sha256=spki)
        (exported / 'request.json').write_text(json.dumps(request, sort_keys=True, indent=2) + '\n', encoding='ascii')
        for path in exported.iterdir():
            path.chmod(0o400)
        bundle.ab.sync_directory(exported)
        os.rename(exported, output)
        bundle.ab.sync_directory(output.parent)
        return request
    finally:
        if not preserve:
            shutil.rmtree(work)


def finalize(prepared, output, cms, certificate, *, rauc='/usr/bin/rauc'):
    """Replace CMS and verify the exact prepared manifest before exporting unsigned facts."""
    prepared = bundle.ab._offline_directory(Path(prepared))
    if {path.name for path in prepared.iterdir()} != FILES:
        raise ValueError('external OS preparation has unexpected files')
    owner = prepared.stat().st_uid
    request = json.loads(bundle._read(prepared / 'request.json', 65536, owner), object_pairs_hook=bundle._pairs)
    bundle._fields(request, REQUEST_FIELDS)
    if type(request['schema_version']) is not int or request['schema_version'] != 1 or request['kind'] != 'os-signing-request':
        raise ValueError('invalid external OS signing request')
    bundle._fields(request['prepared_bundle'], {'size_bytes', 'sha256'})
    bundle._integer(request['prepared_bundle']['size_bytes'], 1, 16 * 1024**3)
    bundle._digest(request['prepared_bundle']['sha256'])
    inline = bundle._read(prepared / 'manifest.bin', 16384, owner)
    validate_inline_manifest(inline, request['inputs'], request['images'])
    if hashlib.sha256(inline).hexdigest() != request['manifest_sha256']:
        raise ValueError('external OS inline manifest changed')
    if (not isinstance(cms, bytes) or not 0 < len(cms) <= 65536
            or hashlib.sha256(certificate).hexdigest() != request['certificate_sha256']
            or bundle.validate_certificate(certificate) != request['cms_signer_spki_sha256']):
        raise ValueError('external OS CMS or operator certificate differs')
    output, work = _workspace(output, rauc)
    try:
        original, replacement, operator, preparer = (work / name for name in ('prepared.raucb', 'replacement.cms', 'operator.pem', 'preparer.pem'))
        _copy_bundle(prepared / 'prepared.raucb', original, request['prepared_bundle'])
        replacement.write_bytes(cms)
        operator.write_bytes(certificate)
        preparer.write_bytes(bundle._read(prepared / 'preparer.pem', 32768, owner))
        verified = bundle._command(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any',
                                    '-CAfile', operator, '-inform', 'DER', '-in', replacement])
        if verified != inline:
            raise ValueError('external CMS does not sign the exact prepared manifest')
        exported = work / 'export'
        exported.mkdir()
        name = f"rosy-os-pinky-pro-{request['inputs']['release_id']}-arm64.raucb"
        result = exported / name
        config = _config(work, preparer)
        bundle._command([rauc, '--conf', config, 'replace-signature', '--keyring', preparer,
                         '--signing-keyring', operator, original, replacement, result], timeout=8 * 3600)
        check = work / 'final.cms'
        bundle._command([rauc, '--conf', config, 'extract-signature', '--keyring', operator, result, check])
        final_inline = bundle._command(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any',
                                        '-CAfile', operator, '-inform', 'DER', '-in', check])
        if final_inline != inline:
            raise ValueError('final external OS manifest differs')
        metadata = bundle._metadata(request['inputs'], request['cms_signer_spki_sha256'], dict(filename=name, **_record(result)))
        import os_rauc
        previous = os_rauc.RAUC
        try:
            os_rauc.RAUC = str(rauc)
            os_rauc._inner(os_rauc._inspect(result, operator), metadata)
        finally:
            os_rauc.RAUC = previous
        result.chmod(0o400)
        (exported / 'metadata.json').write_text(json.dumps(metadata, sort_keys=True, indent=2) + '\n', encoding='ascii')
        bundle.ab.sync_directory(exported)
        os.rename(exported, output)
        bundle.ab.sync_directory(output.parent)
        return metadata
    finally:
        shutil.rmtree(work)


def verify(finalized, raw_metadata, signature, raw_rollout, rollout_signature, public, certificate, *, rauc='/usr/bin/rauc'):
    """Recheck exact public signed outputs with the unchanged device consumer."""
    finalized = bundle.ab._offline_directory(Path(finalized))
    metadata = bundle.verify_metadata(raw_metadata, signature, Path(public))
    if raw_metadata != bundle._read(finalized / 'metadata.json', 16384, finalized.stat().st_uid):
        raise ValueError('operator signed metadata differs from finalization')
    bundle.verify_rollout(raw_rollout, rollout_signature, Path(public), metadata)
    bundle.validate_certificate(certificate)
    original = finalized / metadata['bundle']['filename']
    work = Path(tempfile.mkdtemp(prefix='.os-consumer-proof-', dir=finalized.parent))
    moved = False
    try:
        import os_rauc
        for relative, raw in ((os_rauc.ED_KEY, Path(public).read_bytes()), (os_rauc.CMS_KEY, certificate)):
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        staged = work / os_rauc.COMMON / 'os-update/staging' / metadata['release_id'] / metadata['bundle']['filename']
        staged.parent.mkdir(parents=True)
        # Keep a single link and avoid duplicating a multi-GiB bundle for the consumer path check.
        os.rename(original, staged)
        moved = True
        previous = os_rauc.RAUC
        try:
            os_rauc.RAUC = str(rauc)
            return os_rauc.verify_bundle(work, staged, raw_metadata, signature)
        finally:
            os_rauc.RAUC = previous
    finally:
        if moved:
            try:
                if original.exists() or original.is_symlink():
                    raise FileExistsError('finalized bundle destination changed')
                os.rename(staged, original)
            except OSError as error:
                raise RuntimeError('OS_EXTERNAL_VERIFY_CLEANUP_HOLD preserve ' + str(work)) from error
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    for name in ('dist', 'output', 'public-key', 'certificate'):
        preparation.add_argument('--' + name, type=Path, required=True)
    finalization = commands.add_parser('finalize')
    for name in ('prepared', 'output', 'cms', 'certificate'):
        finalization.add_argument('--' + name, type=Path, required=True)
    verification = commands.add_parser('verify')
    for name in ('finalized', 'metadata', 'metadata-signature', 'rollout', 'rollout-signature', 'public-key', 'certificate'):
        verification.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.dist, args.output, args.public_key, args.certificate)
    elif args.command == 'finalize':
        finalize(args.prepared, args.output, bundle._read(args.cms, 65536, args.cms.parent.stat().st_uid),
                 bundle._read(args.certificate, 32768, args.certificate.parent.stat().st_uid))
    else:
        def raw(path, limit):
            return bundle._read(path, limit, path.parent.stat().st_uid)
        verify(args.finalized, raw(args.metadata, 16384), raw(args.metadata_signature, 512).decode('ascii').strip(),
               raw(args.rollout, 16384), raw(args.rollout_signature, 512).decode('ascii').strip(),
               args.public_key, raw(args.certificate, 32768))
    print('OS_EXTERNAL_' + args.command.upper() + '_VERIFIED')


if __name__ == '__main__':
    main()
