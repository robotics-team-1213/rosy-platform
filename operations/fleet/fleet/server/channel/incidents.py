"""Discord relation admission delegates to the existing current-incident owner."""
import hashlib
import json
from contextlib import closing

from fastapi import Depends, HTTPException

from core_common.protocol.channel_requests import ChannelIncidentClaimRequest, ChannelWorkflowView
from ..console_routes import LineStuckClaimRequest


def incident_view(conn, request_id, principal):
    row = conn.execute('''SELECT i.robot_id, i.stuck_id, i.judgment_revision,
        e.stuck_id AS episode, e.closed_at, c.principal_id FROM fleet_channel_incidents i
        LEFT JOIN fleet_line_stuck_episodes e USING(robot_id, stuck_id)
        LEFT JOIN fleet_incident_claims c USING(robot_id, stuck_id) WHERE i.request_id=?''', (request_id,)).fetchone()
    if row is None:
        return None, 'UNKNOWN'
    reference = {key: row[key] for key in ('robot_id', 'stuck_id', 'judgment_revision')}
    status = ('UNKNOWN' if row['episode'] is None or row['principal_id'] != principal else
              'CLOSED' if row['closed_at'] is not None else 'CLAIMED')
    return reference, status


def install_channel_incident_routes(app, workflow, *, require_operator, read_guard):
    log = app.state.line_stuck._log
    if log is not None and log.path.resolve() != workflow.journal.path.resolve():
        raise ValueError('Discord incident admission requires the existing shared Fleet DB')
    with closing(workflow.journal._connect()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_incidents (
            request_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL,
            judgment_revision TEXT NOT NULL)''')

    @app.post('/api/fleet/channel-requests/{request_id}/incident', dependencies=read_guard,
              response_model=ChannelWorkflowView, tags=['fleet-work'])
    async def claim(request_id: str, body: ChannelIncidentClaimRequest, principal=Depends(require_operator)):
        value = workflow.read(request_id, principal.principal_id)
        owner = getattr(app.state, 'claim_incident', None)
        if log is None or owner is None:
            raise HTTPException(503, detail='CHANNEL_INCIDENT_OWNER_UNAVAILABLE')
        digest = hashlib.sha256(json.dumps(body.model_dump(exclude={'expected_revision'}),
                                           sort_keys=True, allow_nan=False).encode()).hexdigest()
        if value['state'] == 'LINKED':
            with closing(workflow.journal._connect()) as conn:
                saved = conn.execute('SELECT preparation_digest FROM fleet_channel_workflow WHERE request_id=?',
                                     (request_id,)).fetchone()[0]
            workflow._check({**value, 'revision': value['revision'] - 1}, body.expected_hash, body.expected_revision)
            if value['work_kind'] != 'incident' or saved != digest:
                raise HTTPException(409, detail='CHANNEL_WORK_ALREADY_SUBMITTED')
            return value
        workflow._check(value, body.expected_hash, body.expected_revision)

        def admission(conn):
            receipt = workflow._receipt(conn, request_id, principal.principal_id)
            current = workflow._view(conn, receipt)
            workflow._check(current, body.expected_hash, body.expected_revision)
            if current['state'] == 'LINKED':
                raise HTTPException(409, detail='CHANNEL_WORK_ALREADY_SUBMITTED')
            conn.execute('INSERT INTO fleet_channel_incidents VALUES (?, ?, ?, ?)',
                         (request_id, body.robot_id, body.stuck_id, body.judgment_revision))
            conn.execute('''INSERT INTO fleet_channel_workflow
                (request_id, revision, state, candidate, reason, work_id, work_kind, preparation_digest)
                VALUES (?, ?, 'LINKED', NULL, ?, ?, 'incident', ?)
                ON CONFLICT(request_id) DO UPDATE SET revision=excluded.revision, state='LINKED',
                candidate=NULL, reason=excluded.reason, work_id=excluded.work_id,
                work_kind='incident', preparation_digest=excluded.preparation_digest''',
                         (request_id, current['revision'] + 1, body.reason.strip(), request_id, digest))
            if workflow.journal.reply_outbox is not None:
                workflow.journal.reply_outbox.enqueue(conn, receipt, 'LINKED',
                    f'ROSY 사건 담당 인수 · {request_id}\n{body.robot_id} · {body.stuck_id}'
                    ' · 장치 조치·해소는 별도 확인합니다.')

        await owner(body.robot_id, LineStuckClaimRequest(stuck_id=body.stuck_id,
                    judgment_revision=body.judgment_revision), principal, admission=admission)
        return workflow.read(request_id, principal.principal_id)
