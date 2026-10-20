"""Verified HTTPS into a real Fleet app with a temporary ledger and fake robot transport."""
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time

import uvicorn


def test_connected_login_write_task_cancel_read_and_logout(tmp_path):
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    from test_password_session import _accounts, TYPED
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'applications/fleet/dev'))
    from connected import ConnectedAPI
    certificate, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(key), '-out', str(certificate), '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
    console = FleetConsole([RobotEndpoint('rosy_01', 'http://robot.invalid', 'test')], [FakeRobot('rosy_01')])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite3'), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_logins=_accounts(), start_task_dispatcher=False)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    endpoint = f'https://localhost:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, ssl_certfile=str(certificate), ssl_keyfile=str(key),
                                        log_level='error', access_log=False, proxy_headers=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        local = 'https://localhost:4174'
        adapter = ConnectedAPI(endpoint, ssl.create_default_context(cafile=str(certificate)), local)
        cookie = ''
        def request(method, path, body=None, extra=None):
            nonlocal cookie
            response = adapter.handle(method, '/api/fleet' + path,
                {'Host':'localhost:4174', 'Origin':local, 'Content-Type':'application/json', 'Cookie':cookie, **(extra or {})},
                json.dumps(body).encode() if body is not None else b'')
            for name, value in response.headers:
                if name.lower() == 'set-cookie':
                    cookie = value.split(';')[0]
            payload = response.body if isinstance(response.body, bytes) else b''.join(response.body)
            return response.status, json.loads(payload) if payload else None
        assert request('POST', '/auth/login', {'login':'alice', 'password':TYPED})[0] == 204
        assert cookie.startswith('rosy_fleet_session=')
        assert request('PATCH', '/auth/profile', {'display_name':'connected developer'})[0] == 200
        assert request('GET', '/auth/profile')[1]['display_name'] == 'connected developer'
        code, result = request('POST', '/robots/rosy_01/goal', {'x':1,'y':2,'yaw':0}, {'Idempotency-Key':'connected-goal'})
        assert code == 200 and result['task']['status'] == 'QUEUED'
        identifier = result['task']['task_id']
        assert request('POST', '/tasks/' + identifier + '/cancel', {})[0] == 200
        assert request('GET', '/tasks/' + identifier)[1]['task']['status'] == 'CANCELED'
        assert request('POST', '/auth/logout', {})[0] == 204
        assert request('GET', '/auth/session')[0] == 401
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()
