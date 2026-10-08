"""Actual cryptography, disk overlay and HTTP consent/session integration."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_api_web.api import deps
from core_api_web.api.errors import ApiError, register_exception_handlers
from core_api_web.api.peer_pairing.peer_crypto import public_key, transcript, verify
from core_api_web.api.peer_pairing.receiver_service import PeerReceiver, RateLimited, Refused, WrongCode
from core_api_web.api.peer_pairing.receiver_repository import OverlayRepository
from core_api_web.api.peer_pairing.receiver_routes import router


class BoundedPeer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.yaml"
        self.now = datetime.now(timezone.utc)
        owner = deps.new_token_record("fixture-owner-secret", "administrator", source="pair-admin",
                                      expires_at=(self.now + timedelta(hours=2)).isoformat())
        self.owner_id = owner["id"]
        self.svc = SimpleNamespace(config={"auth": {"tokens": deps.stored_token_entries([owner])},
                                          "robot": {"id": "rosy_01"}})
        self.repo = OverlayRepository(self.svc, self.path, clock=lambda: self.now)
        self.receiver = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo,
                                     clock=lambda: self.now)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = public_key(self.key.public_key())

    def sign(self, context, body):
        return base64.b64encode(self.key.sign(transcript(context, body), ec.ECDSA(hashes.SHA256()))).decode()

    def request(self, nonce="a" * 64, source="fixture-lan-peer"):
        info = self.receiver.identity()
        fields = {"receiver_id": info["receiver_id"], "receiver_key_sha256": info["receiver_key_sha256"],
                  "client_id": "tablet-a", "label": "Tablet", "client_public_key": self.pub,
                  "role": "operator", "nonce": nonce}
        return self.receiver.request(fields, self.sign("request", fields), source)

    def grant(self):
        request = self.request()
        decision = self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
        self.assertEqual("approved", decision["state"])
        self.assertFalse(decision["paired"])
        self.assertNotIn("token", decision)
        return request, decision["relationship_id"]

    def test_real_owner_consent_and_client_proof_issue_bounded_existing_token(self):
        request, grant = self.grant()
        self.assertEqual("approved", self.receiver.status(request["request_id"], request["request_secret"])["state"])
        challenge = self.receiver.challenge(grant)
        verify(self.receiver.identity()["receiver_public_key"], challenge["receiver_signature"],
               "receiver-challenge", challenge["fields"])
        issued = self.receiver.session(grant, challenge["fields"], self.sign("session-request", challenge["fields"]))
        self.assertEqual("operator", issued["role"])
        self.assertLessEqual(datetime.fromisoformat(issued["expires_at"]), self.now + timedelta(hours=1))
        self.assertTrue(deps.token_alive(self.svc.config, issued["id"]))
        raw = self.path.read_text()
        self.assertNotIn(issued["token"], raw)
        self.assertNotIn(request["request_secret"], raw)
        self.assertIn(grant, raw)
        with self.assertRaises(Refused):
            self.receiver.session(grant, challenge["fields"], self.sign("session-request", challenge["fields"]))

    def test_code_secret_wrong_key_and_mutated_transcript_cannot_issue_or_approve(self):
        request = self.request()
        for fake in [request["display_code"], request["request_secret"]]:
            with self.assertRaises(Refused):
                self.receiver.decide(fake, request["request_id"], "approve", 0)
        self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
        grant = self.receiver.status(request["request_id"], request["request_secret"])["relationship_id"]
        challenge = self.receiver.challenge(grant)["fields"]
        for change in ["role", "receiver_id", "generation", "nonce"]:
            wrong = dict(challenge)
            wrong[change] = "mutated"
            with self.assertRaises(Refused):
                self.receiver.session(grant, wrong, self.sign("session-request", wrong))
        other = ec.generate_private_key(ec.SECP256R1())
        signature = base64.b64encode(other.sign(transcript("session-request", challenge), ec.ECDSA(hashes.SHA256()))).decode()
        with self.assertRaises(Refused):
            self.receiver.session(grant, challenge, signature)
        self.assertEqual(1, len(deps.auth_entries(self.svc.config)))

    def test_issuer_revoke_and_grant_limit_survive_restart_without_new_code(self):
        _, grant = self.grant()
        restarted = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo, clock=lambda: self.now)
        challenge = restarted.challenge(grant)["fields"]
        issued = restarted.session(grant, challenge, self.sign("session-request", challenge))
        self.assertIn("token", issued)
        self.repo.revoke_issuer(self.owner_id)
        with self.assertRaises(Refused):
            restarted.challenge(grant)
        # Persisted record remains, but the revoked issuer cannot authorize renewed access.
        self.assertIn(grant, self.repo.grants())

    def test_parallel_replay_one_token_and_failed_commit_zero_token(self):
        _, grant = self.grant()
        challenge = self.receiver.challenge(grant)["fields"]
        signature = self.sign("session-request", challenge)
        def issue(_):
            try:
                return self.receiver.session(grant, challenge, signature)["id"]
            except Refused:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(issue, range(4)))
        self.assertEqual(1, sum(value is not None for value in ids))
        fresh = self.receiver.challenge(grant)["fields"]
        before = json.loads(json.dumps(self.svc.config))
        with patch('core_common.config.os.replace', side_effect=OSError('fixture actual disk failure')):
            with self.assertRaises(OSError):
                self.receiver.session(grant, fresh, self.sign("session-request", fresh))
        self.assertEqual(before, self.svc.config)

    def test_cancel_capacity_body_rate_and_receiver_key_missing_fail_closed(self):
        first = self.request()
        self.receiver.cancel(first["request_id"], first["request_secret"])
        with self.assertRaises(Refused):
            self.receiver.decide(self.owner_id, first["request_id"], "approve", 0)
        for n in range(3):  # D-483: a cancelled request holds no slot; three live requests at most
            self.request(f"{n+1:064x}", f"fixture-lan-{n}")
        with self.assertRaises(Refused):
            self.request("f" * 64, "fixture-lan-x")
        # Fresh instance clears pending; existing grant must retain exact receiver identity.
        self.receiver = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo, clock=lambda: self.now)
        _, grant = self.grant()
        (Path(self.tmp.name) / "identity.pem").unlink()
        with self.assertRaises(ValueError):
            PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo, clock=lambda: self.now)
        self.assertIn(grant, self.repo.grants())

    def test_real_https_routes_and_http_refusal_without_any_motion_ports(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.state.core = self.svc
        app.state.peer_receiver = self.receiver
        app.include_router(router)
        secure = TestClient(app, base_url="https://receiver.test", client=('192.168.10.20', 40000))
        plain = TestClient(app, base_url="http://receiver.test")
        self.assertEqual(403, plain.get("/api/v1/auth/peer-pairing/identity").status_code)
        self.assertEqual(200, secure.get("/api/v1/auth/peer-pairing/identity").status_code)
        self.assertEqual(401, secure.get("/api/v1/auth/peer-pairing/pending").status_code)
        self.assertEqual(413, secure.post("/api/v1/auth/peer-pairing/requests", content=b"x"*5000).status_code)
        self.assertEqual(1, len(deps.auth_entries(self.svc.config)))

    def test_fleet_identity_poll_does_not_spend_session_proof_budget(self):
        app = FastAPI()
        app.state.peer_receiver = self.receiver
        app.include_router(router)
        with TestClient(app, base_url="https://receiver.test", client=('192.168.10.20', 40000)) as client:
            for _ in range(35):
                self.assertEqual(200, client.get("/api/v1/auth/peer-pairing/identity").status_code)
            for _ in range(30):
                self.receiver.admit_proof('192.168.10.20')
            with self.assertRaises(Refused):
                self.receiver.admit_proof('192.168.10.20')
            for _ in range(300 - 35):
                self.receiver.admit_proof('192.168.10.20', identity=True)
            with self.assertRaises(Refused):
                self.receiver.admit_proof('192.168.10.20', identity=True)

    def test_final_repository_rechecks_grant_after_successful_key_proof(self):
        _, grant = self.grant()
        fields = self.receiver.challenge(grant)["fields"]
        original = self.repo.issue
        def mutate(grant_id, challenge_id, receiver_fingerprint, expected):
            def change(grants, tokens, doc):
                grants[grant_id]["generation"] += 1
            self.repo.update(change, "fixture_generation_change")
            return original(grant_id, challenge_id, receiver_fingerprint, expected)
        self.repo.issue = mutate
        with self.assertRaises(Refused):
            self.receiver.session(grant, fields, self.sign("session-request", fields))
        self.assertEqual(1, len(deps.auth_entries(self.svc.config)))

    def test_explicit_revoke_cancels_issued_sessions_and_eight_session_limit(self):
        _, grant = self.grant()
        ids = []
        for _ in range(8):
            fields = self.receiver.challenge(grant)["fields"]
            ids.append(self.receiver.session(grant, fields, self.sign("session-request", fields))["id"])
        fields = self.receiver.challenge(grant)["fields"]
        with self.assertRaises(Refused):
            self.receiver.session(grant, fields, self.sign("session-request", fields))
        self.receiver.revoke(self.owner_id, grant)
        for identifier in ids:
            self.assertFalse(deps.token_alive(self.svc.config, identifier))
        with self.assertRaises(Refused):
            self.receiver.challenge(grant)

    def test_issuer_limit_and_failed_decision_commit_keep_pending_and_credentials(self):
        request = self.request()
        before = json.loads(json.dumps(self.svc.config))
        with patch('core_common.config.os.replace', side_effect=OSError('fixture actual disk failure')):
            with self.assertRaises(OSError):
                self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
        self.assertEqual(before, self.svc.config)
        self.assertEqual("pending", self.receiver.status(request["request_id"], request["request_secret"])["state"])
        result = self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
        self.assertLessEqual(datetime.fromisoformat(result["authorization_expires_at"]), self.now + timedelta(hours=2))
        self.now += timedelta(hours=3)
        with self.assertRaises(Refused):
            self.receiver.challenge(result["relationship_id"])
        self.assertIn(result["relationship_id"], self.repo.grants())

    def test_explicit_durable_manual_approval_reconnects_after_year_without_new_consent(self):
        owner = deps.new_token_record('fixture-durable-secret', 'administrator', source='manual')
        self.svc.config['auth']['tokens'] = deps.stored_token_entries([owner])
        self.repo = OverlayRepository(self.svc, self.path, clock=lambda:self.now)
        self.receiver = PeerReceiver('rosy_01',Path(self.tmp.name)/'identity.pem',self.repo,clock=lambda:self.now)
        request = self.request()
        decision = self.receiver.decide(owner['id'], request['request_id'], 'approve', 0, True)
        self.assertTrue(decision['persistent'])
        self.assertIsNone(decision['authorization_expires_at'])
        self.assertFalse(decision['paired'])
        self.now += timedelta(days=365)
        self.receiver = PeerReceiver('rosy_01', Path(self.tmp.name) / 'identity.pem', self.repo,
                                     clock=lambda: self.now)
        fields = self.receiver.challenge(decision['relationship_id'])['fields']
        issued = self.receiver.session(decision['relationship_id'], fields, self.sign('session-request', fields))
        self.assertLessEqual(datetime.fromisoformat(issued['expires_at']), self.now + timedelta(hours=1))
        self.assertEqual(1, len(self.repo.grants()))

    def test_temporary_owner_persist_request_is_truthfully_issuer_bound(self):
        request = self.request()
        decision = self.receiver.decide(self.owner_id, request['request_id'], 'approve', 0, True)
        self.assertFalse(decision['persistent'])
        self.assertLessEqual(datetime.fromisoformat(decision['authorization_expires_at']), self.now + timedelta(hours=2))

    def test_existing_token_writer_issuer_revoke_closes_http_and_socket_child_authority(self):
        _, grant = self.grant()
        fields = self.receiver.challenge(grant)['fields']
        issued = self.receiver.session(grant, fields, self.sign('session-request', fields))
        self.assertTrue(deps.token_alive(self.svc.config, issued['id']))
        deps.authenticate(self.svc.config, 'Bearer ' + issued['token'], None)
        with patch.dict(os.environ, {'ROSY_CONFIG': str(self.path)}):
            deps.persist_token_records(self.svc, [r for r in deps.auth_entries(self.svc.config)
                                                  if r['id'] != self.owner_id])
        # The ordinary token writer retains the child token row, but authority is revoked.
        self.assertTrue(any(r['id'] == issued['id'] for r in deps.auth_entries(self.svc.config)))
        self.assertFalse(deps.token_alive(self.svc.config, issued['id']))
        with self.assertRaises(ApiError) as result:
            deps.authenticate(self.svc.config, 'Bearer ' + issued['token'], None)
        self.assertEqual(401, result.exception.http_status)
        self.assertIn(grant, self.repo.grants())

    def test_invalid_proofs_are_rate_limited_before_expensive_crypto(self):
        fields = {'receiver_id': 'rosy_01', 'receiver_key_sha256': self.receiver.identity()['receiver_key_sha256'],
                  'client_id': 'pilot_01', 'label': 'Pilot', 'client_public_key': self.pub,
                  'role': 'operator', 'nonce': 'e'*64}
        for _ in range(30):
            with self.assertRaises(Refused):
                self.receiver.request(fields, 'invalid', 'fixture-invalid-source')

    def test_peer_token_marker_survives_writer_and_missing_corrupt_grant_denies(self):
        _, grant = self.grant()
        fields = self.receiver.challenge(grant)['fields']
        issued = self.receiver.session(grant, fields, self.sign('session-request', fields))
        original = json.loads(json.dumps(self.svc.config))
        # The normal token writer must retain explicit provenance.
        with patch.dict(os.environ, {'ROSY_CONFIG': str(self.path)}):
            deps.persist_token_records(self.svc, deps.auth_entries(self.svc.config))
        record = next(r for r in deps.auth_entries(self.svc.config) if r['id'] == issued['id'])
        self.assertEqual({'relationship_id': grant, 'generation': 0}, record['peer_binding'])
        for mutation in ('missing-store', 'missing-grant', 'missing-session', 'bad-session', 'bad-grant',
                         'unknown-schema', 'missing-schema', 'scalar-store', 'null-marker'):
            with self.subTest(mutation=mutation):
                self.svc.config = json.loads(json.dumps(original))
                auth = self.svc.config['auth']
                if mutation == 'missing-store': del auth['peer_pairing']
                elif mutation == 'unknown-schema': auth['peer_pairing']['schema'] = 'unsupported'
                elif mutation == 'missing-schema': del auth['peer_pairing']['schema']
                elif mutation == 'scalar-store': auth['peer_pairing'] = 42
                elif mutation == 'missing-grant': auth['peer_pairing']['grants'].clear()
                elif mutation == 'missing-session': auth['peer_pairing']['grants'][grant]['session_ids'] = []
                elif mutation == 'bad-session': auth['peer_pairing']['grants'][grant]['session_ids'] = 42
                elif mutation == 'bad-grant': auth['peer_pairing']['grants'][grant] = {'id': grant}
                else:
                    next(r for r in auth['tokens'] if r['id'] == issued['id'])['peer_binding'] = None
                self.assertFalse(deps.token_alive(self.svc.config, issued['id']))
                with self.assertRaises(ApiError) as result:
                    deps.authenticate(self.svc.config, 'Bearer ' + issued['token'], None)
                self.assertEqual(401, result.exception.http_status)
                # Independent ordinary D193 administrator still authenticates.
                deps.authenticate(self.svc.config, 'Bearer fixture-owner-secret', None)

    def test_direct_null_marker_is_not_an_ordinary_record(self):
        from core_api_web.api.peer_pairing.receiver_session_policy import session_allowed
        record=deps.auth_entries(self.svc.config)[0]
        self.assertTrue(session_allowed(self.svc.config, record, [record]))
        self.assertFalse(session_allowed(self.svc.config, dict(record,peer_binding=None), [record]))

    def test_lower_layer_card_owner_with_unrelated_overlay_is_preserved(self):
        import yaml
        owner=deps.new_token_record('fixture-card-secret','administrator',source='card')
        self.svc.config['auth']['tokens']=deps.stored_token_entries([owner])
        self.path.write_text(yaml.safe_dump({'camera':{'enabled':True}}),encoding='utf8')
        self.repo = OverlayRepository(self.svc, self.path, clock=lambda:self.now)
        self.receiver = PeerReceiver('rosy_01',Path(self.tmp.name)/'identity.pem',self.repo,clock=lambda:self.now)
        request=self.request()
        approved=self.receiver.decide(owner['id'],request['request_id'],'approve',0,True)
        self.assertTrue(approved['persistent'])
        saved=yaml.safe_load(self.path.read_text(encoding='utf8'))
        self.assertEqual({'enabled':True},saved['camera'])
        self.assertEqual('card',saved['auth']['tokens'][0]['source'])

    def test_whole_overlay_removal_never_restores_relationship_from_memory(self):
        _,grant=self.grant()
        fields=self.receiver.challenge(grant)['fields']
        self.assertIn(grant,self.svc.config['auth']['peer_pairing']['grants'])
        self.path.unlink()
        self.assertEqual({},self.repo.grants())
        with self.assertRaises(Refused):self.receiver.challenge(grant)
        with self.assertRaises(Refused):self.receiver.session(grant,fields,self.sign('session-request',fields))

    def test_overlay_owned_issuer_withdrawal_has_no_memory_fallback(self):
        import yaml
        from core_common.protocol.peer_pairing import RepositoryDenied
        self.path.write_text(yaml.safe_dump(self.svc.config),encoding='utf8')
        self.repo=OverlayRepository(self.svc,self.path,clock=lambda:self.now)
        self.path.unlink()
        with self.assertRaises(RepositoryDenied):self.repo.owner(self.owner_id)
        self.assertEqual([],deps.auth_entries(self.repo._document()))

    def test_stored_approval_status_is_unavailable_after_expiry_and_revoke(self):
        request,grant=self.grant()
        self.receiver.revoke(self.owner_id,grant)
        status=self.receiver.status(request['request_id'],request['request_secret'])
        self.assertEqual('approved',status['state'])
        self.assertFalse(status['authorization_available'])

    def test_anonymous_session_rate_admission_precedes_crypto(self):
        _,grant=self.grant()
        fields=self.receiver.challenge(grant)['fields']
        app=FastAPI();app.state.peer_receiver=self.receiver;app.include_router(router)
        with TestClient(app,base_url='https://receiver.fixture',client=('192.168.20.2',1234)) as client:
            for _ in range(30):
                response=client.post(f'/api/v1/auth/peer-pairing/relationships/{grant}/session',json={'fields':fields,'signature':'invalid'})
                self.assertEqual(409,response.status_code)
            with patch('core_api_web.api.peer_pairing.receiver_service.verify',side_effect=AssertionError('crypto must not run')):
                response=client.post(f'/api/v1/auth/peer-pairing/relationships/{grant}/session',json={'fields':fields,'signature':'invalid'})
            self.assertEqual(429,response.status_code)

    def test_actual_app_mount_consent_session_and_named_owner_audit(self):
        from core_api_web.api.app import create_app
        app = create_app(self.svc.config, self.svc)
        app.state.peer_receiver = self.receiver
        client = TestClient(app, base_url='https://receiver.test', client=('192.168.10.20', 40000))
        identity = client.get('/api/v1/auth/peer-pairing/identity').json()
        fields = {'receiver_id': identity['receiver_id'], 'receiver_key_sha256': identity['receiver_key_sha256'],
                  'client_id': 'pilot_01', 'label': 'Tablet', 'client_public_key': self.pub,
                  'role': 'operator', 'nonce': 'd'*64}
        response = client.post('/api/v1/auth/peer-pairing/requests',
                               json={'fields': fields, 'signature': self.sign('request', fields)})
        self.assertEqual(200, response.status_code)
        request = response.json()
        owner = {'Authorization': 'Bearer fixture-owner-secret'}
        pending = client.get('/api/v1/auth/peer-pairing/pending', headers=owner)
        self.assertEqual(200, pending.status_code)
        self.assertEqual(request['request_id'], pending.json()[0]['request_id'])
        approved = client.post('/api/v1/auth/peer-pairing/requests/' + request['request_id'] + '/decision',
                                json={'action': 'approve', 'revision': 0, 'persist_requested': True}, headers=owner)
        self.assertEqual(200, approved.status_code)
        self.assertFalse(approved.json()['persistent'])
        grant = approved.json()['relationship_id']
        challenge = client.post('/api/v1/auth/peer-pairing/relationships/' + grant + '/challenge')
        self.assertEqual(200, challenge.status_code)
        fields = challenge.json()['fields']
        response = client.post('/api/v1/auth/peer-pairing/relationships/' + grant + '/session',
                               json={'fields': fields, 'signature': self.sign('session-request', fields)})
        self.assertEqual(200, response.status_code)
        self.assertEqual('operator', deps.authenticate(self.svc.config, 'Bearer '+response.json()['token'], None).role)
        audit = self.svc.config['auth']['peer_pairing']['audit'][0]
        issuer = next(r for r in deps.auth_entries(self.svc.config) if r['id'] == self.owner_id)
        self.assertEqual(deps.principal_ref(issuer), audit['actor'])
        self.assertEqual(grant, audit['relationship_id'])

    def test_approval_written_but_reply_failed_recovers_status_without_duplicate_or_extension(self):
        from core_common import config
        request = self.request()
        original = config.os.replace
        def failed_after_commit(source, target):
            original(source, target)
            raise OSError('fixture response lost after replace')
        with patch('core_common.config.os.replace', side_effect=failed_after_commit):
            with self.assertRaises(OSError):
                self.receiver.decide(self.owner_id, request['request_id'], 'approve', 0)
        status = self.receiver.status(request['request_id'], request['request_secret'])
        self.assertEqual('approved', status['state'])
        self.assertEqual(request['request_id'], status['relationship_id'])
        deadline = status['authorization_expires_at']
        with self.assertRaises(Refused):
            self.receiver.decide(self.owner_id, request['request_id'], 'approve', 0)
        self.assertEqual(1, len(self.repo.grants()))
        self.assertEqual(deadline, self.repo.grants()[request['request_id']]['expires_at'])
        fields = self.receiver.challenge(request['request_id'])['fields']
        issued = self.receiver.session(request['request_id'], fields, self.sign('session-request', fields))
        self.assertTrue(deps.token_alive(self.svc.config, issued['id']))
        module = self.receiver.__class__.__module__
        with patch(module + '.verify', side_effect=AssertionError('crypto must not run after admission cap')):
            with self.assertRaises(Refused):
                self.receiver.request(fields, 'invalid', 'fixture-invalid-source')


class ScreenCodeApproval(unittest.TestCase):
    """D-483: the robot-screen approval code entered by the requester."""
    sign = BoundedPeer.sign

    def setUp(self):
        BoundedPeer.setUp(self)
        self.display = Path(self.tmp.name) / "peer-display"
        self.display.mkdir()
        self.receiver = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo,
                                     clock=lambda: self.now, display_dir=str(self.display))
        self.file = self.display / "approval.json"

    def shown(self):
        return json.loads(self.file.read_text(encoding="utf-8"))["requests"]

    def code(self, display_code=None):
        rows = self.shown()
        return next(r["approval_code"] for r in rows if display_code in (None, r["display_code"]))

    def wrong(self, code):
        alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
        return "".join(alphabet[(alphabet.index(c) + 1) % len(alphabet)] for c in code)

    def client(self):
        app = FastAPI()
        app.state.peer_receiver = self.receiver
        app.include_router(router)
        return TestClient(app, base_url="https://receiver.test", client=("192.168.10.20", 40000))

    def test_hand_over_shows_code_but_no_response_pending_or_log_carries_it(self):
        with self.assertLogs("core_api_web.api.peer_pairing", "DEBUG") as logs:
            logging.getLogger("core_api_web.api.peer_pairing").debug("fixture marker")
            request = self.request()
            shown, = self.shown()
            code = shown["approval_code"]
            self.assertEqual({"display_code", "approval_code", "expires_at"}, set(shown))  # no label (R4)
            self.assertEqual(request["display_code"], shown["display_code"])
            self.assertRegex(code, r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{6}$")
            if os.name == "posix":
                self.assertEqual(0o640, self.file.stat().st_mode & 0o777)
            seen = [request, self.receiver.status(request["request_id"], request["request_secret"]),
                    self.receiver.pending(self.owner_id)]
            self.now += timedelta(seconds=3)
            seen.append(self.receiver.confirm(request["request_id"], request["request_secret"], code, "fixture"))
        for value in seen:
            self.assertNotIn(code, json.dumps(value))
        self.assertNotIn(code, "\n".join(logs.output))
        self.assertNotIn(code, self.path.read_text())

    def test_five_wrong_codes_reject_and_the_right_code_then_fails(self):
        request = self.request()
        code = self.code()
        for remaining in (4, 3, 2, 1, 0):
            with self.assertRaises(WrongCode) as wrong:
                self.receiver.confirm(request["request_id"], request["request_secret"], self.wrong(code), "fixture")
            self.assertEqual(remaining, wrong.exception.remaining)
        self.assertFalse(self.file.exists())
        with self.assertRaises(Refused):
            self.receiver.confirm(request["request_id"], request["request_secret"], code, "fixture")
        self.now += timedelta(seconds=3)
        self.assertEqual("rejected", self.receiver.status(request["request_id"], request["request_secret"])["state"])
        self.assertEqual({}, self.repo.grants())

    def test_code_without_the_request_secret_cannot_approve(self):
        request = self.request()
        code = self.code()
        client = self.client()
        url = f"/api/v1/auth/peer-pairing/requests/{request['request_id']}/confirm"
        self.assertEqual(422, client.post(url, json={"approval_code": code}).status_code)
        self.assertEqual(409, client.post(url, json={"approval_code": code},
                                          headers={"X-Request-Secret": "x" * 43}).status_code)
        wrong = client.post(url, json={"approval_code": self.wrong(code)},
                            headers={"X-Request-Secret": request["request_secret"]})
        self.assertEqual(400, wrong.status_code)
        self.assertEqual(4, wrong.json()["detail"]["remaining_attempts"])
        self.assertEqual({}, self.repo.grants())
        approved = client.post(url, json={"approval_code": code}, headers={"X-Request-Secret": request["request_secret"]})
        self.assertEqual(200, approved.status_code)
        self.assertEqual("approved", approved.json()["state"])
        self.assertNotIn(code, approved.text)

    def test_console_and_code_race_approves_once(self):
        for _ in range(5):
            request = self.request(nonce=os.urandom(32).hex())
            code = self.code()
            def console(_):
                return self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
            def screen(_):
                return self.receiver.confirm(request["request_id"], request["request_secret"], code, "fixture")
            def attempt(job):
                try:
                    return job(None)["state"]
                except Refused:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, [console, screen]))
            self.assertEqual(1, results.count("approved"), results)
            self.assertIn(request["request_id"], self.repo.grants())

    def test_hand_over_removed_on_every_terminal_state(self):
        def outcome(name):
            request = self.request(nonce=os.urandom(32).hex())
            self.assertTrue(self.file.exists())
            if name == "approve":
                self.receiver.decide(self.owner_id, request["request_id"], "approve", 0)
            elif name == "reject":
                self.receiver.decide(self.owner_id, request["request_id"], "reject", 0)
            elif name == "cancel":
                self.receiver.cancel(request["request_id"], request["request_secret"])
            elif name == "confirm":
                self.receiver.confirm(request["request_id"], request["request_secret"], self.code(), "fixture")
            elif name == "expire":
                self.now += timedelta(seconds=301)
                self.receiver.status(request["request_id"], request["request_secret"])
            elif name == "prune":
                self.now += timedelta(seconds=601)
                self.receiver.admit_proof("fixture")
            self.assertFalse(self.file.exists(), name)
        for name in ("approve", "reject", "cancel", "confirm", "expire", "prune"):
            with self.subTest(name=name):
                outcome(name)

    def test_every_live_request_is_on_the_lcd_newest_first(self):
        made = []
        for n, source in enumerate(("lan-a", "lan-b", "lan-c")):
            made.append(self.request(f"{n+1:064x}", source))
            self.now += timedelta(seconds=1)
        self.assertEqual([r["display_code"] for r in reversed(made)], [r["display_code"] for r in self.shown()])
        with self.assertRaises(Refused):
            self.request("4" * 64, "lan-d")  # R2: never more live requests than the LCD lists
        self.receiver.cancel(made[2]["request_id"], made[2]["request_secret"])
        self.assertEqual([r["display_code"] for r in reversed(made[:2])], [r["display_code"] for r in self.shown()])
        # Each requester's own code sits next to its own display code.
        first = made[0]
        self.receiver.confirm(first["request_id"], first["request_secret"], self.code(first["display_code"]), "lan-a")

    def test_pending_limits_count_live_requests_per_source_and_overall(self):
        self.request("1" * 64)
        self.request("2" * 64)
        with self.assertRaises(Refused):
            self.request("3" * 64)  # a third live request from the same source
        self.request("4" * 64, "lan-b")
        with self.assertRaises(Refused):
            self.request("5" * 64, "lan-c")  # three live overall
        # Terminal rows do not count: cancelling frees a slot at once.
        for row in list(self.receiver._pending.values())[:2]:
            row["state"] = "cancelled"
        self.request("6" * 64, "lan-c")
        self.request("7" * 64)

    def test_cancel_is_charged_to_the_source_rate_limit(self):
        request = self.request()  # one charge
        for _ in range(29):
            with self.assertRaises(Refused) as refused:
                self.receiver.cancel("x" * 32, request["request_secret"], "fixture-lan-peer")
            self.assertNotIsInstance(refused.exception, RateLimited)
        with self.assertRaises(RateLimited):
            self.receiver.cancel(request["request_id"], request["request_secret"], "fixture-lan-peer")

    def test_kept_rows_never_evict_an_approved_result_early(self):
        from core_api_web.api.peer_pairing import receiver_service
        approved = self.request("1" * 64, "lan-a")
        self.receiver.confirm(approved["request_id"], approved["request_secret"], self.code(), "lan-a")
        rejected = self.request("2" * 64, "lan-b")
        self.receiver.decide(self.owner_id, rejected["request_id"], "reject", 0)
        with patch.object(receiver_service, "ROW_LIMIT", 2):
            self.request("3" * 64, "lan-c")  # evicts the rejected row, not the approved one
            self.now += timedelta(seconds=3)
            self.assertEqual("approved", self.receiver.status(approved["request_id"], approved["request_secret"])["state"])
            with self.assertRaises(Refused):
                self.receiver.status(rejected["request_id"], rejected["request_secret"])
            with self.assertRaises(Refused):
                self.request("4" * 64, "lan-d")  # only approved and pending rows left: refuse, keep both

    def test_startup_removes_a_leftover_hand_over(self):
        self.file.write_text('{"requests": []}', encoding="utf-8")
        PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo,
                     clock=lambda: self.now, display_dir=str(self.display))
        self.assertFalse(self.file.exists())

    def test_unwritable_display_never_breaks_the_request(self):
        self.receiver = PeerReceiver("rosy_01", Path(self.tmp.name) / "identity.pem", self.repo,
                                     clock=lambda: self.now, display_dir=str(self.display / "missing"))
        with self.assertLogs("core_api_web.api.peer_pairing", "WARNING") as logs:
            request = self.request()
            self.receiver.request(dict(self.last_fields, nonce="b" * 64),
                                  self.sign("request", dict(self.last_fields, nonce="b" * 64)), "fixture-lan-peer")
        self.assertEqual(1, len(logs.output))
        self.assertEqual("pending", request["state"])

    def request(self, nonce="a" * 64, source="fixture-lan-peer"):
        info = self.receiver.identity()
        self.last_fields = {"receiver_id": info["receiver_id"], "receiver_key_sha256": info["receiver_key_sha256"],
                            "client_id": "tablet-a", "label": "Tablet", "client_public_key": self.pub,
                            "role": "operator", "nonce": nonce}
        return self.receiver.request(self.last_fields, self.sign("request", self.last_fields), source)

    def screen_grant(self):
        request = self.request()
        decision = self.receiver.confirm(request["request_id"], request["request_secret"], self.code(), "fixture")
        return decision["relationship_id"]

    def test_revoking_a_screen_code_relationship_ends_its_session(self):
        grant = self.screen_grant()
        fields = self.receiver.challenge(grant)["fields"]
        issued = self.receiver.session(grant, fields, self.sign("session-request", fields))
        self.assertTrue(deps.token_alive(self.svc.config, issued["id"]))
        self.receiver.revoke(self.owner_id, grant)
        self.assertFalse(deps.token_alive(self.svc.config, issued["id"]))  # live-socket recheck
        with self.assertRaises(ApiError) as result:  # HTTP
            deps.authenticate(self.svc.config, "Bearer " + issued["token"], None)
        self.assertEqual(401, result.exception.http_status)
        with self.assertRaises(Refused):
            self.receiver.challenge(grant)

    def test_relationship_model_rejects_malformed_screen_code_rows(self):
        from core_common.protocol.peer_pairing import Relationship
        grant = self.screen_grant()
        good = self.repo.grants()[grant]
        Relationship(**good)
        approved = datetime.fromisoformat(good["approved_at"])
        for change in ({"persistent": True, "expires_at": None}, {"expires_at": None},
                       {"issuer_digest": "0" * 64}, {"issuer_id": self.owner_id}, {"approved_by": "owner"},
                       {"issuer_source": "manual"}, {"persist_requested": True}, {"approved_at": None},
                       {"expires_at": (approved + timedelta(hours=168, seconds=1)).isoformat()},
                       {"expires_at": approved.isoformat()}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Relationship(**dict(good, **change))

    def test_screen_code_token_id_is_reserved(self):
        record = dict(deps.stored_token_entries([deps.new_token_record("fixture-reserved-secret", "administrator")])[0],
                      id="screen-code")
        config = {"auth": {"tokens": [record]}}
        self.assertEqual([], deps.auth_entries(config))

    def test_dead_relationships_are_pruned_at_capacity_with_an_audit_row(self):
        from core_common.protocol.peer_pairing import Relationship
        grant = self.screen_grant()
        fields = self.receiver.challenge(grant)["fields"]
        live_session = self.receiver.session(grant, fields, self.sign("session-request", fields))["id"]
        template = self.repo.grants()[grant]
        expired = (self.now - timedelta(hours=1)).isoformat()
        def fill(grants, tokens, document):
            for n in range(127):
                key = f"{n:032d}"
                # Row 1 is dead (expired) but still holds a live child session.
                grants[key] = dict(template, id=key, approved_at=(self.now - timedelta(hours=2)).isoformat(),
                                   expires_at=expired, session_ids=[live_session] if n == 1 else [])
        self.repo.update(fill, "fixture_fill")
        self.assertEqual(128, len(self.repo.grants()))
        self.now += timedelta(seconds=1)
        self.screen_grant_from("b" * 64)
        grants = self.repo.grants()
        self.assertLessEqual(len(grants), 128)
        self.assertNotIn("0" * 32, grants)
        self.assertIn(f"{1:032d}", grants)  # dead row with a live session survives
        self.assertIn(grant, grants)  # live row survives
        actions = [row["action"] for row in self.svc.config["auth"]["peer_pairing"]["audit"]]
        self.assertIn("relationship_pruned", actions)
        import yaml
        on_disk = yaml.safe_load(self.path.read_text(encoding="utf8"))["auth"]["peer_pairing"]["grants"]
        self.assertEqual(set(grants), set(on_disk))  # the prune reaches the overlay, not only memory
        Relationship(**grants[next(iter(grants))])

    def test_stored_owner_rows_stay_readable_by_the_release_before_d483(self):
        from typing import Literal
        from pydantic import BaseModel, ConfigDict
        import yaml

        class MainRelationship(BaseModel):  # main's D-456 Relationship fields, Strict, extra forbidden
            model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
            id: str
            receiver_id: str
            receiver_key_sha256: str
            client_id: str
            client_public_key: str
            label: str
            role: Literal["viewer", "operator"]
            generation: int
            revoked: bool
            issuer_id: str
            issuer_source: Literal["card", "manual", "pair-physical", "pair-admin"]
            issuer_digest: str
            approved_by: str
            persistent: bool
            persist_requested: bool
            expires_at: str | None
            used_challenges: list[str]
            session_ids: list[str] = []

        _, owner_grant = BoundedPeer.grant(self)
        self.screen_grant_from("c" * 64)  # a screen-code row in the same write path
        self.repo.update(lambda grants, tokens, document: None, "fixture_rewrite")
        stored = yaml.safe_load(self.path.read_text(encoding="utf8"))["auth"]["peer_pairing"]["grants"]
        MainRelationship(**stored[owner_grant])
        self.assertNotIn("approved_at", stored[owner_grant])
        self.assertNotIn("approved_at", self.svc.config["auth"]["peer_pairing"]["grants"][owner_grant])

    def test_screen_code_row_dated_in_the_future_is_refused_at_use(self):
        grant = self.screen_grant()
        fields = self.receiver.challenge(grant)["fields"]
        issued = self.receiver.session(grant, fields, self.sign("session-request", fields))
        future = (self.now + timedelta(minutes=5)).isoformat()
        def forge(grants, tokens, document):
            grants[grant]["approved_at"] = future
        self.repo.update(forge, "fixture_forge")
        with self.assertRaises(Refused):
            self.receiver.challenge(grant)
        self.assertFalse(deps.token_alive(self.svc.config, issued["id"]))
        from core_common.protocol.peer_pairing import RepositoryDenied
        with self.assertRaises(RepositoryDenied):
            self.repo.issue(grant, "C" * 32, self.receiver.identity()["receiver_key_sha256"], self.repo.grants()[grant])

    def test_global_wrong_code_budget_stops_guessing_across_sources(self):
        from core_api_web.api.peer_pairing.receiver_service import CODE_FAILURE_BUDGET, CodeBudgetSpent
        for n in range(CODE_FAILURE_BUDGET // 5):  # each source: one request, five wrong codes
            source = f"guess-{n}"
            request = self.request(f"{n+1:064x}", source)
            code = self.code(request["display_code"])
            for _ in range(5):
                with self.assertRaises(WrongCode):
                    self.receiver.confirm(request["request_id"], request["request_secret"], self.wrong(code), source)
        honest = self.request("e" * 64, "honest")
        code = self.code(honest["display_code"])
        with self.assertRaises(CodeBudgetSpent):  # even the correct code waits
            self.receiver.confirm(honest["request_id"], honest["request_secret"], code, "honest")
        response = self.client().post(f"/api/v1/auth/peer-pairing/requests/{honest['request_id']}/confirm",
                                      json={"approval_code": code}, headers={"X-Request-Secret": honest["request_secret"]})
        self.assertEqual(429, response.status_code)
        self.assertIn("console", response.json()["detail"])
        self.assertEqual({}, self.repo.grants())
        # Console approval is unaffected.
        self.assertEqual("approved", self.receiver.decide(self.owner_id, honest["request_id"], "approve", 0)["state"])
        # After the window the screen path opens again.
        self.now += timedelta(minutes=10, seconds=1)
        self.screen_grant_from("d" * 64)

    def screen_grant_from(self, nonce):
        request = self.request(nonce)
        return self.receiver.confirm(request["request_id"], request["request_secret"],
                                     self.code(request["display_code"]), "fixture")["relationship_id"]

    def test_screen_code_relationship_is_bounded_and_serves_challenge_and_session(self):
        request = self.request()
        decision = self.receiver.confirm(request["request_id"], request["request_secret"], self.code(), "fixture")
        self.assertFalse(decision["persistent"])
        self.assertEqual(self.now + timedelta(hours=168), datetime.fromisoformat(decision["authorization_expires_at"]))
        stored = self.repo.grants()[request["request_id"]]
        self.assertEqual(("screen-code", "screen-code", False), (stored["approved_by"], stored["issuer_source"],
                                                                  stored["persistent"]))
        self.assertEqual("screen-code", self.svc.config["auth"]["peer_pairing"]["audit"][-1]["actor"])
        grant = decision["relationship_id"]
        fields = self.receiver.challenge(grant)["fields"]
        issued = self.receiver.session(grant, fields, self.sign("session-request", fields))
        self.assertEqual("operator", issued["role"])
        self.assertTrue(deps.token_alive(self.svc.config, issued["id"]))
        self.assertEqual("operator", deps.authenticate(self.svc.config, "Bearer " + issued["token"], None).role)
        self.now += timedelta(hours=169)
        with self.assertRaises(Refused):
            self.receiver.challenge(grant)

    def test_role_above_operator_is_forbidden(self):
        request = self.request()
        code = self.code()
        self.receiver._pending[request["request_id"]]["fields"]["role"] = "administrator"
        response = self.client().post(f"/api/v1/auth/peer-pairing/requests/{request['request_id']}/confirm",
                                      json={"approval_code": code},
                                      headers={"X-Request-Secret": request["request_secret"]})
        self.assertEqual(403, response.status_code)
        self.assertEqual({}, self.repo.grants())

    def test_confirm_shares_the_source_rate_limit(self):
        request = self.request()  # the request itself counts against "fixture-lan-peer"
        code = self.code()
        for _ in range(29):  # wrong codes, then a rejected request: refused but not rate limited
            with self.assertRaises(Refused) as refused:
                self.receiver.confirm(request["request_id"], request["request_secret"], self.wrong(code),
                                      "fixture-lan-peer")
            self.assertNotIsInstance(refused.exception, RateLimited)
        with self.assertRaises(RateLimited):
            self.receiver.confirm(request["request_id"], request["request_secret"], code, "fixture-lan-peer")


if __name__ == "__main__":
    unittest.main()
