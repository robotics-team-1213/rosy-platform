"""Namespace-local relay and fixed OpenCode child. No host environment or secret."""
import socket
import subprocess
import sys
import time


def main():
    arguments = tuple(sys.argv[1:])
    allowed = tuple(('run', '--pure', '--format', 'json', '--model', model) for model in
                    ('zai-coding-plan/glm-5.3-flash', 'opencode/mimo-v2.6-flash-free'))
    if arguments not in allowed:
        raise ValueError('UNTRUSTED_OPENCODE_ARGUMENTS')
    relay = subprocess.Popen(['/usr/bin/python3', '/relay.py'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 2
        while True:
            try:
                with socket.create_connection(('127.0.0.1', 18081), timeout=.1):
                    break
            except OSError:
                if relay.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('RELAY_NOT_READY')
                time.sleep(.01)
        result = subprocess.run(['/provider', *arguments], input=sys.stdin.buffer.read(16385),
                                check=False)
        return result.returncode
    finally:
        relay.kill()
        relay.wait(timeout=1)


if __name__ == '__main__':
    raise SystemExit(main())
