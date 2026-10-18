"""Bind an agent-selected topic to registered Cell documents through the existing Fleet API.

This client does not interpret free text or control devices. The agent chooses registered
documents; explicit admission still belongs to Fleet's named-operator and generation checks.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import uuid
from urllib.parse import urlsplit

import httpx

from core_common.protocol.cell_app import CellAppCompileRequest, CellAppProposalRequest


def validate_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Fleet URL must be an http(s) origin without credentials, path, query or fragment')
    if parsed.scheme == 'http':
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == 'localhost'
        if not loopback:
            raise ValueError('remote Fleet requires verified HTTPS')
    return value.rstrip('/')


class FleetHttp:
    def __init__(self, url, token_file, ca_file=None):
        url = validate_url(url)
        token = Path(token_file).read_text(encoding='utf-8').strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError('nonempty bearer token without whitespace required')
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.client = httpx.Client(base_url=url, headers={'Authorization': 'Bearer '+token},
                                   verify=context, timeout=5., follow_redirects=False, trust_env=False)

    def request(self, method, path, body=None):
        response = self.client.request(method, path, json=body)
        if response.status_code != 200:
            raise ValueError(f'Fleet HTTP {response.status_code}; inspect the Fleet audit without resubmitting')
        return response.json()

    def close(self):
        self.client.close()


def write(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())


def prepare_task(api, topic, binding, output):
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 4096:
        raise ValueError('nonempty topic of at most 4096 characters required')
    if not isinstance(binding, dict):
        raise ValueError('explicit registered document and workcell binding required')
    document = {'topic': topic, 'binding': binding, 'request_id': uuid.uuid4().hex}
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    request_key = 'topic-'+hashlib.sha256(canonical).hexdigest()
    request = CellAppProposalRequest.model_validate({**binding, 'request_key': request_key}, strict=True)
    refs = CellAppCompileRequest.model_validate(request.model_dump(include={
        'recipe_id', 'recipe_digest', 'cell_id', 'cell_digest'}), strict=True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    submitted = False
    try:
        write(output/'request.json', {**document, 'request_key': request_key,
                                      'topic_interpretation': 'caller_selected_registered_documents'})
        preview = api.request('POST', '/api/fleet/cell-app/compile', refs.model_dump())
        candidate = preview.get('candidate', {})
        if (candidate.get('kind') != 'cell_job' or candidate.get('recipe_sha256') != refs.recipe_digest
                or candidate.get('cell_sha256') != refs.cell_digest):
            raise ValueError('Fleet compilation digest differs from the requested document binding')
        write(output/'plan.json', preview)
        write(output/'submission-intent.json', request.model_dump())
        submitted = True  # A lost response is uncertain; no automatic mutation retry.
        response = api.request('POST', '/api/fleet/cell-app/proposals', request.model_dump())
        write(output/'fleet-response.json', response)
        mission = response.get('mission')
        if (not isinstance(mission, dict) or mission.get('status') != 'PROPOSED'
                or not isinstance(mission.get('mission_id'), str)):
            raise ValueError('Fleet proposal did not return a current PROPOSED job; reconcile before proceeding')
        result = dict(request_key=request_key, mission=mission, task_success=None,
                      admission_required=True, device_commands_sent=0,
                      next_read_path='/api/fleet/cell-jobs/'+mission['mission_id'])
        write(output/'receipt.json', result)
        return result
    except Exception as exc:
        # Never persist provider error text, headers, credentials or arbitrary response bodies here.
        write(output/'failure.json', dict(error_type=type(exc).__name__, submission_uncertain=submitted,
                                          request_key=request_key, automatically_retried=False))
        raise


def read_status(api, mission_id, output):
    if not isinstance(mission_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,192}', mission_id):
        raise ValueError('canonical mission identifier required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    snapshot = api.request('GET', '/api/fleet/cell-jobs/'+mission_id)
    job = snapshot.get('job')
    if not isinstance(job, dict) or job.get('mission_id') != mission_id:
        raise ValueError('Fleet job identity differs')
    status = job.get('status')
    result = dict(mission_id=mission_id, status=status, snapshot=snapshot,
                  task_success=True if status == 'GOAL_CONFIRMED' else False if status == 'FAILED' else None,
                  device_commands_sent=0)
    write(output/'status.json', result)
    return result


def admit_task(api, prepared, expected_generation, output):
    """Explicitly approve one saved proposal through Fleet; never rearm or retry it."""
    if type(expected_generation) is not int or expected_generation < 0:
        raise ValueError('explicit nonnegative dispatch generation required')
    prepared = Path(prepared)
    saved = {name: (prepared/name).read_bytes() for name in
             ('request.json', 'submission-intent.json', 'receipt.json')}
    document, intent, receipt = [json.loads(raw) for raw in saved.values()]
    canonical = json.dumps({key: document[key] for key in ('topic', 'binding', 'request_id')},
                           sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    key = 'topic-'+hashlib.sha256(canonical).hexdigest()
    if (document['request_key'] != key or receipt['request_key'] != key
            or intent != {**document['binding'], 'request_key': key}):
        raise ValueError('saved task request digest differs')
    request = CellAppProposalRequest.model_validate(intent, strict=True)
    mission_id = receipt['mission']['mission_id']
    if not isinstance(mission_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,192}', mission_id):
        raise ValueError('canonical mission identifier required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    submitted = False
    try:
        current = api.request('GET', '/api/fleet/proposals/'+mission_id)
        proposal, mission = current['proposal'], current['mission']
        candidate = proposal['candidate']
        if (proposal['proposal_id'] != mission_id or proposal['request_key'] != key
                or proposal['state'] != 'RESOLVED' or mission['mission_id'] != mission_id
                or mission['status'] != 'PROPOSED' or mission['workcell_id'] != request.workcell_id
                or mission['instance_id'] != request.instance_id or candidate.get('kind') != 'cell_job'
                or candidate['recipe_sha256'] != request.recipe_digest
                or candidate['cell_sha256'] != request.cell_digest):
            raise ValueError('current Fleet proposal differs from saved task; reconcile before admission')
        write(output/'admission-intent.json', dict(mission_id=mission_id, request_key=key,
            expected_generation=expected_generation,
            prepared_files={name: hashlib.sha256(raw).hexdigest() for name, raw in saved.items()}))
        submitted = True
        response = api.request('POST', '/api/fleet/missions/'+mission_id+'/admit',
                               {'expected_generation': expected_generation})
        write(output/'fleet-response.json', response)
        mission = response['mission']
        if mission['mission_id'] != mission_id or mission['status'] != 'READY':
            raise ValueError('Fleet admission outcome requires reconciliation')
        result = dict(mission=mission, admission_accepted=True, task_success=None,
                      execution_verified=False, next_read_path='/api/fleet/cell-jobs/'+mission_id)
        write(output/'receipt.json', result)
        return result
    except Exception as exc:
        write(output/'failure.json', dict(error_type=type(exc).__name__, submission_uncertain=submitted,
                                          request_key=key, automatically_retried=False))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fleet-url', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--topic', required=True)
    prepare.add_argument('--binding', type=Path, required=True)
    prepare.add_argument('--out', type=Path, required=True)
    status = commands.add_parser('status')
    status.add_argument('--mission-id', required=True)
    status.add_argument('--out', type=Path, required=True)
    execute = commands.add_parser('admit', help='explicit Fleet admission; may enable device execution')
    execute.add_argument('--prepared', type=Path, required=True)
    execute.add_argument('--expected-generation', type=int, required=True)
    execute.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    api = None
    try:
        api = FleetHttp(args.fleet_url, args.token_file, args.ca_file)
        if args.command == 'prepare':
            result = prepare_task(api, args.topic, json.loads(args.binding.read_text(encoding='utf-8')), args.out)
        elif args.command == 'status':
            result = read_status(api, args.mission_id, args.out)
        else:
            result = admit_task(api, args.prepared, args.expected_generation, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(2, f'Fleet task request stopped ({type(exc).__name__}); preserve the output and inspect Fleet\n')
    finally:
        if api is not None:
            api.close()


if __name__ == '__main__':
    main()
