"""Explicit synthetic-only free SDK probe; never an admitted Fleet provider."""
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import uuid

from deploy.site.deliberation_sandbox import SandboxLauncher, bounded_process, cleanup_scope, protect_cleanup
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import judgment
from . import deliberation_free_codec as codec
from .deliberation_opencode import EXECUTABLE, EXECUTABLE_SHA256, isolated_command, smoke_config
from .deliberation_opencode_process import gateway_session, finish_gateway
from .deliberation_glm_receipt import digest

ARGV = ('opencode', 'run', '--pure', '--format', 'json', '--model', 'opencode/' + codec.MODEL)


def config():
    value = deepcopy(smoke_config())
    value.update(model=ARGV[-1], small_model=ARGV[-1], enabled_providers=['opencode'])
    value['agent']['rosy']['model'] = ARGV[-1]
    provider = value['provider'].pop('zai-coding-plan')
    provider['models'] = {codec.MODEL: dict(name='MiMo fixed free synthetic probe', tool_call=False,
                                         limit=dict(context=8192, output=1024))}
    provider['whitelist'] = [codec.MODEL]
    value['provider'] = {'opencode': provider}
    return value


class FreeLauncher:
    cost_verified = False

    def __init__(self):
        self.sandbox = SandboxLauncher('opencode', EXECUTABLE, EXECUTABLE_SHA256)
        self.used, self.gateway_receipt = False, None

    def __enter__(self): return self
    def __exit__(self, *args): self.sandbox.close()

    async def __call__(self, argv, body, remaining, limit, budget_usd=0):
        if (type(argv) is not tuple or argv != ARGV or type(body) is not bytes
                or type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 30
                or type(limit) is not int or not 1 <= limit <= 16384
                or type(budget_usd) not in (int, float) or budget_usd != 0):
            raise ValueError('FIXED_FREE_PROBE_REQUIRED')
        codec.trusted_body(body)
        if self.used:
            raise ValueError('ONE_SHOT_ALREADY_USED')
        self.used = True
        unit = 'rosy-deliberation-' + uuid.uuid4().hex + '.scope'
        started = asyncio.get_running_loop().time()
        async with asyncio.timeout(remaining):
            with tempfile.TemporaryDirectory(prefix='rosy-free-smoke-') as temporary:
                directory = Path(temporary)
                directory.joinpath('config.json').write_text(canonical(config()), encoding='utf-8')
                source = Path(__file__).parent
                for name in ('relay', 'opencode_runner'):
                    target = 'relay.py' if name == 'relay' else 'runner.py'
                    directory.joinpath(target).write_bytes(source.joinpath('deliberation_' + name + '.py').read_bytes())
                async with gateway_session(body, remaining - (asyncio.get_running_loop().time() - started), directory, free=True) as gateway:
                    try:
                        command = await asyncio.to_thread(isolated_command, self.sandbox, argv, unit, directory)
                        code, raw = await bounded_process(command, body,
                            remaining - (asyncio.get_running_loop().time() - started), limit)
                        self.gateway_receipt = await finish_gateway(gateway, free=True)
                        if code != 0:
                            raise ValueError('FREE_SDK_RESULT_UNKNOWN')
                        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
                        if any(item.get('type') not in {'text', 'step_start', 'step_finish'} for item in records):
                            raise ValueError('FREE_SDK_UNEXPECTED_EVENT')
                        texts = [item['part']['text'] for item in records if item['type'] == 'text']
                        if len(texts) != 1 or sum(item['type'] == 'step_finish' for item in records) != 1:
                            raise ValueError('FREE_SDK_RESULT_UNKNOWN')
                        checked = judgment(codec.PROBLEM, codec.BOUND, json.loads(texts[0]))
                        if (self.gateway_receipt.get('job_sha256') != digest(json.loads(body))
                                or self.gateway_receipt.get('judgment_sha256') != digest(checked.payload)
                                or self.gateway_receipt.get('cost_usd') is not None
                                or self.gateway_receipt.get('cost_complete') is not False
                                or self.gateway_receipt.get('runtime_admitted') is not False
                                or self.gateway_receipt.get('action_admissible') is not False):
                            raise ValueError('FREE_SDK_GATEWAY_BINDING_UNKNOWN')
                        return checked.payload, self.gateway_receipt
                    finally:
                        await protect_cleanup(cleanup_scope(unit))
