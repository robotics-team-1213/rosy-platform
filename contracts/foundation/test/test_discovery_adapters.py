"""D-432 discovery resolves actual endpoints and preserves cache lifecycle."""

import sys
import threading
import time
from types import SimpleNamespace

import pytest

from core_common import discover


def test_avahi_resolves_srv_and_deduplicates_interfaces(monkeypatch):
    monkeypatch.setattr(discover.shutil, "which", lambda _: "avahi-browse")
    row = '=;eth0;IPv4;Dock One;_rosy-dock._tcp;local;real-host.local;192.0.2.1;8090;"role=dock"'
    monkeypatch.setattr(discover.subprocess, "run", lambda args, **kwargs:
                        SimpleNamespace(stdout=row + '\n' + row.replace('eth0', 'wlan0'), returncode=0))
    devices = discover._via_avahi("_rosy-dock._tcp", 1)
    assert len(devices) == 1
    assert (devices[0].instance, devices[0].host, devices[0].port) == ("Dock One", "real-host.local", 8090)
    assert devices[0].addresses == ("192.0.2.1",)
    assert dict(devices[0].txt) == {"role": "dock"}


def test_avahi_never_infers_unresolved_host(monkeypatch):
    monkeypatch.setattr(discover.shutil, "which", lambda _: "avahi-browse")
    monkeypatch.setattr(discover.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(stdout='+;eth0;IPv4;dock;_rosy-dock._tcp;local', returncode=0))
    assert discover._via_avahi("_rosy-dock._tcp", 1) == []


def test_bonjour_resolves_real_host_and_port(monkeypatch):
    monkeypatch.setattr(discover.shutil, "which", lambda _: "dns-sd")
    calls = []

    def capture(args, timeout_s):
        calls.append(args)
        if '-B' in args:
            return '12:00:00.000 Add 2 4 local. _rosy-dock._tcp. Dock One\n'
        if '-G' in args:
            return '12:00:00.000 Add 2 4 actual.local. 192.0.2.1 120\n'
        return 'Dock One._rosy-dock._tcp.local. can be reached at actual.local.:8091 (interface 4)\n role=dock\n'

    monkeypatch.setattr(discover, "_capture_dnssd", capture)
    devices = discover._via_dnssd("_rosy-dock._tcp", 1)
    assert (devices[0].host, devices[0].port) == ("actual.local", 8091)
    assert calls[1] == ['dns-sd', '-L', 'Dock One', '_rosy-dock._tcp', 'local.']
    assert devices[0].addresses == ('192.0.2.1',)
    assert dict(devices[0].txt) == {'role': 'dock'}


def test_cache_updates_removes_and_cancels_browser(monkeypatch):
    instances = []
    info = SimpleNamespace(server="actual.local.", port=8091,
                           properties={b'role': b'dock'}, parsed_addresses=lambda: ['192.0.2.1'])

    class Zc:
        closed = False

        def get_service_info(self, *args, **kwargs):
            return info

        def close(self):
            self.closed = True

    class Browser:
        cancelled = False

        def __init__(self, zc, service, listener):
            self.zc, self.listener = zc, listener
            instances.append(self)

        def cancel(self):
            self.cancelled = True

    monkeypatch.setitem(sys.modules, 'zeroconf', SimpleNamespace(ServiceBrowser=Browser, Zeroconf=Zc))
    with discover.DiscoveryCache() as cache:
        cache.browse('_rosy-dock._tcp')
        browser = instances[0]
        name = 'Dock One._rosy-dock._tcp.local.'
        browser.listener.add_service(browser.zc, '_rosy-dock._tcp.local.', name)
        assert cache.wait('_rosy-dock._tcp', timeout_s=1)[0].port == 8091
        info.port = 8092
        browser.listener.update_service(browser.zc, '_rosy-dock._tcp.local.', name)
        cache.flush(timeout_s=1)
        assert cache.snapshot('_rosy-dock._tcp')[0].port == 8092
        browser.listener.remove_service(browser.zc, '_rosy-dock._tcp.local.', name)
        assert cache.snapshot('_rosy-dock._tcp') == []
        assert len(instances) == 1
    assert browser.cancelled and browser.zc.closed


