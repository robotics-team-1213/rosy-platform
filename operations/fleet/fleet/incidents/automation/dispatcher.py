"""One Fleet loop/outbox owner for installed, independently admitted profile workers."""
import asyncio
import json

from core_common.protocol.schemas import FleetJudgmentReceipt
from rosy.decision.deliberation import canonical
from rosy_situation.snapshot_assessment import POLICY
from rosy_situation.assessment import Assessment
from .contract import CaseScope
from .routing import IncidentProfileRoutes, profile_route
from .worker import IncidentCaseWorker


class IncidentProfileDispatcher:
    def __init__(self, workers):
        if (type(workers) not in (tuple, list) or not 1 <= len(workers) <= 8
                or any(type(w) is not IncidentCaseWorker or w.routed is not True for w in workers)
                or len({w.profile_sha256 for w in workers}) != len(workers)
                or any(w.store is not workers[0].store or w.board is not workers[0].board
                       or w.clock is not workers[0].clock for w in workers)):
            raise ValueError('EXPLICIT_PINNED_WORKERS_REQUIRED')
        self.workers, self.store = tuple(workers), workers[0].store
        self._by_profile = {w.profile_sha256: w for w in workers}
        self._snapshot, self._task, self._shutdown_task, self._closed = None, None, None, False

    @property
    def idle(self):
        return (self._task is None or self._task.done()) and all(w.idle for w in self.workers)

    def prepare_receipt(self, connection, receipt):
        if self._closed: return False
        try:
            data = FleetJudgmentReceipt.model_validate(receipt).model_dump(mode='json')
            request = data['request']
            row = connection.execute('SELECT scope_json FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?',
                                     (request['subject_id'], request['case_id'])).fetchone()
            if row:
                scope = CaseScope(**json.loads(row[0]))
                selected = scope.profile_sha256 if scope.owner_id == 'core' else None
            else:
                route = profile_route(connection, request['owner'], data['policy_revision'])
                selected = route['current'] if route else None
            worker = self._by_profile.get(selected)
            return worker.prepare_receipt(connection, receipt) if worker else False
        except (ValueError, TypeError, KeyError): return False

    def feed(self, snapshot):
        if self._closed: return
        rows = snapshot.get('robots') if type(snapshot) is dict else None
        if type(rows) is not list or len(rows) > 64: raise ValueError('INCIDENT_MAILBOX_LIMIT')
        clean = []
        for row in rows:
            if type(row) is not dict or type(row.get('state') or {}) is not dict:
                raise ValueError('INCIDENT_MAILBOX_LIMIT')
            state = row.get('state') or {}
            clean.append(dict(robot_id=row.get('robot_id'), online=row.get('online'),
                              state={k: state.get(k) for k in ('seq', 'timestamp', 'line_follow')}))
        self._snapshot = json.loads(canonical({'robots': clean}))
        if self._task is None or self._task.done(): self._task = asyncio.create_task(self._drain())

    async def _drain(self):
        while self._snapshot is not None and not self._closed:
            snapshot, self._snapshot = self._snapshot, None
            first = self.workers[0]
            scopes = (*await first._db('active_scopes'), *await first._db('pending_handoffs'))
            route = await asyncio.to_thread(IncidentProfileRoutes(self.store).profile_route, 'core', POLICY.revision)
            grouped = {key: [] for key in self._by_profile}
            for row in snapshot['robots']:
                pinned = tuple(s for s in scopes if s.owner_id == 'core' and s.subject_id == row['robot_id'])
                selected = {s.profile_sha256 for s in pinned}
                assessment = first.board.intervention_assessment(row['robot_id'])
                if route and not (isinstance(assessment, Assessment)
                                  and any(s.case_id == assessment.request.case_id for s in pinned)):
                    selected.add(route['current'])
                for key in selected & grouped.keys(): grouped[key].append(row)
            if self._closed: return
            for key, rows in grouped.items():
                if rows: self._by_profile[key].feed({'robots': rows})

    async def aclose(self):
        if self._shutdown_task is None: self._shutdown_task = asyncio.create_task(self._shutdown())
        cancelled = False
        while not self._shutdown_task.done():
            try: await asyncio.shield(self._shutdown_task)
            except asyncio.CancelledError: cancelled = True
        self._shutdown_task.result()
        if cancelled: raise asyncio.CancelledError

    async def _shutdown(self):
        self._closed, self._snapshot = True, None
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        results = await asyncio.gather(*(w.aclose() for w in self.workers), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException): raise result
