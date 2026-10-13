"""Bounded lifecycle for the single host-owned GLM gateway subprocess."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from deploy.site.deliberation_sandbox import kill_group, protect_cleanup

ROOT = Path(__file__).resolve().parents[2]
SECRET = '/var/lib/rosy-deliberation/glm-coding-plan.json'


@asynccontextmanager
async def gateway_session(body, remaining, directory, *, credential_sha256=None, free=False):
    if type(free) is not bool or free and credential_sha256 is not None:
        raise ValueError('FIXED_GATEWAY_VARIANT_REQUIRED')
    secret = '/var/lib/rosy-deliberation/opencode-free.json' if free else SECRET
    job = {'body': body.decode('utf-8'), 'deadline_s': remaining,
           'socket_path': str(directory / 'gateway.sock'), 'secret_path': secret}
    if credential_sha256 is not None:
        job['credential_sha256'] = credential_sha256
    data = (json.dumps(job, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
    if len(data) > 16384 + 1024:
        raise ValueError('GATEWAY_JOB_LIMIT')
    process = None
    versioned = 'schema' in json.loads(body) or 'profile_revision' in json.loads(body)
    interpreter = sys.executable if versioned else '/usr/bin/python3'
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(interpreter, '-m',
        'deploy.ai_pc.deliberation_free_gateway' if free else 'deploy.ai_pc.deliberation_glm_gateway', stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True, cwd=str(ROOT), limit=4097,
        env={'PATH': '/usr/bin:/bin', 'PYTHONPATH': os.pathsep.join(
            (str(ROOT), str(ROOT / 'operations/decision/src'), str(ROOT / 'contracts/foundation')))}))
    try:
        process = await asyncio.shield(spawn)
        process.stdin.write(data)
        await process.stdin.drain()
        process.stdin.close()
        if await process.stdout.readline() != b'READY\n':
            raise ValueError('GATEWAY_NOT_READY')
        yield process
    finally:
        async def cleanup():
            nonlocal process
            try:
                if process is None:
                    process = await asyncio.shield(spawn)
                kill_group(process)
                while await process.stdout.read(4096):
                    pass
                await process.wait()
            finally:
                if not spawn.done():
                    def late_spawn(done):
                        if not done.cancelled() and done.exception() is None:
                            kill_group(done.result())
                    spawn.add_done_callback(late_spawn)
        await protect_cleanup(cleanup())


async def finish_gateway(process, *, free=False):
    if type(free) is not bool:
        raise ValueError('FIXED_GATEWAY_VARIANT_REQUIRED')
    raw = bytearray()
    while chunk := await process.stdout.read(4097):
        raw.extend(chunk)
        if len(raw) > 4096:
            raise ValueError('GATEWAY_OUTPUT_LIMIT')
    code = await process.wait()
    receipt = json.loads(raw)
    expected = 'PASS_FREE_PROVIDER_ONLY' if free else 'PASS_GLM_PROVIDER_ONLY'
    if (code != 0 or type(receipt) is not dict or receipt.get('state') != expected
            or type(receipt.get('calls')) is not int or receipt['calls'] != 1):
        raise ValueError('GATEWAY_RESULT_UNKNOWN')
    return receipt
