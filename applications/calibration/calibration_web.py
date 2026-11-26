#!/usr/bin/env python3
"""Calibration screen: the cell's real-measurement requests, shown to a person who answers them (D-951, D-1004).

    python3 applications/calibration/calibration_web.py --store ~/.local/state/rosy/cell-requests \
        --account-config <receiver.json> --port 8776

Runs on the OMX control PC next to the engine, bound to 127.0.0.1 behind an HTTPS reverse proxy. The engine
`deploy/robot/omx/cell_requests.py` is the only writer of the store; this server only calls `cell_requests.answer`.
With an Account receiver config, every read needs a signed-in session of the site and an answer needs the site
capability `calibration.operate`; `by` is the session's name, never typed text. Without the config nobody can sign
in, so the screen is read-only (list and view, no answers).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import threading
import time
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "contracts/foundation", ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(extra) not in sys.path:
        sys.path.append(str(extra))
import cell_calibration_view  # noqa: E402
import cell_requests  # noqa: E402
import calibration_jobs  # noqa: E402

try:
    from core_common.protocol.account_client import AccountUnavailable, browser_session
except ImportError:  # no cryptography/pydantic: only the read-only screen can run
    class AccountUnavailable(Exception):
        pass

    browser_session = None

WEB = Path(__file__).resolve().parent / "web"
COMMON = ROOT / "shared" / "web"
OPERATE = "calibration.operate"
SESSION_COOKIE, FLOW_COOKIE = "rosy_calibration_account", "rosy_calibration_flow"
API = "/api/calibration/v1/requests"
ARM_RETURNS = {arm: f"/?arm={arm}" for arm in ("arm_s", "arm_a", "arm_b")}
PROFILES_API = "/api/calibration/v1/profiles"
JOBS_API = ("/api/calibration/status", "/api/calibration/jobs", "/api/calibration/assessments", "/api/calibration/incidents/")
ID = re.compile(r"[A-Za-z0-9_-]{1,96}")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
FRAME_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
FRAME_TIMEOUT_S = 1.5
FRAME_MAX_BYTES = 5 * 1024 * 1024
NOTE_MAX = 300
VALUE_MAX = 1e6  # a reading in mm or deg; anything larger is a typing slip, not a measurement
BODY_MAX = 4096
MEDIA = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'")
_answer_lock = threading.Lock()  # cell_requests.answer reads then writes; one answer per request even when two arrive at once


def _cookie(handler, name):
    jar = SimpleCookie()
    try:
        jar.load(handler.headers.get("Cookie", ""))
        return jar[name].value if name in jar else ""
    except CookieError:
        return ""


def _set_cookie(name, value, age):
    return ("Set-Cookie", f"{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}")


def summary(req: dict) -> dict:
    answer = req.get("answer") or {}
    return {key: req.get(key) for key in ("id", "kind", "item", "question", "status", "opened_at")} | {
        "verdict": answer.get("verdict") or answer.get("result"), "by": answer.get("by"), "answered_at": answer.get("at")}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store: Path, account=None, profiles_path: Path | None = None, jobs=None, **kwargs):
        self.store, self.account, self.profiles_path, self.jobs = store, account, profiles_path, jobs
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    # --- plumbing -----------------------------------------------------------------------------------------------
    def send(self, code, media, body: bytes, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", media)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if media.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, code, value, headers=()):
        self.send(code, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode(), headers)

    def host_ok(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.account:  # the HTTPS proxy forwards the public name
            allowed.add(urlsplit(self.account.callback).netloc)
        return self.headers.get("Host") in allowed

    def same_origin(self):
        if not self.account:
            return False
        url = urlsplit(self.account.callback)
        return self.headers.get("Origin") == f"{url.scheme}://{url.netloc}"

    def claims(self):
        """The signed-in session's claims, or None. Raises AccountUnavailable."""
        if not self.account:
            return None
        try:
            return self.account.resolve(_cookie(self, SESSION_COOKIE))
        except ValueError:
            return None

    def can_operate(self, claims):
        return bool(claims and claims.permits(self.account.resource, OPERATE))

    def by_name(self, claims):
        profile = self.account.profile(_cookie(self, SESSION_COOKIE))
        return profile["display_name"] if profile else claims.sub

    # --- routes -------------------------------------------------------------------------------------------------
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        if not self.host_ok():
            return self.json(403, {"error": "허용되지 않은 호스트입니다."})
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/account/"):
                return self.account_route(method, path)
            if self.jobs and path.startswith(JOBS_API):
                return calibration_jobs.handle(self, method, path)
            if path.startswith(PROFILES_API):
                return self.profiles_api(method, path)
            if path.startswith(API):
                return self.api(method, path)
        except AccountUnavailable:
            return self.json(503, {"error": "Account 서비스에 닿지 않습니다."})
        if method == "GET":
            return self.static(path)
        self.json(404, {"error": "없는 경로입니다."})

    def static(self, path):
        if path.startswith("/common/"):
            name = path.removeprefix("/common/")
            try:
                manifest = json.loads((COMMON / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
            except FileNotFoundError:
                return self.json(503, {"error": "배포본에 공통 화면 자산 목록이 없습니다."})
            if name in manifest and (COMMON / name).is_file():  # the manifest is the allowlist
                return self.send(200, f"{manifest[name]}; charset=utf-8", (COMMON / name).read_bytes())
            return self.json(404, {"error": "없는 파일입니다."})
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        file = WEB / name
        if "/" in name or name.startswith(".") or file.suffix not in MEDIA or not file.is_file():
            return self.json(404, {"error": "없는 파일입니다."})
        self.send(200, MEDIA[file.suffix], file.read_bytes())

    def account_route(self, method, path):
        headers, status, body = [], 200, {}
        try:
            if method == "GET" and path == "/api/account/session":
                if browser_session is None or not self.account:
                    body = {"enabled": False, "authenticated": False, "profile": None, "profile_url": None}
                    claims = None
                else:
                    body, claims = browser_session(self.account, _cookie(self, SESSION_COOKIE))
                body["can_operate"] = self.can_operate(claims)
            elif method == "GET" and path == "/api/account/login" and self.account:
                query = parse_qs(urlsplit(self.path).query, max_num_fields=8)
                arms = query.get("arm", [])
                destination = ARM_RETURNS.get(arms[0], "/") if len(arms) == 1 else "/"
                if destination != "/" and any(k in query for k in ("src_site", "dst_site", "task_id")):
                    keys = ["src_site", "dst_site"] + (["task_id"] if "task_id" in query else [])
                    if any(len(query.get(k, [])) != 1 or not (
                            calibration_jobs.TASK_REF.fullmatch(query[k][0]) if k == "task_id"
                            else re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,95}", query[k][0])) for k in keys):
                        return self.json(422, {"error": "Fleet 경로 링크의 칸과 작업 ID를 확인하세요."})
                    # Build an app-local target; the caller cannot choose a URL, origin or anchor.
                    destination += "&" + urlencode([(k, query[k][0]) for k in keys]) + "#route-" + arms[0]
                    flow, target = self.account.start(destination, destination_allowed=lambda url: url == destination)
                else:
                    flow, target = self.account.start(destination)
                headers = [_set_cookie(FLOW_COOKIE, flow, 600), ("Location", target)]
                status = 303
            elif method == "GET" and path == "/api/account/callback" and self.account:
                query = parse_qs(urlsplit(self.path).query, max_num_fields=8)
                if set(query) != {"state", "code"} or any(len(v) != 1 for v in query.values()):
                    raise ValueError("Invalid callback")
                session, target = self.account.finish(_cookie(self, FLOW_COOKIE), query["state"][0], query["code"][0])
                headers = [_set_cookie(SESSION_COOKIE, session, 2592000), _set_cookie(FLOW_COOKIE, "", 0),
                           ("Location", target)]
                status = 303
            elif method == "POST" and path == "/api/account/logout" and self.same_origin():
                headers = [_set_cookie(SESSION_COOKIE, "", 0)]
                self.account.logout(_cookie(self, SESSION_COOKIE))
            else:
                status, body = 403, {"error": "Account 접근이 거절되었습니다."}
        except ValueError:
            status, body = 401, {"error": "Account 세션이 거절되었습니다."}
        self.json(status, body, headers)

    def api(self, method, path):
        claims = self.claims()
        if self.account and not claims:
            return self.json(401, {"error": "Rosy Account로 로그인해야 합니다."})
        rest = path.removeprefix(API).strip("/")
        parts = rest.split("/") if rest else []
        if method == "GET" and not parts:
            rows = cell_requests.listing(self.store, everything=True)
            rows.sort(key=lambda r: r.get("opened_at", ""), reverse=True)
            return self.json(200, {"requests": [summary(r) for r in rows], "can_operate": self.can_operate(claims)})
        if not parts or not ID.fullmatch(parts[0]):
            return self.json(404, {"error": "없는 요청입니다."})
        try:
            req = cell_requests.load(parts[0], self.store)
        except (ValueError, OSError):
            return self.json(404, {"error": "없는 요청입니다."})
        if method == "GET" and len(parts) == 1:
            return self.json(200, req)
        if method == "GET" and parts[1:] == ["image"]:
            return self.image(req)
        if method == "POST" and parts[1:] == ["answer"]:
            return self.answer(req, claims)
        self.json(404, {"error": "없는 경로입니다."})

    def image(self, req):
        name = req.get("image")
        file = self.store / name if isinstance(name, str) else None
        # Only the file this request stored beside its json: a bare name with an image suffix, never a path.
        if (not file or name != Path(name).name or file.suffix.lower() not in IMAGE_TYPES or not file.is_file()
                or file.is_symlink()):
            return self.json(404, {"error": "그림이 없습니다."})
        self.send(200, IMAGE_TYPES[file.suffix.lower()], file.read_bytes())

    def answer(self, req, claims):
        if not self.account:
            return self.json(403, {"error": "Account 설정이 없어 읽기 전용입니다."})
        if not self.same_origin():
            return self.json(403, {"error": "등록된 출처에서만 답할 수 있습니다."})
        if not self.can_operate(claims):
            return self.json(403, {"error": f"{OPERATE} 권한이 필요합니다."})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= BODY_MAX:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self.json(422, {"error": "JSON 본문이 필요합니다."})
        value, result, note = body.get("value"), body.get("result"), body.get("note", "")
        if (not isinstance(note, str) or len(note) > NOTE_MAX
                or (value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                           or not abs(value) <= VALUE_MAX))):  # NaN, inf and 1<<4000 all fail
            return self.json(422, {"error": "값은 숫자, 메모는 300자 이하여야 합니다."})
        profile = self.account.profile(_cookie(self, SESSION_COOKIE))
        by = f"{profile['display_name']} ({claims.sub})" if profile else claims.sub
        try:
            with _answer_lock:
                done = cell_requests.answer(req["id"], by, value, result, note, self.store)
        except cell_requests.AlreadyAnswered as exc:
            return self.json(409, {"error": str(exc)})
        except ValueError as exc:
            return self.json(422, {"error": str(exc)})
        self.json(200, done)

    def _load_profiles(self) -> list[dict]:
        return cell_calibration_view.load_profile_registry(self.profiles_path)

    def profiles_api(self, method: str, path: str):
        claims = self.claims()
        if self.account and not claims:
            return self.json(401, {"error": "Rosy Account로 로그인해야 합니다."})
        if method != "GET":
            return self.json(405, {"error": "읽기 전용 경로입니다."})
        try:
            entries = self._load_profiles()
        except (OSError, ValueError) as exc:
            return self.json(500, {"error": f"프로파일 레지스트리 오류: {exc}"})

        rest = path.removeprefix(PROFILES_API).strip("/")
        if not rest:
            return self.json(200, cell_calibration_view.build_bundle(entries))
        parts = rest.split("/")
        if len(parts) == 3 and ID.fullmatch(parts[0]) and parts[1] == "frame" and parts[2] in ("reference", "live"):
            entry = next((e for e in entries if e.get("id") == parts[0]), None)
            if entry is None:
                return self.json(404, {"error": "없는 프로파일입니다."})
            return self._serve_profile_frame(entry, parts[2])
        return self.json(404, {"error": "없는 경로입니다."})

    def _send_frame(self, entry, source, body, media, source_stamp=None):
        # The commissioning viewer accepts source age -0.25..2 seconds. Recheck after registration.
        try:
            stamp = float(source_stamp)
        except (TypeError, ValueError):
            stamp = None
        fresh = stamp is not None and -0.25 <= time.time() - stamp <= 2.0
        details = (source == "live" and getattr(self, "headers", {}).get("Accept") == "application/vnd.rosy.fixture-frame+json")
        if source == "reference" or fresh:
            if details:
                body, binding = cell_calibration_view.bind_frame(entry, source, body, include_fixtures=True)
            else:
                body, binding = cell_calibration_view.bind_frame(entry, source, body)
            if binding["status"] == "aligned":
                media = "image/jpeg"
        else:
            binding = {"status": "unverified"}
        remaining = max(0.0, min(2.0, stamp + 2.0 - time.time())) if fresh else 0.0
        headers = [("X-Rosy-Frame-Binding", binding["status"]),
                   ("X-Rosy-Frame-Lifetime-Ms", str(int(remaining * 1000)))]
        for name, key in (("Generation", "generation"), ("Reference-Sha256", "reference_sha256"),
                          ("Shift-Px", "max_px"), ("Inliers", "inliers")):
            if binding.get(key) is not None:
                headers.append((f"X-Rosy-Frame-{name}", str(binding[key])))
        if details:
            return self.json(200, {"media": media, "image": base64.b64encode(body).decode("ascii"),
                                   "fixture_observation": binding.get("fixture_observation")}, headers)
        return self.send(200, media, body, headers)

    def _serve_profile_frame(self, entry: dict, source: str):
        target = cell_calibration_view.resolve_frame_target(entry, source)
        if target.get("kind") == "file":
            f = target.get("path")
            if not f or not f.is_file() or f.suffix.lower() not in IMAGE_TYPES:
                return self.json(404, {"error": "기준 프레임이 없습니다."})
            with f.open("rb") as stream:
                stamp = os.fstat(stream.fileno()).st_mtime
                return self._send_frame(entry, source, stream.read(), IMAGE_TYPES[f.suffix.lower()], stamp)
        if target.get("kind") == "url":
            url = target.get("url")
            if not url:
                return self.json(404, {"error": "카메라 주소가 설정되지 않았습니다."})
            if not cell_calibration_view.is_allowed_frame_url(url):
                return self.json(403, {"error": "허용되지 않은 카메라 주소입니다."})
            try:
                with urlopen(url, timeout=FRAME_TIMEOUT_S) as resp:  # noqa: S310 - loopback URL validated above
                    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                    if ctype not in FRAME_CONTENT_TYPES:
                        return self.json(502, {"error": "카메라 응답 형식이 올바르지 않습니다."})
                    body = resp.read(FRAME_MAX_BYTES + 1)
                    if len(body) > FRAME_MAX_BYTES:
                        return self.json(502, {"error": "카메라 프레임 크기 상한을 넘었습니다."})
                    return self._send_frame(entry, source, body, "image/jpeg" if ctype == "image/jpg" else ctype,
                                            resp.headers.get("X-Source-Stamp"))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                return self.json(503, {"error": "카메라 프레임에 닿지 않습니다."})
        return self.json(404, {"error": "없는 프레임 종류입니다."})


def _load_jobs(cells: Path | None, **hooks):
    if not cells:
        return None
    try:
        return calibration_jobs.Jobs(cells, **hooks)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"calibration jobs disabled ({cells}): {exc}", file=sys.stderr)
        return None


def make_server(store: Path, port: int = 8776, account=None, host: str = "127.0.0.1",
                profiles_path: Path | None = None, cells: Path | None = None, **hooks) -> ThreadingHTTPServer:
    if account and not account.resource.startswith("site:"):
        raise ValueError("Calibration Account requires a site resource")
    return ThreadingHTTPServer(
        (host, port),
        partial(Handler, store=Path(store), account=account, profiles_path=profiles_path,
                jobs=_load_jobs(cells, **hooks)),
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--store", type=Path, default=None, help="request store (default ROSY_CELL_REQUESTS)")
    p.add_argument("--port", type=int, default=8776)
    p.add_argument("--account-config", type=Path, help="Rosy Account receiver json; without it the screen is read-only")
    p.add_argument("--profiles", type=Path, default=None,
                   help="optional JSON registry of arm profiles for 모눈종이 view (default ROSY_CALIBRATION_PROFILES)")
    p.add_argument("--cells", type=Path, help="cells.json (tools, python, work, arms): turns on status, jobs, assessments (D-1035)")
    args = p.parse_args(argv)
    profiles = args.profiles
    if profiles is None:
        env_p = os.environ.get("ROSY_CALIBRATION_PROFILES", "").strip()
        profiles = Path(env_p) if env_p else None
    account = None
    if args.account_config:
        from core_common.protocol.account_client import load_account_client
        account = load_account_client(args.account_config, destinations=("/", *ARM_RETURNS.values()))
    server = make_server(args.store or cell_requests.store(), args.port, account, profiles_path=profiles, cells=args.cells)

    def retry():  # a logout that could not reach Account is retried until it does
        while not stop.wait(20):
            try:
                account.retry_revocations()
            except (AccountUnavailable, ValueError):
                pass

    stop = threading.Event()
    if account:
        threading.Thread(target=retry, daemon=True).start()
    print(f"calibration http://127.0.0.1:{server.server_port}/  {'Account login' if account else 'read-only'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
