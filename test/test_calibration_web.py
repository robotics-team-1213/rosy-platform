"""Calibration screen server (D-1004): read-only without Account, session and capability gates, `by` from the session."""
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications/calibration"))
import calibration_web as web  # noqa: E402
import cell_requests as cr  # noqa: E402

REQUEST = dict(id="belt-end-1", kind="measure", item="belt", question="axis to belt end", how=["tape"],
               candidates=dict(sim=156, camera=215), unit="mm", tolerance=20, means=dict(sim="design", camera="camera"))
ORIGIN = "https://cal.test"


class Account:
    callback = ORIGIN + "/api/account/callback"
    resource = "site:one"
    profile_url = "https://account.test/console/profile"

    def __init__(self):
        self.operate = True

    def resolve(self, cookie):
        if cookie != "valid":
            return None
        return SimpleNamespace(sub="acct-1", sid="family", rev=1, aud="site:one", grants=[],
                               permits=lambda resource, cap: resource == "site:one" and (cap == "calibration.operate") and self.operate)

    def profile(self, cookie):
        return {"account_id": "acct-1", "login": "kim", "display_name": "Kim"}

    def retry_revocations(self):
        pass


def call(url, path, *, cookie="", origin="", body=None, method=None):
    headers = {k: v for k, v in (("Cookie", f"{web.SESSION_COOKIE}={cookie}" if cookie else ""), ("Origin", origin)) if v}
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url + path, data=data, headers=headers, method=method), timeout=5) as r:
            return r.status, r.read()
    except HTTPError as error:
        return error.code, error.read()


@pytest.fixture
def store(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x89PNG-bytes")
    cr.open_request(REQUEST, tmp_path / "pic.png", root=tmp_path / "store")
    (tmp_path / "secret.png").write_bytes(b"secret")
    return tmp_path / "store"


def serve(store, account):
    server = web.make_server(store, 0, account)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def open_screen(store):
    server, url = serve(store, None)
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def account_screen(store):
    account = Account()
    server, url = serve(store, account)
    yield url, account
    server.shutdown()
    server.server_close()


def test_without_account_it_lists_and_shows_but_never_answers(open_screen, store):
    status, body = call(open_screen, web.API)
    rows = json.loads(body)
    assert status == 200 and rows["can_operate"] is False and rows["requests"][0]["id"] == "belt-end-1"
    assert json.loads(call(open_screen, web.API + "/belt-end-1")[1])["candidates"] == REQUEST["candidates"]
    assert call(open_screen, web.API + "/belt-end-1/image")[1] == b"\x89PNG-bytes"
    assert json.loads(call(open_screen, "/api/account/session")[1])["enabled"] is False
    status, _ = call(open_screen, web.API + "/belt-end-1/answer", origin=ORIGIN, body={"value": 160})
    assert status == 403 and cr.load("belt-end-1", store)["status"] == "open"
    assert call(open_screen, "/")[0] == 200 and call(open_screen, "/common/tokens.css")[0] == 200


def test_page_and_assets_are_served_but_not_arbitrary_files(open_screen):
    assert call(open_screen, "/app.js")[0] == 200
    for path in ("/common/../calibration_web.py", "/common/AGENTS.md", "/../calibration_web.py", "/.git"):
        assert call(open_screen, path)[0] == 404


def test_host_header_must_be_local(open_screen):
    request = Request(open_screen + web.API, headers={"Host": "evil.test"})
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 403


def test_with_account_reading_needs_a_session(account_screen):
    url, _ = account_screen
    assert call(url, web.API)[0] == 401 and call(url, web.API + "/belt-end-1")[0] == 401
    assert call(url, web.API + "/belt-end-1/image")[0] == 401
    assert call(url, web.API, cookie="valid")[0] == 200


def test_answer_needs_session_origin_and_capability(account_screen, store):
    url, account = account_screen
    path, body = web.API + "/belt-end-1/answer", {"value": 212}
    assert call(url, path, origin=ORIGIN, body=body)[0] == 401
    assert call(url, path, cookie="valid", origin="https://evil.test", body=body)[0] == 403
    assert call(url, path, cookie="valid", body=body)[0] == 403
    account.operate = False
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body=body)
    assert status == 403 and "calibration.operate" in json.loads(text)["error"]
    assert json.loads(call(url, web.API, cookie="valid")[1])["can_operate"] is False
    assert cr.load("belt-end-1", store)["status"] == "open"


def test_answer_is_recorded_by_the_engine_with_the_session_name(account_screen, store):
    url, _ = account_screen
    path = web.API + "/belt-end-1/answer"
    # a typed `by` is ignored: the name comes from the session
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body={"value": 212, "note": "tape", "by": "someone else"})
    done = json.loads(text)
    assert status == 200 and done["answer"]["verdict"] == "camera" and done["answer"]["by"] == "Kim (acct-1)"
    assert cr.load("belt-end-1", store)["answer"]["note"] == "tape"
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body={"value": 160})
    assert status == 409 and "already" in json.loads(text)["error"]
    assert cr.load("belt-end-1", store)["answer"]["value"] == 212.0


@pytest.mark.parametrize("body", [{}, {"value": "x"}, {"value": True}, {"value": 1, "note": "n" * 301}, {"result": "pass"}])
def test_bad_answers_are_422_and_leave_the_request_open(account_screen, store, body):
    url, _ = account_screen
    assert call(url, web.API + "/belt-end-1/answer", cookie="valid", origin=ORIGIN, body=body)[0] == 422
    assert cr.load("belt-end-1", store)["status"] == "open"


def test_unknown_or_hostile_ids_and_images_are_refused(open_screen, store):
    for rid in ("nope", "..%2Fsecret", "a.b", "%2e%2e"):
        assert call(open_screen, f"{web.API}/{rid}")[0] == 404
    # a request whose stored image names a path outside the store gets no file
    data = cr.load("belt-end-1", store)
    data["image"] = "../secret.png"
    (store / "belt-end-1.json").write_text(json.dumps(data), encoding="utf-8")
    assert call(open_screen, web.API + "/belt-end-1/image")[0] == 404
    data["image"] = "belt-end-1.json"
    (store / "belt-end-1.json").write_text(json.dumps(data), encoding="utf-8")
    assert call(open_screen, web.API + "/belt-end-1/image")[0] == 404


def test_check_request_takes_pass_or_fail(account_screen, store):
    url, _ = account_screen
    cr.open_request(dict(id="pose-1", kind="check", item="pose", question="q", how=["h"], steps=["look"]), root=store)
    status, text = call(url, web.API + "/pose-1/answer", cookie="valid", origin=ORIGIN, body={"result": "fail"})
    assert status == 200 and json.loads(text)["answer"]["result"] == "fail"
    rows = {r["id"]: r for r in json.loads(call(url, web.API, cookie="valid")[1])["requests"]}
    assert rows["pose-1"]["verdict"] == "fail" and rows["belt-end-1"]["status"] == "open"
