"""tools/ops/account_login_check.py against a fake Account issuer and a fake app on loopback."""
import http.server
import importlib.util
import json
import threading
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ops/account_login_check.py"


def _tool():
    spec = importlib.util.spec_from_file_location("account_login_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server(accept_login):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, status, location=None, cookie=None, body=b""):
            self.send_response(status)
            for name, value in (("Location", location), ("Set-Cookie", cookie)):
                if value:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/app/login":
                self._reply(302, base + "/authorize")
            elif self.path == "/authorize":  # only a signed-in browser is sent on to the app callback
                signed_in = "account=1" in self.headers.get("Cookie", "")
                self._reply(302, base + ("/app/callback" if signed_in else "/login"))
            elif self.path == "/app/callback":
                self._reply(303, base + "/app/home", cookie="app=1; Path=/")
            elif self.path == "/app/home":
                self._reply(200)
            elif self.path == "/app/session":
                self._reply(200 if "app=1" in self.headers.get("Cookie", "") else 401)
            else:
                self._reply(404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            good = accept_login and body["login"] == "probe" and self.headers["Origin"] == f"http://127.0.0.1:{self.server.server_port}"
            self._reply(204 if good else 401, cookie="account=1; Path=/" if good else None)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _config(server):
    base = f"http://127.0.0.1:{server.server_port}"
    return {"issuer": base, "login": "probe", "password": "pw", "apps": [
        {"name": "fixture", "start": base + "/app/login", "session": base + "/app/session"}]}


def test_login_chain_passes_and_a_refused_login_fails(tmp_path, capsys):
    tool = _tool()
    for accept, expected in ((True, 0), (False, 1)):
        server = _server(accept)
        try:
            path = tmp_path / f"config-{accept}.json"
            path.write_text(json.dumps(_config(server)), encoding="utf-8")
            assert tool.main(["x", str(path)]) == expected
        finally:
            server.shutdown()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("PASS fixture") and lines[1].startswith("FAIL fixture (account login 401")
