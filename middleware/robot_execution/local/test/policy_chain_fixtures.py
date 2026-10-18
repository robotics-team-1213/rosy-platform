"""Actual loopback Fleet HTTP/auth/SQLite with explicitly synthetic SIM approvals."""
from contextlib import contextmanager, ExitStack
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from types import SimpleNamespace

import uvicorn
import httpx

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'),
               str(ROOT/'middleware/robot_execution/local/src'), str(ROOT/'operations/fleet'),
               *[str(ROOT/path) for path in ('operations/world/src', 'operations/decision/src',
                   'operations/site_execution/src', 'operations/processes/palletizing/src',
                   'contracts/foundation', 'middleware/core/services')]]
from rosy.execution.local.policy_lease import FleetPolicyHttp
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


class HttpServer:
    def __init__(self, app):
        self.app, self.worker, self.listener = app, None, None

    def __enter__(self):
        try:
            self.listener = socket.socket()
            self.listener.bind(('127.0.0.1', 0))
            self.listener.listen()
            self.url = 'http://127.0.0.1:'+str(self.listener.getsockname()[1])
            self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='warning', lifespan='off'))
            self.worker = threading.Thread(target=self.server.run, kwargs={'sockets':[self.listener]})
            self.worker.start()
            deadline = time.monotonic()+10
            while not self.server.started:
                if not self.worker.is_alive() or time.monotonic() >= deadline:
                    raise AssertionError('own HTTP fixture did not start')
                time.sleep(.01)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.worker is not None:
            self.server.should_exit = True
            self.worker.join(5)
            assert not self.worker.is_alive(), 'own HTTP fixture did not exit'
        if self.listener is not None:
            self.listener.close()

    def __exit__(self, *args):
        self.close()


def _operator_request(client, method, path, body=None):
    response = client.request(method, path, json=body)
    response.raise_for_status()
    return response.json()


@contextmanager
def approved_fleet(tmp_path, *, workcell_id, instance_id, policy_revision,
                   rig_revision='sim-rig', calibration_revision='cal-7'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path/'fleet.sqlite3'
    names = {'sim-admin-a':'policy-admin', 'sim-admin-b':'policy-admin',
             'sim-operator':'operator', 'sim-device':'service'}
    credentials = {name: secrets.token_urlsafe(32) for name in names}
    users = {sha256(credentials[name].encode()).hexdigest():dict(principal_id=name, role=role)
             for name, role in names.items()}
    app = create_app(FleetConsole([], []), site_users=users,
        task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db),
        omx_instances={workcell_id:instance_id}, start_task_dispatcher=False)
    timings = []
    run = app.state.policy_governance._run
    def measured_run(fn):
        began, cpu = time.monotonic(), time.thread_time()
        try:
            return run(fn)
        finally:
            timings.append(dict(kind='store_transaction',started_s=began,
                elapsed_s=time.monotonic()-began,cpu_s=time.thread_time()-cpu))
    app.state.policy_governance._run = measured_run
    async def measured_app(scope, receive, send):
        began = time.monotonic()
        row = dict(kind=scope['type'],method=scope.get('method'),path=scope.get('path'),started_s=began)
        async def delivered(message):
            if message['type'] == 'http.response.start':
                row['status'] = message['status']
                row['response_start_s'] = time.monotonic()
            await send(message)
        try:
            await app(scope,receive,delivered)
        finally:
            row['elapsed_s'] = time.monotonic()-began
            timings.append(row)
    with HttpServer(measured_app) as server, ExitStack() as connections:
        clients = {}
        for name, token in credentials.items():
            path = tmp_path/(name+'.private')
            path.touch(mode=0o600, exist_ok=False)
            path.write_text(token)
            if name == 'sim-device':
                clients[name] = connections.enter_context(FleetPolicyHttp(server.url, path, loopback_sim=True))
            else:
                # Approval preparation precedes execution; the device's 0.2s transport budget is unchanged.
                client = connections.enter_context(httpx.Client(base_url=server.url, timeout=2,
                    trust_env=False, follow_redirects=False, headers={'Authorization':'Bearer '+token}))
                clients[name] = partial(_operator_request, client)
        base = '/api/fleet/workcells/'+workcell_id+'/policy'
        admin, second = clients['sim-admin-a'], clients['sim-admin-b']
        revisions = dict(rig_revision=rig_revision, calibration_revision=calibration_revision)
        for stage in ('L0','L1','L2','L3'):
            proposal = admin('POST', base+'/proposals', dict(operator_confirmed=True,
                policy_revision=policy_revision, to_stage=stage, evidence_sha256='a'*64,
                note='synthetic SIM acceptance only', **revisions))
            second('POST', base+'/proposals/'+proposal['proposal_id']+'/decision',
                   dict(operator_confirmed=True, approve=True))
        window = admin('POST', base+'/windows', dict(operator_confirmed=True,
            policy_revision=policy_revision, kind='supervised', scope='SIM fixed reach', minutes=1, **revisions))
        window = second('POST', base+'/windows/'+window['window_id']+'/approve', dict(operator_confirmed=True))
        try:
            yield SimpleNamespace(server=server, admin=admin, operator=clients['sim-operator'],
                device=clients['sim-device'], window=window,
                db=db, base=base, rig_revision=rig_revision, calibration_revision=calibration_revision,
                credentials=credentials, scope='SIM fixed reach')
        finally:
            (tmp_path/'server-timing.json').write_text(json.dumps(timings,indent=2))
