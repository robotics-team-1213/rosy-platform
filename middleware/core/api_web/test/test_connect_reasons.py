"""D-535: every pairing and session refusal carries a reason code; older ``detail`` stays."""
from datetime import timedelta
from pathlib import Path
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_api_web.api.errors import register_exception_handlers
from core_api_web.api.peer_pairing.receiver_routes import router
from core_api_web.api.peer_pairing.receiver_service import PeerReceiver, Refused
from core_common.protocol.connect_reason import REASONS

import test_peer_pairing as peer

BASE = "/api/v1/auth/peer-pairing"


def _app(case):
    app = FastAPI()
    register_exception_handlers(app)
    app.state.core = case.svc
    app.state.peer_receiver = case.receiver
    app.include_router(router)
    return app


def _reason(response, status):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] in REASONS and error["message"] and error["detail"]["action"]
    assert response.headers["cache-control"] == "no-store"
    return error["code"]


class RelationshipReasons(unittest.TestCase):
    setUp, sign, request, grant = (peer.BoundedPeer.setUp, peer.BoundedPeer.sign, peer.BoundedPeer.request,
                                   peer.BoundedPeer.grant)

    def code(self, grant):
        with self.assertRaises(Refused) as refused:
            self.receiver.challenge(grant)
        return refused.exception.code

    def test_unknown_expired_and_revoked_relationships_name_their_reason(self):
        self.assertEqual("PAIRING_REQUIRED", self.code("x" * 32))
        _, grant = self.grant()
        self.now += timedelta(days=8)
        self.assertEqual("APPROVAL_EXPIRED", self.code(grant))
        self.now -= timedelta(days=8)
        self.receiver.revoke(self.owner_id, grant)
        self.assertEqual("PAIRING_REQUIRED", self.code(grant))

    def test_http_refusal_names_tls_and_keeps_the_older_detail(self):
        plain = TestClient(_app(self), base_url="http://receiver.test")
        response = plain.get(f"{BASE}/identity")
        self.assertEqual("TLS_REQUIRED", _reason(response, 403))
        self.assertEqual("authenticated HTTPS required", response.json()["detail"])

    def test_off_lan_request_and_lost_request_are_typed(self):
        secure = TestClient(_app(self), base_url="https://receiver.test", client=("8.8.8.8", 4000))
        self.assertEqual("LAN_REQUIRED", _reason(secure.post(f"{BASE}/requests", json={}), 403))
        lan = TestClient(_app(self), base_url="https://receiver.test", client=("192.168.10.20", 4000))
        lost = lan.get(f"{BASE}/requests/{'x' * 32}", headers={"X-Request-Secret": "y" * 43})
        self.assertEqual("APPROVAL_EXPIRED", _reason(lost, 409))
        self.assertEqual("request unavailable or changed", lost.json()["detail"])


class ScreenCodeReasons(unittest.TestCase):
    setUp, sign, request = peer.ScreenCodeApproval.setUp, peer.BoundedPeer.sign, peer.BoundedPeer.request
    code, wrong, shown = peer.ScreenCodeApproval.code, peer.ScreenCodeApproval.wrong, peer.ScreenCodeApproval.shown

    def test_wrong_code_then_denied_keep_remaining_attempts(self):
        request = self.request()
        code = self.code()
        client = TestClient(_app(self), base_url="https://receiver.test", client=("192.168.10.20", 4000))
        url = f"{BASE}/requests/{request['request_id']}/confirm"
        headers = {"X-Request-Secret": request["request_secret"]}
        for remaining in (4, 3, 2, 1):
            wrong = client.post(url, json={"approval_code": self.wrong(code)}, headers=headers)
            self.assertEqual("APPROVAL_CODE_WRONG", _reason(wrong, 400))
            self.assertEqual(remaining, wrong.json()["detail"]["remaining_attempts"])
            self.assertEqual(remaining, wrong.json()["error"]["detail"]["remaining_attempts"])
        last = client.post(url, json={"approval_code": self.wrong(code)}, headers=headers)
        self.assertEqual("APPROVAL_DENIED", _reason(last, 400))
        after = client.post(url, json={"approval_code": code}, headers=headers)
        self.assertEqual("APPROVAL_DENIED", _reason(after, 409))

    def test_pairing_word_reports_full_and_console_only(self):
        self.assertEqual("open", self.receiver.pairing_state())
        for index in range(3):
            self.request(nonce=str(index) * 64, source=f"peer-{index}")
        self.assertEqual("full", self.receiver.pairing_state())
        missing = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo,
                               clock=lambda: self.now, display_dir=str(Path(self.tmp.name) / "absent"))
        self.assertEqual("console_only", missing.pairing_state())
        none = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo, clock=lambda: self.now)
        self.assertEqual("console_only", none.pairing_state())

