"""Core connects to the address but checks the certificate against tls_host (D-512 on Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import edge_drive  # noqa: E402


class Ctx:
    def __init__(self):
        self.names = []

    def wrap_socket(self, sock, server_hostname=None):
        self.names.append(server_hostname)
        return sock


def test_tls_host_names_the_certificate_and_the_address_is_dialled(monkeypatch):
    dialled = []
    monkeypatch.setattr(edge_drive.socket, "create_connection",
                        lambda addr, timeout: dialled.append(addr) or object())
    ctx = Ctx()
    core = edge_drive.Core("192.0.2.7", "t", 8080, ctx, tls_host="rosy-pinky-test.local")
    conn = core._connection(1.0)
    conn.connect()
    assert dialled == [("192.0.2.7", 8080)]
    assert ctx.names == ["rosy-pinky-test.local"]


def test_without_tls_host_the_stock_connection_is_kept():
    core = edge_drive.Core("192.0.2.7", "t", 8080, Ctx())
    conn = core._connection(1.0)
    assert "connect" not in vars(conn)          # http.client's own connect, host = address
    assert conn.host == "192.0.2.7"
