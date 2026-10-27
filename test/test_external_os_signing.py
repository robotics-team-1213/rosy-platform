"""Exact external CMS request validation using real pinned RAUC output."""
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

from os_rauc_fakes import RELEASE, make_bundle, run, signer, rauc_tool


ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('external_os_signing', ROOT / 'tools/release/external_os_signing.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def prepared(tmp_path, rauc_tool):
    key, certificate = signer(tmp_path / 'prepare-authority')
    directory = tmp_path / 'prepare'
    bundle, config = make_bundle(directory, rauc_tool, key, certificate)
    signature = tmp_path / 'original.cms'
    run([rauc_tool, '--conf', config, 'extract-signature', '--keyring', certificate, bundle, signature])
    raw = run(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', certificate,
               '-inform', 'DER', '-in', signature])
    expected = dict(release_id=RELEASE, source_revision='b' * 40,
                    native_factory=dict(release_id='2026.10.26-010', checksums_sha256='a' * 64),
                    boot_abi=2, state_schema=dict(read_min=1, read_max=1, write=1))
    images = {}
    for name in ('rootfs.ext4', 'boot.vfat'):
        image = directory / 'source' / name
        images[name] = dict(size_bytes=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    return raw, expected, images


def test_accepts_exact_real_rauc_verity_request(prepared):
    raw, expected, images = prepared
    assert module().validate_inline_manifest(raw, expected, images) == raw


@pytest.mark.parametrize('fault', ['source', 'release', 'factory', 'checksum', 'size', 'hook', 'extra_image',
                                   'duplicate', 'unknown', 'default', 'format', 'oversize', 'non_ascii'])
def test_refuses_foreign_or_executable_inline_request(prepared, fault):
    raw, expected, images = prepared
    if fault == 'source':
        raw = raw.replace(('b' * 40).encode(), ('c' * 40).encode())
    elif fault == 'release':
        raw = raw.replace(('version=' + RELEASE).encode(), b'version=2026.10.26-099')
    elif fault == 'factory':
        raw = raw.replace(('a' * 64).encode(), ('d' * 64).encode())
    elif fault == 'checksum':
        raw = raw.replace(images['rootfs.ext4']['sha256'].encode(), b'0' * 64)
    elif fault == 'size':
        images['rootfs.ext4']['size_bytes'] += 1
    elif fault == 'hook':
        raw += b'\n[hooks]\nfilename=hook.sh\n'
    elif fault == 'extra_image':
        raw += b'\n[image.extra]\nfilename=extra.ext4\n'
    elif fault == 'duplicate':
        raw += b'\n[update]\ncompatible=rosy-pinky-pro-ab-v2\n'
    elif fault == 'unknown':
        raw += b'unknown=unreviewed\n'
    elif fault == 'default':
        raw = b'[DEFAULT]\nignored=unreviewed\n' + raw
    elif fault == 'format':
        raw = raw.replace(b'format=verity', b'format=plain')
    elif fault == 'oversize':
        raw += b'#' * 16385
    elif fault == 'non_ascii':
        raw += b'\xff'
    with pytest.raises(ValueError):
        module().validate_inline_manifest(raw, expected, images)


@pytest.fixture
def cms_request(prepared, tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    raw, expected, images = prepared
    preparer_key, preparer = signer(tmp_path / 'external-preparer')
    private, certificate = signer(tmp_path / 'external-operator')
    cms = run(['openssl', 'cms', '-sign', '-binary', '-signer', preparer, '-inkey', preparer_key,
               '-nodetach', '-outform', 'DER'], data=raw)
    public = run(['openssl', 'x509', '-pubkey', '-noout'], data=certificate.read_bytes())
    spki = hashlib.sha256(run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], data=public)).hexdigest()
    pins = dict(certificate_sha256=hashlib.sha256(certificate.read_bytes()).hexdigest(), signer_spki_sha256=spki)
    return raw, expected, images, cms, preparer.read_bytes(), private, certificate.read_bytes(), pins


def test_signs_exact_verified_inline_bytes_with_operator_key(cms_request, tmp_path):
    raw, expected, images, cms, preparer, private, certificate, pins = cms_request
    signed = module().sign_inline_cms(cms, preparer, expected, images, private, certificate, **pins)
    target = tmp_path / 'operator.cms'
    target.write_bytes(signed)
    authority = tmp_path / 'operator.pem'
    authority.write_bytes(certificate)
    assert run(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', authority,
                '-inform', 'DER', '-in', target]) == raw


@pytest.mark.parametrize('fault', ['signature', 'source', 'certificate_pin', 'spki_pin', 'unsafe_key', 'ci'])
def test_external_cms_refuses_untrusted_or_nonlocal_authority(cms_request, tmp_path, monkeypatch, fault):
    _, expected, images, cms, preparer, private, certificate, pins = cms_request
    if fault == 'signature':
        cms = b'invalid CMS'
    elif fault == 'source':
        expected['source_revision'] = 'c' * 40
    elif fault == 'certificate_pin':
        pins['certificate_sha256'] = '0' * 64
    elif fault == 'spki_pin':
        pins['signer_spki_sha256'] = '0' * 64
    elif fault == 'unsafe_key':
        alias = tmp_path / 'private-key-link'
        os.link(private, alias)
    elif fault == 'ci':
        monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with pytest.raises(ValueError):
        module().sign_inline_cms(cms, preparer, expected, images, private, certificate, **pins)
