"""Compose the existing incident ports in Fleet's journal; no default admission."""
import asyncio
import time

from .store import IncidentCaseStore
from .observation import IncidentObservationPort
from .worker import IncidentCaseWorker


def install_incident_runtime(app, config):
    if config is None:
        return None
    loop = getattr(app.state, 'stuck_resolver', None)
    if type(config) is not dict or loop is None or loop._board._log is None:
        raise ValueError('EXISTING_INCIDENT_JOURNAL_AND_LOOP_REQUIRED')
    log = loop._board._log
    if loop.incident_worker is not None:
        raise ValueError('EXISTING_INCIDENT_JOURNAL_AND_EMPTY_WORKER_REQUIRED')
    clock = config.get('clock', time.time)
    def human_owned(robot_id, case_id):
        return log.handoff.get(robot_id, case_id) is not None or loop._resolver.is_claimed(robot_id, case_id)
    async def final_handoff(scope, summary):
        return await asyncio.to_thread(log.notifications.enqueue_final, scope, summary, now=clock())
    worker = IncidentCaseWorker(IncidentCaseStore(log.path, clock=clock),
        IncidentObservationPort(loop._board, human_owned=human_owned, clock=clock), loop._board,
        human_owned=human_owned, final_handoff=final_handoff, **config)
    log.notifications.set_automation(worker.prepare_receipt)
    loop.incident_worker = worker
    return worker
