"""Current authority transfer and mask-only revisions must not reuse legacy keys."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import shutil
import subprocess
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
import review_bridge
from test_learning_cycle import make_review


WORKSPACE = 'a' * 32


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()


def current(generation=1, mask_decision='pending'):
    value = {'schema': 'rosy.pinky-review-decisions/1', 'workspace_id': WORKSPACE,
             'generation': generation, 'map_reference_sha256': None,
             'frames': [{'frame': 0, 'review_uid': WORKSPACE + ':0',
                         'identity': 'video:' + 'b' * 64 + ':3',
                         'image_sha256': hashlib.sha256(b'immutable source image').hexdigest(),
                         'source_session': 'source-session', 'capture_group': 'capture-one',
                         'source_video_sha256': 'b' * 64, 'original_video_verified': False,
                         'video_frame': 3, 'fixed_eval_overlap': False,
                         'object_version': 1, 'object_decision': 'approved',
                         'mask_version': generation, 'mask_decision': mask_decision,
                         'mask_sha256': None, 'map_revision': None, 'map_pose': None}]}
    return dict(value, decision_sha256=hashlib.sha256(encoded(value)).hexdigest())


def bundle(root, authority):
    folder = make_review(root)
    source = json.loads((folder / 'inputs/source.jsonl').read_text())
    human = json.loads((folder / 'inputs/human.jsonl').read_text())
    (folder / 'application-snapshot.json').write_bytes(encoded([
        {'index': 0, 'source': source, 'review': human, 'status': 'approved', 'version': 1}]))
    (folder / 'pixel-reviews.jsonl').write_bytes(b'')
    (folder / 'pinky-review-receipt.json').write_bytes(encoded({'export_id': 'fixture'}))
    files = [{'path': p.relative_to(folder).as_posix(), 'bytes': p.stat().st_size,
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(folder.rglob('*')) if p.is_file()]
    doc = {'schema': 'rosy.pinky-review-export/2', 'export_id': 'fixture',
           'authority': authority, 'pixel_approved_frames': 0,
           'current_decisions_required': True, 'latest_decisions_endpoint': '/api/decisions',
           'training_dataset_qualified': False, 'pixel_projection_verified': False, 'files': files}
    raw = encoded(doc)
    (folder / 'review-contract.json').write_bytes(raw)
    (folder / 'AUTHORITY_COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    return folder


def config(source):
    return {'source': str(source), 'peer': 'approved-model-peer', 'remote_reviews': '/srv/reviews',
            'interval_s': 3, 'max_attempts': 2,
            'authority': {'endpoint': 'http://127.0.0.1:8767/api/decisions', 'workspace_id': WORKSPACE}}


def test_v2_waits_for_authority_seal_and_never_falls_back_to_legacy(tmp_path):
    source = tmp_path / 'incoming'
    folder = bundle(source, current())
    (folder / 'AUTHORITY_COMPLETE').unlink()
    calls = []
    state = review_bridge.run_once(config(source), tmp_path / 'state',
                                  publisher=lambda *args: calls.append(args),
                                  current_fetcher=lambda cfg: current(),
                                  current_publisher=lambda *args: {'available': True})
    assert not calls and not state['steps']


def test_authority_mode_never_transfers_legacy_before_outer_contract_exists(tmp_path):
    source = tmp_path / 'incoming'
    make_review(source)
    calls = []
    state = review_bridge.run_once(config(source), tmp_path / 'state',
                                  publisher=lambda *args: calls.append(args),
                                  current_fetcher=lambda cfg: current(),
                                  current_publisher=lambda *args: {'available': True})
    assert not calls and not state['steps']


def test_mask_only_revision_has_distinct_transfer_key_and_all_sealed_files(tmp_path):
    source = tmp_path / 'incoming'
    first = bundle(source, current())
    seen, deliveries = [], []
    def publish(folder, key, cfg, out):
        seen.append(key)
        paths = review_bridge.export_files(folder)
        assert {'review-contract.json', 'AUTHORITY_COMPLETE', 'pixel-reviews.jsonl',
                'application-snapshot.json', 'manifest.json', 'COMPLETE'} <= set(paths)
        return {'training_dataset_qualified': False}
    review_bridge.run_once(config(source), tmp_path / 'state', publisher=publish,
                           current_fetcher=lambda cfg: current(),
                           current_publisher=lambda snapshot, *args: deliveries.append(snapshot))
    second = bundle(source / 'second', current(2, 'excluded'))
    second.rename(source / 'export-2')
    state = review_bridge.run_once(config(source), tmp_path / 'state', publisher=publish,
                                  current_fetcher=lambda cfg: current(2, 'excluded'),
                                  current_publisher=lambda snapshot, *args: deliveries.append(snapshot))
    assert len(set(seen)) == 2 and len(state['steps']) == 2
    assert deliveries[-1]['authority']['generation'] == 2


def test_current_failure_delivers_unavailable_and_never_publishes_v2(tmp_path):
    source = tmp_path / 'incoming'
    bundle(source, current())
    def offline(cfg):
        raise OSError('GUI offline')
    calls, deliveries = [], []
    state = review_bridge.run_once(config(source), tmp_path / 'state',
                                  publisher=lambda *args: calls.append(args), current_fetcher=offline,
                                  current_publisher=lambda snapshot, *args: deliveries.append(snapshot))
    assert not calls and not state['steps']
    assert deliveries[-1]['available'] is False and deliveries[-1]['authority'] is None


def test_same_generation_conflict_blocks_current_and_export(tmp_path):
    source = tmp_path / 'incoming'
    bundle(source, current())
    deliveries = []
    kwargs = {'publisher': lambda *args: {'training_dataset_qualified': False},
              'current_publisher': lambda snapshot, *args: deliveries.append(snapshot)}
    review_bridge.run_once(config(source), tmp_path / 'state',
                           current_fetcher=lambda cfg: current(), **kwargs)
    bad = current(mask_decision='excluded')
    state = review_bridge.run_once(config(source), tmp_path / 'state',
                                  current_fetcher=lambda cfg: bad, **kwargs)
    assert deliveries[-1]['available'] is False
    assert state['current_authority']['status'] == 'unavailable'


def test_new_authority_cannot_refresh_receiver_ttl_when_delivery_fails(tmp_path):
    source = tmp_path / 'incoming'
    bundle(source, current())
    def disconnected(*args):
        raise OSError('SSH offline')
    state = review_bridge.run_once(config(source), tmp_path / 'state',
                                  publisher=lambda *args: pytest.fail('not delivered current authority'),
                                  current_fetcher=lambda cfg: current(), current_publisher=disconnected)
    assert state['current_authority']['status'] == 'delivery_failed'


def test_actual_receiver_script_atomic_replace_refuses_revision_rollback(tmp_path, monkeypatch):
    """Execute the exact SSH receiver script locally, without claiming live SSH proof."""
    remote = tmp_path / 'remote'
    remote.mkdir()
    out = tmp_path / 'out'
    out.mkdir()
    cfg = config(tmp_path)
    def shell(args, **kwargs):
        if args[0] == 'scp':
            shutil.copyfile(args[-2], remote / '.current-upload.json')
            return subprocess.CompletedProcess(args, 0)
        script = kwargs['input'].replace(repr('/srv/reviews'), repr(str(remote)))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(script, '<actual-current-receiver>', 'exec'), {})
        return subprocess.CompletedProcess(args, 0, stdout=stdout.getvalue())
    monkeypatch.setattr(review_bridge.subprocess, 'run', shell)
    def delivery(generation):
        auth = current(generation)
        return {'schema': 'rosy.pinky-review-current-delivery/1', 'workspace_id': WORKSPACE,
                'authority': auth, 'available': True, 'checked_at_unix': time.time(),
                'revision': {k: auth[k] for k in ('workspace_id', 'generation', 'decision_sha256')}}
    review_bridge.publish_current(delivery(2), cfg, out)
    target = remote / '.authority/current.json'
    before = target.read_bytes()
    with pytest.raises(AssertionError):
        review_bridge.publish_current(delivery(1), cfg, out)
    assert target.read_bytes() == before
    without_history = delivery(2)
    without_history.update(available=False, authority=None, revision=None)
    with pytest.raises(AssertionError):
        review_bridge.publish_current(without_history, cfg, out)
    assert target.read_bytes() == before
    negative = delivery(2)
    negative.update(available=False, authority=None)
    assert review_bridge.publish_current(negative, cfg, out)['available'] is False
    assert json.loads(target.read_bytes())['available'] is False


def test_actual_v2_transfer_includes_and_validates_both_seals(tmp_path, monkeypatch):
    """Execute the archive receiver on host scratch; verify the remote-script logic."""
    source = tmp_path / 'incoming'
    folder = bundle(source, current())
    remote, out = tmp_path / 'remote', tmp_path / 'out'
    remote.mkdir(); out.mkdir()
    digest = hashlib.sha256((folder / 'review-contract.json').read_bytes()).hexdigest()
    def shell(args, **kwargs):
        if args[0] == 'scp':
            shutil.copyfile(args[-2], remote / ('.incoming-' + digest + '.tar'))
            return subprocess.CompletedProcess(args, 0)
        script = kwargs['input'].replace(repr('/srv/reviews'), repr(str(remote)))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(script, '<actual-bundle-receiver>', 'exec'), {})
        return subprocess.CompletedProcess(args, 0, stdout=stdout.getvalue())
    monkeypatch.setattr(review_bridge.subprocess, 'run', shell)
    receipt = review_bridge.publish(folder, digest, config(source), out)
    destination = Path(receipt['remote_path'])
    assert (destination / 'AUTHORITY_COMPLETE').read_bytes() == (folder / 'AUTHORITY_COMPLETE').read_bytes()
    assert (destination / 'pixel-reviews.jsonl').is_file()
    assert receipt['training_dataset_qualified'] is False


def test_current_receiver_publishes_exact_verified_bytes_despite_incoming_replacement(tmp_path, monkeypatch):
    remote, out = tmp_path / 'remote', tmp_path / 'out'
    remote.mkdir(); out.mkdir()
    incoming = remote / '.current-upload.json'
    auth = current(2)
    snapshot = {'schema': 'rosy.pinky-review-current-delivery/1', 'workspace_id': WORKSPACE,
                'authority': auth, 'available': True, 'checked_at_unix': time.time(),
                'revision': {k: auth[k] for k in ('workspace_id', 'generation', 'decision_sha256')}}
    expected = (json.dumps(snapshot, sort_keys=True, allow_nan=False) + '\n').encode()
    original_read = Path.read_bytes
    changed = [False]
    def interleave(path):
        data = original_read(path)
        if path == incoming and not changed[0]:
            changed[0] = True
            altered = dict(snapshot, checked_at_unix=snapshot['checked_at_unix'] + 300)
            incoming.write_text(json.dumps(altered))
        return data
    monkeypatch.setattr(Path, 'read_bytes', interleave)
    def shell(args, **kwargs):
        if args[0] == 'scp':
            shutil.copyfile(args[-2], incoming)
            return subprocess.CompletedProcess(args, 0)
        stdout = io.StringIO()
        script = kwargs['input'].replace(repr('/srv/reviews'), repr(str(remote)))
        with contextlib.redirect_stdout(stdout):
            exec(compile(script, '<receiver-interleave>', 'exec'), {})
        return subprocess.CompletedProcess(args, 0, stdout=stdout.getvalue())
    monkeypatch.setattr(review_bridge.subprocess, 'run', shell)
    review_bridge.publish_current(snapshot, config(tmp_path), out)
    assert original_read(remote / '.authority/current.json') == expected
