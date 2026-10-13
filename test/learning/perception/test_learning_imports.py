"""Immutable, permission-bound HF downloads; no external accounts or scripts."""
import hashlib
import json

import pytest

from learning_imports import LearningImports


SHA = 'a' * 40
RIGHTS = {'internal_use': True, 'evidence': 'Project license review 17'}


class Transport:
    def __init__(self):
        self.data = {'clip.mp4': b'video', 'meta.json': b'{}'}
        self.gated = False
        self.fail = False
        self.downloads = []

    def resolve(self, kind, repo, revision, token):
        assert token == 'selected-secret'
        return {'sha': SHA, 'gated': self.gated, 'private': False,
                'siblings': [{'rfilename': n, 'size': len(v)} for n, v in self.data.items()]}

    def chunks(self, kind, repo, revision, filename, token):
        self.downloads.append((revision, filename, token))
        yield self.data[filename][:1]
        if self.fail:
            raise RuntimeError('selected-secret must never enter persisted errors')
        yield self.data[filename][1:]


def make(tmp_path):
    transport = Transport()
    authority = {'allowed': True, 'generation': 1}
    def authorize(actor, project, capability):
        if actor != 'alice' or project != 'alpha' or not authority['allowed']:
            raise PermissionError('denied')
    def credential(actor, project, connection, generation=None, resource=None):
        authorize(actor, project, 'import')
        if connection != 'account-a' or generation not in (None, authority['generation']):
            raise PermissionError('revoked')
        return {'token': 'selected-secret', 'generation': authority['generation']}
    return LearningImports(tmp_path / 'imports', authorize, credential, transport=transport), transport, authority


def create(service, **kw):
    args = dict(actor='alice', project_id='alpha', connection_id='account-a', repo_type='dataset',
                repo_id='org/data', revision='main', files=['clip.mp4', 'meta.json'], rights=RIGHTS)
    args.update(kw)
    return service.create(**args)


def test_fixed_revision_hash_readback_and_no_secrets(tmp_path):
    service, transport, _ = make(tmp_path)
    job = create(service)
    service.run(job['id'], 'alice')
    done = service.get('alice', 'alpha', job['id'])
    assert done['status'] == 'completed'
    assert done['revision'] == SHA
    assert done['curation_status'] == 'pending_curation'
    assert done['files'][0]['sha256'] == hashlib.sha256(b'video').hexdigest()
    assert all(row[0] == SHA for row in transport.downloads)
    assert 'selected-secret' not in json.dumps(done)
    with pytest.raises(PermissionError):
        service.get('bob', 'alpha', job['id'])
    with pytest.raises(PermissionError):
        service.get('alice', 'beta', job['id'])


def test_failure_retry_and_restart_keep_revision(tmp_path):
    service, transport, _ = make(tmp_path)
    job = create(service)
    transport.fail = True
    service.run(job['id'], 'alice')
    failed = service.get('alice', 'alpha', job['id'])
    assert failed['status'] == 'failed'
    assert 'selected-secret' not in json.dumps(failed)
    assert not list((tmp_path / 'imports').rglob('manifest.json'))
    transport.fail = False
    service.retry('alice', 'alpha', job['id'])
    service.run(job['id'], 'alice')
    assert service.get('alice', 'alpha', job['id'])['status'] == 'completed'
    assert all(row[0] == SHA for row in transport.downloads)


def test_gated_hold_and_revocation(tmp_path):
    service, transport, authority = make(tmp_path)
    transport.gated = True
    job = create(service)
    assert job['status'] == 'rights_hold'
    service.run(job['id'], 'alice')
    assert not transport.downloads
    transport.gated = False
    other = create(service, files=['meta.json'])
    authority['generation'] = 2
    service.run(other['id'], 'alice')
    assert service.get('alice', 'alpha', other['id'])['status'] == 'blocked'
    assert not transport.downloads


@pytest.mark.parametrize('files', [['../secret'], ['/tmp/a'], ['a\\b'], ['a/../b'], ['https://evil/a']])
def test_unsafe_names_rejected(tmp_path, files):
    service, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        create(service, files=files)


def test_cancel_and_missing_rights(tmp_path):
    service, transport, _ = make(tmp_path)
    with pytest.raises(ValueError):
        create(service, rights={'internal_use': True})
    job = create(service)
    service.cancel('alice', 'alpha', job['id'])
    service.run(job['id'], 'alice')
    assert service.get('alice', 'alpha', job['id'])['status'] == 'cancelled'
    assert not transport.downloads

