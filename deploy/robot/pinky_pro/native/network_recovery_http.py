"""Bounded, AP-address-only HTTPS transport and accessible network recovery form."""
from __future__ import annotations

import hashlib
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import stat
import threading
from urllib.parse import parse_qs, urlsplit

from network_recovery import RecoveryError

MAX_BODY = 4096
IO_SECONDS = 5
COOKIE = "__Host-rosy-recovery"
ASSETS = {"tokens.css", "components.css"}

PAGE = r'''<!doctype html>
<html lang="ko" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ROSY Wi-Fi 복구</title>
<link rel="stylesheet" href="/common/tokens.css"><link rel="stylesheet" href="/common/components.css">
<style nonce="{nonce}">
*{box-sizing:border-box}body{margin:0;background:var(--surface-canvas);color:var(--ink);font-family:var(--body);font-size:var(--text-body);line-height:var(--leading-copy)}
main{max-width:42rem;margin:auto;padding:var(--space-5)}h1{font-size:var(--text-display)}h2{font-size:var(--text-title)}
section,form{margin-block:var(--space-5)}label{display:block;margin-block:var(--space-3)}
.ui-field{width:100%}button{min-height:var(--target-primary);padding:var(--inset-button-primary);border:0;border-radius:var(--radius-button);background:var(--button-primary-bg);color:var(--button-primary-ink);font:inherit;cursor:pointer}
button:disabled{opacity:var(--disabled-opacity);cursor:default}button:focus-visible,a:focus-visible{outline:var(--focus-ring-width) solid var(--focus-ring);outline-offset:var(--focus-ring-offset-outer)}
code,p{overflow-wrap:anywhere}code{font-family:var(--mono)}[hidden]{display:none!important}
.ui-check{min-height:var(--target-secondary)}#message{min-height:var(--target-secondary)}
</style></head><body><main>
<h1>Wi-Fi 연결 복구</h1>
<p>로봇의 초기 연결을 복구합니다. 먼저 이 장치의 인증서를 확인하세요.</p>
<section aria-labelledby="trust-title"><h2 id="trust-title">장치 확인</h2>
<p>로봇 LCD 또는 물리 콘솔의 장치명과 전체 SHA-256 지문을 브라우저 인증서 보기에서 비교하세요.
일치하면 이 장치 인증서만 운영 PC에 등록한 뒤 복구 코드를 입력하세요.</p>
<p>이 페이지의 지문은 비교용입니다. 반드시 물리 화면과 확인하세요.</p><code id="fingerprint">{fingerprint}</code></section>
<p id="message" role="status" tabindex="-1" aria-live="polite"></p>
<form id="login" autocomplete="off"><label class="ui-check"><input id="trusted" type="checkbox" required> 물리 화면과 전체 지문을 확인하고 이 장치 인증서를 등록했습니다</label>
<label for="code">화면에 표시된 복구 코드</label><input class="ui-field" id="code" type="password" autocomplete="off" maxlength="9" required aria-describedby="code-help">
<p id="code-help">8자리 코드 · 발급 후 10분 · 한 번만 사용 · 5회 실패하면 물리 콘솔에서 새 코드를 요청하세요.</p>
<button type="submit">복구 코드 확인</button></form>
<form id="network" hidden autocomplete="off"><label for="ssid">현장 Wi-Fi 이름 (SSID)</label>
<input class="ui-field" id="ssid" maxlength="32" autocomplete="off" required>
<label for="psk">Wi-Fi 비밀번호</label><input class="ui-field" id="psk" type="password" minlength="8" maxlength="63" autocomplete="new-password" required>
<p>연결을 적용하면 현재 복구 AP가 잠시 끊길 수 있습니다. 실패하면 같은 AP로 다시 접속해 결과를 확인하세요.</p>
<button id="review" type="submit">연결 내용 확인</button>
<section id="confirm" hidden aria-labelledby="confirm-title"><h2 id="confirm-title">이 Wi-Fi로 연결할까요?</h2>
<p id="target"></p><button id="apply" type="button">Wi-Fi 연결 적용</button> <button id="cancel" type="button">취소</button></section></form>
<section id="job" hidden><h2>연결 작업</h2><p id="job-id"></p><p id="job-state" role="status"></p>
<button id="refresh" type="button">결과 다시 확인</button> <button id="resume" type="button" hidden>접수된 연결 적용</button></section>
<noscript>이 복구 화면에는 JavaScript가 필요합니다. 운영 PC 브라우저에서 허용한 뒤 다시 여세요.</noscript>
</main><script nonce="{nonce}">
const el=id=>document.getElementById(id);let csrf='',job=sessionStorage.getItem('rosy-recovery-job')||'';
const labels={prepared:'작업 접수됨 · 연결 적용 대기',activating:'Wi-Fi 연결 확인 중',committing:'검증한 연결 저장 중',committed:'연결 저장 완료',rolling_back:'기존 연결 복원 중',rolled_back:'연결 실패 · 기존 연결 복원됨',held:'연결 복구 보류 · 물리 콘솔에서 확인 필요',rejected:'요청 거절 · 로봇이 정지한 정비 상태인지 확인하세요.',busy:'다른 연결 작업이 진행 중입니다. 잠시 후 결과를 확인하세요.'};
const errors={code_invalid:'복구 코드가 맞지 않습니다. 화면의 코드를 다시 확인하세요.',code_expired:'복구 코드가 만료되었습니다. 물리 콘솔에서 새 코드를 요청하세요.',code_unavailable:'이 코드는 이미 사용되었거나 5회 실패했습니다. 물리 콘솔에서 새 코드를 요청하세요.',session_expired:'복구 세션이 만료되었습니다. 물리 콘솔에서 새 코드를 요청하세요.',image_required:'이 장치에는 새 복구 지원 이미지가 필요합니다.',network_input_invalid:'Wi-Fi 이름은 UTF-8 32바이트 이내, 비밀번호는 8~63자여야 합니다.',network_unavailable:'네트워크 작업을 확인할 수 없습니다. 연결 후 결과를 다시 확인하세요.',recovery_unavailable:'복구 화면이 닫혔습니다. 로봇 화면의 현재 연결 안내를 확인하세요.'};
function message(text){el('message').textContent=text;el('message').focus()}
async function api(path,body){let response;try{response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify({...body,csrf}):undefined,cache:'no-store'})}catch{throw Error('연결이 끊겼습니다. 같은 복구 AP에 다시 접속한 뒤 결과를 확인하세요.')}const data=await response.json();if(!response.ok)throw Error(errors[data.error]||'요청을 처리하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요.');return data}
function showJob(data){el('job').hidden=false;el('job-id').textContent='작업 ID: '+job;el('job-state').textContent=labels[data.state]||'결과 확인 대기';el('resume').hidden=data.state!=='prepared'}
async function refresh(){try{showJob(await api('/network/status?request_id='+encodeURIComponent(job)))}catch(error){message(error.message)}}
async function ready(data){csrf=data.csrf;el('login').hidden=true;el('network').hidden=false;if(!data.write_available){el('review').disabled=true;message(errors.image_required)}if(job)await refresh()}
el('login').onsubmit=async event=>{event.preventDefault();const code=el('code').value;el('code').value='';try{await ready(await api('/session',{code}));if(!job)message('복구 코드가 확인되었습니다. 현장 Wi-Fi 정보를 입력하세요.')}catch(error){message(error.message)}};
el('network').onsubmit=event=>{event.preventDefault();el('target').textContent='Wi-Fi 이름: '+el('ssid').value;el('confirm').hidden=false;el('apply').focus()};
el('cancel').onclick=()=>{el('confirm').hidden=true;el('review').focus()};
el('apply').onclick=async()=>{job=crypto.randomUUID();sessionStorage.setItem('rosy-recovery-job',job);el('apply').disabled=true;const psk=el('psk').value;el('psk').value='';try{showJob(await api('/network/connect',{ssid:el('ssid').value,psk,request_id:job}));message('작업이 접수되었습니다. AP가 끊기면 다시 연결한 뒤 결과를 확인하세요.')}catch(error){showJob({});message(error.message)}finally{el('apply').disabled=false;el('confirm').hidden=true}};
el('refresh').onclick=refresh;el('resume').onclick=async()=>{try{showJob(await api('/network/start',{request_id:job}));message('접수된 연결을 적용합니다. 잠시 후 결과를 다시 확인하세요.')}catch(error){message(error.message)}};
api('/session').then(ready).catch(()=>{});
</script></body></html>'''


