"""Local profile selection; reuses the case journal and grants no provider authority."""
from rosy.decision.deliberation import identifier
from .ledger.contract import sha256


def profile_route(conn, owner_id, policy_revision):
    identifier(owner_id); identifier(policy_revision)
    row = conn.execute('SELECT current,previous,revision FROM fleet_incident_v2_profile_routes '
                       'WHERE owner_id=? AND policy_revision=?', (owner_id, policy_revision)).fetchone()
    if row is None: return None
    sha256(row[0])
    if row[1] is not None: sha256(row[1])
    if type(row[2]) is not int or row[2] < 1: raise ValueError('INVALID_PROFILE_ROUTE')
    return dict(current=row[0], previous=row[1], revision=row[2])


class IncidentProfileRoutes:
    def __init__(self, store):
        self.store = store

    def profile_route(self, owner_id, policy_revision):
        with self.store._transaction() as conn: return profile_route(conn, owner_id, policy_revision)

    def _select(self, owner_id, policy_revision, target, expected_revision, *, rollback=False):
        if type(expected_revision) is not int or not 0 <= expected_revision < 2**63 - 1:
            raise ValueError('EXPLICIT_ROUTE_REVISION_REQUIRED')
        with self.store._transaction() as conn:
            prior = profile_route(conn, owner_id, policy_revision)
            if (prior['revision'] if prior else 0) != expected_revision: raise ValueError('PROFILE_ROUTE_CHANGED')
            if rollback:
                if prior is None or prior['previous'] is None: raise ValueError('PREVIOUS_PROFILE_REQUIRED')
                target = prior['previous']
            sha256(target)
            if prior and target == prior['current']: raise ValueError('PROFILE_ALREADY_SELECTED')
            result = dict(current=target, previous=prior['current'] if prior else None, revision=expected_revision + 1)
            conn.execute('INSERT INTO fleet_incident_v2_profile_routes VALUES (?,?,?,?,?) '
                         'ON CONFLICT(owner_id,policy_revision) DO UPDATE SET '
                         'current=excluded.current,previous=excluded.previous,revision=excluded.revision',
                         (owner_id, policy_revision, result['current'], result['previous'], result['revision']))
            return result

    def select_profile(self, owner_id, policy_revision, profile_sha256, *, expected_revision):
        return self._select(owner_id, policy_revision, profile_sha256, expected_revision)

    def rollback_profile(self, owner_id, policy_revision, *, expected_revision):
        return self._select(owner_id, policy_revision, None, expected_revision, rollback=True)
