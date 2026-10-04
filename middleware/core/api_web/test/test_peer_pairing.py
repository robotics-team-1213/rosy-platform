"""Actual cryptography, disk overlay and HTTP consent/session integration."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
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
from core_api_web.api.peer_pairing.receiver_service import PeerReceiver, Refused
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

    def request(self, nonce="a" * 64):
        info = self.receiver.identity()
        fields = {"receiver_id": info["receiver_id"], "receiver_key_sha256": info["receiver_key_sha256"],
                  "client_id": "tablet-a", "label": "Tablet", "client_public_key": self.pub,
                  "role": "operator", "nonce": nonce}
        return self.receiver.request(fields, self.sign("request", fields), "fixture-lan-peer")

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
        for n in range(15):
            self.request(f"{n+1:064x}")
        with self.assertRaises(Refused):
            self.request("f" * 64)
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

    def test_explicit_revoke_cancels_issued_sessions_and_four_session_limit(self):
        _, grant = self.grant()
        ids = []
        for _ in range(4):
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


if __name__ == "__main__":
    unittest.main()