class RecoveryHTTP:
    def __init__(self, coordinator, *, fingerprint: str, assets_dir: Path | None = None):
        self.coordinator = coordinator
        self.fingerprint = fingerprint
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.after_response = None

    def response(self, method: str, target: str, headers, body: bytes):
        self.after_response = None
        nonce = secrets.token_urlsafe(24)
        response_headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; connect-src 'self'; style-src 'self' 'nonce-" + nonce
                + "'; script-src 'nonce-" + nonce + "'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}
        def result(status, data):
            return status, response_headers, json.dumps(data).encode("utf-8")
        state = self.coordinator.active_state()
        if state is None:
            return result(503, {"error": "recovery_unavailable"})
        authority = f"{state.ap_address}:8443"
        if headers.get("Host") != authority:
            return result(403, {"error": "origin_invalid"})
        if method == "POST" and headers.get("Origin") != "https://" + authority:
            return result(403, {"error": "origin_invalid"})
        if len(body) > MAX_BODY:
            return result(413, {"error": "body_too_large"})
        try:
            route = urlsplit(target)
            cookie = SimpleCookie()
            cookie.load(headers.get("Cookie", ""))
            session = cookie[COOKIE].value if COOKIE in cookie else ""
            if method == "GET":
                if route.path == "/":
                    response_headers["Content-Type"] = "text/html; charset=utf-8"
                    page = PAGE.replace("{nonce}", nonce).replace("{fingerprint}", escape(self.fingerprint))
                    return 200, response_headers, page.encode("utf-8")
                if route.path == "/status":
                    return result(200, {"active": True, "write_available": state.handoff_supported})
                if route.path == "/session":
                    return result(200, self.coordinator.session_info(session))
                if route.path == "/network/status":
                    query = parse_qs(route.query, max_num_fields=1)
                    return result(200, self.coordinator.status(session, query.get("request_id", [None])[0]))
                if route.path.startswith("/common/") and route.path[8:] in ASSETS and self.assets_dir:
                    response_headers["Content-Type"] = "text/css; charset=utf-8"
                    return 200, response_headers, (self.assets_dir / route.path[8:]).read_bytes()
            if method == "POST":
                if headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    return result(415, {"error": "content_type_invalid"})
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError()
                if route.path == "/session":
                    session, csrf = self.coordinator.exchange(data.get("code"))
                    response_headers["Set-Cookie"] = f"{COOKIE}={session}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=600"
                    return result(200, {"csrf": csrf, "write_available": state.handoff_supported})
                if route.path in {"/network/connect", "/network/start"}:
                    csrf, request_id = data.get("csrf", ""), data.get("request_id")
                    if route.path == "/network/connect":
                        accepted = self.coordinator.connect(session, csrf, data.get("ssid"), data.get("psk"), request_id)
                    else:
                        self.coordinator.authenticate(session, csrf)
                        accepted = self.coordinator.status(session, request_id)
                    if accepted.get("state") == "prepared":
                        self.after_response = lambda: self.coordinator.start(session, csrf, request_id)
                    return result(202 if accepted.get("state") == "prepared" else 200, accepted)
            return result(404, {"error": "not_found"})
        except RecoveryError as error:
            return result(403 if str(error) == "csrf_invalid" else 400, {"error": str(error)})
        except (ValueError, TypeError, KeyError):
            return result(400, {"error": "request_invalid"})
        except Exception:
            return result(503, {"error": "recovery_unavailable"})