def test_one_total_fallback_deadline(monkeypatch):
    budgets = []
    monkeypatch.setattr(discover, '_via_zeroconf', lambda service, timeout: None)
    monkeypatch.setattr(discover, '_via_avahi', lambda service, timeout: budgets.append(timeout))
    monkeypatch.setattr(discover, '_via_dnssd', lambda service, timeout: budgets.append(timeout) or [])
    assert discover.discover_devices('_rosy-dock._tcp', timeout_s=.1) == []
    assert all(0 < budget <= .1 for budget in budgets)


@pytest.mark.parametrize('timeout', [-1, float('inf'), float('nan')])
def test_invalid_deadline_rejected(timeout):
    with pytest.raises(ValueError):
        discover.discover_devices('_rosy-dock._tcp', timeout_s=timeout)


def test_remove_during_resolution_never_resurrects_and_cap_is_bounded(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Zc:
        def get_service_info(self, *args, **kwargs):
            entered.set()
            release.wait(1)
            return SimpleNamespace(server='old.local.', port=80, properties={}, parsed_addresses=lambda: [])

        def close(self):
            release.set()

    class Browser:
        def __init__(self, *args):
            pass

        def cancel(self):
            pass

    monkeypatch.setitem(sys.modules, 'zeroconf', SimpleNamespace(ServiceBrowser=Browser, Zeroconf=Zc))
    with discover.DiscoveryCache() as cache:
        cache.browse('_rosy-dock._tcp')
        cache.add_service(cache._zc, '_rosy-dock._tcp', 'removed')
        assert entered.wait(1)
        cache.remove_service(cache._zc, '_rosy-dock._tcp', 'removed')
        for index in range(discover.MAX_CANDIDATES + 2):
            cache.add_service(cache._zc, '_rosy-dock._tcp', f'dock-{index}')
        assert len(cache._versions) == discover.MAX_CANDIDATES
        assert cache.overloaded >= 2
        release.set()
        cache.flush(timeout_s=1)
        assert all(item.instance != 'removed' for item in cache.snapshot('_rosy-dock._tcp'))


@pytest.mark.parametrize('present', [True, False])
def test_warm_cache_reads_do_not_create_new_browsers(monkeypatch, present):
    monkeypatch.setitem(sys.modules, 'zeroconf', SimpleNamespace(
        Zeroconf=lambda: SimpleNamespace(close=lambda: None),
        ServiceBrowser=lambda *a: SimpleNamespace(cancel=lambda: None)))
    with discover.DiscoveryCache() as cache:
        cache.browse('_rosy-dock._tcp')
        cache._started['_rosy-dock._tcp'] = time.monotonic() - 4
        if present:
            cache._records[('_rosy-dock._tcp', 'dock')] = discover.DiscoveredDevice(
                'dock', '_rosy-dock._tcp', 'actual.local', 8091)
        before = time.monotonic()
        assert len(cache.wait('_rosy-dock._tcp', timeout_s=3)) == int(present)
        assert time.monotonic() - before < .1
        assert len(cache._browsers) == 1


def test_bonjour_timeout_always_reaps_child(monkeypatch):
    class Child:
        killed = False
        calls = 0

        def communicate(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise discover.subprocess.TimeoutExpired('dns-sd', timeout)
            return 'fixture', ''

        def kill(self):
            self.killed = True

        def poll(self):
            return 0 if self.killed else None

    child = Child()
    monkeypatch.setattr(discover.subprocess, 'Popen', lambda *a, **kw: child)
    assert discover._capture_dnssd(['dns-sd', '-B'], .01) == 'fixture'
    assert child.killed and child.calls == 2
