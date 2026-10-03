"""Bounded DNS-SD adapters and shared change-driven discovery cache (D-432).

Advertisements are untrusted endpoint hints, never connection authorization.
"""
from __future__ import annotations

import atexit
import ipaddress
import math
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

MAX_CANDIDATES = 64
RESOLVE_TIMEOUT_MS = 500


@dataclass(frozen=True)
class DiscoveredDevice:
    """A DNS-SD endpoint; TXT is public metadata, not authenticated identity."""

    instance: str
    service_type: str
    host: str
    port: int
    addresses: tuple[str, ...] = ()
    txt: tuple[tuple[str, str], ...] = ()
    interface: str = ""


def _service(service_type):
    value = service_type.removesuffix('.local.').rstrip('.')
    if not re.fullmatch(r'_[a-zA-Z0-9-]+\._(?:tcp|udp)', value):
        raise ValueError('invalid DNS-SD service type')
    return value


def _timeout(timeout_s):
    if not math.isfinite(timeout_s) or timeout_s < 0:
        raise ValueError('discovery timeout must be finite and nonnegative')
    return float(timeout_s)


def _deduplicate(rows):
    found = {}
    for row in rows:
        key = (row.service_type, row.instance, row.host, row.port, row.txt)
        if key in found:
            old = found[key]
            found[key] = DiscoveredDevice(old.instance, old.service_type, old.host, old.port,
                                          tuple(sorted(set(old.addresses + row.addresses))), old.txt)
        elif len(found) < MAX_CANDIDATES:
            found[key] = row
    return list(found.values())


