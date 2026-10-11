"""Offline-only provider sandbox. No credentials, host workspace or network admission."""
import asyncio
import hashlib
import math
import os
import re
import signal
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from deploy.site.deliberation_install import BWRAP


_CLEANUPS = set()


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def protect_cleanup(cleanup):
    task = asyncio.create_task(asyncio.wait_for(cleanup, 2))
    _CLEANUPS.add(task)
    task.add_done_callback(_CLEANUPS.discard)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Consume cleanup errors while preserving the caller's cancellation.
        try:
            task.result()
        except Exception:
            pass
        raise asyncio.CancelledError
    return task.result()


async def cleanup_scope(unit):
    if type(unit) is not str or re.fullmatch(r'rosy-deliberation-[a-z0-9-]+\.scope', unit) is None:
        raise ValueError('invalid owned sandbox scope')
    code, _ = await bounded_process(('/usr/bin/systemctl', '--user', 'kill',
        '--kill-whom=all', '--signal=KILL', unit), b'', 1, 256)
    if code != 0:
        code, raw = await bounded_process(('/usr/bin/systemctl', '--user', 'show',
            '--property=LoadState', '--value', unit), b'', 1, 256)
        if code != 0 or raw != b'not-found\n':
            raise RuntimeError('SANDBOX_CLEANUP_UNCONFIRMED')


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
        async def cleanup():
            nonlocal process
            try:
                if process is None:
                    process = await asyncio.shield(spawn)
                kill_group(process)
                # Drain discarded pipe data so asyncio can finish its subprocess transport.
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


class SandboxLauncher:
    def __init__(self, kind, executable, executable_sha256):
        if kind not in {'claude', 'opencode'}:
            raise ValueError('unsupported provider kind')
        self.kind = kind
        source = Path(executable).resolve(strict=True)
        if not source.is_file() or type(executable_sha256) is not str or re.fullmatch('[0-9a-f]{64}', executable_sha256) is None:
            raise ValueError('invalid pinned executable')
        self._snapshot = tempfile.TemporaryDirectory(prefix='rosy-deliberation-')
        self.executable = Path(self._snapshot.name) / 'provider'
        digest, size = hashlib.sha256(), 0
        try:
            with source.open('rb') as src, self.executable.open('xb') as dest:
                while block := src.read(65536):
                    size += len(block)
                    if size > 512 * 1024 * 1024:
                        raise ValueError('provider executable exceeds snapshot budget')
                    digest.update(block)
                    dest.write(block)
            if digest.hexdigest() != executable_sha256:
                raise ValueError('provider executable digest changed')
            self.executable.chmod(0o500)
        except BaseException:
            self._snapshot.cleanup()
            raise
        self.digest = executable_sha256

    def close(self):
        self._snapshot.cleanup()

    def command(self, argv, unit):
        if (type(argv) is not tuple or not argv or argv[0] != self.kind
                or any(type(v) is not str or '\0' in v for v in argv)
                or re.fullmatch(r'rosy-deliberation-[a-z0-9-]+\.scope', unit) is None):
            raise ValueError('invalid trusted sandbox command')
        with self.executable.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.digest:
                raise ValueError('provider executable digest changed')
        return ('/usr/bin/systemd-run', '--user', '--quiet', '--scope', '--collect', f'--unit={unit}',
            '-p', 'MemoryMax=1G', '-p', 'CPUQuota=100%', '-p', 'TasksMax=32',
            '-p', 'RuntimeMaxSec=35s', '--',
            str(BWRAP), '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--ro-bind', str(self.executable), '/provider', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/tmp/home', '--chdir', '/tmp', '--clearenv',
            '--setenv', 'HOME', '/tmp/home', '--setenv', 'PATH', '/usr/bin:/bin', '--', '/provider', *argv[1:])

    async def __call__(self, argv, body, remaining, output_limit, budget_usd):
        if type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 30:
            raise ValueError('invalid provider deadline')
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
            # Kill only this generated scope, including children that changed their process group.
            await protect_cleanup(cleanup_scope(unit))


@contextmanager
def sandbox_provider(*, kind, executable, executable_sha256, model, profile_id, cli_version='2.0.22'):
    from rosy.decision.deliberation.cli import CliProvider
    launcher = SandboxLauncher(kind, executable, executable_sha256)
    try:
        yield CliProvider(kind=kind, model=model, profile_id=profile_id, launch=launcher, cli_version=cli_version)
    finally:
        launcher.close()
