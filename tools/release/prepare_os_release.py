"""Operator-local preparation of source-bound OS updates; never activates a robot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for relative in ('deploy/robot/pinky_pro/release', 'deploy/robot/pinky_pro/native'):
    sys.path.insert(0, str(ROOT / relative))
from tools.release.publish_os_release import _capture, _plain
from signing import find_unlisted_files, parse_sha256sums, sign_checksums, verify_checksums, verify_signature
from os_update_manifest import _digest, _fields, _integer, release_id as validate_release_id, validate_metadata
from os_update_rollout import _shape as validate_rollout, verify as verify_rollout
from os_state_layout import _pairs
from tools.release.deployment_targets import require_image_backend
from tools.release.prepare_os_tools import prepare as prepare_tools, _ensure_directory as ensure_private_directory
from tools.release.os_tools_vm import WindowsGuest
from tools.release.external_os_signing import _local_private_key, _openssl_run, _public_certificate, sign_inline_cms


def authenticated_distribution(dist, public_key, *, release_id, source_revision):
    """Capture one signed authority and independently bind every requested identity."""
    validate_release_id(release_id)
    if not isinstance(source_revision, str) or not re.fullmatch('[0-9a-f]{40}', source_revision):
        raise ValueError('operator image source requires an exact commit')
    dist = Path(dist).absolute()
    for parent in (*reversed(dist.parents), dist):
        _plain(parent, directory=True)
    with tempfile.TemporaryDirectory(prefix='rosy-public-image-facts-') as temporary:
        work = Path(temporary)
        authority = work / 'authority.pem'
        _capture(Path(public_key), authority, 8192)
        _capture(dist / 'SHA256SUMS', work / 'sums', 16 * 1024**2)
        _capture(dist / 'SHA256SUMS.sig', work / 'signature', 512)
        sums, signature = (work / 'sums').read_bytes(), (work / 'signature').read_bytes()
        try:
            errors = verify_signature(sums, signature.decode('ascii').strip(), authority)
        except UnicodeError as error:
            raise ValueError('operator image signature is malformed') from error
        if errors:
            raise ValueError('operator image distribution is not authenticated')
        entries, errors = parse_sha256sums(sums)
        if errors or verify_checksums(dist, entries) or find_unlisted_files(dist, entries):
            raise ValueError('operator image distribution differs from its signed inventory')
        count = 0

        def record(name, limit=65536, *, decoded=True):
            nonlocal count
            path = dist / name
            for parent in path.parents:
                if parent == dist:
                    break
                _plain(parent, directory=True)
            count += 1
            captured = work / ('record-' + str(count))
            bound = _capture(path, captured, limit)
            if bound['digest'] != 'sha256:' + entries.get(name, ''):
                raise ValueError('operator record differs from the authenticated checksum snapshot')
            raw = captured.read_bytes()
            return json.loads(raw, object_pairs_hook=_pairs) if decoded else raw

        value = record('os-bundle-inputs/inputs.json')
        manifest, provenance = record('manifest.json'), record('build-provenance.json')
        try:
            _integer(value['schema_version'], 1, 1)
            _integer(value['boot_abi'], 2, 2)
            _integer(manifest['schema_version'], 2, 2)
            if (value['kind'] != 'os-bundle-inputs' or value['board'] != 'pinky_pro' or value['arch'] != 'arm64'
                    or value['release_id'] != release_id or value['source_revision'] != source_revision
                    or manifest['release_id'] != release_id or manifest['product'] != 'rosy-os'
                    or manifest['board'] != 'pinky_pro' or manifest['architecture'] != 'arm64'
                    or manifest['layout'] != value['layout'] or provenance['architecture'] != 'aarch64'
                    or provenance['source_revision'] != source_revision):
                raise ValueError('operator image identity differs from expected release or source')
            image = manifest['image']
            if (image['filename'] != f'rosy-os-pinky-pro-{release_id}-arm64.img.xz'
                    or image['sha256'] != entries.get(image['filename'])):
                raise ValueError('operator image bytes differ from the authenticated manifest')
            factory = value['native_factory']
            _fields(factory, {'release_id', 'checksums_sha256'})
            _digest(factory['checksums_sha256'])
            if factory['release_id'] != release_id:
                raise ValueError('operator image belongs to another native factory')
            prefix = 'factory-release/' + release_id + '/'
            native = record(prefix + 'SHA256SUMS', 16 * 1024**2, decoded=False)
            native_sig = record(prefix + 'SHA256SUMS.sig', 512, decoded=False)
            if (hashlib.sha256(native).hexdigest() != factory['checksums_sha256']
                    or verify_signature(native, native_sig.decode('ascii').strip(), authority)):
                raise ValueError('operator native factory signature differs')
            native_entries, errors = parse_sha256sums(native)
            native_manifest = record(prefix + 'manifest.json', 1024**2, decoded=False)
            if (errors or native_entries.get('manifest.json') != hashlib.sha256(native_manifest).hexdigest()
                    or json.loads(native_manifest, object_pairs_hook=_pairs)['release_id'] != release_id):
                raise ValueError('operator native factory manifest differs')
        except (KeyError, TypeError, UnicodeError) as error:
            raise ValueError('operator image facts are malformed') from error
        return dict(inputs=value, entries=entries, sizes={name: _plain(dist / name).st_size for name in entries},
                    checksums=sums, signature=signature, public_key=authority.read_bytes())


def _tools_revision():
    try:
        command = ['git', '-C', str(ROOT)]
        revision = subprocess.run([*command, 'rev-parse', 'HEAD'], check=True, capture_output=True, timeout=30).stdout.decode().strip()
        status = subprocess.run([*command, 'status', '--porcelain', '--untracked-files=normal', '--',
                                 'tools/release', 'deploy', 'contracts/foundation'],
                                check=True, capture_output=True, timeout=30).stdout
        if status or not re.fullmatch('[0-9a-f]{40}', revision):
            raise ValueError('operator preparation requires committed release code')
        subprocess.run([*command, 'cat-file', '-e', revision + ':tools/release/prepare_os_release.py'],
                       check=True, capture_output=True, timeout=30)
        return revision
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError('operator preparation requires a committed source checkout') from error


def _approved_cms():
    import yaml
    section = yaml.safe_load((ROOT / 'deploy/robot/pinky_pro/image/inputs.lock.yaml').read_bytes())['os_updates']
    name = 'deploy/robot/pinky_pro/release/public-keys/rosy-os-cms-2026-01.pem'
    if section.get('cms_verified') is not True or section.get('cms_certificate') != name:
        raise ValueError('operator CMS build trust has not been selected')
    expected, spki = section.get('cms_certificate_sha256'), section.get('cms_signer_spki_sha256')
    _digest(expected)
    _digest(spki)
    with tempfile.TemporaryDirectory(prefix='rosy-public-cms-pin-') as temporary:
        target = Path(temporary) / 'certificate.pem'
        _capture(ROOT / name, target, 32768)
        raw = target.read_bytes()
    _public_certificate(raw)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('operator CMS certificate differs from approved build trust')
    return dict(certificate=raw, certificate_sha256=expected, cms_signer_spki_sha256=spki)


def _guest_bytes(guest, path, limit):
    result = guest._ssh('head -c ' + str(limit + 1) + ' ' + shlex.quote(path), timeout=60)
    if result.returncode or not 0 < len(result.stdout) <= limit:
        raise ValueError('owned guest public record is missing or exceeds its bound')
    return result.stdout


def _stage(guest, action):
    arguments = {
        'prepare': '--dist /work/dist --output /work/prepared --public-key /work/operator-release.pub.pem --certificate /work/operator-cms.pem',
        'finalize': '--prepared /work/prepared --output /work/finalized --cms /work/operator.cms --certificate /work/operator-cms.pem',
        'verify': '--finalized /work/finalized --metadata /work/operator-update.json --metadata-signature /work/operator-update.json.sig '
                  '--rollout /work/operator-rollout.json --rollout-signature /work/operator-rollout.json.sig '
                  '--public-key /work/operator-release.pub.pem --certificate /work/operator-cms.pem',
    }
    result = guest.run('cd /work/source && python3 deploy/robot/pinky_pro/release/os_bundle_external.py '
                       + action + ' ' + arguments[action], timeout=8 * 3600)
    if result.strip() != 'OS_EXTERNAL_' + action.upper() + '_VERIFIED':
        raise ValueError('owned guest did not confirm the requested OS stage')


def _policy(release_id, digest, canary):
    return validate_rollout(dict(schema_version=1, kind='os-update', release_id=release_id,
        bundle=f'rosy-os-pinky-pro-{release_id}-arm64.raucb', bundle_sha256=digest,
        published_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), canary=list(canary),
        canary_ok=False, withdrawn=False, wave_delay_s=600))


def _remove_owned(path, parent):
    if path.exists():
        _plain(path, directory=True)
        if path.resolve() != path or path.parent.resolve() != parent.resolve():
            raise ValueError('operator temporary cleanup path redirects')
        shutil.rmtree(path)


def prepare_release(target, dist, output, private_key, public_key, cms_private_key, *,
                    release_id, source_revision, canary, guest_factory=None):
    """Prepare exactly five signed assets; never publishes or contacts a robot."""
    from tools.release.os_public_inputs import serve_inputs, RECEIVE_SCRIPT
    profile = require_image_backend(target)
    if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
        raise ValueError('product OS preparation must run on the operator PC')
    output, dist = Path(output).absolute(), Path(dist).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('signed OS output already exists')
    if output == Path(output.anchor) or '..' in output.parts:
        raise ValueError('signed OS output path is unsafe')
    _plain(output.parent, directory=True)
    _policy(release_id, '0' * 64, canary)
    snapshot = authenticated_distribution(dist, public_key, release_id=release_id, source_revision=source_revision)
    approved = _approved_cms()
    tools_revision = _tools_revision()
    private_key, cms_private_key = _local_private_key(private_key), _local_private_key(cms_private_key)
    cache = prepare_tools()
    if any(key.is_relative_to(parent) for key in (private_key, cms_private_key) for parent in (dist, output, cache)):
        raise ValueError('product private keys must remain outside image and tools workspaces')
    work = cache / ('release-prep-' + uuid.uuid4().hex)
    staged = output.with_name('.' + output.name + '-' + uuid.uuid4().hex + '.staging')
    complete = False
    ensure_private_directory(work)
    try:
        public = work / 'release-authority.pem'
        public.write_bytes(snapshot['public_key'])
        with serve_inputs(dist, snapshot, approved['certificate']) as description:
            guest_directory = work / 'guest'
            ensure_private_directory(guest_directory)
            with (guest_factory or WindowsGuest)(guest_directory) as guest:
                guest.provision_source(ROOT, revision=tools_revision)
                guest.run('cd /work/source && python3 -c ' + shlex.quote(RECEIVE_SCRIPT),
                          data=json.dumps(description).encode(), timeout=8 * 3600)
                _stage(guest, 'prepare')
                request = json.loads(_guest_bytes(guest, '/work/prepared/request.json', 65536), object_pairs_hook=_pairs)
                _fields(request, {'schema_version', 'kind', 'inputs', 'images', 'prepared_bundle', 'manifest_sha256',
                                  'certificate_sha256', 'cms_signer_spki_sha256'})
                _integer(request['schema_version'], 1, 1)
                if (request['kind'] != 'os-signing-request' or request['inputs'] != snapshot['inputs']
                        or request['certificate_sha256'] != approved['certificate_sha256']
                        or request['cms_signer_spki_sha256'] != approved['cms_signer_spki_sha256']):
                    raise ValueError('owned signing request differs from authenticated operator facts')
                _fields(request['prepared_bundle'], {'size_bytes', 'sha256'})
                _integer(request['prepared_bundle']['size_bytes'], 1, 16 * 1024**3)
                _digest(request['prepared_bundle']['sha256'])
                _digest(request['manifest_sha256'])
                _fields(request['images'], {'rootfs.ext4', 'boot.vfat'})
                for name, item in request['images'].items():
                    _fields(item, {'size_bytes', 'sha256'})
                    expected = snapshot['inputs']['images'][name]
                    _integer(item['size_bytes'], expected['size_bytes'], expected['size_bytes'])
                    _digest(item['sha256'])
                    if name == 'boot.vfat' and item['sha256'] != expected['sha256']:
                        raise ValueError('owned preparation changed the authenticated boot image')
                cms = _guest_bytes(guest, '/work/prepared/manifest.cms', 65536)
                preparer = _guest_bytes(guest, '/work/prepared/preparer.pem', 32768)
                _public_certificate(preparer)
                (work / 'preparer.pem').write_bytes(preparer)
                (work / 'request.cms').write_bytes(cms)
                inline = _openssl_run(['cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', work / 'preparer.pem',
                                       '-inform', 'DER', '-in', work / 'request.cms'])
                if hashlib.sha256(inline).hexdigest() != request['manifest_sha256']:
                    raise ValueError('owned CMS differs from the prepared inline manifest hash')
                replacement = sign_inline_cms(cms, preparer, request['inputs'], request['images'], cms_private_key,
                    approved['certificate'], certificate_sha256=approved['certificate_sha256'],
                    signer_spki_sha256=approved['cms_signer_spki_sha256'])
                guest.run('cat > /work/operator.cms', data=replacement)
                _stage(guest, 'finalize')
                raw_metadata = _guest_bytes(guest, '/work/finalized/metadata.json', 16384)
                metadata = validate_metadata(json.loads(raw_metadata, object_pairs_hook=_pairs))
                expected = dict(release_id=release_id, source_revision=source_revision,
                    compatible=profile['os_compatible'], native_factory=snapshot['inputs']['native_factory'], boot_abi=2,
                    state_schema=snapshot['inputs']['state_schema'], cms_signer_spki_sha256=approved['cms_signer_spki_sha256'],
                    rootfs_bytes=request['images']['rootfs.ext4']['size_bytes'], boot_bytes=request['images']['boot.vfat']['size_bytes'])
                if any(metadata[name] != value for name, value in expected.items()):
                    raise ValueError('finalized OS metadata differs from authenticated operator facts')
                ensure_private_directory(staged)
                item = metadata['bundle']
                guest.copy_from('/work/finalized/' + item['filename'], staged / item['filename'],
                                size_bytes=item['size_bytes'], sha256=item['sha256'])
                metadata_signature = sign_checksums(raw_metadata, private_key)
                if verify_signature(raw_metadata, metadata_signature, public):
                    raise ValueError('operator Ed25519 key differs from the image authority')
                policy = _policy(release_id, item['sha256'], canary)
                raw_policy = (json.dumps(policy, sort_keys=True, indent=2) + '\n').encode()
                policy_signature = sign_checksums(raw_policy, private_key)
                verify_rollout(raw_policy, policy_signature, public, metadata)
                records = {'os-update.json': raw_metadata, 'os-update.json.sig': (metadata_signature + '\n').encode(),
                           'os-rollout.json': raw_policy, 'os-rollout.json.sig': (policy_signature + '\n').encode()}
                for name, raw in records.items():
                    with (staged / name).open('xb') as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    guest_name = name.replace('os-update', 'operator-update').replace('os-rollout', 'operator-rollout')
                    guest.run('cat > /work/' + guest_name, data=raw)
                _stage(guest, 'verify')
        # Guest shutdown and HTTP cleanup must succeed before output becomes visible.
        if output.exists() or output.is_symlink():
            raise FileExistsError('signed OS output appeared during preparation')
        os.rename(staged, output)
        complete = True
        return metadata
    finally:
        _remove_owned(staged, output.parent)
        # Retain failed protected guest workspaces for recovery, including live-disk cleanup holds.
        if complete:
            _remove_owned(work, cache)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('target', 'release-id', 'source-revision'):
        parser.add_argument('--' + name, required=True)
    for name in ('dist', 'output', 'private-key', 'public-key', 'cms-private-key'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--canary', action='append', required=True)
    args = parser.parse_args(argv)
    try:
        metadata = prepare_release(args.target, args.dist, args.output, args.private_key, args.public_key,
            args.cms_private_key, release_id=args.release_id, source_revision=args.source_revision, canary=args.canary)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        print('OS_RELEASE_PREPARE_HOLD: ' + reason, file=sys.stderr)
        return 1
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
