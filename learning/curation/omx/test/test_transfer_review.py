"""Review-only exports keep their bytes and recovery groups across partitions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'transfer_review.py'
    assert path.is_file(), 'transfer outcome review package is not implemented'
    spec = importlib.util.spec_from_file_location('transfer_review', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def source(tmp_path, mission, *, root=None, child=None, index=0):
    root = root or mission
    document = dict(schema='rosy.transfer-outcome-export/2', scope='unreviewed_metadata_only',
        mission_id=mission, raw_camera_bytes_available=False, behavior_training_eligible=False,
        outcomes=[], execution_review={'physical_failure_cause': None, 'failure_phase': 'grasp'},
        recovery_lineage=dict(root_mission_id=root, parent_mission_id=root if child else None,
                              child_mission_id=child, attempt_index=index, recovery_limit=1))
    path = tmp_path / (mission + '.json')
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def test_preserves_exact_sources_unknown_cause_and_review_only_status(module, tmp_path):
    parent = source(tmp_path, 'parent', child='child')
    child = source(tmp_path, 'child', root='parent', child='child', index=1)
    other = source(tmp_path, 'other')
    output = tmp_path / 'package'
    manifest = module.prepare(output, train=[parent, child], evaluation=[other])
    assert module.load(output) == manifest
    assert manifest['scope'] == 'unreviewed_metadata_only'
    assert manifest['behavior_training_eligible'] is False
    for record, original in zip(manifest['records'], [parent, child, other]):
        copied = (output / record['source_file']).read_bytes()
        assert copied == original.read_bytes()
        assert hashlib.sha256(copied).hexdigest() == record['source_sha256']
        assert json.loads(copied)['execution_review']['physical_failure_cause'] is None
    assert [r['split'] for r in manifest['records']] == ['train', 'train', 'eval']


def test_root_overlap_is_rejected_before_creating_output(module, tmp_path):
    parent = source(tmp_path, 'parent', child='child')
    child = source(tmp_path, 'child', root='parent', child='child', index=1)
    output = tmp_path / 'package'
    with pytest.raises(ValueError, match='root.*partition'):
        module.prepare(output, train=[parent], evaluation=[child])
    assert not output.exists()


def test_duplicate_mission_is_rejected_even_with_different_bytes(module, tmp_path):
    one, other = source(tmp_path, 'one'), source(tmp_path, 'other')
    duplicate = tmp_path / 'copy.json'
    duplicate.write_bytes(one.read_bytes() + b' ')
    with pytest.raises(ValueError, match='duplicate mission'):
        module.prepare(tmp_path / 'package', train=[one, duplicate], evaluation=[other])


def test_partial_recovery_group_is_reviewable_without_inventing_parent(module, tmp_path):
    child = source(tmp_path, 'child', root='parent', child='child', index=1)
    other = source(tmp_path, 'other')
    result = module.prepare(tmp_path / 'package', train=[child], evaluation=[other])
    assert result['records'][0]['root_mission_id'] == 'parent'
    assert len(result['records']) == 2


def test_linked_child_cannot_redeclare_itself_as_an_independent_eval_root(module, tmp_path):
    parent = source(tmp_path, 'parent', child='child')
    child = source(tmp_path, 'child')
    with pytest.raises(ValueError, match='lineage'):
        module.prepare(tmp_path / 'package', train=[parent], evaluation=[child])


def test_different_roots_cannot_claim_the_same_missing_child(module, tmp_path):
    first = source(tmp_path, 'first', child='missing')
    second = source(tmp_path, 'second', child='missing')
    with pytest.raises(ValueError, match='lineage'):
        module.prepare(tmp_path / 'package', train=[first], evaluation=[second])


@pytest.mark.parametrize('change', ['unlinked-root', 'wrong-child', 'bool-index', 'limit', 'reciprocal'])
def test_invalid_or_inconsistent_lineage_is_rejected(module, tmp_path, change):
    parent = source(tmp_path, 'parent', child='child')
    child = source(tmp_path, 'child', root='parent', child='child', index=1)
    other = source(tmp_path, 'other')
    target = other if change == 'unlinked-root' else child
    doc = json.loads(target.read_bytes())
    key, value = {'unlinked-root': ('root_mission_id', 'another'),
                  'wrong-child': ('child_mission_id', 'another'),
                  'bool-index': ('attempt_index', True), 'limit': ('recovery_limit', 2),
                  'reciprocal': ('child_mission_id', None)}[change]
    doc['recovery_lineage'][key] = value
    target.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='lineage'):
        module.prepare(tmp_path / 'package', train=[parent, child], evaluation=[other])


@pytest.mark.parametrize('change', ['scope', 'training', 'schema', 'duplicate-key', 'nan', 'overflow'])
def test_unaccepted_export_is_rejected(module, tmp_path, change):
    one, other = source(tmp_path, 'one'), source(tmp_path, 'other')
    doc = json.loads(one.read_bytes())
    if change in ('scope', 'schema'):
        doc[change] = 'other'
    elif change == 'training':
        doc['behavior_training_eligible'] = True
    raw = json.dumps(doc)
    if change == 'duplicate-key':
        raw = raw[:-1] + ', "mission_id": "other"}'
    elif change == 'nan':
        raw = raw.replace('null', 'NaN')
    elif change == 'overflow':
        raw = raw.replace('null', '1e999')
    one.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        module.prepare(tmp_path / 'package', train=[one], evaluation=[other])


@pytest.mark.parametrize('change', ['source', 'manifest-root', 'escape', 'training'])
def test_reload_detects_source_or_manifest_changes(module, tmp_path, change):
    one, other = source(tmp_path, 'one'), source(tmp_path, 'other')
    output = tmp_path / 'package'
    doc = module.prepare(output, train=[one], evaluation=[other])
    if change == 'source':
        with (output / doc['records'][0]['source_file']).open('ab') as stream:
            stream.write(b' ')
    else:
        if change == 'manifest-root':
            doc['records'][0]['root_mission_id'] = 'forged'
        elif change == 'escape':
            doc['records'][0]['source_file'] = '../one.json'
        else:
            doc['behavior_training_eligible'] = True
        (output / 'manifest.json').write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError):
        module.load(output)


def test_output_is_exclusive_and_stays_outside_source_checkouts(module, tmp_path):
    one, other = source(tmp_path, 'one'), source(tmp_path, 'other')
    output = tmp_path / 'package'
    output.mkdir()
    (output / 'keep').write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        module.prepare(output, train=[one], evaluation=[other])
    assert (output / 'keep').read_bytes() == b'keep'
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / '.git').write_text('gitdir: elsewhere\n')
    with pytest.raises(ValueError, match='outside source'):
        module.prepare(checkout / 'package', train=[one], evaluation=[other])


def test_cli_prepares_and_verifies_from_unrelated_cwd(module, tmp_path):
    one, other = source(tmp_path, 'one'), source(tmp_path, 'other')
    output = tmp_path / 'package'
    for args in [[str(output), '--train', str(one), '--eval', str(other)], ['--verify', str(output)]]:
        result = subprocess.run([sys.executable, module.__file__, *args], cwd=tmp_path,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['behavior_training_eligible'] is False
