#!/usr/bin/env python3
"""Log in to every Account-backed app with one read-only test account, the way a browser does.

usage: account_login_check.py <config.json> [--insecure] [app ...]

The config file stays out of the repository (private/). It holds the test account and the app list:
  {"issuer": "https://...", "login": "...", "password": "...",
   "apps": [{"name": "...", "start": "https://.../login", "session": "https://.../session"}]}
Per app: GET start (must redirect to the issuer) -> POST issuer login (204) -> follow authorize and the
app callback -> GET session (200). One PASS/FAIL line per app; exit 1 if any app fails. Only the stdlib.
"""
import http.cookiejar
import json
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

MAX_HOPS = 6


class _SeeEveryHop(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx surfaces as HTTPError so every hop is visible


def _opener(insecure):
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    return urllib.request.build_opener(
        _SeeEveryHop, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=context))


def _send(opener, request):
    """(status, headers, body) for any response, including 3xx and 4xx."""
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.headers, response.read(300).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read(300).decode("utf-8", "replace")


def check_app(app, config, insecure=False):
    """Return (ok, detail) for one app."""
    issuer, opener = config["issuer"], _opener(insecure)
    try:
        status, headers, _ = _send(opener, urllib.request.Request(app["start"]))
        url = urljoin(app["start"], headers.get("Location", ""))
        if not url.startswith(issuer + "/"):
            return False, f"start {status} did not go to the Account issuer"
        body = json.dumps({"login": config["login"], "password": config["password"], "remember": False})
        status, _, text = _send(opener, urllib.request.Request(
            issuer + "/api/fleet/auth/login", body.encode(), {"Content-Type": "application/json", "Origin": issuer}))
        if status != 204:
            return False, f"account login {status}"
        for _ in range(MAX_HOPS):  # authorize -> app callback -> app page
            status, headers, text = _send(opener, urllib.request.Request(url))
            if status not in (301, 302, 303, 307) or "/login" in headers.get("Location", ""):
                break
            url = urljoin(url, headers["Location"])
            if urlsplit(url).netloc not in {urlsplit(issuer).netloc, urlsplit(app["session"]).netloc}:
                break
        if status >= 400:
            return False, f"callback chain ended {status} at {urlsplit(url).path}"
        status, _, text = _send(opener, urllib.request.Request(app["session"]))
        # Some apps answer 200 with authenticated:false when the callback failed (2026-11-13 Calibration).
        try:
            signed_in = json.loads(text).get("authenticated", True) is not False
        except (ValueError, AttributeError):
            signed_in = True
        return status == 200 and signed_in, f"session {status}" + ("" if signed_in else " not authenticated")
    except (OSError, ValueError, KeyError) as error:
        return False, f"{type(error).__name__}: {str(error)[:100]}"


def main(argv):
    insecure = "--insecure" in argv
    args = [item for item in argv[1:] if item != "--insecure"]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        config = json.load(handle)
    only, failed = set(args[1:]), False
    for app in config["apps"]:
        if only and app["name"] not in only:
            continue
        ok, detail = check_app(app, config, insecure)
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'} {app['name']} ({detail})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
