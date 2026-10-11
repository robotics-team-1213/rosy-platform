"""Named Console review and references to existing Fleet work; no dispatch."""
import json
import sqlite3
from contextlib import closing

from fastapi import Depends, HTTPException

from core_common.protocol.channel_requests import (
    ChannelNavigationCandidate, ChannelReviewRequest, ChannelTaskLinkRequest, ChannelWorkflowView,
)


class ChannelWorkflow:
    def __init__(self, journal, *, task_store):
        if journal.path.resolve() != task_store.path.resolve():
            raise ValueError('Discord workflow requires the existing tasks DB')
        self.journal, self.task_store = journal, task_store
        with closing(journal._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_workflow (
                request_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL,
                candidate TEXT, reason TEXT, work_id TEXT)''')

    def _receipt(self, conn, request_id, principal):
        self.journal.operator(principal)
        row = conn.execute("SELECT receipt FROM fleet_channel_requests WHERE principal_id=? "
                           "AND json_extract(receipt, '$.request_id')=?", (principal, request_id)).fetchone()
        if row is None:
            raise HTTPException(404, detail='CHANNEL_REQUEST_NOT_FOUND')
        receipt = json.loads(row[0])
        cfg = self.journal.config
        if (cfg.users.get(receipt['author_id']) != principal or receipt['guild_id'] != cfg.guild_id
                or receipt['channel_id'] != cfg.channel_id):
            raise HTTPException(403, detail='CHANNEL_OWNER_CHANGED')
        return receipt

    def _view(self, conn, receipt):
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM fleet_channel_workflow WHERE request_id=?',
                           (receipt['request_id'],)).fetchone()
        value = {'request_id': receipt['request_id'], 'content_hash': receipt['content_hash'],
                 'revision': 0, 'state': 'REQUESTED', 'candidate': None, 'reason': None, 'work_id': None}
        if row is not None:
            value.update(dict(row))
            value['candidate'] = json.loads(row['candidate']) if row['candidate'] else None
        value.update(work_kind='task' if value['work_id'] else None, work_status=None,
                     request_key='discord-' + receipt['request_id'])
        if value['work_id']:
            task = conn.execute('SELECT status FROM fleet_tasks WHERE task_id=?', (value['work_id'],)).fetchone()
            value['work_status'] = task[0] if task else 'UNKNOWN'
        return value

    def read(self, request_id, principal):
        with closing(self.journal._connect()) as conn:
            return self._view(conn, self._receipt(conn, request_id, principal))

    @staticmethod
    def _check(value, expected_hash, expected_revision):
        if (expected_hash != value['content_hash'] or type(expected_revision) is not int
                or expected_revision < 0 or expected_revision != value['revision']):
            raise HTTPException(409, detail='CHANNEL_REVIEW_CHANGED')

    def review(self, request_id, principal, *, expected_hash, expected_revision, state, candidate=None, reason):
        if state not in {'READY', 'HOLD', 'REJECTED'} or type(reason) is not str or not 1 <= len(reason.strip()) <= 256:
            raise ValueError('invalid channel review')
        if state == 'READY':
            candidate = ChannelNavigationCandidate.model_validate(candidate).model_dump()
        elif candidate is not None:
            raise ValueError('only READY review can contain a navigation candidate')
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(conn, request_id, principal)
            value = self._view(conn, receipt)
            self._check(value, expected_hash, expected_revision)
            existing = conn.execute('SELECT 1 FROM fleet_tasks WHERE source=? AND actor_id=? AND request_key=?',
                                    ('operator', principal, value['request_key'])).fetchone()
            if value['state'] == 'LINKED' or existing:
                raise HTTPException(409, detail='CHANNEL_WORK_ALREADY_SUBMITTED')
            conn.execute('''INSERT INTO fleet_channel_workflow VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(request_id) DO UPDATE SET revision=excluded.revision,
                state=excluded.state, candidate=excluded.candidate, reason=excluded.reason''',
                         (request_id, value['revision'] + 1, state,
                          json.dumps(candidate) if candidate else None, reason.strip()))
            return self._view(conn, receipt)


    def link_task(self, request_id, principal, *, task_id, expected_hash, expected_revision):
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(conn, request_id, principal)
            value = self._view(conn, receipt)
            if value['state'] == 'LINKED' and value['work_id'] == task_id and expected_hash == receipt['content_hash']:
                return value
            self._check(value, expected_hash, expected_revision)
            if value['state'] != 'READY':
                raise HTTPException(409, detail='CHANNEL_REVIEW_NOT_READY')
            task = conn.execute('SELECT * FROM fleet_tasks WHERE task_id=?', (task_id,)).fetchone()
            if task is None:
                raise HTTPException(404, detail='CHANNEL_TASK_NOT_FOUND')
            if task['actor_id'] != principal or task['source'] != 'operator':
                raise HTTPException(403, detail='CHANNEL_TASK_OWNER_REQUIRED')
            goal = value['candidate']
            request = {'goal': {key: goal[key] for key in ('x', 'y', 'yaw')}}
            if (task['request_key'] != value['request_key'] or task['robot_id'] != goal['robot_id']
                    or task['task_type'] != 'navigate' or json.loads(task['request_json']) != request):
                raise HTTPException(409, detail='CHANNEL_TASK_PROVENANCE_MISMATCH')
            conn.execute("UPDATE fleet_channel_workflow SET revision=revision+1, state='LINKED', work_id=? "
                         "WHERE request_id=?", (task_id, request_id))
            return self._view(conn, receipt)



def install_workflow_routes(app, workflow, *, require_operator, read_guard):
    @app.get('/api/fleet/channel-requests/{request_id}/review', dependencies=read_guard,
             response_model=ChannelWorkflowView, tags=['fleet-work'])
    def read_review(request_id: str, principal=Depends(require_operator)):
        return workflow.read(request_id, principal.principal_id)

    @app.put('/api/fleet/channel-requests/{request_id}/review', dependencies=read_guard,
             response_model=ChannelWorkflowView, tags=['fleet-work'])
    def review_request(request_id: str, body: ChannelReviewRequest, principal=Depends(require_operator)):
        return workflow.review(request_id, principal.principal_id, **body.model_dump())

    @app.post('/api/fleet/channel-requests/{request_id}/task', dependencies=read_guard,
              response_model=ChannelWorkflowView, tags=['fleet-work'])
    def link_task(request_id: str, body: ChannelTaskLinkRequest, principal=Depends(require_operator)):
        return workflow.link_task(request_id, principal.principal_id, **body.model_dump())

