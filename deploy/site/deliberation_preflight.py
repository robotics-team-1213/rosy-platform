"""Real offline host acceptance, without model inference or robot commands."""
import asyncio
import hashlib
import json
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path

from deploy.site.deliberation_install import BWRAP, PROFILE, PROFILE_PATH
from deploy.site.deliberation_sandbox import SandboxLauncher, bounded_process, cleanup_scope, protect_cleanup


def resource_checks(properties, cgroup):
    quota = (cgroup / 'cpu.max').read_text().split()
    return {'cgroup_limits': (
        properties.get('MemoryMax') == '1073741824' and properties.get('TasksMax') == '32'
        and properties.get('CPUQuotaPerSecUSec') == '1s' and properties.get('RuntimeMaxUSec') == '35s'
        and (cgroup / 'memory.max').read_text().strip() == '1073741824'
        and (cgroup / 'pids.max').read_text().strip() == '32'
        and len(quota) == 2 and quota[0] == quota[1] and int(quota[0]) > 0)}


async def check():
    result = dict(state='HOLD', reason='ADMIN_INSTALL_REQUIRED', checks={})
    if not BWRAP.is_file() or not PROFILE_PATH.is_file():
        return result
    launcher, task = None, None
    unit = 'rosy-deliberation-' + uuid.uuid4().hex + '.scope'
    try:
        for path in (BWRAP, PROFILE_PATH, *BWRAP.parents):
            st = path.lstat()
            if path.resolve() != path or st.st_uid != 0 or st.st_mode & 0o022:
                raise ValueError('UNTRUSTED_INSTALL')
        if PROFILE_PATH.read_bytes() != PROFILE or BWRAP.read_bytes() != Path('/usr/bin/bwrap').read_bytes():
            raise ValueError('INSTALL_PIN_MISMATCH')
        host = {name: os.readlink('/proc/self/ns/' + name) for name in ('user', 'net', 'pid', 'mnt')}
        script = '''import errno,json,os,socket,subprocess,sys,time
host=json.loads(sys.argv[1])
checks={name+'_isolated':os.readlink('/proc/self/ns/'+name)!=value for name,value in host.items()}
checks['environment_empty']=set(os.environ)<= {'HOME','PATH','LC_CTYPE'} and os.environ.get('HOME')=='/tmp/home'
checks['host_paths_hidden']=not any(os.path.exists(p) for p in ('/home','/etc','/run','/var'))
checks['network_loopback_only']=all(name=='lo' for _,name in socket.if_nameindex())
checks['capabilities_dropped']=next(line.split()[1] for line in open('/proc/self/status') if line.startswith('CapEff:'))=='0000000000000000'
try:
    open('/usr/rosy-deliberation-preflight-sentinel','wb').close()
    checks['runtime_readonly']=False
except OSError as exc:
    checks['runtime_readonly']=exc.errno==errno.EROFS
subprocess.Popen(['/provider','-c','import os,time;os.setsid();time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(json.dumps(checks),flush=True)
time.sleep(1)
'''
        executable = Path('/usr/bin/python3').resolve()
        launcher = SandboxLauncher('claude', executable, hashlib.sha256(executable.read_bytes()).hexdigest())
        command = launcher.command(('claude', '-c', script, json.dumps(host)), unit)
        task = asyncio.create_task(bounded_process(command, b'', 10, 4096))
        properties = {}
        for _ in range(20):
            await asyncio.sleep(.05)
            code, raw = await bounded_process(('/usr/bin/systemctl', '--user', 'show', unit,
                '--property=ControlGroup,MemoryMax,TasksMax,CPUQuotaPerSecUSec,RuntimeMaxUSec'), b'', 1, 2048)
            properties = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
            if code == 0 and properties.get('ControlGroup'):
                break
            if task.done():
                break
        group = properties.get('ControlGroup', '')
        cgroup = (Path('/sys/fs/cgroup') / group.lstrip('/')).resolve()
        if not group or not cgroup.is_relative_to('/sys/fs/cgroup') or cgroup.name != unit:
            raise ValueError('CGROUP_READBACK_MISSING')
        checks = resource_checks(properties, cgroup)
        code, raw = await task
        if code != 0:
            raise ValueError('ISOLATION_PROBE_FAILED')
        observation = json.loads(raw)
        expected = {'user_isolated','net_isolated','pid_isolated','mnt_isolated','environment_empty',
            'host_paths_hidden','network_loopback_only','capabilities_dropped','runtime_readonly'}
        if type(observation) is not dict or set(observation) != expected or any(type(v) is not bool for v in observation.values()):
            raise ValueError('PROBE_READBACK_INVALID')
        checks.update(observation)
        await protect_cleanup(cleanup_scope(unit))
        checks['descendants_reaped'] = not cgroup.exists() or (cgroup / 'pids.current').read_text().strip() == '0'
        result['checks'] = checks
        result['reason'] = 'OFFLINE_HOST_ONLY' if all(checks.values()) else 'BOUNDARY_CHECK_FAILED'
        result['state'] = 'PASS_HOST_OFFLINE_ONLY' if all(checks.values()) else 'HOLD'
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        result['reason'] = str(exc)[:256]
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            try:
                await protect_cleanup(cleanup_scope(unit))
            except (OSError, ValueError, RuntimeError, TimeoutError):
                result.update(state='HOLD', reason='SANDBOX_CLEANUP_UNCONFIRMED')
        if launcher is not None:
            launcher.close()
    return result


if __name__ == '__main__':
    if sys.platform != 'linux':
        raise SystemExit('LINUX_HOST_REQUIRED')
    receipt = asyncio.run(check())
    print(json.dumps(receipt, sort_keys=True))
    raise SystemExit(0 if receipt['state'] == 'PASS_HOST_OFFLINE_ONLY' else 1)
