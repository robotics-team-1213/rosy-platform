"""Review AI and version routes enforce session, CSRF, identity and read-only history."""
from contextlib import contextmanager
import json
import threading
import urllib.request

import pytest

from review_app import make_server
from review_ai_jobs import Jobs
from test_review_ai_jobs import workspace
from test_learning_collaboration import Accounts, request


class Team(Accounts):
    def authenticate(self, session):
        if session == 'other-editor' and self.active:
            return dict(user_id=session, project_id='alpha', capabilities=['view', 'edit'])
        return super().authenticate(session)


@contextmanager
def running(tmp_path, backend=None, collaboration=True):
    store = workspace(tmp_path)
    accounts = Team() if collaboration else None
    jobs = Jobs(store, backend=backend or (lambda *_: {'boxes': []}))
    server = make_server(store, 0, accounts=accounts, ai_jobs=jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', store, jobs, accounts
    finally:
        server.shutdown(); server.server_close(); thread.join(5)


def token(url, session='editor'):
    code, value = request(url, '/api/workspace', session)
    assert code == 200
    return value['token']


@pytest.mark.parametrize('path', ['/api/review-ai/0', '/api/review-history/object/0',
    '/api/review-versions/object/0/1', '/api/review-version-images/0/1'])
def test_ai_and_history_require_view_identity(tmp_path, path):
    with running(tmp_path) as (url, _, _, _):
        assert request(url, path)[0] == 401


def test_csrf_viewer_and_forged_actor_fail_closed(tmp_path):
    with running(tmp_path) as (url, _, jobs, _):
        csrf = token(url)
        body = {'action': 'object_draft', 'version': 1}
        assert request(url, '/api/review-ai/0', 'editor', body)[0] == 403
        assert request(url, '/api/review-ai/0', 'reader', body, csrf)[0] == 403
        for field in ('actor', 'reviewer', 'author', 'command', 'model'):
            assert request(url, '/api/review-ai/0', 'editor', dict(body, **{field: 'forged'}), csrf)[0] == 400
        assert jobs.status(0)['jobs'] == []


def test_success_uses_authenticated_actor_and_stale_request_is_conflict(tmp_path):
    with running(tmp_path) as (url, store, jobs, _):
        csrf = token(url)
        assert request(url, '/api/review-ai/0', 'editor', {'action': 'object_draft', 'version': 0}, csrf)[0] == 409
        code, job = request(url, '/api/review-ai/0', 'editor', {'action': 'object_draft', 'version': 1}, csrf)
        assert code == 200 and job['actor'] == 'editor'
        jobs.thread.join(5)
        _, status = request(url, '/api/review-ai/0', 'reader')
        assert status['jobs'][0]['state'] == 'succeeded'
        assert store.get(0)['status'] == 'pending'


@pytest.mark.parametrize('canceller', ['editor', 'reviewer'])
def test_cancel_requires_owner_or_manager_and_editor_capability(tmp_path, canceller):
    started = threading.Event()
    def backend(_, cancel):
        started.set(); assert cancel.wait(5)
        return {'boxes': []}
    with running(tmp_path, backend) as (url, store, jobs, _):
        csrf = token(url)
        code, job = request(url, '/api/review-ai/0', 'editor', {'action': 'object_draft', 'version': 1}, csrf)
        assert code == 200 and started.wait(5)
        path = '/api/review-ai-cancel/' + job['id']
        assert request(url, path, 'reader', {}, csrf)[0] == 403
        assert request(url, path, 'other-editor', {}, csrf)[0] == 403
        assert request(url, path, canceller, {}, csrf)[0] == 200
        jobs.thread.join(5)
        done = jobs.status(0)['jobs'][0]
        assert done['state'] == 'cancelled' and done['cancelled_by'] == canceller
        assert not store.object_drafts(0)


def test_revoked_session_cannot_publish_finished_ai_result(tmp_path):
    started, release = threading.Event(), threading.Event()
    def backend(*_):
        started.set(); assert release.wait(5)
        return {'boxes': []}
    with running(tmp_path, backend) as (url, store, jobs, accounts):
        csrf = token(url)
        assert request(url, '/api/review-ai/0', 'editor', {'action': 'object_draft', 'version': 1}, csrf)[0] == 200
        assert started.wait(5)
        accounts.active = False
        release.set(); jobs.thread.join(5)
        assert jobs.status(0)['jobs'][0]['state'] == 'failed'
        assert not store.object_drafts(0)


def test_history_pages_previews_and_static_assets_are_read_only(tmp_path):
    with running(tmp_path) as (url, store, _, _):
        before = store.get(0)
        assert request(url, '/api/review-history/object/0?limit=1', 'reader')[1]['events'][0]['version'] == 1
        assert request(url, '/api/review-history/object/0?before=1', 'reader')[1]['events'] == []
        assert request(url, '/api/review-history/object/0?before=1&before=2', 'reader')[0] == 400
        assert request(url, '/api/review-history/object/0?limit=101', 'reader')[0] == 400
        assert request(url, '/api/review-versions/object/0/1', 'reader')[1]['available']
        assert request(url, '/api/review-versions/pixel/0/1', 'reader')[1]['available']
        for path in ('/api/review-version-images/0/1', '/versions.js', '/ai-jobs.js'):
            req = urllib.request.Request(url + path, headers={'Cookie': 'rosy_learning_session=reader'})
            with urllib.request.urlopen(req) as response:
                assert response.status == 200 and response.read()
        assert store.get(0) == before


def test_local_actor_is_explicitly_unidentified_and_server_close_releases_jobs(tmp_path):
    with running(tmp_path, collaboration=False) as (url, _, jobs, _):
        csrf = token(url, None)
        code, job = request(url, '/api/review-ai/0', None, {'action': 'object_draft', 'version': 1}, csrf)
        assert code == 200 and job['actor'] == 'local-unidentified'
        jobs.thread.join(5)
    assert jobs.lease is None
