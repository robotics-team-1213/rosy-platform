"""deploy/site/account_login_check.py against a fake Account issuer and a fake app on loopback."""
import http.server
import importlib.util
import json
import threading
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/site/account_login_check.py"


def _tool():
    spec = importlib.util.spec_from_file_location("account_login_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server(accept_login, callback_ok=True, session_body=None):
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
                self._reply(303, base + "/app/home", cookie="app=1; Path=/" if callback_ok else None)
            elif self.path == "/app/home":
                self._reply(200)
            elif self.path == "/app/session":  # like Calibration: 200 either way, the body says who is in
                signed_in = "app=1" in self.headers.get("Cookie", "")
                body = json.dumps({"authenticated": signed_in}).encode() if session_body is None else session_body
                self._reply(200, body=body)
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


def test_a_200_session_that_is_not_signed_in_fails(tmp_path, capsys):
    server = _server(True, callback_ok=False)
    try:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(_config(server)), encoding="utf-8")
        assert _tool().main(["x", str(path)]) == 1
    finally:
        server.shutdown()
    assert "not authenticated" in capsys.readouterr().out


def test_site_timer_runs_the_signed_release_script_every_30_minutes_and_ships_in_the_candidate():
    root = SCRIPT.parents[2]
    unit = (root / "deploy/site/rosy-site-account-login-check.service").read_text()
    timer = (root / "deploy/site/rosy-site-account-login-check.timer").read_text()
    assert ("ExecStart=/usr/bin/python3 -I /opt/rosy/candidate/deploy/site/account_login_check.py "
            "/etc/rosy/site/account-login-check.json") in unit
    assert "Type=oneshot" in unit and "OnUnitInactiveSec=30min" in timer
    assert "Unit=rosy-site-account-login-check.service" in timer
    for name in ("build_candidate.py", "verify_candidate.py"):
        assert "rosy-site-account-login-check.timer" in (root / "deploy/site" / name).read_text()


def _verdict(tmp_path, capsys, body):
    server = _server(True, session_body=body)
    try:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(_config(server)), encoding="utf-8")
        code = _tool().main(["x", str(path)])
    finally:
        server.shutdown()
    return code, capsys.readouterr().out


def test_session_verdict_needs_positive_evidence_of_a_signed_in_user(tmp_path, capsys):
    passing = [b'{"authenticated": true}', b'{"user_id": "u1"}', b'{"account_id": "a1"}', b'{"principal_id": "p1"}']
    failing = [b"{}", b"[]", b'"ok"', b"<html>error</html>", b"", b'{"authenticated": false, "user_id": "u1"}',
               b'{"user_id": ""}', b'{"user_id": 7}', b'{"authenticated": "yes"}']
    for body in passing:
        assert _verdict(tmp_path, capsys, body)[0] == 0, body
    for body in failing:
        assert _verdict(tmp_path, capsys, body)[0] == 1, body


def test_a_session_body_that_hits_the_read_limit_fails_even_if_it_starts_like_success(tmp_path, capsys):
    body = json.dumps({"authenticated": True, "padding": "x" * 70000}).encode()
    code, out = _verdict(tmp_path, capsys, body)
    assert code == 1 and "64 KiB" in out
    small = json.dumps({"authenticated": True, "padding": "x" * 20000}).encode()
    assert _verdict(tmp_path, capsys, small)[0] == 0


def test_a_run_that_checked_no_app_is_not_a_success(tmp_path, capsys):
    server = _server(True)
    try:
        config = _config(server)
        path = tmp_path / "config.json"
        path.write_text(json.dumps({**config, "apps": []}), encoding="utf-8")
        assert _tool().main(["x", str(path)]) != 0
        path.write_text(json.dumps(config), encoding="utf-8")
        assert _tool().main(["x", str(path), "no-such-app"]) != 0
        assert _tool().main(["x", str(path), "fixture"]) == 0
    finally:
        server.shutdown()
    assert "no app was checked" in capsys.readouterr().err


def test_every_request_has_a_10_second_timeout():
    assert "timeout=10)" in SCRIPT.read_text() and "timeout=15" not in SCRIPT.read_text()


def test_start_timeout_covers_the_worst_case_of_seven_slow_apps():
    unit = (SCRIPT.parents[2] / "deploy/site/rosy-site-account-login-check.service").read_text()
    assert "TimeoutStartSec=15min" in unit and "9 requests" in unit


def test_the_status_file_holds_app_names_and_verdicts_only(tmp_path, capsys):
    tool, status = _tool(), tmp_path / "status.json"
    for accept in (True, False):
        server = _server(accept)
        try:
            path = tmp_path / "config.json"
            path.write_text(json.dumps(_config(server)), encoding="utf-8")
            assert tool.main(["x", "--status", str(status), str(path)]) == (0 if accept else 1)
        finally:
            server.shutdown()
        written = json.loads(status.read_text(encoding="utf-8"))
        assert written["apps"] == {"fixture": accept} and isinstance(written["time"], int)
        assert "pw" not in status.read_text(encoding="utf-8") and "probe" not in status.read_text(encoding="utf-8")
    assert tool.main(["x", "--status"]) == 2


def test_a_run_that_checked_no_app_leaves_the_status_file_alone(tmp_path):
    server, status = _server(True), tmp_path / "status.json"
    try:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({**_config(server), "apps": []}), encoding="utf-8")
        assert _tool().main(["x", "--status", str(status), str(path)]) == 2
    finally:
        server.shutdown()
    assert not status.exists()


def test_the_unit_writes_the_status_file_the_guard_reads():
    unit = (SCRIPT.parents[2] / "deploy/site/rosy-site-account-login-check.service").read_text()
    assert "--status /var/lib/rosy-account-login-check/status.json" in unit and "StateDirectory=rosy-account-login-check" in unit
