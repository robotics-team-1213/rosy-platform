"""browser_harness port and opt-in helpers (no Chromium needed)."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import socket
import sys
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


def _install_fake_playwright(monkeypatch):
    events = []
    state = {"launches": [], "contexts": [], "stops": 0}

    class FakePage:
        def __init__(self):
            self.listeners = {}
            self.timeout = None

        def on(self, name, fn):
            self.listeners[name] = fn

        def set_default_timeout(self, ms):
            self.timeout = ms

    class FakeContext:
        def __init__(self, options):
            self.options = options
            self.closed = 0
            self.pages = [FakePage()]

        def new_page(self):
            return self.pages[0]

        def close(self):
            self.closed += 1
            if self in shared_browser.contexts:
                shared_browser.contexts.remove(self)

    class FakeBrowser:
        def __init__(self, options, is_shared=True):
            self.options = options
            self.connected = True
            self.closed = 0
            self.contexts = []
            self.fail_close = False
            self.is_shared = is_shared

        def is_connected(self):
            return self.connected

        def new_context(self, **options):
            ctx = FakeContext(options)
            self.contexts.append(ctx)
            state["contexts"].append(ctx)
            return ctx

        def new_page(self, **options):
            events.append(("dedicated_new_page", options))
            return FakePage()

        def close(self):
            self.closed += 1
            if self.fail_close:
                raise RuntimeError("close failed")

    shared_browser = None

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def launch(self, **options):
            nonlocal shared_browser
            state["launches"].append(options)
            browser = FakeBrowser(options, is_shared=("args" not in options))
            if browser.is_shared:
                shared_browser = browser
            return browser

        def stop(self):
            state["stops"] += 1

    class FakeStarter:
        def start(self):
            return FakePlaywright()

    fake_api = SimpleNamespace(sync_playwright=lambda: FakeStarter())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=fake_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
    return state, events


def test_context_lease_closes_only_context_and_is_idempotent():
    closed = []
    ctx = SimpleNamespace(close=lambda: closed.append("ctx"))
    with browser_harness._ContextLease(ctx) as lease:
        lease.close()
        lease.close()
    lease.close()
    assert closed == ["ctx"]


def test_shared_browser_crash_recovery_and_close_idempotency(monkeypatch):
    browser_harness.close_shared_browser()
    state, _ = _install_fake_playwright(monkeypatch)
    try:
        b1 = browser_harness.shared_browser()
        assert browser_harness.shared_browser() is b1
        b1.connected = False
        b2 = browser_harness.shared_browser()
        assert b2 is not b1
        assert state["stops"] == 1
        assert len(state["launches"]) == 2
        b2.contexts.append(SimpleNamespace(close=lambda: None))
        b2.fail_close = True
        browser_harness.close_shared_browser()
        assert state["stops"] == 2
        browser_harness.close_shared_browser()
        assert state["stops"] == 2
    finally:
        browser_harness._SHARED = None


def test_open_shared_page_restricted_port_fallback_vs_safe_port(monkeypatch):
    browser_harness.close_shared_browser()
    state, events = _install_fake_playwright(monkeypatch)
    try:
        lease, page, errors = browser_harness.open_page(None, 800, 600, url="http://127.0.0.1:43123/", ignore_https_errors=True)
        assert isinstance(lease, browser_harness._ContextLease)
        assert page.timeout == 15_000
        assert state["contexts"][0].options == {"viewport": {"width": 800, "height": 600}, "ignore_https_errors": True}
        page.listeners["pageerror"](RuntimeError("boom"))
        assert errors == ["boom"]
        lease.close()
        assert state["contexts"][0].closed == 1

        dedicated, page2, _ = browser_harness.open_page(None, 390, 844, url="http://127.0.0.1:6000/")
        assert not isinstance(dedicated, browser_harness._ContextLease)
        assert state["launches"][-1]["args"] == ["--explicitly-allowed-ports=6000"]
        assert events[-1] == ("dedicated_new_page", {"viewport": {"width": 390, "height": 844}})
        dedicated.close()
        assert dedicated.closed == 1
    finally:
        browser_harness.close_shared_browser()


def test_open_token_access_uses_auth_predicate_and_retries_details_toggle():
    calls = []

    class FakeSummary:
        def __init__(self, details):
            self._details = details

        def click(self):
            calls.append("summary.click")
            self._details.open_states.pop(0)

    class FakeLocator:
        def __init__(self, name, page):
            self.name = name
            self.page = page
            self.open_states = [None, None, ""] if name == "#token-access" else []

        def is_visible(self):
            return self.name == "#topbar-more"

        def get_attribute(self, attr):
            if self.name == "#topbar-more" and attr == "aria-expanded":
                return "true" if self.page.menu_open else "false"
            if self.name == "#token-access" and attr == "open":
                return self.open_states[0]
            return None

        def click(self):
            calls.append(f"{self.name}.click")
            if self.name == "#topbar-more":
                self.page.menu_open = True

        def locator(self, sub):
            assert self.name == "#token-access" and sub == "summary"
            return FakeSummary(self)

        @property
        def first(self):
            return self

        def wait_for(self, *, state, timeout=None):
            calls.append(f"{self.name}.wait_for({state})")

    class FakePage:
        def __init__(self):
            self.menu_open = False
            self._locs = {}

        def wait_for_load_state(self, *args, **kwargs):
            raise AssertionError("networkidle wait_for_load_state must not be called")

        def wait_for_function(self, expr):
            raise AssertionError("wait_for_function freezes under page.clock.install()")

        def locator(self, sel):
            return self._locs.setdefault(sel, FakeLocator(sel, self))

    page = FakePage()
    browser_harness.open_token_access(page)
    assert "user-role" in calls[0] and "token-save" in calls[1]
    assert calls[2:] == ["#topbar-more.click", "summary.click", "summary.click", "#console-token.wait_for(visible)"]


def test_open_shared_page_retries_once_when_new_page_disposes(monkeypatch):
    browser_harness.close_shared_browser()
    state, _ = _install_fake_playwright(monkeypatch)
    orig_ctx = state["contexts"]
    failed_once = {"done": False}
    orig_shared = browser_harness.shared_browser

    def flaky_shared():
        browser = orig_shared()
        if not failed_once["done"]:
            orig_new_context = browser.new_context

            def failing_ctx(**opts):
                ctx = orig_new_context(**opts)

                def boom():
                    failed_once["done"] = True
                    raise RuntimeError("BrowserContext.new_page: Response has been disposed")

                ctx.new_page = boom
                return ctx

            browser.new_context = failing_ctx
        return browser

    monkeypatch.setattr(browser_harness, "shared_browser", flaky_shared)
    try:
        lease, page, _ = browser_harness.open_shared_page(800, 600)
        assert isinstance(lease, browser_harness._ContextLease)
        assert page.timeout == 15_000
        assert len(orig_ctx) == 2
        assert orig_ctx[0].closed == 1
        assert state["stops"] == 1
        lease.close()
    finally:
        browser_harness.close_shared_browser()
