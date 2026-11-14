#!/usr/bin/env python3
"""Log in to every Account-backed app with one read-only test account, the way a browser does.

usage: account_login_check.py <config.json> [--insecure] [--status FILE] [app ...]

The config file stays out of the repository (private/). It holds the test account and the app list:
  {"issuer": "https://...", "login": "...", "password": "...",
   "apps": [{"name": "...", "start": "https://.../login", "session": "https://.../session"}]}
--status FILE writes {"time", "apps": {name: bool}, "configured": [every app name of the config]} (names and verdicts
only, never credentials or details; a run for a few apps shows as partial against "configured") for
rosy-host-guard, which alerts through the operator webhook on a failure streak and when the file stops being renewed.
Per app: GET start (must redirect to the issuer) -> POST issuer login (204) -> follow authorize and the
app callback -> GET session (200). One PASS/FAIL line per app; exit 1 if any app fails. Only the stdlib.
"""
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

MAX_HOPS = 6
SESSION_LIMIT = 64 * 1024  # a session body that fills this is cut off and cannot be judged
IDENTITY_KEYS = ("user_id", "account_id", "principal_id")


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


def _send(opener, request, limit=300):
    """(status, headers, body bytes, at most `limit`) for any response, including 3xx and 4xx."""
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.headers, response.read(limit)
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read(limit)


def session_verdict(status, raw):
    """(ok, detail): PASS needs positive evidence of a signed-in user, never just the absence of a refusal."""
    if status != 200:
        return False, f"session {status}"
    if len(raw) >= SESSION_LIMIT:
        return False, "session body reached the 64 KiB read limit"
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return False, "session 200 body is not JSON"
    if not isinstance(body, dict):
        return False, "session 200 body is not a JSON object"
    if body.get("authenticated") is False:
        return False, "session 200 not authenticated"
    if body.get("authenticated") is True or any(isinstance(body.get(key), str) and body[key] for key in IDENTITY_KEYS):
        return True, "session 200"
    return False, "session 200 without proof of a signed-in user"


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
        status, _, raw = _send(opener, urllib.request.Request(app["session"]), SESSION_LIMIT)
        # Some apps answer 200 with authenticated:false when the callback failed (2026-11-13 Calibration).
        return session_verdict(status, raw)
    except (OSError, ValueError, KeyError) as error:
        return False, f"{type(error).__name__}: {str(error)[:100]}"


def write_status(path, results, configured):
    """Atomic and world-readable (the guard runs as another user); results is {app name: ok}."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"time": int(time.time()), "apps": results, "configured": configured}, handle)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv):
    insecure = "--insecure" in argv
    args = [item for item in argv[1:] if item != "--insecure"]
    status = None
    if "--status" in args:
        at = args.index("--status")
        status, args = (args[at + 1] if at + 1 < len(args) else None), args[:at] + args[at + 2:]
        if status is None:
            print("--status needs a file", file=sys.stderr)
            return 2
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        config = json.load(handle)
    only, failed, checked, results = set(args[1:]), False, 0, {}
    for app in config["apps"]:
        if only and app["name"] not in only:
            continue
        ok, detail = check_app(app, config, insecure)
        failed |= not ok
        checked += 1
        results[app["name"]] = ok
        print(f"{'PASS' if ok else 'FAIL'} {app['name']} ({detail})")
    if not checked:
        print("no app was checked (empty app list or no name matched)", file=sys.stderr)
        return 2
    if status:
        write_status(status, results, [app["name"] for app in config["apps"]])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
