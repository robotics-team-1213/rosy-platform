"""HTTP delegation keeps the center snapshot and worker result intact."""
from types import SimpleNamespace
import pytest

import omx_center_web as web


def test_center_routes_dispatch_once_and_leave_other_routes_untouched():
    calls, sent = [], []

    def operation(name):
        def invoke(body=None):
            calls.append((name, body))
            return {'operation': name, 'body': body}
        return invoke

    center = SimpleNamespace(**{name: operation(name) for name in
                               ('snapshot', 'upload', 'publish', 'start', 'start_online', 'experience', 'stop')})
    handler = SimpleNamespace(send=sent.append)
    assert web.get(handler, web.PREFIX, center)
    for route, method in [('upload', 'upload'), ('publish', 'publish'),
                          ('run', 'start'), ('online-run', 'start_online'),
                          ('experience', 'experience'), ('stop', 'stop')]:
        body = {'request': route}
        assert web.post(handler, web.PREFIX + '/' + route, body, center)
        assert calls[-1] == (method, body)
        assert sent[-1] == {'operation': method, 'body': body}
    assert not web.get(handler, '/api/learning/omx', center)
    assert not web.post(handler, web.PREFIX + '/unknown', {}, center)
    assert len(calls) == len(sent) == 7


def test_existing_review_app_routes_work_without_a_configured_center():
    sent = []
    handler = SimpleNamespace(send=sent.append)
    assert not web.post(handler, '/api/frames/1', {}, None)
    assert web.get(handler, web.PREFIX, None)
    assert sent[0]['status'] == 'not_configured'
    with pytest.raises(ValueError, match='연결되지 않았습니다'):
        web.post(handler, web.PREFIX + '/run', {}, None)


def test_live_artifact_route_returns_worker_bytes_with_zip_type():
    run_id = '720ea4ee-6471-4f53-a02a-949946663ec9'
    calls = []
    center = SimpleNamespace(artifact=lambda identity: calls.append(identity) or b'policy-version-000001')
    sent = []
    handler = SimpleNamespace(send=lambda payload, **kwargs: sent.append((payload, kwargs)))
    assert web.get(handler, web.PREFIX + '/artifact/' + run_id, center)
    assert calls == [run_id]
    assert sent == [(b'policy-version-000001', {'mime': 'application/zip'})]
