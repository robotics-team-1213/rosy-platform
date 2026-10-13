"""Named Console review and references to existing Fleet work; no dispatch."""
import json
import sqlite3
from contextlib import closing

from fastapi import Depends, HTTPException

from core_common.protocol.channel_requests import (
    ChannelNavigationCandidate, ChannelReviewRequest, ChannelSubmitRequest, ChannelTaskLinkRequest, ChannelWorkflowView,
)
from ..task_store import IdempotencyConflict


class ChannelWorkflow:
    def __init__(self, journal, *, task_store):
        if journal.path.resolve() != task_store.path.resolve():
            raise ValueError('Discord workflow requires the existing tasks DB')
        self.journal, self.task_store = journal, task_store
        with closing(journal._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_workflow (
                request_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL,
                candidate TEXT, reason TEXT, work_id TEXT)''')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(fleet_channel_workflow)')}
            for name, definition in [('work_kind', "TEXT NOT NULL DEFAULT 'task'"), ('preparation_digest', 'TEXT')]:
                if name not in columns:
                    conn.execute(f'ALTER TABLE fleet_channel_workflow ADD COLUMN {name} {definition}')

    def _receipt(self, conn, request_id, principal):
        self.journal.operator(principal)
        row = conn.execute("SELECT receipt FROM fleet_channel_requests WHERE principal_id=? "
                           "AND json_extract(receipt, '$.request_id')=?", (principal, request_id)).fetchone()
        if row is None:
            raise HTTPException(404, detail='CHANNEL_REQUEST_NOT_FOUND')
        receipt = json.loads(row[0])
        self.journal.current_receipt(receipt)
        return receipt

    def _view(self, conn, receipt):
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM fleet_channel_workflow WHERE request_id=?',
                           (receipt['request_id'],)).fetchone()
        value = {'request_id': receipt['request_id'], 'content_hash': receipt['content_hash'],
                 'revision': 0, 'state': 'REQUESTED', 'candidate': None, 'reason': None, 'work_id': None}
        if row is not None:
            value.update({key: row[key] for key in value if key in row.keys()})
            value['candidate'] = json.loads(row['candidate']) if row['candidate'] else None
        value.update(work_kind=row['work_kind'] if value['work_id'] else None, work_status=None,
                     request_key='discord-' + receipt['request_id'])
        if value['work_id']:
            if value['work_kind'] == 'incident':
                from .incidents import incident_view
                value['incident'], value['work_status'] = incident_view(conn, receipt['request_id'], receipt['principal_id'])
                return value
            table, key = {'task': ('fleet_tasks', 'task_id'), 'mission': ('fleet_missions', 'mission_id'),
                          'cell_job': ('fleet_cell_jobs', 'mission_id')}[value['work_kind']]
            work = conn.execute(f'SELECT status FROM {table} WHERE {key}=?', (value['work_id'],)).fetchone()
            value['work_status'] = work[0] if work else 'UNKNOWN'
        return value

    def read(self, request_id, principal):
        with closing(self.journal._connect()) as conn:
            return self._view(conn, self._receipt(conn, request_id, principal))

    async def submit(self, request_id, principal, *, task_service, expected_hash, expected_revision):
        if task_service.store.path.resolve() != self.journal.path.resolve():
            raise ValueError('Discord admission requires the existing tasks DB')
        snapshot = self.read(request_id, principal)
        goal = snapshot['candidate']
        if goal is None:
            raise HTTPException(409, detail='CHANNEL_REVIEW_NOT_READY')

        def admission(conn, task_id):
            receipt = self._receipt(conn, request_id, principal)
            current = self._view(conn, receipt)
            if current['state'] == 'LINKED' and current['work_id'] == task_id:
                self._check({**current, 'revision': current['revision'] - 1}, expected_hash, expected_revision)
                return
            self._check(current, expected_hash, expected_revision)
            if current['state'] != 'READY' or current['candidate'] != goal:
                raise HTTPException(409, detail='CHANNEL_REVIEW_NOT_READY')
            # The existing Task insertion and its review reservation commit together.
            conn.execute("UPDATE fleet_channel_workflow SET revision=revision+1, state='LINKED', work_id=? "
                         "WHERE request_id=?", (task_id, request_id))
            if self.journal.reply_outbox is not None:
                self.journal.reply_outbox.enqueue(
                    conn, receipt, 'LINKED', f"ROSY 작업 원장 연결 · {request_id}\nTask {task_id}"
                    " · 장치 실행 완료를 의미하지 않습니다.")

        await task_service.submit_navigation(robot_id=goal['robot_id'], x=goal['x'], y=goal['y'], yaw=goal['yaw'],
                                             source='operator', actor_id=principal, request_key=snapshot['request_key'],
                                             admission=admission)
        return self.read(request_id, principal)

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
            conn.execute('''INSERT INTO fleet_channel_workflow
                (request_id, revision, state, candidate, reason, work_id) VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(request_id) DO UPDATE SET revision=excluded.revision,
                state=excluded.state, candidate=excluded.candidate, reason=excluded.reason''',
                         (request_id, value['revision'] + 1, state,
                          json.dumps(candidate) if candidate else None, reason.strip()))
            if self.journal.reply_outbox is not None:
                self.journal.reply_outbox.enqueue(
                    conn, receipt, f"REVIEW:{value['revision'] + 1}",
                    f"ROSY 요청 검토 · {request_id}\n{state} · 실행 요청 전입니다."
                    " 자세한 검토 사유는 Fleet Console에서 확인하세요.")
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
            if self.journal.reply_outbox is not None:
                self.journal.reply_outbox.enqueue(
                    conn, receipt, 'LINKED', f"ROSY 작업 원장 연결 · {request_id}\nTask {task_id}"
                    " · 장치 실행 완료를 의미하지 않습니다.")
            return self._view(conn, receipt)


def install_workflow_routes(app, workflow, *, require_operator, read_guard, task_service=None, console=None):
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

    @app.post('/api/fleet/channel-requests/{request_id}/submit', dependencies=read_guard,
              response_model=ChannelWorkflowView, tags=['fleet-work'])
    async def submit_request(request_id: str, body: ChannelSubmitRequest, principal=Depends(require_operator)):
        if task_service is None:
            raise HTTPException(503, detail='CHANNEL_TASK_SERVICE_REQUIRED')
        snapshot = workflow.read(request_id, principal.principal_id)
        if console is not None and snapshot['candidate'] and console.trip_busy(snapshot['candidate']['robot_id']):
            raise HTTPException(409, detail='TRIP_ROBOT_BUSY')
        try:
            return await workflow.submit(request_id, principal.principal_id,
                                         task_service=task_service, **body.model_dump())
        except IdempotencyConflict:
            raise HTTPException(409, detail='CHANNEL_TASK_PROVENANCE_MISMATCH') from None
        except ValueError as error:
            raise HTTPException(404 if str(error) == 'UNKNOWN_ROBOT' else 400, detail=str(error)) from None
