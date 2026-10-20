"""Actual native service and kernel boundary for a pre-promotion SIM study."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from g2_common import ROOT
from g2_ports import isolation_guard
from native_sim_inputs import STUDY_EXPERIMENTS, read_json, study_approval
from native_sim_job import validate_state


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _process(pid):
    root=Path('/proc')/str(pid)
    raw=(root/'stat').read_text()
    fields=raw[raw.rfind(')')+2:].split()
    return dict(pid=pid,ppid=int(fields[1]),start_ticks=int(fields[19]),
        cgroup=(root/'cgroup').read_text().strip(),
        argv_sha256=hashlib.sha256((root/'cmdline').read_bytes()).hexdigest())


def _kernel(source,model,cgroup):
    if Path('/proc/self/cgroup').read_text().strip()!=cgroup:
        raise PermissionError('native service cgroup changed')
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if status['NoNewPrivs'].strip()!='1' or int(status['CapEff'].strip(),16)!=0:
        raise PermissionError('native process privileges are not closed')
    if any(not os.statvfs(path).f_flag & os.ST_RDONLY for path in (Path('/'),source,model)):
        raise PermissionError('study source/model/root must remain read-only')
    if any(path.name!='lo' for path in Path('/sys/class/net').iterdir()):
        raise PermissionError('study requires network-none')
    if Path('/dev/serial/by-id').exists() or any(
            list(Path('/dev').glob(pattern)) for pattern in ('video*','ttyACM*','ttyUSB*','ttyS*')):
        raise PermissionError('study refuses physical device visibility')


@dataclass(frozen=True)
class NativeStudyScope:
    state: Path
    source: Path
    policy_input: Path
    approval: bytes
    job: bytes
    cgroup: str
    start_intent_sha256: str
    run_intent_sha256: str


def native_scope(state):
    state=Path(state).absolute()
    document=validate_state(state)
    run_id=document['run_id']
    managed=Path('/var/lib/rosy-native-sim')/str(os.getuid())
    if (state!=managed/'state'/run_id[-12:] or state.resolve()!=state
            or Path(document['source'])!=ROOT.resolve()
            or os.environ.get('OMX_NATIVE_STATE')!=str(state)
            or os.environ.get('OMX_NATIVE_RUN_ID')!=run_id
            or document.get('experiment') not in STUDY_EXPERIMENTS):
        raise PermissionError('exact managed native policy study required')
    isolation_guard(ROOT)
    start=read_json(state/'start-intent.json')
    run=read_json(state/'run-intent.json')
    approval=study_approval(document)
    if (start.get('run_id')!=run_id or start.get('revision')!=document['revision']
            or start.get('state')!=str(state) or start.get('uid')!=os.getuid()
            or start.get('approval')!=['isolated-simulation','startup-home']
            or start.get('study_approval')!=approval or run.get('run_id')!=run_id
            or run.get('runtime')!='UNKNOWN' or type(run.get('pid')) is not int
            or not start['created_at']<=run['started_at']<=start['expires_at']):
        raise PermissionError('actual native user approvals and launch identity required')
    cgroup='0::/system.slice/'+document['unit']+'.service'
    model=Path(document['policy_input'])
    _kernel(ROOT,model,cgroup)
    process=_process(run['pid'])
    expected=[b'/usr/bin/python3',b'-B',str(ROOT/'deploy/robot/omx/native_sim_job.py').encode(),
              b'run',b'--state',str(state).encode()]
    argv=(Path('/proc')/str(run['pid'])/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    if process['cgroup']!=cgroup or argv!=expected:
        raise PermissionError('native job executable or service identity differs')
    ancestor=os.getpid()
    for _ in range(64):
        if ancestor==run['pid']:break
        ancestor=_process(ancestor)['ppid']
        if ancestor<=1:raise PermissionError('native job is not the study process ancestor')
    else:
        raise PermissionError('native job ancestry is unbounded')
    return NativeStudyScope(state,ROOT,model,_encoded(approval),_encoded(process),cgroup,
        hashlib.sha256((state/'start-intent.json').read_bytes()).hexdigest(),
        hashlib.sha256((state/'run-intent.json').read_bytes()).hexdigest())


def scope_live(scope):
    _kernel(scope.source,scope.policy_input,scope.cgroup)
    process=json.loads(scope.job)
    if (_encoded(_process(process['pid']))!=scope.job or (scope.state/'exit.json').exists()
            or hashlib.sha256((scope.state/'start-intent.json').read_bytes()).hexdigest()!=scope.start_intent_sha256
            or hashlib.sha256((scope.state/'run-intent.json').read_bytes()).hexdigest()!=scope.run_intent_sha256):
        raise PermissionError('native job or original approval identity changed')
    return True
