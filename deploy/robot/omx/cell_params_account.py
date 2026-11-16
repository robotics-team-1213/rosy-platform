"""ROSY Core Account session and authorization helpers for `cell_params_web.py`."""
from __future__ import annotations

from http.cookies import CookieError, SimpleCookie
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

ACCOUNT_COOKIE, FLOW_COOKIE = "rosy_cell_params_account", "rosy_cell_params_flow"
FOUNDATION = Path(__file__).resolve().parents[3] / "contracts" / "foundation"
if FOUNDATION.is_dir() and str(FOUNDATION) not in sys.path:
    sys.path.append(str(FOUNDATION))
try:
    from core_common.protocol.account_client import AccountUnavailable, browser_session, load_account_client
except ImportError:  # environments without cryptography stay local-only
    class AccountUnavailable(Exception):
        pass

    browser_session = load_account_client = None


def cookie_value(handler, name: str) -> str:
    jar = SimpleCookie()
    try:
        jar.load(handler.headers.get("Cookie", ""))
        return jar[name].value if name in jar else ""
    except CookieError:
        return ""


def set_cookie_header(name: str, value: str, age: int) -> tuple[str, str]:
    return ("Set-Cookie", f"{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}")


def same_callback_origin(handler, account) -> bool:
    if not account:
        return False
    cb = urlsplit(account.callback)
    return handler.headers.get("Origin") == f"{cb.scheme}://{cb.netloc}"


def handle_account_route(handler, account, method: str, path: str, query_path: str):
    headers, status, body = [], 200, {}
    try:
        if method == "GET" and path == "/api/account/session":
            if account and browser_session:
                body, _ = browser_session(account, cookie_value(handler, ACCOUNT_COOKIE))
            else:
                body = {"enabled": False, "authenticated": False, "profile": None, "profile_url": None}
        elif method == "GET" and path == "/api/account/login" and account:
            flow, target = account.start("/")
            headers, status = [set_cookie_header(FLOW_COOKIE, flow, 600), ("Location", target)], 303
        elif method == "GET" and path == "/api/account/callback" and account:
            query = parse_qs(urlsplit(query_path).query, max_num_fields=8)
            if set(query) != {"state", "code"} or any(len(v) != 1 for v in query.values()):
                raise ValueError("Invalid callback")
            sess, target = account.finish(cookie_value(handler, FLOW_COOKIE), query["state"][0], query["code"][0])
            headers = [set_cookie_header(ACCOUNT_COOKIE, sess, 2592000), set_cookie_header(FLOW_COOKIE, "", 0), ("Location", target)]
            status = 303
        elif method == "POST" and path == "/api/account/logout" and same_callback_origin(handler, account):
            headers = [set_cookie_header(ACCOUNT_COOKIE, "", 0)]
            account.logout(cookie_value(handler, ACCOUNT_COOKIE))
        else:
            status, body = 403, {"error": "Account 접근이 거절되었습니다."}
    except AccountUnavailable:
        status, body = 503, {"error": "Account 서비스에 닿지 않습니다."}
    except ValueError:
        status, body = 401, {"error": "Account 세션이 거절되었습니다."}
    return handler.reply(status, body, headers=headers)


def authorize_request(handler, account, capabilities=None):
    """Return (error_tuple | None, access_token | None) for a request when `account` is configured."""
    if not account:
        return None, None
    if capabilities is not None and not same_callback_origin(handler, account):
        return (403, {"error": "등록된 출처에서만 변경할 수 있습니다."}), None
    try:
        claims, token = account.access_token_for(cookie_value(handler, ACCOUNT_COOKIE))
    except AccountUnavailable:
        return (503, {"error": "Account 서비스에 닿지 않습니다."}), None
    if claims is None:
        return (401, {"error": "ROSY Account 로그인이 필요합니다."}), None
    if capabilities and not any(claims.permits(account.resource, cap) for cap in capabilities):
        return (403, {"error": "운영 권한이 필요합니다."}), None
    return None, token
