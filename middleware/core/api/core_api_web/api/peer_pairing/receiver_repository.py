"""HTTP-auth owner adapter: existing token records, one overlay replacement."""
import copy
from datetime import datetime, timedelta, timezone
import json
import threading

import yaml

from core_api_web.api import deps
from core_common.config import patch_local_config as patch_locked
from core_common.config_transaction import transaction


from core_common.protocol.peer_pairing import RepositoryDenied, Relationship, SCREEN_CODE_ISSUER, screen_code_dated


class OverlayRepository:
    def __init__(self, svc, path, clock=lambda: datetime.now(timezone.utc)):
        self.svc, self.path, self.clock = svc, path, clock
        self._base = copy.deepcopy(svc.config)
        self._base.setdefault('auth', {}).pop('peer_pairing', None)
        if path.exists():
            initial = yaml.safe_load(path.read_text(encoding='utf8'))
            if not isinstance(initial, dict):
                raise RepositoryDenied('invalid overlay')
            if 'tokens' in initial.get('auth', {}):
                self._base['auth']['tokens'] = []  # Overlay-owned issuers cannot become lower-layer fallback.

    def _document(self):
        if self.path.exists():
            document = yaml.safe_load(self.path.read_text(encoding="utf8"))
            if not isinstance(document, dict):
                raise RepositoryDenied("invalid overlay")
            from core_common.config import _deep_merge
            merged = _deep_merge(copy.deepcopy(self._base), document)
            # Existing configured/card issuers can come from lower config layers.
            # Our own relationship store is overlay-owned, never memory-restored.
            if 'peer_pairing' not in document.get('auth', {}):
                merged.setdefault('auth', {}).pop('peer_pairing', None)
            return merged
        return copy.deepcopy(self._base)

    def _owner(self, config, token_id):
        record = next((r for r in deps.auth_entries(config) if r["id"] == token_id), None)
        if (not record or record["role"] != "administrator" or record["legacy"] or
                record["source"] in {"legacy", "pair-development"} or record["digest"] in deps.DEV_TOKEN_DIGESTS):
            raise RepositoryDenied("existing receiver administrator required")
        raw = next((r for r in config.get("auth", {}).get("tokens", [])
                    if isinstance(r, dict) and r.get("id") == token_id), None)
        if raw is None or raw.get("source") != record["source"]:
            raise RepositoryDenied("issuer provenance unavailable")
        expiry = record.get("expires_at")
        if expiry and datetime.fromisoformat(expiry) <= self.clock():
            raise RepositoryDenied("issuer expired")
        return record

    def owner(self, token_id):
        with deps.TOKEN_WRITE_LOCK, transaction(self.path):
            return self._owner(self._document(), token_id)

    def grants(self):
        with deps.TOKEN_WRITE_LOCK, transaction(self.path):
            document = self._document()
        state = document.get("auth", {}).get("peer_pairing", {})
        if not isinstance(state, dict) or state.get("schema", "rosy.peer-grants/1") != "rosy.peer-grants/1":
            raise RepositoryDenied("invalid relationship store")
        grants = state.get("grants", {})
        if not isinstance(grants, dict) or len(grants) > 128:
            raise RepositoryDenied("invalid relationship records")
        try:
            if any(not isinstance(v, dict) or k != v.get("id") for k, v in grants.items()):
                raise RepositoryDenied("invalid relationship identity")
            return {k: Relationship(**v).model_dump() for k, v in grants.items()}
        except (ValueError, TypeError) as exc:
            raise RepositoryDenied("invalid relationship record") from exc

    def update(self, mutate, action, actor_id=None, grant_id=None, actor=None):
        with deps.TOKEN_WRITE_LOCK, transaction(self.path):
            document = self._document()
            auth = document.setdefault("auth", {})
            state = copy.deepcopy(auth.get("peer_pairing", {"schema": "rosy.peer-grants/1", "grants": {}}))
            if state.get("schema") != "rosy.peer-grants/1" or not isinstance(state.get("grants"), dict):
                raise RepositoryDenied("invalid relationship store")
            tokens = [r for r in deps.auth_entries(document) if not deps.is_expired(r, self.clock())]
            result = mutate(state["grants"], tokens, document)
            pruned = []
            if len(state["grants"]) > 128:
                # D-483 M2: routine 168 h re-approval must not fill the cap. Only dead rows go:
                # expired or revoked, with no live child session, never the row being changed.
                live = {r["id"] for r in tokens}
                pruned = [k for k, g in state["grants"].items() if k != grant_id
                          and (g.get("revoked") or (g.get("expires_at") is not None
                               and datetime.fromisoformat(g["expires_at"]) <= self.clock()))
                          and not live & set(g.get("session_ids", []))]
                for key in pruned:
                    del state["grants"][key]
            if len(state["grants"]) > 128:
                raise RepositoryDenied("relationship capacity reached")
            try:
                if any(not isinstance(v, dict) or k != v.get("id") for k, v in state["grants"].items()):
                    raise RepositoryDenied("invalid relationship identity")
                state["grants"] = {k: Relationship(**v).stored() for k, v in state["grants"].items()}
            except (ValueError, TypeError) as exc:
                raise RepositoryDenied("invalid relationship record") from exc
            stored = deps.stored_token_entries(tokens)
            grant = state["grants"].get(grant_id, {})
            if actor is None:
                actor = deps.principal_ref(self._owner(document, actor_id)) if actor_id else "receiver:key-proof"
            removed = [{"at": self.clock().isoformat(), "actor": "receiver:capacity", "action": "relationship_pruned",
                        "relationship_id": key, "generation": None, "relationship_count": len(state["grants"])}
                       for key in pruned]
            state["audit"] = (state.get("audit", []) + removed + [{"at": self.clock().isoformat(), "actor": actor,
                              "action": action, "relationship_id": grant_id, "generation": grant.get("generation"),
                              "relationship_count": len(state["grants"])}])[-256:]
            # Relationships are retained on expiry/revoke; only a capacity prune removes rows.
            patch_locked({"auth": {"tokens": stored, "peer_pairing": state}}, self.path,
                         replace=("auth", "peer_pairing", "grants") if pruned else ())
            self.svc.config["auth"] = dict(auth, tokens=stored, peer_pairing=state)
            return result

    def approve(self, token_id, relationship, request_deadline):
        def change(grants, tokens, document):
            if self.clock() >= request_deadline:
                raise RepositoryDenied('request expired before approval')
            issuer = self._owner(document, token_id)
            relationship["issuer_id"] = issuer["id"]
            relationship["approved_by"] = deps.principal_ref(issuer)
            relationship["issuer_source"] = issuer["source"]
            relationship["issuer_digest"] = issuer["digest"]
            relationship["persistent"] = bool(relationship["persist_requested"] and
                deps.is_durable_admin(issuer) and issuer["source"] in {"card", "manual"})
            if relationship["persistent"]:
                relationship["expires_at"] = None
            if issuer.get("expires_at"):
                relationship["expires_at"] = deps.expires_before(relationship["expires_at"], issuer["expires_at"])
            if relationship["id"] in grants:
                old = grants[relationship['id']]
                bound = ('receiver_id', 'receiver_key_sha256', 'client_id', 'client_public_key', 'role',
                         'label', 'issuer_id', 'issuer_digest', 'issuer_source', 'persist_requested', 'persistent')
                if old['revoked'] or any(old.get(key) != relationship.get(key) for key in bound):
                    raise RepositoryDenied('stored approval differs')
                return copy.deepcopy(old)  # Lost response never extends an existing approval.
            grants[relationship["id"]] = copy.deepcopy(relationship)
            return copy.deepcopy(relationship)
        return self.update(change, "owner_approved", token_id, relationship["id"])

    def approve_screen_code(self, relationship, request_deadline):
        """D-483 5: the robot-screen code approval; bounded, never persistent, no issuer token."""
        def change(grants, tokens, document):
            if self.clock() >= request_deadline:
                raise RepositoryDenied('request expired before approval')
            if relationship["id"] in grants:
                old = grants[relationship['id']]
                bound = ('receiver_id', 'receiver_key_sha256', 'client_id', 'client_public_key', 'role',
                         'label', 'issuer_id', 'issuer_digest', 'issuer_source', 'persist_requested', 'persistent')
                if old['revoked'] or any(old.get(key) != relationship.get(key) for key in bound):
                    raise RepositoryDenied('stored approval differs')
                return copy.deepcopy(old)
            grants[relationship["id"]] = copy.deepcopy(relationship)
            return copy.deepcopy(relationship)
        return self.update(change, "screen_code_approved", grant_id=relationship["id"], actor=SCREEN_CODE_ISSUER)

    def issue(self, grant_id, challenge_id, receiver_fingerprint, expected_grant):
        def change(grants, tokens, document):
            grant = grants.get(grant_id)
            if not grant or grant["revoked"] or grant["receiver_key_sha256"] != receiver_fingerprint:
                raise RepositoryDenied("relationship unavailable")
            fields = ("generation", "client_public_key", "role", "receiver_key_sha256", "issuer_id", "expires_at",
                      "client_id", "receiver_id", "persistent", "issuer_digest", "issuer_source")
            if any(grant.get(key) != expected_grant.get(key) for key in fields):
                raise RepositoryDenied("relationship changed during proof")
            if grant["issuer_source"] == SCREEN_CODE_ISSUER:
                if not screen_code_dated(grant, self.clock()):
                    raise RepositoryDenied("screen-code approval dated in the future")
                issuer = {"id": SCREEN_CODE_ISSUER}  # D-483 5: bounded by the relationship's own expiry only.
            else:
                issuer = self._owner(document, grant["issuer_id"])
                if issuer["digest"] != grant["issuer_digest"] or issuer["source"] != grant["issuer_source"]:
                    raise RepositoryDenied("issuer identity changed")
            if grant["persistent"] and (not deps.is_durable_admin(issuer) or issuer["source"] not in {"card", "manual"}):
                raise RepositoryDenied("persistent issuer authority changed")
            if ((grant["expires_at"] is not None and datetime.fromisoformat(grant["expires_at"]) <= self.clock())
                    or challenge_id in grant["used_challenges"]):
                raise RepositoryDenied("relationship or challenge expired")
            expiry = deps.expires_before((self.clock() + timedelta(hours=1)).isoformat(), grant["expires_at"])
            expiry = deps.expires_before(expiry, issuer.get("expires_at"))
            token = deps.generate_token()
            record = deps.new_token_record(token, grant["role"], grant["label"], source="pair-admin",
                                           expires_at=expiry, paired_via=issuer["id"])
            record['peer_binding'] = {'relationship_id': grant_id, 'generation': grant['generation']}
            tokens.append(record)
            grant["used_challenges"] = (grant["used_challenges"] + [challenge_id])[-64:]
            grant["session_ids"] = [item for item in grant.get("session_ids", [])
                                    if any(r["id"] == item and not deps.is_expired(r) for r in tokens)]
            if len(grant["session_ids"]) >= 8:
                raise RepositoryDenied("active session limit reached")
            grant["session_ids"].append(record["id"])
            return {"id": record["id"], "token": token, "role": grant["role"], "expires_at": expiry}
        return self.update(change, "session_issued", grant_id=grant_id)

    def revoke_issuer(self, token_id):
        def change(grants, tokens, document):
            children = {session for grant in grants.values() if grant["issuer_id"] == token_id
                        for session in grant.get("session_ids", [])}
            tokens[:] = [r for r in tokens if r["id"] != token_id and r["id"] not in children]
        self.update(change, "issuer_revoked")

    def revoke(self, token_id, grant_id):
        def change(grants, tokens, document):
            self._owner(document, token_id)
            grant = grants.get(grant_id)
            if not grant or grant["revoked"]:
                raise RepositoryDenied("relationship unavailable")
            grant["revoked"] = True
            grant["generation"] += 1
            tokens[:] = [r for r in tokens if r["id"] not in grant.get("session_ids", [])]
            return {"relationship_id": grant_id, "state": "revoked", "generation": grant["generation"]}
        return self.update(change, "owner_revoked", token_id, grant_id)
