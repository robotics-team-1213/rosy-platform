"""Read-only work metadata through the owning Fleet store's connection port."""

from contextlib import closing


def work_summaries(store, *, source: str, limit: int, principal_id: str | None = None) -> list[dict]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 101:
        raise ValueError("work summary limit must be 1..101")
    if source == "task":
        query = ("SELECT task_id AS source_id, task_type AS action_kind, status, "
                 "robot_id AS device_id, reason, updated_at FROM fleet_tasks "
                 "ORDER BY updated_at DESC, task_id DESC LIMIT ?")
        params = (limit,)
    elif source == "mission" and principal_id:
        query = ("SELECT m.mission_id AS source_id, m.action_kind, m.status, "
                 "m.instance_id AS device_id, m.workcell_id, m.reason, m.updated_at "
                 "FROM fleet_missions m WHERE m.principal_id=? AND EXISTS "
                 "(SELECT 1 FROM fleet_proposals p WHERE p.proposal_id=m.mission_id "
                 "AND p.principal_id=? AND p.state='RESOLVED') "
                 "ORDER BY m.updated_at DESC, m.mission_id DESC LIMIT ?")
        params = (principal_id, principal_id, limit)
    else:
        raise ValueError("work summary requires a known source and Mission owner")
    with closing(store._connect()) as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]
