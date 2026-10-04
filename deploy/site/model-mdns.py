#!/usr/bin/env python3
"""Publish the model host's real SSH service while its listener is ready (D-452)."""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time


def policy():
    # Installed alongside this script by the rootless installer. Source use is
    # supported too; neither path imports an ambient PYTHONPATH module (-I).
    path = Path(__file__).with_name('discovery_txt.py')
    if not path.is_file():
        path = Path(__file__).resolve().parents[2] / 'contracts/foundation/core_common/protocol/discovery_txt.py'
    spec = importlib.util.spec_from_file_location('_rosy_model_discovery_policy', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ssh_ready(port, *, runner=subprocess.run, connector=socket.create_connection):
    """Bounded specific-port probe: LAN-capable binding and an SSH-2.0 banner."""
    try:
        result = runner(['ss', '-H', '-ltn', f'sport = :{port}'],
                        capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode:
        return False
    targets = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[0] != 'LISTEN':
            continue
        host, sep, value = fields[3].rpartition(':')
        if not sep or value != str(port):
            continue
        host = host.strip('[]')
        if host == '*':
            host = '0.0.0.0'
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if address.is_loopback or address.is_link_local or address.is_multicast:
            continue
        target = ('127.0.0.1' if address.version == 4 else '::1') if address.is_unspecified else str(address)
        if target not in targets:
            targets.append(target)
    for host in targets[:4]:
        try:
            with connector((host, port), timeout=.75) as stream:
                deadline = time.monotonic() + .75
                banner = b''
                while len(banner) < 256 and b'\n' not in banner:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    stream.settimeout(remaining)
                    block = stream.recv(256 - len(banner))
                    if not block:
                        break
                    banner += block
                if banner.startswith(b'SSH-2.0-') and b'\n' in banner:
                    return True
        except OSError:
            continue
    return False


class Publisher:
    """Own one Avahi client process; withdraw its registration on loss/stop."""

    def __init__(self, port, name, *, spawn=subprocess.Popen):
        self.port, self.name, self.spawn = port, name, spawn
        self.child = None
        self.profile = policy()

    def update(self, ready):
        if self.child is not None and self.child.poll() is not None:
            self.child = None
        if not ready:
            self.close()
        elif self.child is None:
            metadata = self.profile.REQUIRED[self.profile.MODEL]
            self.child = self.spawn(['avahi-publish-service', f'ROSY Model {self.name}',
                                     self.profile.MODEL, str(self.port),
                                     *(f'{key}={value}' for key, value in metadata.items())],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    def close(self):
        child, self.child = self.child, None
        if child is None or child.poll() is not None:
            return
        try:
            child.terminate()
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()  # Only the process created by this Publisher.
            child.wait(timeout=2)
        except ProcessLookupError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=22)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('SSH port must be between 1 and 65535')
    if not all(shutil.which(tool) for tool in ('ss', 'avahi-publish-service')):
        parser.error('iproute2 and avahi-utils are required; no service is advertised')
    stopped = threading.Event()
    for kind in (signal.SIGINT, signal.SIGTERM):
        signal.signal(kind, lambda *_: stopped.set())
    publisher = Publisher(args.port, socket.gethostname().split('.')[0])
    previous = None
    try:
        while not stopped.is_set():
            ready = ssh_ready(args.port)
            publisher.update(ready)
            if ready != previous:
                print('model SSH discovery: ' + ('listener ready' if ready else 'withdrawn, listener unavailable'), flush=True)
                previous = ready
            stopped.wait(5)
    finally:
        publisher.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
