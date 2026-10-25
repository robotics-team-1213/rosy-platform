"""Fixed loopback v2 broker; admitted local inference grants no tool authority."""
from dataclasses import replace
import json
import math
from pathlib import Path
import signal
import sys
import time
import urllib.request

from deploy.site.deliberation_sandbox import bounded_process
from rosy.decision.deliberation import Problem, canonical, identifier
from rosy.decision.deliberation.judgment import judgment, judgment_schema, schema_missing_allowlist
from rosy.decision.deliberation.profiles import AdapterCapabilities, BoundProfile, ModelProfile
from rosy.decision.structured_output import ollama_chat, ollama_reply

MODEL = 'qwen3-vl:8b-instruct'
DIGEST = '0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319'
CAPABILITIES = AdapterCapabilities('local', MODEL, DIGEST, 'ollama-json-v2', 2,
    ('line_follow', 'door', 'arm_target'), ('text',), False, False, False)
LIMIT = 16384


def model_profile(revision):
    return ModelProfile('ollama-primary', revision, 'primary', 'local', MODEL, DIGEST,
        CAPABILITIES.adapter, CAPABILITIES.domains, ('text',), 30, LIMIT, 1, 0)


def status_capabilities():
    return replace(CAPABILITIES, adapter='ollama-status-json-v2', domains=('fleet_status',))


def status_model_profile(revision):
    return replace(model_profile(revision), profile_id='ollama-status-primary',
                   adapter=status_capabilities().adapter, domains=('fleet_status',))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('LOCAL_REDIRECT_REFUSED')


def exchange(path, body, remaining):
    if path not in {'/api/ps', '/api/chat'} or (path == '/api/ps') != (body is None):
        raise ValueError('LOCAL_ROUTE_REFUSED')
    request = urllib.request.Request('http://127.0.0.1:11434' + path,
        None if body is None else canonical(body).encode(), {'Content-Type': 'application/json'},
        method='GET' if body is None else 'POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=remaining) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('LOCAL_RESPONSE_EXCEEDED')
    return json.loads(raw)


def loaded(data):
    matches = [item for item in data['models'] if item.get('name') == MODEL]
    if (len(matches) != 1 or matches[0].get('model') != MODEL or matches[0].get('digest') != DIGEST
            or matches[0].get('context_length') != 8192):
        raise ValueError('LOCAL_MODEL_CHANGED_OR_UNLOADED')


def execute(raw, remaining):
    if (type(raw) is not bytes or len(raw) > LIMIT or type(remaining) not in (int, float)
            or not math.isfinite(remaining) or not 0 < remaining <= 30):
        raise ValueError('INVALID_LOCAL_BUDGET')
    deadline = time.monotonic() + remaining
    def available():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError('LOCAL_DEADLINE')
        return value
    body = json.loads(raw)
    if set(body) != {'problem', 'profile_revision', 'schema', 'prior', 'instruction'}:
        raise ValueError('INVALID_LOCAL_JOB')
    fields = dict(body['problem'])
    digest = fields.pop('input_hash')
    problem = Problem(**fields)
    if digest != problem.digest or type(body['prior']) is not list or len(body['prior']) > 2:
        raise ValueError('INVALID_LOCAL_JOB')
    profile = (status_model_profile if problem.domain == 'fleet_status' else model_profile)(body['profile_revision'])
    bound = BoundProfile(profile, problem.digest)
    missing = schema_missing_allowlist(body['schema'])
    if len(missing) > 16 or len(set(missing)) != len(missing):
        raise ValueError('INVALID_LOCAL_JOB')
    schema = judgment_schema(problem, bound, missing_allowlist=missing)
    if canonical(schema) != canonical(body['schema']):
        raise ValueError('INVALID_LOCAL_SCHEMA')
    for entry in body['prior']:
        prior = dict(entry)
        previous = replace(profile, profile_id=identifier(prior.pop('profile_id')),
                           profile_revision=identifier(prior['profile_revision']))
        judgment(problem, BoundProfile(previous, problem.digest), prior, missing_allowlist=missing)
    loaded(exchange('/api/ps', None, available()))
    request = ollama_chat(MODEL, [{'role': 'user', 'content': canonical(body)}], schema)
    response = exchange('/api/chat', request, available())
    loaded(exchange('/api/ps', None, available()))
    payload, usage = ollama_reply(response, MODEL, 'INVALID_LOCAL_RESPONSE')
    checked = judgment(problem, bound, payload, missing_allowlist=missing)
    return {'model_id': MODEL, 'model_revision': DIGEST, 'cost_usd': 0.0,
            'usage': usage, 'judgment': checked.payload}


class OllamaTransport:
    schema_versions = (2,)

    def __init__(self, *, admission=None):
        selected = CAPABILITIES if admission is None else admission
        if (type(selected) is not AdapterCapabilities
                or replace(selected, ready=False, isolated=False, cost_verified=False)
                not in (CAPABILITIES, status_capabilities())):
            raise ValueError('LOCAL_BACKEND_MISMATCH')
        # Runtime admission must come from host verification, never source inspection.
        self.adapter_capabilities = selected
        self.cost_verified = selected.cost_verified

    async def __call__(self, body, remaining, output_limit):
        if not all((self.adapter_capabilities.ready, self.adapter_capabilities.isolated, self.cost_verified)):
            raise ValueError('LOCAL_RUNTIME_NOT_ADMITTED')
        source = Path(__file__).resolve()
        bootstrap = ('import sys,runpy;from pathlib import Path;'
            'root=Path(sys.argv[1]).parents[2];'
            'sys.path[:0]=[str(root),str(root/"operations/decision/src"),str(root/"contracts/foundation")];'
            'sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name="__main__")')
        return await bounded_process((str(Path(sys.executable).absolute()), '-c', bootstrap,
            str(source), str(remaining)), body, remaining, output_limit)


def main():
    previous_handler = signal.getsignal(signal.SIGALRM)
    try:
        remaining = float(sys.argv[1])
        if not math.isfinite(remaining) or not 0 < remaining <= 30:
            raise ValueError('INVALID_LOCAL_BUDGET')
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
        signal.setitimer(signal.ITIMER_REAL, remaining)
        result = execute(sys.stdin.buffer.read(LIMIT + 1), remaining)
        print(canonical(result), flush=True)
        return 0
    except Exception as error:
        # Diagnose boundaries without retaining provider content or exception text.
        kind = ('TIMEOUT' if isinstance(error, TimeoutError) else
                'TRANSPORT' if isinstance(error, OSError) else
                'VALIDATION' if isinstance(error, (ValueError, KeyError, TypeError)) else 'INTERNAL')
        print(canonical({'state': 'HOLD', 'reason': 'LOCAL_PROVIDER_FAILED', 'failure_kind': kind}), flush=True)
        return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


if __name__ == '__main__':
    sys.exit(main())
