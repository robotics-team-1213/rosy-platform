"""host_ops (D-991): the Fleet-down path takes the screen's closed list to the same helper."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/remote'))
_spec = importlib.util.spec_from_file_location('host_ops', ROOT / 'tools/remote/host_ops.py')
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

CONFIG = {'site_host': 'ops@site-pc', 'sim_hosts': ['ml@model-pc=model', 'ai@ai-pc=ai', 'x@spare-pc']}


def _runner(code=0):
    calls = []

    def run(argv, **_):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code)
    return run, calls


def test_a_person_reboot_asks_the_helper_to_stop_at_jobs():
    run, calls = _runner()
    assert ops.run('model', 'reboot', None, CONFIG, runner=run) == 0
    assert calls[0][-5:] == ['ml@model-pc', 'sudo', '-n', ops.HELPER, 'reboot-if-free']


def test_only_the_second_word_passes_jobs():
    run, calls = _runner()
    assert ops.run('ai', 'reboot-over-jobs', None, CONFIG, runner=run) == 0
    assert calls[0][-1] == 'reboot' and 'ai@ai-pc' in calls[0]


@pytest.mark.parametrize('host, action, unit', [
    ('site', 'pkill', None), ('site', 'stop-unit', 'docker.service'), ('site', 'clean-storage', None),
    ('ai', 'restart-unit', 'pinky-frontend.service'), ('robot', 'reboot', None)])
def test_what_the_screen_refuses_never_reaches_ssh(host, action, unit):
    run, calls = _runner()
    assert ops.run(host, action, unit, CONFIG, runner=run) == 2
    assert calls == []


def test_a_helper_refusal_keeps_its_exit_code_and_says_why(capsys):
    run, _ = _runner(6)
    assert ops.run('site', 'reboot', None, CONFIG, runner=run) == 6
    assert 'arm session' in capsys.readouterr().err


def test_a_hung_ssh_reports_an_unknown_result(capsys):
    def run(argv, **_):
        raise subprocess.TimeoutExpired(argv, 60)
    assert ops.run('site', 'reboot', None, CONFIG, runner=run) == 1
    assert 'unknown' in capsys.readouterr().err


def test_a_mistyped_confirm_stops_before_anything_loads(monkeypatch):
    monkeypatch.setattr(ops.lab_hosts, 'load', lambda: pytest.fail('read the host list'))
    with pytest.raises(SystemExit):
        ops.main(['model', 'reboot', '--confirm', 'site'])


def test_unbound_candidates_are_not_targets():
    assert ops.targets(CONFIG) == {'site': 'ops@site-pc', 'model': 'ml@model-pc', 'ai': 'ai@ai-pc'}


def test_omx_hosts_adds_cell_target_and_accepts_root_maintenance():
    cfg = {**CONFIG, 'omx_hosts': ['cellop@cell-pc']}
    assert ops.targets(cfg)['cell'] == 'cellop@cell-pc'
    run, calls = _runner()
    assert ops.run('cell', 'root-maintenance', None, cfg, runner=run) == 0
    assert calls[0][-5:] == ['cellop@cell-pc', 'sudo', '-n', ops.HELPER, 'root-maintenance']


def test_api_status_and_control_via_bearer_and_oauth(tmp_path, monkeypatch, capsys):
    import http.server
    import json
    import threading
    import urllib.request

    monkeypatch.delenv('ROSY_FLEET_TOKEN', raising=False)
    monkeypatch.delenv('ROSY_FLEET_ACCOUNT_FILE', raising=False)
    received = []
    next_code = {'status': 200, 'body': {'code': 'ACCEPTED'}}
    redirect_to = {'url': None}

    class FleetHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith('/api/fleet/auth/login'):
                if redirect_to['url']:
                    self.send_response(303)
                    self.send_header('Location', redirect_to['url'])
                    self.end_headers()
                    return
                self.send_response(303)
                self.send_header('Location', f'http://127.0.0.1:{acct_port}/authorize?client_id=fleet&state=s1')
                self.end_headers()
                return
            if self.path.startswith('/callback'):
                self.send_response(303)
                self.send_header('Set-Cookie', 'fleet_session=ok-cookie; Path=/; HttpOnly')
                self.send_header('Location', '/console/maintenance')
                self.end_headers()
                return
            if self.path == '/console/maintenance':
                if 'fleet_session=ok-cookie' not in self.headers.get('Cookie', ''):
                    self.send_response(403)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
                return
            if self.path == '/api/fleet/hosts':
                auth = self.headers.get('Authorization', '')
                cookie = self.headers.get('Cookie', '')
                if auth != 'Bearer secret-tok' and 'fleet_session=ok-cookie' not in cookie:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"detail":{"code":"UNAUTHORIZED"}}')
                    return
                payload = {
                    'hosts': [{'host': 'model', 'actions': ['clean-storage', 'root-maintenance']}],
                    'guard': {'model': {'state': 'ok', 'resources': {
                        'avail_pct': 70, 'disk': {'test_free_gb': 85.0, 'test_use_pct': 80,
                                                  'root_free_gb': 85.0, 'root_use_pct': 10}}}},
                }
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length).decode())
            auth = self.headers.get('Authorization', '')
            cookie = self.headers.get('Cookie', '')
            if auth != 'Bearer secret-tok' and 'fleet_session=ok-cookie' not in cookie:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"detail":{"code":"UNAUTHORIZED"}}')
                return
            received.append((self.path, self.headers.get('Origin'), body))
            self.send_response(next_code['status'])
            self.end_headers()
            self.wfile.write(json.dumps(next_code['body']).encode())

    class AcctHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            cred = json.loads(self.rfile.read(length).decode())
            if (self.path == '/api/fleet/auth/login' and cred == {'login': 'op', 'password': 'pw'}
                    and self.headers.get('Origin') == acct_url):
                self.send_response(204)
                self.send_header('Set-Cookie', 'acct_session=a1; Path=/; HttpOnly')
                self.end_headers()
                return
            self.send_response(401)
            self.end_headers()

        def do_GET(self):
            if self.path.startswith('/authorize') and 'acct_session=a1' in self.headers.get('Cookie', ''):
                self.send_response(303)
                self.send_header('Location', f'http://127.0.0.1:{fleet_port}/callback?code=c1&state=s1')
                self.end_headers()
                return
            self.send_response(403)
            self.end_headers()

    fleet_srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FleetHandler)
    acct_srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), AcctHandler)
    fleet_port = fleet_srv.server_address[1]
    acct_port = acct_srv.server_address[1]
    fleet_url = f'http://127.0.0.1:{fleet_port}'
    acct_url = f'http://127.0.0.1:{acct_port}'
    for srv in (fleet_srv, acct_srv):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        tok_file = tmp_path / 'tok'
        tok_file.write_text('secret-tok\n', encoding='utf-8')
        acct_file = tmp_path / 'acct.json'
        acct_file.write_text(json.dumps({'login': 'op', 'password': 'pw'}), encoding='utf-8')

        assert ops.status_api(CONFIG, fleet_url=fleet_url, account_url=acct_url, account_file=str(acct_file)) == 0
        out = capsys.readouterr().out
        assert 'model: state=ok test=85.0GiB(80%)' in out

        assert ops.run_api('model', 'clean-storage', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, token_file=str(tok_file)) == 0
        assert received[-1] == ('/api/fleet/hosts/model/control', fleet_url,
                                {'action': 'clean-storage', 'unit': None, 'operator_confirmed': True})

        assert ops.run_api('site', 'root-maintenance', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, account_file=str(acct_file)) == 0
        assert received[-1] == ('/api/fleet/hosts/site/control', fleet_url,
                                {'action': 'root-maintenance', 'unit': None, 'operator_confirmed': True})

        next_code.update({'status': 409, 'body': {'detail': {'code': 'ARM_SESSION_ACTIVE'}}})
        assert ops.run_api('site', 'reboot', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, token_file=str(tok_file)) == 6

        next_code.update({'status': 409, 'body': {'detail': {'code': 'NO_STORAGE_SERVICE'}}})
        assert ops.run_api('ai', 'root-maintenance', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, token_file=str(tok_file)) == 5

        assert ops.run_api('site', 'clean-storage', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, token_file=str(tok_file)) == 2

        next_code.update({'status': 200, 'body': {'code': 'ACCEPTED'}})
        assert ops.main(['model', 'clean-storage', '--confirm', 'model', '--via-api',
                         '--fleet-url', fleet_url, '--account-url', acct_url,
                         '--token-file', str(tok_file)]) == 0
        out = capsys.readouterr().out
        assert 'model clean-storage: ACCEPTED' in out

        # Auto-API selects HTTPS API without --via-api when token and URL are configured.
        monkeypatch.setenv('ROSY_FLEET_TOKEN', 'secret-tok')
        monkeypatch.setenv('ROSY_FLEET_URL', fleet_url)
        monkeypatch.setenv('ROSY_ACCOUNT_URL', acct_url)
        assert ops.main(['ai', 'root-maintenance', '--confirm', 'ai']) == 0
        assert received[-1] == ('/api/fleet/hosts/ai/control', fleet_url,
                                {'action': 'root-maintenance', 'unit': None, 'operator_confirmed': True})

        # Explicit account_file overrides ROSY_FLEET_TOKEN env var.
        assert ops.resolve_auth(account_file=str(acct_file)) == ('account', ('op', 'pw'))

        # --via-ssh bypasses API and reaches ops.run directly.
        ssh_calls = []
        monkeypatch.setattr(ops, 'run', lambda h, a, u, c: ssh_calls.append((h, a, u)) or 0)
        monkeypatch.setattr(ops.lab_hosts, 'load', lambda: CONFIG)
        assert ops.main(['ai', 'clean-storage', '--confirm', 'ai', '--via-ssh']) == 0
        assert ssh_calls == [('ai', 'clean-storage', None)]

        monkeypatch.delenv('ROSY_FLEET_TOKEN', raising=False)
        monkeypatch.delenv('ROSY_FLEET_URL', raising=False)
        monkeypatch.delenv('ROSY_ACCOUNT_URL', raising=False)
        redirect_to['url'] = 'https://evil.example/steal'
        assert ops.status_api(CONFIG, fleet_url=fleet_url, account_url=acct_url,
                              account_file=str(acct_file)) == 1
        assert 'REDIRECT_OUTSIDE_TRUSTED_ORIGINS' in capsys.readouterr().err

        # Also verify Bearer succeeds without login and 401 failure returns exit 1 cleanly.
        assert ops.status_api(CONFIG, fleet_url=fleet_url, account_url=acct_url,
                              token_file=str(tok_file)) == 0
        redirect_to['url'] = None
        bad_tok = tmp_path / 'badtok'
        bad_tok.write_text('wrong\n', encoding='utf-8')
        assert ops.run_api('model', 'clean-storage', None, CONFIG,
                           fleet_url=fleet_url, account_url=acct_url, token_file=str(bad_tok)) == 1
        assert 'HTTP 401' in capsys.readouterr().err

        with pytest.raises(ValueError, match='https'):
            ops.resolve_urls(CONFIG, fleet_url='http://remote.example:8443')
        resolved = ops.resolve_urls(CONFIG, fleet_url='https://other.ts.net:8443')
        assert resolved == ('https://other.ts.net:8443', 'https://other.ts.net:8443',
                            'https://other.ts.net', 'https://other.ts.net')
        assert ops.resolve_urls(CONFIG, fleet_url='HTTPS://OTHER.TS.NET:443/') == (
            'https://other.ts.net', 'https://other.ts.net', 'https://other.ts.net', 'https://other.ts.net')
        with pytest.raises(ValueError) as bad_url:
            ops.resolve_urls(CONFIG, fleet_url='https://user:topsecret@other.ts.net')
        assert 'topsecret' not in str(bad_url.value)
        hdr = ops._AllowedRedirectHandler({'https://a.example', 'https://b.example'})
        req = urllib.request.Request('https://a.example/x',
                                     headers={'Authorization': 'Bearer tok', 'Origin': 'https://a.example'})
        nxt = hdr.redirect_request(req, None, 303, 'See Other', {}, 'https://b.example/y?code=1')
        assert nxt is not None and 'Authorization' not in nxt.headers and 'Origin' not in nxt.headers
        assert ops.main(['ai', 'clean-storage', '--confirm', 'ai',
                         '--token-file', str(tmp_path / 'missing-tok')]) == 1
        assert len(ssh_calls) == 1
    finally:
        fleet_srv.shutdown()
        acct_srv.shutdown()
        fleet_srv.server_close()
        acct_srv.server_close()
