"""Compose the existing incident ports in Fleet's journal; no default admission."""
import asyncio
import time

from .store import IncidentCaseStore
from .observation import IncidentObservationPort
from .worker import IncidentCaseWorker
from .dispatcher import IncidentProfileDispatcher


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
    operating_config = config.get('operating')
    config = {k: v for k, v in config.items() if k != 'operating'}
    variants = config.get('profile_workers')
    if variants is not None:
        if (set(config) - {'profile_workers', 'clock'} or type(variants) not in (tuple, list)
                or not 1 <= len(variants) <= 8 or any(type(v) is not dict or 'clock' in v
                or v.get('routed', True) is not True for v in variants)):
            raise ValueError('EXPLICIT_PROFILE_WORKER_CONFIGS_REQUIRED')
        configs = tuple({**v, 'clock': clock, 'routed': True} for v in variants)
    else: configs = (config,)
    def human_owned(robot_id, case_id):
        return log.handoff.get(robot_id, case_id) is not None or loop._resolver.is_claimed(robot_id, case_id)
    async def final_handoff(scope, summary):
        return await asyncio.to_thread(log.notifications.enqueue_final, scope, summary, now=clock())
    store = IncidentCaseStore(log.path, clock=clock)
    if operating_config is not None:
        from .operating.state import OperationalState
        from rosy.decision.deliberation import identifier
        if (type(operating_config) is not dict or set(operating_config) != {'trusted', 'evidence', 'grant_id'}
                or any(v.get('recovery_enabled') is not True for v in configs)):
            raise ValueError('EXPLICIT_OPERATING_OWNER_PORTS_REQUIRED')
        grant_id = identifier(operating_config['grant_id'])
        operating = OperationalState(store, trusted=operating_config['trusted'], evidence=operating_config['evidence'])
        configs = tuple({**v, 'recovery_submit': loop._model_answer} for v in configs)
    observation = IncidentObservationPort(loop._board, human_owned=human_owned, clock=clock)
    workers = tuple(IncidentCaseWorker(store, observation, loop._board,
        human_owned=human_owned, final_handoff=final_handoff,
        **{**v, 'baseline': v.get('baseline', loop.rule_baseline)}) for v in configs)
    worker = IncidentProfileDispatcher(workers) if variants is not None else workers[0]
    log.notifications.set_automation(worker.prepare_receipt)
    if operating_config is not None:
        loop.operating_state, loop.operating_grant = operating, grant_id
    loop.incident_worker = worker
    return worker
