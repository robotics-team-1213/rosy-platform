"""Explicit one-shot GLM smoke port; no automatic Fleet/provider activation."""
import asyncio
import json
import math
import tempfile
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from deploy.site.deliberation_sandbox import SandboxLauncher, bounded_process, cleanup_scope, protect_cleanup
from deploy.ai_pc.deliberation_opencode_process import SECRET, gateway_session, finish_gateway

EXECUTABLE = '/opt/rosy-deliberation/providers/opencode-1.18.35'
EXECUTABLE_SHA256 = '77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa'
MODEL = 'zai-coding-plan/glm-5.3-flash'
ARGV = ('opencode', 'run', '--pure', '--format', 'json', '--model', MODEL)


def smoke_config():
    return {'model': MODEL, 'small_model': MODEL, 'enabled_providers': ['zai-coding-plan'],
        'default_agent': 'rosy', 'plugin': [], 'mcp': {}, 'permission': 'deny',
        'autoupdate': False, 'share': 'disabled', 'snapshot': False, 'lsp': False,
        'formatter': False, 'compaction': {'auto': False},
        'agent': {'rosy': {'mode': 'primary', 'steps': 1, 'permission': 'deny', 'model': MODEL,
            'prompt': 'Return only the requested advisory JSON. Never use tools.'},
            **{name: {'disable': True} for name in
               ('title', 'summary', 'compaction', 'build', 'plan', 'general', 'explore')}},
        'provider': {'zai-coding-plan': {'npm': '@ai-sdk/openai-compatible',
            'options': {'baseURL': 'http://127.0.0.1:18081/v1', 'apiKey': 'rosy-gateway-no-secret'},
            'models': {'glm-5.3-flash': {'name': 'GLM bounded smoke', 'tool_call': False,
                'limit': {'context': 8192, 'output': 1024}}}}}}


def isolated_command(sandbox, argv, unit, directory):
    command = sandbox.command(argv, unit)
    split = max(index for index, value in enumerate(command) if value == '--')
    mounts = tuple(value for name, target in
        (('gateway.sock', '/gateway.sock'), ('config.json', '/config.json'),
         ('relay.py', '/relay.py'), ('runner.py', '/runner.py'))
        for value in ('--ro-bind', str(directory / name), target))
    return (*command[:split], *mounts, '--setenv', 'OPENCODE_CONFIG', '/config.json',
            '--', '/usr/bin/python3', '/runner.py', *argv[1:])


class GlmOpenCodeLauncher:
    cost_verified = False
    schema_versions = (1, 2)

    def __init__(self, *, admission=None, billing_policy=None, profile=None):
        if billing_policy is not None:
            from .deliberation_glm_receipt import TrustedIncludedPlanPolicy
            if type(billing_policy) is not TrustedIncludedPlanPolicy:
                raise ValueError('BILLING_POLICY_UNKNOWN')
        if admission is not None:
            from .deliberation_glm_receipt import admission as validate
            validate(admission)
        if profile is not None or admission is not None or billing_policy is not None:
            from . import deliberation_glm_receipt as bridge
            from rosy.decision.deliberation.profiles import ModelProfile
            if type(profile) is not ModelProfile:
                raise ValueError('EXACT_GLM_PROFILE_REQUIRED')
            selected = bridge.codec.status_model_profile if profile.domains == ('fleet_status',) else bridge.codec.model_profile
            expected = bridge.status_capabilities() if profile.domains == ('fleet_status',) else bridge.CAPABILITIES
            if (profile != selected(profile.profile_revision) or admission is not None
                    and replace(admission,ready=False,isolated=False,cost_verified=False) != expected):
                raise ValueError('EXACT_GLM_PROFILE_REQUIRED')
            if billing_policy is not None:
                billing_policy.validate(bridge.digest(asdict(profile)))
        self.profile = profile
        self._admission, self.billing_policy = admission, billing_policy
        self.cost_verified = (admission is not None and admission.ready and admission.isolated
                              and admission.cost_verified and billing_policy is not None)
        self.sandbox = SandboxLauncher('opencode', EXECUTABLE, EXECUTABLE_SHA256)
        self.used = False
        self.gateway_receipt = None
        self.billing_receipt = None

    @property
    def adapter_capabilities(self):
        from .deliberation_glm_receipt import CAPABILITIES, status_capabilities
        if self._admission is not None: return self._admission
        return status_capabilities() if self.profile is not None and self.profile.domains == ('fleet_status',) else CAPABILITIES

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.sandbox.close()

    async def __call__(self, argv, body, remaining, output_limit, budget_usd):
        if (type(argv) is not tuple or argv != ARGV or type(body) is not bytes or len(body) > 16384
                or type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 30
                or type(output_limit) is not int or not 1 <= output_limit <= 16384
                or type(budget_usd) not in (int, float) or not math.isfinite(budget_usd) or not 0 <= budget_usd <= 10):
            raise ValueError('INVALID_ONE_SHOT_INPUT')
        versioned = 'schema' in json.loads(body) or 'profile_revision' in json.loads(body)
        if versioned:
            from . import deliberation_glm_receipt as bridge
            if not self.cost_verified:
                raise ValueError('GLM_RUNTIME_OR_BILLING_NOT_ADMITTED')
            _, bound, _, _ = bridge.codec.request(json.loads(body))
            if bound.profile != self.profile:
                raise ValueError('CASE_OR_PROFILE_CHANGED')
            if type(self.billing_policy) is not bridge.TrustedIncludedPlanPolicy:
                raise ValueError('BILLING_POLICY_UNKNOWN')
            self.billing_policy.validate(bridge.digest(asdict(bound.profile)))
        elif budget_usd <= 0:
            raise ValueError('INVALID_ONE_SHOT_INPUT')
        if self.used:
            raise ValueError('ONE_SHOT_ALREADY_USED')
        self.used = True
        unit = 'rosy-deliberation-' + uuid.uuid4().hex + '.scope'
        started = asyncio.get_running_loop().time()
        async with asyncio.timeout(remaining):
            with tempfile.TemporaryDirectory(prefix='rosy-glm-smoke-') as temporary:
                directory = Path(temporary)
                directory.joinpath('config.json').write_text(json.dumps(smoke_config()), encoding='utf-8')
                source = Path(__file__).parent
                directory.joinpath('relay.py').write_bytes(source.joinpath('deliberation_relay.py').read_bytes())
                directory.joinpath('runner.py').write_bytes(source.joinpath('deliberation_opencode_runner.py').read_bytes())
                options = {'credential_sha256': self.billing_policy.credential_sha256} if versioned else {}
                async with gateway_session(body, remaining - (asyncio.get_running_loop().time() - started), directory, **options) as gateway:
                    try:
                        command = await asyncio.to_thread(isolated_command, self.sandbox, argv, unit, directory)
                        result = await bounded_process(command, body,
                            remaining - (asyncio.get_running_loop().time() - started), output_limit)
                        self.gateway_receipt = await finish_gateway(gateway)
                        if versioned:
                            if result[0] != 0:
                                raise ValueError('CLI_RESULT_UNKNOWN')
                            raw, self.billing_receipt = bridge.normalize(body, result[1],
                                self.gateway_receipt, self.billing_policy, output_limit, budget_usd)
                            return 0, raw
                        return result
                    finally:
                        await protect_cleanup(cleanup_scope(unit))
