"""Fail-closed supervisor for the two media processes it creates, never Fleet."""

import ctypes
import math
import os
import signal
import subprocess
import sys
import time


class MediaSupervisor:
    def __init__(self, commands, *, health_check):
        if len(commands) != 2 or any(not command for command in commands):
            raise ValueError('media supervisor requires authority and backend commands')
        self._commands, self._health_check = commands, health_check
        self.children = []
        self._last_healthy = None

    def start(self, *, now):
        if self.children:
            raise RuntimeError('media supervisor already started')
        if sys.platform != 'linux':
            raise RuntimeError('media supervision requires native Linux child lifetime binding')
        libc = ctypes.CDLL(None, use_errno=True)
        parent = os.getpid()

        def bind_parent():
            # PR_SET_PDEATHSIG; check the fork/parent-exit race before exec.
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
                os._exit(127)
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGKILL)

        self._last_healthy = now
        try:
            for command in self._commands:
                self.children.append(subprocess.Popen(command, preexec_fn=bind_parent))
        except Exception:
            self.stop()
            raise

    def tick(self, *, now):
        if not self.children or any(child.poll() is not None for child in self.children):
            self.stop()
            return False
        if now < self._last_healthy:
            self.stop()
            return False
        try:
            heartbeat = self._health_check()
        except Exception:
            heartbeat = False
        if heartbeat is True:
            self._last_healthy = now
        elif (type(heartbeat) in (float, int) and math.isfinite(heartbeat)
              and self._last_healthy <= heartbeat <= now):
            self._last_healthy = heartbeat
        if now - self._last_healthy >= 3:
            self.stop()
            return False
        return True

    def stop(self):
        for child in reversed(self.children):
            if child.poll() is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 2
        for child in self.children:
            if child.poll() is None:
                try:
                    child.wait(timeout=max(.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=1)


def main(argv=None):
    """python -m rosy_media.supervisor <media-authority.json> <mediamtx> <mediamtx.yaml>

    Exits non-zero when either child or the authority heartbeat fails; the
    container/service restart policy (with backoff) brings both back fresh.
    """
    import json
    from urllib.request import ProxyHandler, build_opener
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        raise SystemExit(__doc__)
    config, binary, mediamtx_config = argv
    with open(config, encoding='utf-8') as file:
        port = int(json.load(file).get('listen_port', 9121))
    http = build_opener(ProxyHandler({}))

    def health():
        with http.open(f'http://127.0.0.1:{port}/health', timeout=.5) as response:
            return response.status == 200

    supervisor = MediaSupervisor([[sys.executable, '-m', 'rosy_media.main', config],
                                  [binary, mediamtx_config]], health_check=health)
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    supervisor.start(now=time.monotonic())
    try:
        while not stopping and supervisor.tick(now=time.monotonic()):
            time.sleep(.5)
    finally:
        supervisor.stop()
    raise SystemExit(0 if stopping else 1)


if __name__ == '__main__':
    main()
