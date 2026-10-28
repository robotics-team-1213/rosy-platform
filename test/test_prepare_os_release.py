"""Operator facts are captured from real signed inputs before any guest or private key."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from test_os_bundle_signer import distribution
from signing import build_sha256sums, sign_checksums
from auto_update_fakes import HOST
from os_rauc_fakes import signer, run, rauc_tool
from tools.release.deployment_targets import DeploymentError


ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('prepare_os_release_test', ROOT / 'tools/release/prepare_os_release.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_captures_exact_authenticated_image_and_factory_facts(tmp_path):
    _, dist, _, public = distribution(tmp_path)
    expected = __import__('json').loads((dist / 'os-bundle-inputs/inputs.json').read_bytes())
    result = module().authenticated_distribution(dist, public, release_id=expected['release_id'], source_revision='a' * 40)
    assert result['inputs'] == expected
    assert result['checksums'] == (dist / 'SHA256SUMS').read_bytes()
    assert result['signature'] == (dist / 'SHA256SUMS.sig').read_bytes()
    assert result['public_key'] == public.read_bytes()
    for name, digest in result['entries'].items():
        assert digest == hashlib.sha256((dist / name).read_bytes()).hexdigest()
        assert result['sizes'][name] == (dist / name).stat().st_size


@pytest.mark.parametrize('fault', ['source', 'release', 'signature', 'record', 'factory_signature', 'missing'])
def test_refuses_wrong_or_unsigned_operator_inputs(tmp_path, fault):
    _, dist, private, public = distribution(tmp_path)
    import json
    identity = json.loads((dist / 'os-bundle-inputs/inputs.json').read_bytes())['release_id']
    source = 'a' * 40
    if fault == 'source':
        source = 'b' * 40
    elif fault == 'release':
        identity = '2026.10.26-099'
    elif fault == 'signature':
        (dist / 'SHA256SUMS.sig').write_bytes(b'invalid')
    elif fault == 'record':
        (dist / 'os-bundle-inputs/inputs.json').write_bytes(b'{}')
    elif fault == 'missing':
        (dist / 'os-bundle-inputs/inputs.json').unlink()
    elif fault == 'factory_signature':
        (dist / 'factory-release' / identity / 'SHA256SUMS.sig').write_bytes(b'invalid')
        paths = [p.relative_to(dist).as_posix() for p in dist.rglob('*') if p.is_file()
                 and p.relative_to(dist).as_posix() not in {'SHA256SUMS', 'SHA256SUMS.sig'}]
        raw = build_sha256sums(dist, paths)
        (dist / 'SHA256SUMS').write_bytes(raw)
        (dist / 'SHA256SUMS.sig').write_text(sign_checksums(raw, private))
    with pytest.raises(ValueError):
        module().authenticated_distribution(dist, public, release_id=identity, source_revision=source)


def test_record_is_bound_to_the_verified_checksum_snapshot(tmp_path, monkeypatch):
    _, dist, _, public = distribution(tmp_path)
    m = module()
    import json
    identity = json.loads((dist / 'os-bundle-inputs/inputs.json').read_bytes())['release_id']
    original = m.verify_checksums
    def mutate(root, entries):
        result = original(root, entries)
        path = dist / 'os-bundle-inputs/inputs.json'
        value = json.loads(path.read_bytes())
        path.write_text(json.dumps(dict(value, source_revision='b' * 40)))
        return result
    monkeypatch.setattr(m, 'verify_checksums', mutate)
    with pytest.raises(ValueError):
        m.authenticated_distribution(dist, public, release_id=identity, source_revision='a' * 40)


@pytest.mark.parametrize('target', ['rasptank_metal', 'dji_neo_2', 'omx', 'unknown'])
def test_unsupported_profile_stops_before_inputs_or_workspace(target, tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, 'authenticated_distribution', lambda *a, **k: pytest.fail('unsupported target touched inputs'))
    with pytest.raises(DeploymentError):
        m.prepare_release(target, tmp_path / 'absent', tmp_path / 'output', tmp_path / 'key',
                          tmp_path / 'public', tmp_path / 'cms-key',
                          release_id='2026.10.26-011', source_revision='a' * 40, canary=[HOST])
    assert not (tmp_path / 'output').exists()


@pytest.fixture
def scenario(tmp_path, monkeypatch, rauc_tool):
    from test_external_os_bundle import module as guest_module
    from tools.release.external_os_signing import sign_inline_cms
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    _, dist, private, public = distribution(tmp_path)
    value = json.loads((dist / 'os-bundle-inputs/inputs.json').read_bytes())
    cms_private, certificate = signer(tmp_path / 'operator-cms')
    raw_cert = certificate.read_bytes()
    public_der = run(['openssl', 'x509', '-pubkey', '-noout'], data=raw_cert)
    spki = hashlib.sha256(run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], data=public_der)).hexdigest()
    m, core = module(), guest_module()
    monkeypatch.setattr(core.bundle, 'prepare_root', lambda *a: None)
    cache = tmp_path / 'cache'
    cache.mkdir(mode=0o700)
    monkeypatch.setattr(m, 'prepare_tools', lambda: cache, raising=False)
    monkeypatch.setattr(m, 'ensure_private_directory', lambda path: Path(path).mkdir(parents=True, mode=0o700), raising=False)
    monkeypatch.setattr(m, '_tools_revision', lambda: 'c' * 40, raising=False)
    monkeypatch.setattr(m, '_approved_cms', lambda: dict(certificate=raw_cert,
        certificate_sha256=hashlib.sha256(raw_cert).hexdigest(), cms_signer_spki_sha256=spki), raising=False)
    state = SimpleNamespace(fault=None, guests=[], cms_signs=0, ed_signs=0, calls=[])
    def cms(*a, **k):
        state.cms_signs += 1
        return sign_inline_cms(*a, **k)
    def ed(*a, **k):
        state.ed_signs += 1
        return sign_checksums(*a, **k)
    monkeypatch.setattr(m, 'sign_inline_cms', cms, raising=False)
    monkeypatch.setattr(m, 'sign_checksums', ed, raising=False)

    class Guest:
        def __init__(self, directory):
            self.directory = Path(directory)
            self.directory.mkdir(parents=True, exist_ok=True)
            self.inbound = {}
            self.closed = False
            state.guests.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True
            if state.fault == 'close_failure':
                raise ValueError('owned guest termination failed')

        def provision_source(self, source, *, revision):
            assert Path(source) == ROOT and revision == 'c' * 40

        def run(self, command, *, data=None, timeout=300):
            state.calls.append((command, data))
            if command.startswith('cat > '):
                self.inbound[shlex.split(command)[-1]] = data
                return ''
            if 'os_bundle_external.py prepare' in command:
                core.prepare(dist, self.directory / 'prepared', public, certificate, rauc=str(rauc_tool))
                return 'OS_EXTERNAL_PREPARE_VERIFIED\n'
            if 'os_bundle_external.py finalize' in command:
                core.finalize(self.directory / 'prepared', self.directory / 'finalized',
                              self.inbound['/work/operator.cms'], raw_cert, rauc=str(rauc_tool))
                return 'OS_EXTERNAL_FINALIZE_VERIFIED\n'
            if 'os_bundle_external.py verify' in command:
                if state.fault == 'consumer':
                    raise ValueError('native signed consumer rejected')
                core.verify(self.directory / 'finalized', self.inbound['/work/operator-update.json'],
                    self.inbound['/work/operator-update.json.sig'].decode().strip(),
                    self.inbound['/work/operator-rollout.json'],
                    self.inbound['/work/operator-rollout.json.sig'].decode().strip(), public, raw_cert, rauc=str(rauc_tool))
                return 'OS_EXTERNAL_VERIFY_VERIFIED\n'
            # The receiver is independently exercised against real HTTP in its owner suite.
            if data is not None and 'files' in json.loads(data):
                descriptor = json.loads(data)
                assert all(record['destination'].startswith('/work/') for record in descriptor['files'])
                return ''
            pytest.fail('unexpected guest command: ' + command)

        def _ssh(self, command, *, timeout=60):
            fields = shlex.split(command)
            assert fields[:2] == ['head', '-c']
            relative = fields[-1].removeprefix('/work/')
            raw = (self.directory / relative).read_bytes()
            if relative == 'prepared/request.json' and state.fault in ('request_source', 'request_certificate', 'request_images'):
                request = json.loads(raw)
                if state.fault == 'request_source':
                    request['inputs']['source_revision'] = 'b' * 40
                elif state.fault == 'request_certificate':
                    request['certificate_sha256'] = '0' * 64
                else:
                    request['images']['boot.vfat']['sha256'] = '0' * 64
                raw = json.dumps(request).encode()
            if relative == 'finalized/metadata.json' and state.fault == 'metadata_source':
                metadata = json.loads(raw)
                raw = json.dumps(dict(metadata, source_revision='b' * 40)).encode()
            return subprocess.CompletedProcess(command, 0, raw[:int(fields[2])], b'')

        def copy_from(self, remote, target, *, size_bytes, sha256):
            if state.fault == 'transfer':
                raise ValueError('bounded guest transfer failed')
            source = self.directory / remote.removeprefix('/work/')
            raw = source.read_bytes()
            assert len(raw) == size_bytes and hashlib.sha256(raw).hexdigest() == sha256
            Path(target).write_bytes(raw)
            return Path(target)

    def prepare(output=None):
        return m.prepare_release('pinky_pro', dist, output or tmp_path / 'signed-os', private, public, cms_private,
            release_id=value['release_id'], source_revision='a' * 40, canary=[HOST], guest_factory=Guest)
    return m, state, prepare, tmp_path / 'signed-os', private, cms_private, public, value


def test_operator_command_produces_exact_signed_assets_and_closes_guest(scenario):
    from tools.release.publish_os_release import publish
    _, state, prepare, output, private, cms_private, public, value = scenario
    result = prepare()
    assert result['release_id'] == value['release_id'] and result['source_revision'] == 'a' * 40
    published = publish(output, public, release_id=value['release_id'], source_revision='a' * 40)
    assert len(published['assets']) == 5 and published['applied'] is False
    assert state.cms_signs == 1 and state.ed_signs == 2
    assert len(state.guests) == 1 and state.guests[0].closed
    for command, data in state.calls:
        for path in (private, cms_private):
            assert str(path) not in command
            assert data is None or str(path).encode() not in data


@pytest.mark.parametrize('fault', ['request_source', 'request_certificate', 'request_images', 'metadata_source',
                                   'transfer', 'consumer', 'close_failure'])
def test_operator_command_never_exposes_partial_or_unverified_outputs(scenario, fault):
    _, state, prepare, output, *_ = scenario
    state.fault = fault
    with pytest.raises(ValueError):
        prepare()
    assert not output.exists()
    assert state.guests[0].closed
    assert not list(output.parent.glob('.' + output.name + '-*.staging'))
    if fault in ('request_source', 'request_certificate'):
        assert state.cms_signs == 0 and state.ed_signs == 0
    if fault == 'metadata_source':
        assert state.ed_signs == 0


def test_operator_command_preserves_existing_output_before_guest(scenario):
    _, state, prepare, output, *_ = scenario
    output.mkdir()
    (output / 'keep').write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        prepare()
    assert (output / 'keep').read_bytes() == b'existing'
    assert not state.guests
