"""D-720 forced-command broker, running only as the protected deliberation UID."""
import asyncio
from dataclasses import asdict,replace
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time

from rosy.decision.deliberation import Problem,canonical
from rosy.decision.deliberation.profiles import BoundProfile
from rosy.decision.deliberation.status_profiles import profiles,status_query_policy
from rosy.decision.deliberation.versioned_request import prepare_request
from rosy.decision.deliberation.contracts.billing import call_cost_evidence
from . import deliberation_ollama as local
from . import deliberation_glm_judgment as glm
from . import deliberation_glm_receipt as billing
from .deliberation_opencode import GlmOpenCodeLauncher,EXECUTABLE,EXECUTABLE_SHA256
from rosy.decision.deliberation.providers.versioned_cli import VersionedCliProvider

CONFIG=Path('/etc/rosy-deliberation/status.json')
ROOT=Path(__file__).resolve().parents[2]


def protected(path,owner=0):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_mode&0o022:
        raise ValueError('BROKER_PROTECTED_FILE_REQUIRED')
    data=path.read_bytes()
    if len(data)>2_000_000:raise ValueError('BROKER_FILE_LIMIT')
    return data


def validate_job(data,revision):
    if (type(data) is not dict or set(data)!={'role','remaining','job'}
            or data['role'] not in ('primary','reviewer')):raise ValueError('INVALID_STATUS_JOB')
    job=data['job'];fields=dict(job['problem']);digest=fields.pop('input_hash')
    problem=Problem(**fields)
    if problem.domain!='fleet_status' or problem.digest!=digest:raise ValueError('INVALID_STATUS_BINDING')
    profile=profiles(revision)[0 if data['role']=='primary' else 1]
    bound=BoundProfile(profile,problem.digest)
    if data['role']=='primary':
        _,raw=prepare_request(problem,bound,(),data['remaining'],budget_usd=0,
                             missing_allowlist=('core_state','network','camera','map'))
        if canonical(job)!=raw.decode():raise ValueError('INVALID_STATUS_PRIMARY_JOB')
        return problem,bound,(),raw
    current,checked,missing,raw=glm.request(job)
    if current!=problem or checked.profile!=profile or missing!=('core_state','network','camera','map'):
        raise ValueError('INVALID_STATUS_REVIEW_JOB')
    previous=BoundProfile(profiles(revision)[0],problem.digest)
    from rosy.decision.deliberation.judgment import judgment
    prior=[]
    for item in job['prior']:
        payload=dict(item);payload.pop('profile_id')
        value=judgment(problem,previous,payload,missing_allowlist=missing)
        if not {'conflict','insufficient_evidence'}&set(value.payload['objections']):
            raise ValueError('STATUS_REVIEW_NOT_REQUIRED')
        prior.append((previous,value))
    if len(prior)!=1:raise ValueError('STATUS_BOUND_PRIMARY_REQUIRED')
    prepare_request(problem,bound,prior,data['remaining'],budget_usd=0,missing_allowlist=missing)
    return problem,bound,tuple(prior),raw.encode()


def configuration():
    import pwd
    if os.getuid()!=pwd.getpwnam('rosy-deliberation').pw_uid:raise ValueError('PROTECTED_BROKER_UID_REQUIRED')
    cfg=json.loads(protected(CONFIG))
    if set(cfg)!={'source_commit','profile_revision','valid_until','reviewer_admission','billing_policy','files','status_query_policy'}:
        raise ValueError('INVALID_HOST_ADMISSION')
    if type(cfg['valid_until']) not in (int,float) or not time.time()<cfg['valid_until']:
        raise ValueError('HOST_ADMISSION_EXPIRED')
    if cfg['status_query_policy']!=status_query_policy(cfg['source_commit'],cfg['profile_revision']):
        raise ValueError('STATUS_QUERY_POLICY_NOT_ADMITTED')
    files=cfg['files']
    if type(files) is not dict or not files or len(files)>1000:raise ValueError('SOURCE_MANIFEST_REQUIRED')
    for name,digest in files.items():
        path=ROOT/name
        if path.resolve().is_relative_to(ROOT) is False:raise ValueError('SOURCE_PATH_REFUSED')
        # A protected SHA manifest binds the installed dependency closure, not a writable checkout.
        content=protected(path)
        if hashlib.sha256(content).hexdigest()!=digest:raise ValueError('BROKER_SOURCE_CHANGED')
    return cfg


async def execute(data,cfg):
    problem,bound,prior,body=validate_job(data,cfg['profile_revision'])
    remaining=data['remaining']
    if bound.profile.role=='primary':
        result=await asyncio.to_thread(local.execute,body,remaining)
        payload=result['judgment'];cost=0.0;evidence=None
    else:
        caps=billing.AdapterCapabilities(**cfg['reviewer_admission'])
        billing.admission(caps)
        if not all((caps.ready,caps.isolated,caps.cost_verified)):raise ValueError('REVIEWER_NOT_ADMITTED')
        if hashlib.sha256(Path(EXECUTABLE).read_bytes()).hexdigest()!=EXECUTABLE_SHA256:
            raise ValueError('PINNED_PROVIDER_CHANGED')
        policy=billing.TrustedIncludedPlanPolicy(**cfg['billing_policy'])
        with GlmOpenCodeLauncher(profile=bound.profile,admission=caps,billing_policy=policy) as launch:
            provider=VersionedCliProvider(profile=bound.profile,adapter=caps,launch=launch,cli_version='1.18.35')
            raw=await provider(problem,bound,prior,remaining,budget_usd=0,
                               missing_allowlist=('core_state','network','camera','map'))
            checked,cost=raw
            evidence,error=call_cost_evidence(raw,problem,bound,checked,cost)
            if error or evidence is None:raise ValueError('REVIEW_BILLING_UNKNOWN')
            payload=checked.payload;evidence=evidence.payload
    return dict(source_commit=cfg['source_commit'],profile=asdict(bound.profile),
                judgment=payload,cost_usd=cost,cost_evidence=evidence)


def main():
    try:
        if len(sys.argv)!=1:raise ValueError('BROKER_ARGUMENTS_REFUSED')
        signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError()))
        signal.setitimer(signal.ITIMER_REAL,30)
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise ValueError('STATUS_INPUT_LIMIT')
        cfg=configuration()
        result=asyncio.run(execute(json.loads(raw),cfg))
        print(canonical(result),flush=True)
        return 0
    except Exception:
        print('{"state":"HOLD","reason":"STATUS_BROKER_NOT_ADMITTED_OR_RESULT_UNKNOWN"}',flush=True)
        return 1
    finally:signal.setitimer(signal.ITIMER_REAL,0)


if __name__=='__main__':sys.exit(main())
