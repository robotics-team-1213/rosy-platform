"""Actual profile/binding and SQLite readback, not authenticated site reception."""
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/path) for path in (
    'contracts/learning/src', 'middleware/execution/local/src',
    'middleware/execution/local/test', 'middleware/apps/device/omx/adapter',
    'middleware/apps/device/omx/adapter/test', 'learning/registry/policy',
    'learning/registry/policy/test', 'learning/curation/pinky',
    'learning/curation/pinky/test', 'test')]

from test_policy_execution_episode import produce
from test_fleet_join import export_inputs
from fleet_join import export
from fleet.server.learning_receiver import LearningReceiver
from fleet.server.learning_bundle import decode, pack, unpack
from rosy.contracts.learning import seal


def native_inputs(tmp_path):
    doc, root, _, _ = produce(tmp_path/'native')
    wire = root/'owner-receipts/000000.json'
    result = tmp_path/'fleet.json'
    export(root/'manifest.json', wire, result)
    return result, root/'manifest.json', wire, doc


def count(path):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT count(*) FROM learning_evidence').fetchone()[0]


def test_native_receive_duplicate_restart_preserves_unknown_and_original_bytes(tmp_path):
    output, manifest, wire, doc = native_inputs(tmp_path)
    path = tmp_path/'receiver.sqlite3'
    receiver = LearningReceiver(path)
    received = receiver.ingest(output, manifest, wire)
    assert received['created']
    value = received['export']
    assert value['episode_outcome']['task'] == 'unknown'
    assert value['policy_revision'] == doc['revisions']['policy']
    assert received['authentication'] == 'not_verified'
    first = receiver.get(value['revision'])
    assert not receiver.ingest(output, manifest, wire)['created']
    assert count(path) == 1
    # A received historical snapshot survives disappearance of sender inputs.
    output.unlink()
    manifest.unlink()
    wire.unlink()
    assert LearningReceiver(path).get(value['revision']) == first


def test_demonstration_unmatched_null_policy_remains_unmatched(tmp_path):
    manifest, wire = export_inputs(tmp_path)
    output = tmp_path/'fleet.json'
    result = export(manifest, wire, output)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    got = receiver.ingest(output, manifest, wire)['export']
    assert got == result
    assert got['policy_revision'] is None
    assert receiver.get(got['revision'])['export'] == got


def test_pinky_real_profile_preserves_unknown_without_creating_correlations(tmp_path):
    from test_pinky_episode import recording
    from pinky_episode import convert
    from test_fleet_join import receipt
    raw, meta = recording(tmp_path/'original')
    root = tmp_path/'episode'
    doc = convert(raw, meta, root, environment='real', clock_domain='ros_system')
    wire = tmp_path/'receipt.json'
    wire.write_text(json.dumps(receipt()), encoding='utf-8')
    output = tmp_path/'fleet.json'
    result = export(root/'episode.json', wire, output)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    assert receiver.ingest(output, root/'episode.json', wire)['export'] == result
    got = receiver.get(result['revision'])['export']
    assert got['binding'] is None and got['status'] == 'unmatched'
    assert got['episode_outcome'] == doc['outcome']
    assert got['policy_revision'] is None and got['environment'] == 'real'


def test_competing_duplicates_publish_one_row(tmp_path):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: receiver.ingest(output, manifest, wire), range(2)))
    assert sorted(row['created'] for row in results) == [False, True]
    assert count(receiver.path) == 1


def test_same_revision_other_raw_bytes_conflicts_without_replacing_record(tmp_path):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    first = receiver.ingest(output, manifest, wire)['export']
    original = receiver.get(first['revision'])
    output.write_bytes(output.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='different received bytes'):
        receiver.ingest(output, manifest, wire)
    assert receiver.get(first['revision']) == original and count(receiver.path) == 1


