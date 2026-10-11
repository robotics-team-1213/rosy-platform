"""Compose the existing incident ports in Fleet's journal; no default admission."""
import asyncio
import time

from .store import IncidentCaseStore
from .observation import IncidentObservationPort
from .worker import IncidentCaseWorker


def install_incident_runtime(loop, *, profiles, providers, admission, current_profiles,
                             budget, enabled=False, baseline=None, clock=time.time):
    log = loop._board._log
    if log is None or loop.incident_worker is not None:
        raise ValueError('EXISTING_INCIDENT_JOURNAL_AND_EMPTY_WORKER_REQUIRED')
    def human_owned(robot_id, case_id):
        return log.handoff.get(robot_id, case_id) is not None or loop._resolver.is_claimed(robot_id, case_id)
    async def final_handoff(scope, summary):
        return await asyncio.to_thread(log.notifications.enqueue_final, scope, summary, now=clock())
    worker = IncidentCaseWorker(IncidentCaseStore(log.path, clock=clock),
        IncidentObservationPort(loop._board, human_owned=human_owned, clock=clock), loop._board,
        profiles=profiles, providers=providers, admission=admission, current_profiles=current_profiles,
        human_owned=human_owned, budget=budget, final_handoff=final_handoff,
        enabled=enabled, baseline=baseline, clock=clock)
    log.notifications.set_automation(worker.prepare_receipt)
    loop.incident_worker = worker
    return worker
