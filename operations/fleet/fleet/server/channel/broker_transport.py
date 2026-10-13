"""Fixed forced-command SSH transport; every owned process is killed and reaped."""
import asyncio
import json
import os
import signal


async def exchange(c, command, packet, remaining, *, output_limit=16384):
    if command not in ('rosy-status-v1', 'rosy-conversation-v1'):
        raise ValueError('FIXED_BROKER_COMMAND_REQUIRED')
    port = getattr(c, 'ssh_port', 22)
    if type(port) is not int or port not in (22, 2222):
        raise ValueError('FIXED_BROKER_PORT_REQUIRED')
    argv=('ssh','-F','/dev/null','-T','-p',str(port),'-o','BatchMode=yes','-o','IdentitiesOnly=yes',
          '-o','StrictHostKeyChecking=yes','-o','GlobalKnownHostsFile=/dev/null',
          '-o','UserKnownHostsFile='+c.known_hosts_file,'-o','ConnectTimeout=5',
          '-o','ClearAllForwardings=yes','-o','IdentityAgent=none','-i',c.key_file,'rosy-model-ingress@'+c.host,command)
    process=None
    spawn=asyncio.create_task(asyncio.create_subprocess_exec(*argv,stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,start_new_session=True,limit=output_limit+1))
    try:
        async with asyncio.timeout(remaining):
            process=await asyncio.shield(spawn)
            process.stdin.write(packet);await process.stdin.drain();process.stdin.close()
            output=bytearray()
            while chunk:=await process.stdout.read(4096):
                output.extend(chunk)
                if len(output)>output_limit:raise ValueError('STATUS_BROKER_OUTPUT_LIMIT')
            if await process.wait()!=0:raise ValueError('STATUS_BROKER_HOLD')
            return json.loads(output)
    finally:
        # Owned SSH process is always reaped, including cancellation during spawn.
        async def cleanup():
            owned=process if process is not None else await asyncio.shield(spawn)
            if owned.returncode is None:
                try:os.killpg(owned.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            await owned.wait()
        task=asyncio.create_task(cleanup())
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise
