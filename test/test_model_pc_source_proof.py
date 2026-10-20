"""Retained Ed25519 source closure; actual isolated child, no GPU or service install."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from test_model_pc_autoupdate import candidate, keys, module, updater  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Linux signed executor and immutable source modes')
PROOF = '.rosy-source-proof'
DEPENDENCY = 'tools/perception/proof_dependency.py'
ENTRY = 'tools/perception/source_probe.py'


@pytest.mark.parametrize('missing', range(9))
def test_omx_review_archive_requires_its_exact_dependencies(tmp_path, keys, missing):
    m = module()
    files = {name: b'pass\n' for name in m.OMX_REVIEW_FILES}
    files['learning/curation/perception/omx_web.py'] = b'pass\n'
    del files[m.OMX_REVIEW_FILES[missing]]
    folder = candidate(m, tmp_path, keys, extra_files=files)
    with pytest.raises(ValueError, match='missing OMX review dependency'):
        m.unpack(folder / 'code.tar', tmp_path / 'incomplete')


@pytest.fixture
def installed(tmp_path, keys, monkeypatch):
    m = module()
    root, work = tmp_path / 'controller', tmp_path / 'work'
    work.mkdir()
    files = {DEPENDENCY: b'VALUE = "signed dependency"\n',
             ENTRY: b'import pathlib,sys,proof_dependency\npathlib.Path(sys.argv[1]).write_text(proof_dependency.VALUE)\n'}
    folder = candidate(m, root, keys, extra_files=files)
    manifest_bytes = (folder / 'release.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    assert updater(m, root, keys).run()['result'] == 'applied'
    source = (root / 'current').resolve()
    config = dict(root=str(root), key_id='test', public_key=str(keys[1]), python=sys.executable,
                  work_dir=str(work), legacy_roots=[])
    expected = dict(source_commit=manifest['source_commit'], environment_sha256=manifest['environment_sha256'],
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())
    monkeypatch.setattr(m, 'legacy_busy', lambda roots: None)
    monkeypatch.setattr(m, 'gpu_busy', lambda: None)
    monkeypatch.setattr(m.Updater, 'probe_environment', lambda self: 'e' * 64)
    return m, config, expected, source, folder


def execute(installed, tmp_path, **changes):
    m, config, expected, _, _ = installed
    marker = tmp_path / 'child-result'
    args = dict(source_expectation=expected)
    args.update(changes)
    return m.execute(config, 'source_probe.py', [str(marker)], **args)


def rewrite(path, data):
    path.chmod(0o600)
    path.write_bytes(data)
    path.chmod(0o444)


def test_signed_proof_retained_with_source_and_survives_inbox_removal_restart(installed, tmp_path):
    m, config, expected, source, folder = installed
    proof = source / PROOF
    assert {path.name for path in proof.iterdir()} == {'release.json', 'release.json.sig', 'READY', 'code.tar'}
    for name in ('release.json', 'release.json.sig', 'READY', 'code.tar'):
        assert (proof / name).read_bytes() == (folder / name).read_bytes()
    shutil.rmtree(folder)
    # A new controller object and missing inbox cannot weaken independent proof.
    assert m.Updater(config['root'], config['key_id'], config['public_key'], config['python']).state()['result'] == 'applied'
    assert execute(installed, tmp_path) == 0
    assert (tmp_path / 'child-result').read_text() == 'signed dependency'
    receipts = list((Path(config['root']) / 'jobs').glob('*.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_bytes())
    closure = receipt['source_proof']
    assert closure['schema'] == 'rosy.model-code-source/1'
    assert closure['source_commit'] == receipt['source_commit'] == expected['source_commit']
    assert closure['manifest_sha256'] == expected['manifest_sha256']
    assert closure['environment_sha256'] == receipt['environment_sha256'] == expected['environment_sha256']
    assert closure['archive_sha256'] == m.digest(proof / 'code.tar')
    assert len(closure['inventory_sha256']) == 64 and closure['sequence'] == 1
    assert str(source) not in json.dumps(closure)


@pytest.mark.parametrize('fault', ['entry', 'dependency', 'missing', 'extra_py', 'extra_so',
                                  'shadow_package', 'pyc', 'pycache', 'link', 'directory_link', 'mode'])
def test_strict_execution_refuses_changed_or_shadow_source_before_child(installed, tmp_path, fault):
    _, _, _, source, _ = installed
    parent = source / 'tools/perception'
    parent.chmod(0o755)
    if fault == 'entry': rewrite(source / ENTRY, b'raise RuntimeError("changed")\n')
    elif fault == 'dependency': rewrite(source / DEPENDENCY, b'VALUE = "tampered"\n')
    elif fault == 'missing': (source / DEPENDENCY).unlink()
    elif fault == 'extra_py': (parent / 'untracked.py').write_text('pass\n')
    elif fault == 'extra_so': (parent / 'proof_dependency.so').write_bytes(b'untracked extension')
    elif fault == 'shadow_package': (parent / 'proof_dependency').mkdir()
    elif fault == 'pyc': (parent / 'proof_dependency.pyc').write_bytes(b'untracked bytecode')
    elif fault == 'pycache':
        cache = parent / '__pycache__'
        cache.mkdir()
        (cache / 'proof_dependency.cpython-312.pyc').write_bytes(b'untracked cache')
    elif fault == 'link':
        external = tmp_path / 'external.py'
        external.write_bytes((source / DEPENDENCY).read_bytes())
        (source / DEPENDENCY).unlink()
        (source / DEPENDENCY).symlink_to(external)
    elif fault == 'directory_link':
        other = tmp_path / 'outside'
        other.mkdir()
        (parent / 'extra').symlink_to(other, target_is_directory=True)
    else: (source / DEPENDENCY).chmod(0o555)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()


@pytest.mark.parametrize('member', ['release.json', 'release.json.sig', 'READY', 'code.tar'])
def test_each_retained_signed_proof_member_is_reverified(installed, tmp_path, member):
    _, _, _, source, _ = installed
    path = source / PROOF / member
    rewrite(path, path.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()


@pytest.mark.parametrize('fault', ['unsigned_inventory', 'linked_manifest', 'linked_proof'])
def test_retained_proof_has_exact_regular_files_without_local_trust_shortcuts(installed, tmp_path, fault):
    _, _, _, source, _ = installed
    proof = source / PROOF
    source.chmod(0o755)
    proof.chmod(0o755)
    if fault == 'unsigned_inventory':
        (proof / 'inventory.json').write_text(json.dumps({'trusted': True, 'files': {}}))
    elif fault == 'linked_manifest':
        target = tmp_path / 'manifest-copy'
        target.write_bytes((proof / 'release.json').read_bytes())
        (proof / 'release.json').unlink()
        (proof / 'release.json').symlink_to(target)
    else:
        target = tmp_path / 'proof-copy'
        proof.rename(target)
        proof.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()


@pytest.mark.parametrize('field', ['source_commit', 'manifest_sha256', 'environment_sha256'])
def test_expected_pins_cannot_be_replaced_with_mutable_activation_state(installed, tmp_path, field):
    m, config, expected, _, _ = installed
    wrong = dict(expected, **{field: 'f' * len(expected[field])})
    state_path = Path(config['root']) / 'state.json'
    state = json.loads(state_path.read_bytes())
    state[field] = wrong[field]
    m.atomic_json(state_path, state)
    with pytest.raises(ValueError):
        execute(installed, tmp_path, source_expectation=wrong)
    assert not (tmp_path / 'child-result').exists()


def test_strict_execution_checks_actual_environment_and_pending_switch(installed, tmp_path, monkeypatch):
    m, config, _, _, _ = installed
    monkeypatch.setattr(m.Updater, 'probe_environment', lambda self: 'f' * 64)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    monkeypatch.setattr(m.Updater, 'probe_environment', lambda self: 'e' * 64)
    state_path = Path(config['root']) / 'state.json'
    state = json.loads(state_path.read_bytes())
    state['pending'] = dict(previous=None, sequence=1)
    m.atomic_json(state_path, state)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()


def test_source_changed_during_environment_probe_rejects_before_child_and_receipt(installed, tmp_path, monkeypatch):
    m, config, expected, source, _ = installed
    probe_marker = tmp_path / 'environment-probed'

    def probe_environment(self):
        rewrite(source / DEPENDENCY, b'VALUE = "changed during environment probe"\n')
        probe_marker.write_text('source changed')
        return expected['environment_sha256']

    monkeypatch.setattr(m.Updater, 'probe_environment', probe_environment)
    # Keep the real isolated child path: stale verification would execute the
    # changed dependency and publish both its marker and a misleading receipt.
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert probe_marker.read_text() == 'source changed'
    assert not (tmp_path / 'child-result').exists()
    assert not list((Path(config['root']) / 'jobs').glob('*.json'))


@pytest.mark.parametrize('expected', [{}, {'source_commit': 'a' * 40},
                                     dict(source_commit='a' * 40, environment_sha256='e' * 64,
                                          manifest_sha256='b' * 64, trusted=True)])
def test_strict_expectation_requires_exact_pins(installed, tmp_path, expected):
    with pytest.raises(ValueError):
        execute(installed, tmp_path, source_expectation=expected)
    assert not (tmp_path / 'child-result').exists()


def test_source_verification_is_inside_existing_exclusive_work_lock(installed, tmp_path, monkeypatch):
    import model_code_source
    m, config, _, _, _ = installed
    original = model_code_source.verify_source
    checks = []
    def verify(*args, **kwargs):
        with pytest.raises(BlockingIOError):
            with m.work_lock(config['root'], exclusive=True):
                pass
        checks.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(model_code_source, 'verify_source', verify)
    assert execute(installed, tmp_path) == 0
    assert checks == [True]


def test_legacy_release_without_proof_rejects_strict_but_preserves_existing_execute(installed, tmp_path):
    m, config, _, source, _ = installed
    source.chmod(0o755)
    (source / PROOF).rename(tmp_path / 'removed-proof')
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()
    marker = tmp_path / 'legacy-result'
    assert m.execute(config, 'source_probe.py', [str(marker)]) == 0
    assert marker.read_text() == 'signed dependency'


def test_only_enrolled_top_level_data_link_is_allowed(installed, tmp_path):
    _, config, _, source, _ = installed
    source.chmod(0o755)
    data = Path(config['work_dir']) / 'data'
    data.mkdir()
    (data / 'recording.bin').write_bytes(b'not executable source')
    (source / 'data').symlink_to(data, target_is_directory=True)
    assert execute(installed, tmp_path) == 0
    (tmp_path / 'child-result').unlink()
    (source / 'data').unlink()
    other = tmp_path / 'other-data'
    other.mkdir()
    (source / 'data').symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()


def test_source_and_retained_proof_publish_as_one_release_before_activation(tmp_path, keys):
    m = module()
    folder = candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    observed = []
    def health(source):
        proof = source / PROOF
        observed.append(source)
        assert (proof / 'code.tar').read_bytes() == (folder / 'code.tar').read_bytes()
        assert (proof / 'release.json.sig').read_bytes() == (folder / 'release.json.sig').read_bytes()
    u.health = health
    assert u.run()['result'] == 'applied'
    assert len(observed) == 2


def test_installed_controller_includes_source_proof_helper():
    from test_model_pc_autoupdate import SCRIPT
    installer = (SCRIPT.parent / 'install-model-code.sh').read_text()
    assert '"$HERE/model_code_source.py"' in installer


@pytest.mark.parametrize('fault', ['sequence', 'target_alias', 'root_link'])
def test_strict_source_requires_exact_activation_and_unlinked_enrollment(installed, tmp_path, fault):
    m, config, _, source, _ = installed
    root = Path(config['root'])
    if fault == 'sequence':
        state = json.loads((root / 'state.json').read_bytes())
        state['sequence'] += 1
        m.atomic_json(root / 'state.json', state)
    elif fault == 'target_alias':
        alias = source.parent / 'alias'
        alias.symlink_to(source, target_is_directory=True)
        (root / 'current').unlink()
        (root / 'current').symlink_to(alias, target_is_directory=True)
    else:
        alias = tmp_path / 'linked-controller'
        alias.symlink_to(root, target_is_directory=True)
        config['root'] = str(alias)
    with pytest.raises(ValueError):
        execute(installed, tmp_path)
    assert not (tmp_path / 'child-result').exists()
    assert not list((root / 'jobs').glob('*.json'))


@pytest.mark.parametrize('value', [True, 'A' * 64, 'e' * 63])
def test_strict_pins_refuse_noncanonical_digest_before_receipt(installed, tmp_path, value):
    _, config, expected, _, _ = installed
    with pytest.raises(ValueError):
        execute(installed, tmp_path, source_expectation=dict(expected, environment_sha256=value))
    assert not (tmp_path / 'child-result').exists()
    assert not list((Path(config['root']) / 'jobs').glob('*.json'))