@pytest.mark.parametrize('mutation', ['binding', 'binding_float', 'inputs', 'source', 'missing', 'profile', 'roles'])
def test_invalid_or_resealed_inputs_never_create_receiver_row(tmp_path, mutation):
    output, manifest, wire, doc = native_inputs(tmp_path)
    value = json.loads(output.read_bytes())
    if mutation == 'binding':
        value['binding']['dispatch_generation'] += 1
        output.write_text(json.dumps(seal(value)), encoding='utf-8')
    elif mutation == 'binding_float':
        value['binding']['dispatch_generation'] = float(value['binding']['dispatch_generation'])
        output.write_text(json.dumps(seal(value)), encoding='utf-8')
    elif mutation == 'inputs':
        value['inputs']['receipt_sha256'] = 'a'*64
        output.write_text(json.dumps(seal(value)), encoding='utf-8')
    elif mutation == 'source':
        source = manifest.parent/doc['sources'][0]['path']
        source.write_bytes(source.read_bytes()+b' ')
    elif mutation == 'missing':
        (manifest.parent/doc['sources'][0]['path']).unlink()
    elif mutation == 'roles':
        doc['streams']['events'] = dict(doc['streams']['events'], bytes=0)
        manifest.write_text(json.dumps(seal(doc)), encoding='utf-8')
    else:
        doc['profile'] = 'pilot_recording_v1'
        manifest.write_text(json.dumps(seal(doc)), encoding='utf-8')
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    with pytest.raises(ValueError):
        receiver.ingest(output, manifest, wire)
    assert count(receiver.path) == 0


@pytest.mark.parametrize('rehash', [False, True])
def test_readback_rejects_corruption_even_when_bundle_hash_is_recomputed(tmp_path, rehash):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    revision = receiver.ingest(output, manifest, wire)['export']['revision']
    with sqlite3.connect(receiver.path) as connection:
        raw, digest = connection.execute('SELECT bundle,bundle_sha256 FROM learning_evidence').fetchone()
        bundle = unpack(raw)
        bundle['sources']['native.json'] += b'changed'
        raw = pack(bundle)
        if rehash:
            digest = hashlib.sha256(raw).hexdigest()
        connection.execute('UPDATE learning_evidence SET bundle=?,bundle_sha256=?', (raw, digest))
    with pytest.raises(ValueError, match='hash differs'):
        receiver.get(revision)


def test_commit_failure_rolls_back_whole_bundle(tmp_path, monkeypatch):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    original = receiver._connect

    class CommitFailure:
        def __init__(self):
            self.connection = original()

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            return self

        def __exit__(self, *error):
            self.connection.rollback()
            raise OSError('simulated commit failure')

    with monkeypatch.context() as patch:
        patch.setattr(receiver, '_connect', CommitFailure)
        with pytest.raises(OSError, match='simulated commit failure'):
            receiver.ingest(output, manifest, wire)
    assert count(receiver.path) == 0


@pytest.mark.parametrize('columns', [
    'revision TEXT,bundle BLOB,bundle_sha256 TEXT',
    'revision TEXT PRIMARY KEY,bundle BLOB NOT NULL,bundle_sha256 TEXT NOT NULL',
    'revision TEXT NOT NULL PRIMARY KEY,bundle BLOB NOT NULL,bundle_sha256 TEXT NOT NULL,extra TEXT',
])
def test_malformed_preexisting_schema_is_refused(tmp_path, columns):
    path = tmp_path/'receiver.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE learning_evidence ('+columns+')')
    with pytest.raises(ValueError, match='schema/uniqueness'):
        LearningReceiver(path)


@pytest.mark.parametrize('extra', [
    'CREATE INDEX extra ON learning_evidence(bundle_sha256)',
    "CREATE TRIGGER extra BEFORE INSERT ON learning_evidence BEGIN SELECT RAISE(ABORT,'denied'); END",
])
def test_unapproved_schema_change_is_refused_by_ingest_and_readback(tmp_path, extra):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    revision = receiver.ingest(output, manifest, wire)['export']['revision']
    with sqlite3.connect(receiver.path) as connection:
        connection.execute(extra)
    with pytest.raises(ValueError, match='schema/uniqueness'):
        receiver.ingest(output, manifest, wire)
    with pytest.raises(ValueError, match='schema/uniqueness'):
        receiver.get(revision)
    assert count(receiver.path) == 1


def test_duplicate_json_header_and_symlink_are_rejected(tmp_path):
    output, manifest, wire, _ = native_inputs(tmp_path)
    receiver = LearningReceiver(tmp_path/'receiver.sqlite3')
    with pytest.raises(ValueError, match='duplicate JSON'):
        decode(b'{"revision":1,"revision":2}')
    alias = tmp_path/'alias.json'
    try:
        alias.symlink_to(output)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(ValueError, match='symlink'):
        receiver.ingest(alias, manifest, wire)
    assert count(receiver.path) == 0
