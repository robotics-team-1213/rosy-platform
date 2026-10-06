"""Read-only policy for HTTP and live-socket checks of relationship sessions."""
from datetime import datetime, timezone

from core_common.protocol.peer_pairing import Relationship, SCREEN_CODE_ISSUER


def session_allowed(config, record, records):
    if 'peer_binding' not in record:
        return True  # Ordinary D193 records are unchanged.
    binding = record['peer_binding']
    if (not isinstance(binding, dict) or set(binding) != {'relationship_id', 'generation'}
            or not isinstance(binding['relationship_id'], str)
            or type(binding['generation']) is not int or binding['generation'] < 0):
        return False
    state = config.get("auth", {}).get("peer_pairing", {})
    if not isinstance(state, dict) or state.get("schema") != "rosy.peer-grants/1":
        return False
    grants = state.get("grants", {})
    if not isinstance(grants, dict):
        return False
    try:
        grant = Relationship(**grants[binding['relationship_id']]).model_dump()
        if (grant['id'] != binding['relationship_id'] or grant['generation'] != binding['generation']
                or record['id'] not in grant['session_ids']):
            return False
        now = datetime.now(timezone.utc)
        if (grant["revoked"] or (grant["expires_at"] is not None and
                datetime.fromisoformat(grant["expires_at"]) <= now)):
            return False
        if grant["issuer_source"] == SCREEN_CODE_ISSUER:
            # D-483 5: no issuer token; the model already pins the bounded, non-persistent shape.
            return record["role"] == grant["role"] and record["paired_via"] == SCREEN_CODE_ISSUER
        issuer = next(r for r in records if r["id"] == grant["issuer_id"])
        from core_api_web.api import deps
        if (issuer["role"] != "administrator" or issuer["legacy"] or deps.is_expired(issuer, now)
                or issuer["digest"] != grant["issuer_digest"] or issuer["source"] != grant["issuer_source"]
                or issuer["digest"] in deps.DEV_TOKEN_DIGESTS):
            return False
        if record["role"] != grant["role"] or record["paired_via"] != issuer["id"]:
            return False
        if grant["persistent"] and (not grant["persist_requested"] or
                not deps.is_durable_admin(issuer) or issuer["source"] not in {"card", "manual"}):
            return False
        return True
    except (ValueError, TypeError, StopIteration, KeyError):
        return False
