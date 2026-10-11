import asyncio
import json

import pytest

from rosy.decision.deliberation.cli import CliProvider
from test_deliberation import problem, reply


def test_unconfigured_isolation_never_launches():
    with pytest.raises(ValueError, match='ISOLATED_LAUNCHER_REQUIRED'):
        CliProvider(kind='claude', model='pinned-model', profile_id='p', launch=None)
    with pytest.raises(ValueError):
        CliProvider(kind='claude', model='--dangerously-skip-permissions', profile_id='p', launch=lambda: None)


@pytest.mark.parametrize('kind', ['claude', 'opencode'])
def test_fixed_argv_minimal_stdin_and_no_tool_authority(kind):
    seen = []
    async def launch(argv, stdin, timeout_s, output_limit, budget_usd):
        seen.append((argv, stdin, timeout_s, output_limit, budget_usd))
        response = reply(problem())
        if kind == 'claude':
            return 0, json.dumps({'structured_output': response, 'total_cost_usd': 0.01, 'is_error': False}).encode()
        return 0, (json.dumps({'type': 'text', 'part': {'text': json.dumps(response)}}) + '\n'
                   + json.dumps({'type': 'step_finish', 'part': {'cost': 0.01}})).encode()
    provider = CliProvider(kind=kind, model='provider/pinned', profile_id='p', launch=launch)
    payload, cost = asyncio.run(provider(problem(), (), 1.0, budget_usd=0.1))
    assert payload['choice'] == 'reobserve' and cost == 0.01
    argv, stdin, timeout, limit, budget = seen[0]
    assert '--continue' not in argv and '--session' not in argv and '--auto' not in argv
    assert timeout == 1.0 and limit == 16384 and budget == 0.1
    assert json.loads(stdin)['problem']['case_id'] == 'lane-1'
    if kind == 'claude':
        assert '--bare' in argv and argv[argv.index('--tools') + 1] == ''
    else:
        assert '--standalone' in argv


@pytest.mark.parametrize('stdout,code', [(b'{}', 0), (b'partial', 0), (b'x'*16385, 0),
                                      (b'{"structured_output":{},"total_cost_usd":1}', 1)])
def test_failure_partial_oversize_unknown_cost_refuses(stdout, code):
    async def launch(*args):
        return code, stdout
    provider = CliProvider(kind='claude', model='pinned', profile_id='p', launch=launch)
    with pytest.raises(ValueError):
        asyncio.run(provider(problem(), (), 1, budget_usd=0.1))


def test_opencode_installed_version_uses_pure_without_tool_approval():
    seen = []
    async def launch(argv, *args):
        seen.append(argv)
        return 0, (json.dumps({'type': 'text', 'part': {'text': json.dumps(reply(problem()))}})
                   + '\n' + json.dumps({'type': 'step_finish', 'part': {'cost': 0}})).encode()
    provider = CliProvider(kind='opencode', model='ollama/qwen3-vl:8b-instruct',
                           profile_id='local', launch=launch, cli_version='1.18.35')
    assert asyncio.run(provider(problem(), (), 1, budget_usd=0.1))[1] == 0
    assert seen[0] == ('opencode', 'run', '--pure', '--format', 'json',
                       '--model', 'ollama/qwen3-vl:8b-instruct')


@pytest.mark.parametrize('version', ['1.18.34', 'latest', '', None, ['1.18.35']])
def test_opencode_unverified_version_refuses_before_launch(version):
    with pytest.raises(ValueError, match='UNSUPPORTED_OPENCODE_VERSION'):
        CliProvider(kind='opencode', model='ollama/pinned', profile_id='local',
                    launch=lambda: None, cli_version=version)


def test_cli_passes_fleet_baseline_and_one_valid_primary_for_review():
    request = problem(fleet_choice='human')
    primary = {'profile_id': 'qwen', **reply(request)}
    seen = []
    async def launch(argv, stdin, *args):
        seen.append(json.loads(stdin))
        return 0, (json.dumps({'type': 'text', 'part': {'text': json.dumps(reply(request))}})
            + '\n' + json.dumps({'type': 'step_finish', 'part': {'cost': 0}})).encode()
    provider = CliProvider(kind='opencode', model='configured/glm', profile_id='review', launch=launch)
    asyncio.run(provider(request, (primary,), 1, budget_usd=.1))
    assert seen[0]['problem']['fleet_choice'] == 'human'
    assert seen[0]['prior'] == [primary]


@pytest.mark.parametrize('change', [{'generation': 'old'}, {'input_hash': 'wrong'}, {'verified': True},
                                    {'profile_id': ''}])
def test_cli_rejects_unbound_primary_review_before_launch(change):
    request = problem(fleet_choice='human')
    primary = {'profile_id': 'qwen', **reply(request), **change}
    async def forbidden(*args):
        pytest.fail('untrusted comparison must not launch')
    provider = CliProvider(kind='opencode', model='configured/glm', profile_id='review', launch=forbidden)
    with pytest.raises(ValueError):
        asyncio.run(provider(request, (primary,), 1, budget_usd=.1))

def test_unverified_launcher_billing_is_not_known_zero():
    class Launch:
        cost_verified = False

        async def __call__(self, argv, body, remaining, output_limit, budget_usd):
            request = json.loads(body)['problem']
            payload = {key: request[key] for key in ('subject_id', 'case_id', 'generation', 'input_hash')}
            payload.update(choice='reobserve', evidence_ids=request['evidence_ids'], objections=[])
            records = [dict(type='text', part=dict(text=json.dumps(payload))),
                       dict(type='step_finish', part=dict(cost=0))]
            return 0, '\n'.join(json.dumps(row) for row in records).encode()

    provider = CliProvider(kind='opencode', model='glm', profile_id='glm', launch=Launch())
    with pytest.raises(ValueError, match='CLI_COST_UNKNOWN_OR_EXCEEDED'):
        asyncio.run(provider(problem(), (), 1, budget_usd=.1))

