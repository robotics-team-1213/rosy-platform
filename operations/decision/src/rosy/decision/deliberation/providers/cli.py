"""Fixed CLI translation. Deployment must inject a proven isolated launcher."""
import json
import math
import re
from dataclasses import asdict

from .. import canonical, identifier, opinion
from ..contracts.billing import RejectedJudgment


def _argv(kind, model, cli_version, schema, budget_usd):
    if kind == 'claude':
        return ('claude', '--bare', '-p', '--tools', '', '--setting-sources', '',
                '--disable-slash-commands', '--no-session-persistence', '--strict-mcp-config',
                '--mcp-config', '{"mcpServers":{}}', '--output-format', 'json',
                '--json-schema', canonical(schema), '--model', model,
                '--max-turns', '1', '--max-budget-usd', str(budget_usd))
    # shortcut: supported versions still require launcher token/cost caps and tool denial.
    mode = '--pure' if cli_version == '1.18.35' else '--standalone'
    return ('opencode', 'run', mode, '--format', 'json', '--model', model)


def _decode_result(kind, launch, code, raw, output_limit, budget_usd, *, bound=None):
    if code != 0 or type(raw) is not bytes or len(raw) > output_limit:
        raise ValueError('CLI_RESULT_UNKNOWN')
    if kind == 'claude':
        envelope = json.loads(raw)
        if envelope.get('is_error') is not False:
            raise ValueError('CLI_RESULT_UNKNOWN')
        payload, cost = envelope['structured_output'], envelope['total_cost_usd']
    else:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if any(record.get('type') not in {'text', 'step_start', 'step_finish'} for record in records):
            raise ValueError('CLI_UNEXPECTED_EVENT')
        texts = [record['part']['text'] for record in records if record['type'] == 'text']
        costs = [record['part']['cost'] for record in records if record['type'] == 'step_finish']
        if len(texts) != 1 or len(costs) != 1:
            raise ValueError('CLI_RESULT_UNKNOWN')
        payload, cost = texts[0], costs[0]
    if (getattr(launch, 'cost_verified', True) is not True
            or type(cost) not in (int, float) or not math.isfinite(cost) or not 0 <= cost <= budget_usd):
        raise ValueError('CLI_COST_UNKNOWN_OR_EXCEEDED')
    if kind != 'claude':
        try: payload = json.loads(payload)
        except (ValueError, TypeError, RecursionError, OverflowError):
            if bound is not None and getattr(launch, 'billing_receipt', None) is None:
                raise RejectedJudgment(bound, cost) from None
            raise
    return payload, cost


class CliProvider:
    def __init__(self, *, kind, model, profile_id, launch, cli_version='2.0.22'):
        if not callable(launch):
            raise ValueError('ISOLATED_LAUNCHER_REQUIRED')
        if kind not in {'claude', 'opencode'}:
            raise ValueError('unsupported CLI')
        if kind == 'opencode' and (type(cli_version) is not str or cli_version not in {'1.18.35', '2.0.22'}):
            raise ValueError('UNSUPPORTED_OPENCODE_VERSION')
        if type(model) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:#-]{0,127}', model) is None:
            raise ValueError('invalid configured model ID')
        self.kind, self.model, self.profile_id = kind, identifier(model), identifier(profile_id)
        self.launch = launch
        self.cli_version = cli_version

    async def __call__(self, problem, prior, remaining, *, budget_usd):
        if (type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 30
                or type(budget_usd) not in (int, float) or not math.isfinite(budget_usd)
                or not 0 < budget_usd <= 10 or type(prior) not in (tuple, list) or len(prior) not in (0, 1, 2)):
            raise ValueError('invalid CLI budget')
        profiles = []
        for item in prior:
            if type(item) is not dict or 'profile_id' not in item:
                raise ValueError('INVALID_REVIEW_PRIOR')
            profiles.append(identifier(item['profile_id']))
            opinion(problem, {key: value for key, value in item.items() if key != 'profile_id'})
        if len(set(profiles)) != len(profiles):
            raise ValueError('INVALID_REVIEW_PRIOR')
        if len(prior) == 1 and (problem.fleet_choice is None
                or prior[0]['choice'] == problem.fleet_choice or 'unsafe' in prior[0]['objections']):
            raise ValueError('INVALID_REVIEW_PRIOR')
        body = canonical({'problem': {**asdict(problem), 'input_hash': problem.digest}, 'prior': prior,
                          'instruction': 'Return only an advisory choice, evidence IDs and unresolved objections. '
                                         'Never use tools or claim physical verification.'}).encode()
        if self.kind == 'claude':
            schema = {'type': 'object', 'additionalProperties': False,
                      'properties': {key: {'type': 'string'} for key in
                                     ('subject_id', 'case_id', 'generation', 'input_hash', 'choice')}}
            schema['properties'].update({key: {'type': 'array', 'items': {'type': 'string'}}
                                         for key in ('evidence_ids', 'objections')})
            schema['required'] = list(schema['properties'])
        else:
            schema = None
        argv = _argv(self.kind, self.model, self.cli_version, schema, budget_usd)
        code, raw = await self.launch(argv, body, remaining, 16384, budget_usd)
        payload, cost = _decode_result(self.kind, self.launch, code, raw, 16384, budget_usd)
        return opinion(problem, payload), cost