def handler(app):
    class RecoveryHandler(BaseHTTPRequestHandler):
        def handle(self):
            self.connection.settimeout(IO_SECONDS)
            def expire():
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            timer = threading.Timer(IO_SECONDS, expire)
            timer.daemon = True
            timer.start()
            try:
                super().handle()
            finally:
                timer.cancel()

        def _respond(self):
            self.close_connection = True
            if any(len(self.headers.get_all(name, [])) > 1 for name in ("Host", "Origin", "Content-Length")):
                self.send_error(400)
                return
            length = self.headers.get("Content-Length", "0")
            if self.headers.get("Transfer-Encoding") or not length.isascii() or not length.isdecimal():
                self.send_error(400)
                return
            if len(length) > 6 or int(length) > MAX_BODY:
                self.send_error(413)
                return
            try:
                body = self.rfile.read(int(length))
                if len(body) != int(length):
                    return
                status, headers, content = app.response(self.command, self.path, self.headers, body)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(content)
                self.wfile.flush()
                if app.after_response:
                    app.after_response()
            except (OSError, RecoveryError):
                return

        do_GET = do_POST = _respond

        def log_message(self, *_args):
            pass
    return RecoveryHandler


class RecoveryServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(IO_SECONDS)
        try:
            return self.tls.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise OSError("tls_unavailable") from None

    def handle_error(self, *_args):
        pass


def create_server(coordinator, certificate: Path, private_key: Path, *, assets_dir: Path | None = None,
                  server_factory=RecoveryServer):
    state = coordinator.active_state()
    if state is None:
        raise ValueError("recovery_unavailable")
    descriptors = []
    try:
        for path in (certificate, private_key):
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise ValueError("tls_unavailable")
        pem = os.read(descriptors[0], 65537).decode("ascii")
        fingerprint = ":".join(f"{byte:02X}" for byte in hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(*(f"/proc/self/fd/{fd}" for fd in descriptors))
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    app = RecoveryHTTP(coordinator, fingerprint=fingerprint, assets_dir=assets_dir)
    server = server_factory((state.ap_address, 8443), handler(app))
    server.tls = context
    server.timeout = 0.5
    return server


def serve(coordinator, certificate: Path, private_key: Path, *, assets_dir: Path):
    """Exit and discard sessions on AP/identity/CORE transition; never bind again implicitly."""
    try:
        with create_server(coordinator, certificate, private_key, assets_dir=assets_dir) as server:
            while coordinator.active_state() is not None:
                server.handle_request()
    finally:
        coordinator.close()
