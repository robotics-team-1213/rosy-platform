"""Actual loopback Fleet HTTP/auth/SQLite with explicitly synthetic SIM approvals."""
from contextlib import contextmanager, ExitStack
from functools import partial
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import uvicorn
import httpx

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'),
               str(ROOT/'middleware/robot_execution/local/src'), str(ROOT/'operations/fleet'),
               *[str(ROOT/path) for path in ('contracts/foundation', 'operations/world/src', 'operations/decision/src',
                   'operations/site_execution/src', 'operations/processes/palletizing/src',
                   'middleware/core/services')]]
sys.path[:0] = [str(ROOT/'contracts/skill/src'),str(ROOT/'contracts/learning/src')]
from rosy.execution.local.policy_lease import FleetPolicyHttp
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


def exception_types(error):
    rows, seen = [], set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        row = {'type': type(error).__name__}
        status = getattr(getattr(error, 'response', None), 'status_code', getattr(error, 'code', None))
        if type(status) is int and 100 <= status <= 599:
            row['status'] = status
        rows.append(row)
        error = error.__cause__ or error.__context__  # include context suppressed by `from None`
    return rows


def failure_diagnostics(error, exchanges, timings):
    def numeric(row):
        result = {k: row[k] for k in ('started_s', 'elapsed_s', 'cpu_s', 'response_start_s', 'status')
                  if type(row.get(k)) in (int, float) and math.isfinite(row[k])}
        for key in ('closed_before', 'closed_after'):
            if type(row.get(key)) is bool:
                result[key] = row[key]
        if isinstance(row.get('error'), BaseException):
            result['exception_types'] = exception_types(row['error'])
        return result
    return {'exception_types': exception_types(error),
            'client_http': [numeric(row) for row in exchanges],
            'server_timing': [numeric(row) for row in timings if isinstance(row, dict)]}


def public_provenance(db):
    modules = {}
    for name in ('rosy.execution.local.policy_lease', 'rosy.execution.local.policy_chain',
                 'fleet.server.app', 'httpx', 'uvicorn'):
        path = getattr(sys.modules.get(name), '__file__', None)
        if path:
            modules[name] = sha256(Path(path).read_bytes()).hexdigest()
    target = db.resolve()
    mounts = [line.split() for line in Path('/proc/mounts').read_text().splitlines()]
    matched = [(len(row[1]), row[2]) for row in mounts if len(row) > 2
               and target.is_relative_to(Path(row[1]))]
    filesystem = max(matched)[1] if matched else ''
    return {'module_sha256': modules, 'storage': 'tmpfs' if filesystem in ('tmpfs', 'ramfs')
            else 'disk' if filesystem else 'unknown'}


class MeasuredPolicyHttp(FleetPolicyHttp):
    def __call__(self, *args, **kwargs):
        row = {'started_s': time.monotonic(), 'closed_before': self._closed}
        try:
            return super().__call__(*args, **kwargs)
        except Exception as error:
            row['error'] = error
            raise
        finally:
            row.update(elapsed_s=time.monotonic()-row['started_s'], closed_after=self._closed)
            self.exchanges.append(row)


class HttpServer:
    def __init__(self, app):
        self.app, self.worker, self.listener = app, None, None

    def __enter__(self):
        try:
            self.listener = socket.socket()
            self.listener.bind(('127.0.0.1', 0))
            self.listener.listen()
            self.url = 'http://127.0.0.1:'+str(self.listener.getsockname()[1])
            self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='warning', lifespan='off', log_config=None))
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


def _fleet_app(db, users, workcell_id, instance_id, timings):
    app = create_app(FleetConsole([], []), site_users=users,
        task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db),
        omx_instances={workcell_id:instance_id}, start_task_dispatcher=False)
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
    return measured_app


@contextmanager
def _fleet_server(db, users, workcell_id, instance_id):
    exchanges, failure = [], None
    child = subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve())],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def close():
        child.stdin.close()
        try:
            code = child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
            raise AssertionError('own Fleet process did not exit') from None
        assert code == 0, 'own Fleet process failed'
    try:
        child.stdin.write(json.dumps(dict(db=str(db),users=users,
            workcell_id=workcell_id,instance_id=instance_id))+'\n')
        child.stdin.flush()
        assert select.select([child.stdout],[],[],15)[0], 'Fleet process preparation timeout'
        server = SimpleNamespace(url=json.loads(child.stdout.readline())['url'],close=close, exchanges=exchanges)
        yield server
    except Exception as error:
        failure = error
        raise
    finally:
        close()
        if failure is not None or os.environ.get('ROSY_POLICY_DIAGNOSTICS') == '1':
            try:
                timings = json.loads(db.with_name('server-timing.json').read_text())
                report = failure_diagnostics(failure, exchanges, timings)
                report.update(public_provenance(db))
                text = 'POLICY_FIXTURE_DIAGNOSTICS ' + json.dumps(report, allow_nan=False)
                if failure is not None:
                    failure.add_note(text)
                else:
                    print(text, flush=True)
            except Exception as diagnostic_error:
                if failure is not None:
                    failure.add_note('policy diagnostic unavailable: ' + type(diagnostic_error).__name__)


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
    with _fleet_server(db,users,workcell_id,instance_id) as server, ExitStack() as connections:
        clients = {}
        for name, token in credentials.items():
            path = tmp_path/(name+'.private')
            path.touch(mode=0o600, exist_ok=False)
            path.write_text(token)
            if name == 'sim-device':
                clients[name] = connections.enter_context(MeasuredPolicyHttp(server.url, path, loopback_sim=True))
                clients[name].exchanges = server.exchanges
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
        yield SimpleNamespace(server=server, admin=admin, operator=clients['sim-operator'],
            device=clients['sim-device'], window=window,
            db=db, base=base, rig_revision=rig_revision, calibration_revision=calibration_revision,
            credentials=credentials, scope='SIM fixed reach')


if __name__ == '__main__':
    settings = json.loads(sys.stdin.readline())
    timings = []
    try:
        with HttpServer(_fleet_app(**settings,timings=timings)) as server:
            print(json.dumps(dict(url=server.url)),flush=True)
            sys.stdin.readline()
    finally:
        Path(settings['db']).with_name('server-timing.json').write_text(json.dumps(timings,indent=2))
