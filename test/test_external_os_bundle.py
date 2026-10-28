"""Keyless preparation and replacement feed the existing consumer with real CMS/verity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from auto_update_fakes import HOST

from os_rauc_fakes import signer, rauc_tool
from test_os_bundle_signer import distribution
from test_ab_image_layout import IMAGE, RELEASE_ID
from test_external_os_signing import module as external_signer
from signing import sign_checksums


def module():
    spec = importlib.util.spec_from_file_location('external_os_bundle', IMAGE.parent / 'release/os_bundle_external.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def staged(tmp_path, monkeypatch, rauc_tool):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    _, dist, private, public = distribution(tmp_path)
    m = module()
    # Real filesystem injection has a separate disposable-kernel gate.
    monkeypatch.setattr(m.bundle, 'prepare_root', lambda *a: None)
    cms_private, certificate = signer(tmp_path / 'operator')
    prepared = tmp_path / 'prepared'
    value = m.prepare(dist, prepared, public, certificate, rauc=str(rauc_tool))
    return m, dist, prepared, private, public, cms_private, certificate, value


def replacement(staged):
    _, _, prepared, _, _, private, certificate, request = staged
    return external_signer().sign_inline_cms((prepared / 'manifest.cms').read_bytes(),
        (prepared / 'preparer.pem').read_bytes(), request['inputs'], request['images'], private,
        certificate.read_bytes(), certificate_sha256=request['certificate_sha256'],
        signer_spki_sha256=request['cms_signer_spki_sha256'])


def test_keyless_prepare_external_sign_finalize_passes_existing_consumer(staged, tmp_path, monkeypatch, rauc_tool):
    m, dist, prepared, private, public, _, certificate, request = staged
    assert {p.name for p in prepared.iterdir()} == {'prepared.raucb', 'preparer.pem', 'manifest.cms', 'manifest.bin', 'request.json'}
    assert request == json.loads((prepared / 'request.json').read_bytes())
    assert request['inputs']['source_revision'] == 'a' * 40
    assert request['manifest_sha256'] == hashlib.sha256((prepared / 'manifest.bin').read_bytes()).hexdigest()
    before = hashlib.sha256((prepared / 'prepared.raucb').read_bytes()).hexdigest()
    result = tmp_path / 'finalized'
    metadata = m.finalize(prepared, result, replacement(staged), certificate.read_bytes(), rauc=str(rauc_tool))
    assert hashlib.sha256((prepared / 'prepared.raucb').read_bytes()).hexdigest() == before
    assert (result / 'metadata.json').is_file()
    from test_os_rauc import _consumer
    consumer = _consumer(monkeypatch, rauc_tool)
    root = tmp_path / 'consumer'
    for path, raw in ((consumer.ED_KEY, public.read_bytes()), (consumer.CMS_KEY, certificate.read_bytes())):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    destination = root / 'var/lib/rosy-device/os-update/staging' / RELEASE_ID / metadata['bundle']['filename']
    destination.parent.mkdir(parents=True)
    shutil.copyfile(result / metadata['bundle']['filename'], destination)
    destination.chmod(0o400)
    raw = (json.dumps(metadata, sort_keys=True, indent=2) + '\n').encode()
    facts = consumer.verify_bundle(root, destination, raw, sign_checksums(raw, private))
    assert facts['metadata'] == metadata
    assert facts['images']['rootfs']['sha256'] == request['images']['rootfs.ext4']['sha256']


@pytest.mark.parametrize('fault', ['bundle', 'request', 'signature', 'certificate', 'existing_output'])
def test_external_finalize_rejects_changed_inputs_without_output(staged, tmp_path, rauc_tool, fault):
    m, _, prepared, _, _, _, certificate, _ = staged
    signed = replacement(staged)
    raw_cert = certificate.read_bytes()
    result = tmp_path / 'finalized'
    if fault in ('bundle', 'request'):
        target = prepared / ('prepared.raucb' if fault == 'bundle' else 'request.json')
        target.chmod(0o600)
        target.write_bytes(b'tampered')
    elif fault == 'signature':
        signed = b'invalid CMS'
    elif fault == 'certificate':
        _, other = signer(tmp_path / 'unapproved')
        raw_cert = other.read_bytes()
    elif fault == 'existing_output':
        result.mkdir()
        (result / 'preserve').write_bytes(b'existing')
    with pytest.raises(ValueError):
        m.finalize(prepared, result, signed, raw_cert, rauc=str(rauc_tool))
    if fault == 'existing_output':
        assert (result / 'preserve').read_bytes() == b'existing'
    else:
        assert not result.exists()


@pytest.mark.parametrize('fault', [None, 'metadata_signature', 'rollout_signature', 'rollout_binding', 'metadata_bytes'])
def test_guest_reverifies_final_signed_public_outputs_and_preserves_bundle(staged, tmp_path, rauc_tool, fault):
    from datetime import datetime, timezone
    m, _, prepared, private, public, _, certificate, _ = staged
    final = tmp_path / 'finalized'
    metadata = m.finalize(prepared, final, replacement(staged), certificate.read_bytes(), rauc=str(rauc_tool))
    raw = (final / 'metadata.json').read_bytes()
    signature = sign_checksums(raw, private)
    policy = dict(schema_version=1, kind='os-update', release_id=metadata['release_id'],
                  bundle=metadata['bundle']['filename'], bundle_sha256=metadata['bundle']['sha256'],
                  published_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  canary=[HOST], canary_ok=False, withdrawn=False, wave_delay_s=600)
    if fault == 'rollout_binding':
        policy['bundle_sha256'] = '0' * 64
    rollout = (json.dumps(policy, sort_keys=True, indent=2) + '\n').encode()
    rollout_signature = sign_checksums(rollout, private)
    if fault == 'metadata_signature':
        signature = 'invalid'
    elif fault == 'rollout_signature':
        rollout_signature = 'invalid'
    elif fault == 'metadata_bytes':
        raw = b'{}'
        signature = sign_checksums(raw, private)
    bundle = final / metadata['bundle']['filename']
    before = hashlib.sha256(bundle.read_bytes()).hexdigest()
    def verify():
        return m.verify(final, raw, signature, rollout, rollout_signature, public, certificate.read_bytes(), rauc=str(rauc_tool))
    if fault:
        with pytest.raises(ValueError):
            verify()
    else:
        proof = verify()
        assert proof['metadata'] == metadata
        assert proof['images']['rootfs']['sha256'] == staged[-1]['images']['rootfs.ext4']['sha256']
    assert bundle.is_file() and hashlib.sha256(bundle.read_bytes()).hexdigest() == before
    assert {path.name for path in final.iterdir()} == {metadata['bundle']['filename'], 'metadata.json'}
