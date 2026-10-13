"""Optional conversation execution shares existing app owners and lifecycle."""
import asyncio
from contextlib import asynccontextmanager
import logging

from .journal import ExecutionJournal
from .worker import ExecutionWorker


def install_execution(app,jobs,task_service,scope,admitted,environment,*,refresh):
    if task_service is None:raise ValueError('CHANNEL_TASK_SERVICE_REQUIRED')
    journal=ExecutionJournal(jobs,task_service.store,producer_scope=scope,admitted=admitted,environment=environment)
    if task_service.channel_admission is not None:raise ValueError('ONE_CHANNEL_EXECUTION_OWNER_REQUIRED')
    task_service.channel_admission=journal.task_reason
    worker=ExecutionWorker(journal,app.state.intent_execution)
    app.state.channel_execution=journal
    app.state.channel_execution_worker=worker
    jobs.execution=journal
    app.state.intent_execution.console.goal_leases.selected_context=journal.context_for_task

    async def run():
        journal.recover()
        while True:
            try:
                pending=worker.pending()
                fresh=True
                if pending:
                    try:await refresh()
                    except Exception:fresh=False
                for rid in pending:
                    try:await worker.step(rid,allow_dispatch=fresh)
                    except Exception:logging.getLogger(__name__).warning('Channel outcome remains unresolved')
            except asyncio.CancelledError:raise
            except Exception:logging.getLogger(__name__).warning('Channel execution cycle held; unknown steps are not replayed')
            await asyncio.sleep(1)

    previous=app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state:
            task=asyncio.create_task(run())
            try:yield state
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
    app.router.lifespan_context=lifespan
