"""Offline-only provider sandbox. No credentials, host workspace or network admission."""
import asyncio
import hashlib
import math
import os
import re
import signal
import sys
import uuid
from pathlib import Path


async def bounded_process(argv, body, remaining, output_limit):
    if (sys.platform != 'linux' or type(argv) is not tuple or not argv
            or any(type(v) is not str or '\0' in v for v in argv)
            or not Path(argv[0]).is_absolute() or sum(map(len, argv)) > 16384
            or type(body) is not bytes or len(body) > 16384
            or type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 30
            or type(output_limit) is not int or not 1 <= output_limit <= 16384):
        raise ValueError('invalid bounded process input')
    process = None
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(*argv,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True, cwd='/tmp',
        env={'PATH': '/usr/bin:/bin', 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'},
        limit=output_limit + 1))
    try:
        async with asyncio.timeout(remaining):
            process = await asyncio.shield(spawn)
            process.stdin.write(body)
            await process.stdin.drain()
            process.stdin.close()
            raw = bytearray()
            while chunk := await process.stdout.read(min(4096, output_limit + 1)):
                raw.extend(chunk)
                if len(raw) > output_limit:
                    raise ValueError('PROVIDER_OUTPUT_LIMIT')
            return await process.wait(), bytes(raw)
    finally:
        if process is None:
            try:
                process = await asyncio.shield(spawn)
            except Exception:
                pass
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


class SandboxLauncher:
    def __init__(self, kind, executable, executable_sha256):
        if kind not in {'claude', 'opencode'}:
            raise ValueError('unsupported provider kind')
        self.kind = kind
        self.executable = Path(executable).resolve(strict=True)
        if not self.executable.is_file() or type(executable_sha256) is not str or len(executable_sha256) != 64:
            raise ValueError('invalid pinned executable')
        self.digest = executable_sha256

    def command(self, argv, unit):
        if (type(argv) is not tuple or not argv or argv[0] != self.kind
                or any(type(v) is not str or '\0' in v for v in argv)
                or re.fullmatch(r'rosy-deliberation-[a-z0-9-]+\.scope', unit) is None):
            raise ValueError('invalid trusted sandbox command')
        with self.executable.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.digest:
                raise ValueError('provider executable digest changed')
        return ('/usr/bin/systemd-run', '--user', '--quiet', '--scope', '--collect', f'--unit={unit}',
            '-p', 'MemoryMax=1G', '-p', 'CPUQuota=100%', '-p', 'TasksMax=32', '--',
            '/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--ro-bind', str(self.executable), '/provider', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/tmp/home', '--chdir', '/tmp', '--clearenv',
            '--setenv', 'HOME', '/tmp/home', '--setenv', 'PATH', '/usr/bin:/bin', '--', '/provider', *argv[1:])

    async def __call__(self, argv, body, remaining, output_limit, budget_usd):
        if type(budget_usd) not in (int, float) or not math.isfinite(budget_usd) or not 0 < budget_usd <= 10:
            raise ValueError('invalid provider cost budget')
        unit = 'rosy-deliberation-' + uuid.uuid4().hex + '.scope'
        started = asyncio.get_running_loop().time()
        async with asyncio.timeout(remaining):
            command = await asyncio.to_thread(self.command, argv, unit)
        try:
            return await bounded_process(command, body,
                remaining - (asyncio.get_running_loop().time() - started), output_limit)
        finally:
            # Stop only this generated scope, including children that changed their process group.
            code, _ = await bounded_process(('/usr/bin/systemctl', '--user', 'stop', unit), b'', 2, 256)
            if code not in (0, 5):
                raise RuntimeError('SANDBOX_CLEANUP_UNCONFIRMED')
