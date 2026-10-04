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


def _load_dbus():
    import dbus  # Optional system Python dependency, only without the CLI.
    return dbus


class DBusPublisher:
    """Own a private connection and one Avahi group; no shared bus or callbacks."""

    def __init__(self, port, name, profile, module):
        self.port, self.name, self.profile, self.module = port, name, profile, module
        self.bus = self.owner = self.group = None
        self.started = None

    def call(self, path, interface, method, signature='', args=()):
        return self.bus.call_blocking(self.owner, path, interface, method,
                                      signature, args, timeout=2)

    def update(self, ready):
        if not ready:
            self.close()
            return
        server, group = 'org.freedesktop.Avahi.Server', 'org.freedesktop.Avahi.EntryGroup'
        try:
            if self.bus is None:
                self.bus = self.module.SystemBus(private=True)
                self.bus.set_exit_on_disconnect(False)
                self.owner = str(self.bus.call_blocking(
                    'org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'GetNameOwner', 's',
                    ('org.freedesktop.Avahi',), timeout=2))
                if not self.owner.startswith(':'):
                    raise RuntimeError('Avahi owner unavailable')
                if str(self.call('/', server, 'GetHostName')).casefold() != self.name.casefold():
                    raise RuntimeError('Avahi host identity differs')
                self.group = self.call('/', server, 'EntryGroupNew')
                dbus = self.module
                metadata = self.profile.REQUIRED[self.profile.MODEL]
                txt = dbus.Array([dbus.ByteArray(f'{key}={value}'.encode('utf-8'))
                                  for key, value in metadata.items()], signature='ay')
                self.call(self.group, group, 'AddService', 'iiussssqaay',
                          (dbus.Int32(-1), dbus.Int32(-1), dbus.UInt32(0),
                           f'ROSY Model {self.name}', self.profile.MODEL, '', '',
                           dbus.UInt16(self.port), txt))
                self.call(self.group, group, 'Commit')
                self.started = time.monotonic()
            value = int(self.call(self.group, group, 'GetState'))
            if value not in (1, 2) or (value == 1 and time.monotonic() - self.started >= 10):
                raise RuntimeError('Avahi group not established')
            if str(self.call('/', server, 'GetHostName')).casefold() != self.name.casefold():
                raise RuntimeError('Avahi host identity changed')
        except BaseException:
            self.close()
            raise  # The owned user service provides its existing 30s restart policy.

    def close(self):
        bus, owner, group = self.bus, self.owner, self.group
        self.bus = self.owner = self.group = self.started = None
        if bus is None:
            return
        try:
            if group is not None:
                try:
                    bus.call_blocking(owner, group, 'org.freedesktop.Avahi.EntryGroup',
                                      'Free', '', (), timeout=2)
                except Exception:
                    pass  # Closing this private owner also withdraws its groups.
        finally:
            bus.close()


class Publisher:
    """Own one CLI publisher or private D-Bus group; withdraw on loss/stop."""

    def __init__(self, port, name, *, spawn=subprocess.Popen, which=shutil.which, dbus_loader=None):
        self.port, self.name, self.spawn = port, name, spawn
        self.child = None
        self.profile = policy()
        self.dbus = None if which('avahi-publish-service') else DBusPublisher(
            port, name, self.profile, (dbus_loader or _load_dbus)())

    def update(self, ready):
        if self.dbus is not None:
            self.dbus.update(ready)
            return
        if self.child is not None and self.child.poll() is not None:
            self.child = None
            raise RuntimeError('owned Avahi publisher exited')
        if not ready:
            self.close()
        elif self.child is None:
            metadata = self.profile.REQUIRED[self.profile.MODEL]
            self.child = self.spawn(['avahi-publish-service', f'ROSY Model {self.name}',
                                     self.profile.MODEL, str(self.port),
                                     *(f'{key}={value}' for key, value in metadata.items())],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    def close(self):
        if self.dbus is not None:
            self.dbus.close()
            return
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
    if not shutil.which('ss'):
        parser.error('iproute2 is required; no service is advertised')
    stopped = threading.Event()
    for kind in (signal.SIGINT, signal.SIGTERM):
        signal.signal(kind, lambda *_: stopped.set())
    try:
        publisher = Publisher(args.port, socket.gethostname().split('.')[0])
    except ImportError:
        parser.error('avahi-utils or system Python dbus is required; no service is advertised')
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
