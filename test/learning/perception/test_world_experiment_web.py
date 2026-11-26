"""Exercise the Account and request-boundary behavior on the real Learning HTTP server."""

from contextlib import contextmanager
import json
import threading
import urllib.error
import urllib.request

import pytest

from review_app import make_server
from test_review_app import open_store
from test_learning_collaboration import Accounts, request


PATH = '/api/learning/world-experiments'
RUN_ID = 'de3db801-3844-41c3-aeb3-3abbdd260c97'
START = {'preset_id': 'mujoco-act-cpu', 'request_id': RUN_ID}


class Center:
    def __init__(self):
        self.calls = []

    def bind_workspace(self, project):
        self.project = project

    def world_experiment(self):
        return {'preset': {'id': START['preset_id']}, 'runs': []}

    def start_world_experiment(self, body):
        self.calls.append(('start', body))
        return {'id': RUN_ID, 'status': 'running'}

    def stop_world_experiment(self, body):
        self.calls.append(('stop', body))
        return {'id': RUN_ID, 'status': 'stopping'}


@contextmanager
def running(tmp_path, accounts, center):
    server = make_server(open_store(tmp_path), 0, accounts=accounts, omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_world_controls_require_project_manager_csrf_and_origin(tmp_path):
    center = Center()
    accounts = Accounts()
    with running(tmp_path, accounts, center) as base:
        assert request(base, PATH)[0] == 401
        assert request(base, PATH, 'reader')[1]['can_manage'] is False
        assert request(base, PATH, 'reviewer')[1]['can_manage'] is True
        reader_token = request(base, '/api/accounts/session', 'reader')[1]['token']
        manager_token = request(base, '/api/accounts/session', 'reviewer')[1]['token']
        assert request(base, PATH + '/start', 'reader', START, reader_token)[0] == 403
        assert request(base, PATH + '/start', 'reviewer', START, 'invalid-token')[0] == 403
        forged = urllib.request.Request(base + PATH + '/start', data=json.dumps(START).encode(), headers={
            'Origin': 'https://other.invalid', 'Cookie': 'rosy_learning_session=reviewer',
            'X-Pinky-Token': manager_token,
        })
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(forged)
        assert failure.value.code == 403
        assert center.calls == []
        assert request(base, PATH + '/start', 'reviewer', START, manager_token)[1]['id'] == RUN_ID
        assert request(base, PATH + '/stop', 'reviewer', {'id': RUN_ID}, manager_token)[1]['status'] == 'stopping'
        accounts.active = False
        assert request(base, PATH + '/start', 'reviewer', START, manager_token)[0] == 403
        assert center.calls == [('start', START), ('stop', {'id': RUN_ID})]


def test_unidentified_local_mode_cannot_control_world_experiments(tmp_path):
    center = Center()
    with running(tmp_path, None, center) as base:
        assert request(base, PATH)[0] == 403
        assert center.calls == []
