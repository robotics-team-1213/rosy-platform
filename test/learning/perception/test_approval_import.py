"""D-898: the model PC records a signed Fleet approval only after every check, under model-watch's lock."""
import fcntl
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import approval_import as ai
import promotion_request as pr
from rosy.contracts.learning.promotion_request import decision_encoded, sign
from store import file_hashes
from test_promotion_request import candidate

KEY_ID = 'perception-decision-v1'


def private_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


@pytest.fixture
def made(tmp_path):
    root, control = candidate(tmp_path)
    bundle = pr.build(root, 'learner', control, now='2026-10-27T00:00:00+00:00')
    state = tmp_path / 'state'
    state.mkdir()
    sha = pr.write(state, bundle)['sha256']
    key = Ed25519PrivateKey.generate()
    (tmp_path / 'model-code').mkdir()
    row = {'bundle_sha256': sha, 'model_revision': bundle['model']['revision'], 'files': bundle['model']['files'],
           'proposed_by': 'admin-a', 'decided_by': 'admin-b', 'decided_ns': 1, 'state': 'APPROVED'}
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return SimpleNamespace(tmp=tmp_path, root=root, ledger=control.out / 'state.json', state=state, key=key,
                           public=public, row=row, store=tmp_path / 'store', work=tmp_path / 'model-code',
                           accepted=tmp_path / 'store/models/accepted' / row['model_revision'],
                           approvals=tmp_path / 'store/models/approvals' / sha)


def run(made, *, key=None, signed_id=KEY_ID, pinned_id=KEY_ID, signature=None, **change):
    raw = decision_encoded(dict(made.row, **change))
    doc = {'key_id': signed_id, 'decision': raw.decode(),
           'signature': signature or sign(raw, private_pem(key or made.key), signed_id)}
    path = made.tmp / 'decision.signed'
    path.write_text(json.dumps(doc), encoding='utf-8')
    return ai.run(path, made.public, pinned_id, made.state, made.ledger, made.store, made.work)


def untouched(made):
    assert not made.accepted.exists() and not made.approvals.exists()
    assert not (made.store / 'models/inbox').exists() or not any((made.store / 'models/inbox').iterdir())


def test_an_approval_lands_in_accepted_and_approvals_only(made):
    before = file_hashes(made.root)
    assert 'accepted' in run(made)
    assert file_hashes(made.accepted) == before  # the whole result folder, model manifest and report included
    assert json.loads((made.approvals / 'decision.json').read_bytes())['decided_by'] == 'admin-b'
    signed = json.loads((made.approvals / 'decision.signed').read_bytes())
    assert signed['key_id'] == KEY_ID and signed['decision'].encode() == (made.approvals / 'decision.json').read_bytes()
    assert not any((made.store / 'models/inbox').iterdir())
    # Nothing but accepted/ and approvals/ appeared under models/ (no active pointer, shadow or deploy).
    assert sorted(p.name for p in (made.store / 'models').iterdir()) == ['accepted', 'approvals', 'inbox']
    assert 'approval already recorded' in run(made)  # a second import is a no-op


def test_the_model_watch_work_lock_is_taken(made):
    with (made.work / 'work.lock').open('a+') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            run(made)
    untouched(made)


@pytest.mark.parametrize('case, refusal', [
    ('signature', 'signature'), ('key', 'signature'), ('key_id', 'key id'), ('state', 'APPROVED'),
    ('bundle', 'hash'), ('revision', 'revision'), ('folder', 'result folder'), ('same_person', 'proposer'),
])
def test_each_check_refuses_before_any_write(made, case, refusal):
    kwargs = {}
    if case == 'signature':
        kwargs['signature'] = sign(b'other bytes', private_pem(made.key), KEY_ID)
    elif case == 'key':
        kwargs['key'] = Ed25519PrivateKey.generate()
    elif case == 'key_id':
        kwargs['signed_id'] = 'other-key'
    elif case == 'state':
        kwargs['state'] = 'REJECTED'
    elif case == 'bundle':
        path = made.state / 'promotion-requests' / f"{made.row['bundle_sha256']}.json"
        path.write_bytes(path.read_bytes().replace(b'learner', b'learnerX'))
    elif case == 'revision':
        kwargs['model_revision'] = 'lane-other'
    elif case == 'folder':
        (made.root / 'model.onnx').write_bytes(b'retrained')
    else:
        kwargs['decided_by'] = 'admin-a'
    with pytest.raises(ValueError, match=refusal):
        run(made, **kwargs)
    untouched(made)


def test_accepted_with_other_files_refuses_and_same_files_is_a_no_op(made):
    made.accepted.mkdir(parents=True)
    (made.accepted / 'model.onnx').write_bytes(b'something else')
    with pytest.raises(ValueError, match='different files'):
        run(made)
    assert not made.approvals.exists()
    (made.accepted / 'model.onnx').write_bytes((made.root / 'model.onnx').read_bytes())
    before = {p.name: p.stat().st_mtime_ns for p in made.accepted.iterdir()}
    assert 'already accepted' in run(made)
    assert {p.name: p.stat().st_mtime_ns for p in made.accepted.iterdir()} == before
    assert not (made.store / 'models/inbox').exists()
    assert (made.approvals / 'decision.json').is_file()