class DiscoveryCache:
    """One optional zeroconf listener for multiple service kinds with bounded work.

    TTL/update/remove events maintain the cache rather than periodic rescans.
    A resolver worker keeps lookup off the browser/control thread. Full queues
    drop new hints and increment ``overloaded``; at most 64 names are retained.
    """

    def __init__(self):
        self._zc = None
        self._browsers = {}
        self._started = {}
        self._records = {}
        self._versions = {}
        self._pending = set()
        self._jobs = queue.Queue(maxsize=MAX_CANDIDATES)
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._closed = False
        self._worker = None
        self.overloaded = 0
        self._generation = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def browse(self, service_type):
        service_type = _service(service_type)
        with self._lock:
            if self._closed:
                raise RuntimeError('discovery cache is closed')
            if service_type in self._browsers:
                return True
            try:
                from zeroconf import ServiceBrowser, Zeroconf
            except ImportError:
                return False
            if self._zc is None:
                try:
                    self._zc = Zeroconf()
                except OSError:
                    return False
                self._worker = threading.Thread(target=self._resolve, name='rosy-discovery', daemon=True)
                self._worker.start()
            self._started[service_type] = time.monotonic()
            try:
                self._browsers[service_type] = ServiceBrowser(self._zc, service_type + '.local.', self)
            except (OSError, RuntimeError):
                self._started.pop(service_type, None)
                return False
            return True

    def add_service(self, zc, type_, name):
        key = (_service(type_), name)
        with self._lock:
            if self._closed:
                return
            if key not in self._versions and len(self._versions) >= MAX_CANDIDATES:
                self.overloaded += 1
                return
            self._generation += 1
            self._versions[key] = self._generation
            # Updated endpoints are unconfirmed until their current SRV resolves.
            self._records.pop(key, None)
            if key in self._pending:
                return
            try:
                self._jobs.put_nowait(key)
                self._pending.add(key)
            except queue.Full:
                self.overloaded += 1

    update_service = add_service

    def remove_service(self, zc, type_, name):
        key = (_service(type_), name)
        with self._lock:
            self._versions.pop(key, None)
            self._records.pop(key, None)
            self._changed.notify_all()

    def _resolve(self):
        while not self._closed:
            try:
                key = self._jobs.get(timeout=.1)
            except queue.Empty:
                continue
            with self._lock:
                version = self._versions.get(key)
            info = None
            try:
                if version is not None:
                    info = self._zc.get_service_info(key[0] + '.local.', key[1], timeout=RESOLVE_TIMEOUT_MS)
                row = _from_info(key, info)
            except Exception:
                # An optional adapter failure never establishes readiness.
                row = None
            with self._lock:
                self._pending.discard(key)
                if not self._closed and version is not None and self._versions.get(key) == version:
                    if row is None:
                        self._records.pop(key, None)
                    else:
                        self._records[key] = row
                elif key in self._versions and not self._closed:
                    self.add_service(self._zc, key[0], key[1])
                self._changed.notify_all()
            self._jobs.task_done()

    def snapshot(self, service_type):
        service_type = _service(service_type)
        with self._lock:
            return _deduplicate(row for key, row in self._records.items() if key[0] == service_type)

    def wait(self, service_type, *, timeout_s=3.0):
        service_type = _service(service_type)
        deadline = time.monotonic() + _timeout(timeout_s)
        if not self.browse(service_type):
            return _fallback(service_type, deadline)
        with self._changed:
            # The initial bounded window collects competing advertisements. Later
            # callers reuse live snapshots and never trigger a periodic rescan.
            initial = time.monotonic() - self._started[service_type] < timeout_s
            while not self._closed and (initial or not self.snapshot(service_type)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            return self.snapshot(service_type)

    def flush(self, *, timeout_s=1.0):
        """Wait for currently queued work, bounded by the caller's deadline."""
        deadline = time.monotonic() + _timeout(timeout_s)
        with self._changed:
            while self._pending and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._records.clear()
            self._versions.clear()
            self._changed.notify_all()
        for browser in self._browsers.values():
            browser.cancel()
        if self._zc is not None:
            self._zc.close()
        if self._worker is not None:
            self._worker.join(timeout=RESOLVE_TIMEOUT_MS / 1000 + .2)


def _from_info(key, info):
    if info is None or not info.server or not 0 < info.port <= 65535:
        return None
    type_, name = key
    suffix = '.' + type_ + '.local.'
    instance = name[:-len(suffix)] if name.endswith(suffix) else name
    txt = tuple(sorted((k.decode('utf-8', 'replace'), (v or b'').decode('utf-8', 'replace'))
                       for k, v in info.properties.items()))
    return DiscoveredDevice(instance, type_, info.server.rstrip('.').lower(), info.port,
                            tuple(info.parsed_addresses()), txt)


_shared = None
_shared_lock = threading.Lock()


def close_shared_cache():
    """Owner-lifecycle teardown without creating a cache if discovery was unused."""
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
            _shared = None


def get_shared_cache():
    """Process singleton; explicitly closable and also closed at process exit."""
    global _shared
    with _shared_lock:
        if _shared is None or _shared._closed:
            _shared = DiscoveryCache()
        return _shared


atexit.register(close_shared_cache)


def discover_devices(service_type, *, timeout_s=3.0):
    """Bounded one-shot lookup; runtime consumers should use the shared cache."""
    service_type = _service(service_type)
    deadline = time.monotonic() + _timeout(timeout_s)
    result = _via_zeroconf(service_type, max(0, deadline - time.monotonic()))
    return result if result is not None else _fallback(service_type, deadline)


def _fallback(service_type, deadline):
    for attempt in (_via_avahi, _via_dnssd):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return []
        result = attempt(service_type, remaining)
        if result is not None:
            return result
    return []


def _via_zeroconf(service_type, timeout_s):
    with DiscoveryCache() as cache:
        if not cache.browse(service_type):
            return None
        # First-list scan gathers multiple candidates instead of selecting first reply.
        deadline = time.monotonic() + timeout_s
        with cache._changed:
            while time.monotonic() < deadline:
                cache._changed.wait(max(0, deadline - time.monotonic()))
        return cache.snapshot(service_type)


def _unescape(value):
    return re.sub(r'\\(\d{3})', lambda match: chr(int(match[1])), value)


def parse_avahi_devices(output, service_type):
    """Parse Avahi -p -r records including SRV target, A/AAAA, port and TXT."""
    from .protocol.discovery_txt import parse_txt_pairs
    rows = []
    for line in output.splitlines():
        columns = line.split(';', 9)
        if len(columns) != 10 or columns[0] != '=' or columns[4] != service_type or columns[5] != 'local':
            continue
        try:
            port = int(columns[8])
        except ValueError:
            continue
        if not columns[6] or not columns[7] or not 0 < port <= 65535:
            continue
        rows.append(DiscoveredDevice(_unescape(columns[3]), service_type,
                                     _unescape(columns[6]).rstrip('.').lower(), port,
                                     (columns[7],), tuple(sorted(parse_txt_pairs(columns[9]))), columns[1]))
        if len(rows) >= MAX_CANDIDATES:
            break
    return _deduplicate(rows)


def _via_avahi(service_type, timeout_s):
    if shutil.which('avahi-browse') is None:
        return None
    try:
        result = subprocess.run(['avahi-browse', '-r', '-t', '-p', '-k', service_type],
                                capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ''
        return parse_avahi_devices(output.decode() if isinstance(output, bytes) else output, service_type)
    except OSError:
        return None
    return parse_avahi_devices(result.stdout, service_type) if result.returncode == 0 else None


def _capture_dnssd(args, timeout_s):
    """Bonjour commands are continuous; always kill and reap the child."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            output, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate(timeout=.2)
        return output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=.2)


def _via_dnssd(service_type, timeout_s):
    if shutil.which('dns-sd') is None:
        return None
    deadline = time.monotonic() + timeout_s
    try:
        output = _capture_dnssd(['dns-sd', '-B', service_type, 'local.'], timeout_s / 2)
        names = {}
        for line in output.splitlines():
            match = re.search(r'\b(Add|Rmv)\s+\d+\s+\d+\s+local\.\s+'
                              + re.escape(service_type) + r'\.?\s+(.+)$', line)
            if match:
                if match[1] == 'Rmv':
                    names.pop(match[2], None)
                elif len(names) < MAX_CANDIDATES:
                    names[match[2]] = None
        rows = []
        for index, name in enumerate(names):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            budget = remaining / (len(names) - index)
            output = _capture_dnssd(['dns-sd', '-L', name, service_type, 'local.'], budget / 2)
            match = re.search(r'can be reached at (\S+):(\d+)\s', output)
            if match and 0 < int(match[2]) <= 65535:
                from .protocol.discovery_txt import parse_txt_pairs
                host = match[1].rstrip('.').lower()
                txt = tuple(pair for line in output.splitlines()
                            if 'can be reached' not in line for pair in parse_txt_pairs(line))
                addresses = []
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    answer = _capture_dnssd(['dns-sd', '-G', 'v4v6', host], min(remaining, budget / 2))
                    for line in answer.splitlines():
                        action = re.search(r'\b(Add|Rmv)\s+', line)
                        if action is None:
                            continue
                        for value in line.split():
                            try:
                                address = str(ipaddress.ip_address(value))
                            except ValueError:
                                continue
                            if action[1] == 'Rmv' and address in addresses:
                                addresses.remove(address)
                            elif action[1] == 'Add' and address not in addresses:
                                addresses.append(address)
                rows.append(DiscoveredDevice(name, service_type, host, int(match[2]), tuple(addresses), txt))
        return _deduplicate(rows)
    except (OSError, subprocess.TimeoutExpired):
        return []
