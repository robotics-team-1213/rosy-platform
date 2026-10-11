import asyncio
import json

import pytest

from rosy.decision.deliberation.cli import CliProvider
from test_deliberation import problem, reply


def test_unconfigured_isolation_never_launches():
    with pytest.raises(ValueError, match='ISOLATED_LAUNCHER_REQUIRED'):
        CliProvider(kind='claude', model='pinned-model', profile_id='p', launch=None)


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

