"""Physical approval records belong to the existing atomic job migration."""


def ensure(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS fleet_physical_transfer_approvals (
        mission_id TEXT PRIMARY KEY REFERENCES fleet_cell_jobs(mission_id),
        proposal_digest TEXT NOT NULL CHECK(length(proposal_digest)=64),
        approved_by TEXT NOT NULL,
        approved_at_ns INTEGER NOT NULL CHECK(approved_at_ns>=0),
        claims_acquired_at_ns INTEGER NOT NULL CHECK(claims_acquired_at_ns>=approved_at_ns),
        authority_epoch INTEGER NOT NULL CHECK(authority_epoch>=0),
        dispatch_generation INTEGER NOT NULL CHECK(dispatch_generation>=0)
    )""")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS fleet_physical_request_key "
                       "ON fleet_cell_jobs(proposal_principal_id,request_key) WHERE provenance_kind='physical'")
    connection.execute("""CREATE TABLE IF NOT EXISTS fleet_physical_transfer_attempts (
        mission_id TEXT PRIMARY KEY REFERENCES fleet_physical_transfer_approvals(mission_id),
        step_id TEXT NOT NULL UNIQUE,
        action_id TEXT NOT NULL UNIQUE,
        attempt_id TEXT NOT NULL UNIQUE,
        request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
        grant_json TEXT NOT NULL,
        prepared_at_ns INTEGER NOT NULL CHECK(prepared_at_ns>=0),
        status TEXT NOT NULL CHECK(status IN ('PREPARED','SUBMITTING','ACTION_SUCCEEDED','HOLD','UNKNOWN')),
        CHECK(step_id!=action_id AND step_id!=attempt_id AND action_id!=attempt_id)
    )""")


def hold_for_site_stop(connection, *, now, reason, event):
    """Retain every physical claim; an in-flight outcome needs reconciliation."""
    if "provenance_kind" not in {row[1] for row in connection.execute("PRAGMA table_info(fleet_cell_jobs)")}:
        return  # A pre-v5 host starts its task journal before migrating the job journal.
    rows = connection.execute("SELECT mission_id FROM fleet_cell_jobs WHERE provenance_kind='physical' "
                              "AND status IN ('READY','RUNNING','ACTION_SUCCEEDED')").fetchall()
    for row in rows:
        mission_id = row["mission_id"]
        connection.execute("UPDATE fleet_cell_jobs SET status='HOLD',reason=?,updated_at=? WHERE mission_id=?",
                           (reason, now, mission_id))
        connection.execute("UPDATE fleet_action_claims SET phase=CASE phase WHEN 'DISPATCHING' THEN 'UNKNOWN' "
                           "WHEN 'CLAIMED' THEN 'HELD' ELSE phase END,lease_until=NULL "
                           "WHERE owner_kind='mission' AND owner_id=?", (mission_id,))
        event(connection, mission_id, None, "PHYSICAL_TRANSFER_HELD", "site-stop", {"reason": reason})
