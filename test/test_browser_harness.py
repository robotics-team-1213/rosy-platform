"""browser_harness port and opt-in helpers (no Chromium needed)."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import socket
import threading
from types import SimpleNamespace
from urllib.request import urlopen

import browser_harness
import pytest


@pytest.mark.parametrize('outcomes,expected_error', [
    (['ok'], None),
    (['asset', 'ok'], None),
    (['navigation', 'ok'], None),
    (['asset', 'asset'], 'ERR_NETWORK_CHANGED'),
    (['other'], 'ERR_CONNECTION_REFUSED'),
])
def test_navigation_recovers_only_one_observed_network_change(outcomes, expected_error):
    class Page:
        def __init__(self):
            self.calls = []
            self.listeners = {}

        def on(self, event, callback):
            self.listeners[event] = callback

        def remove_listener(self, event, callback):
            assert self.listeners.pop(event) is callback

        def goto(self, url):
            result = outcomes[len(self.calls)]
            self.calls.append(url)
            if result == 'asset':
                self.listeners['requestfailed'](SimpleNamespace(
                    resource_type='script', failure='net::ERR_NETWORK_CHANGED'))
            elif result != 'ok':
                raise RuntimeError('net::' + ('ERR_NETWORK_CHANGED' if result == 'navigation'
                                             else 'ERR_CONNECTION_REFUSED'))
            return 'loaded'

    page = Page()
    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            browser_harness.goto_with_network_change_retry(page, 'http://127.0.0.1/console/site-map')
    else:
        assert browser_harness.goto_with_network_change_retry(
            page, 'http://127.0.0.1/console/site-map') == 'loaded'
    assert len(page.calls) == len(outcomes)
    assert not page.listeners


def test_safe_listener_skips_a_restricted_port(monkeypatch):
    handed = iter([2049, 10080, 43123])

    class FakeSocket:
        def __init__(self):
            self.port = next(handed)
            self.closed = False

        def bind(self, address):
            pass

        def getsockname(self):
            return ("127.0.0.1", self.port)

        def close(self):
            self.closed = True

    monkeypatch.setattr(browser_harness.socket, "socket", FakeSocket)
    assert browser_harness.safe_listener().getsockname()[1] == 43123


def test_free_port_is_bindable_and_not_restricted():
    port = browser_harness.free_port()
    assert port not in browser_harness.CHROMIUM_RESTRICTED_PORTS
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_restricted_list_has_the_ports_seen_on_windows():
    assert {2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6669, 6697, 10080} \
        <= browser_harness.CHROMIUM_RESTRICTED_PORTS


def test_either_opt_in_name_enables_browser_tests(monkeypatch):
    for name in ("ROSY_RUN_BROWSER_TESTS", "ROSY_BROWSER_TESTS"):
        monkeypatch.delenv("ROSY_RUN_BROWSER_TESTS", raising=False)
        monkeypatch.delenv("ROSY_BROWSER_TESTS", raising=False)
        assert not browser_harness.browser_tests_enabled()
        monkeypatch.setenv(name, "1")
        assert browser_harness.browser_tests_enabled()
    monkeypatch.setenv("ROSY_BROWSER_TESTS", "0")
    monkeypatch.setenv("ROSY_RUN_BROWSER_TESTS", "0")
    assert not browser_harness.browser_tests_enabled()


def test_safe_http_server_serves_on_the_bound_safe_socket():
    class Hello(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = browser_harness.safe_http_server(Hello)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert port not in browser_harness.CHROMIUM_RESTRICTED_PORTS
        assert server.socket.getsockname()[1] == port == server.server_port
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as reply:
            assert reply.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()
