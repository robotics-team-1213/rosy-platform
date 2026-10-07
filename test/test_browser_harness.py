"""browser_harness port and opt-in helpers (no Chromium needed)."""

from __future__ import annotations

import socket

import browser_harness


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
