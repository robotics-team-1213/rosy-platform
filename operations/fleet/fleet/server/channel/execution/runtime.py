"""Optional conversation execution shares existing app owners and lifecycle."""
import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends

from .journal import ExecutionJournal
from .worker import ExecutionWorker


def install_execution(app,jobs,task_service,scope,admitted,environment,*,require_operator,read_guard):
    if task_service is None:raise ValueError('CHANNEL_TASK_SERVICE_REQUIRED')
    journal=ExecutionJournal(jobs,task_service.store,producer_scope=scope,admitted=admitted,environment=environment)
    if task_service.channel_admission is not None:raise ValueError('ONE_CHANNEL_EXECUTION_OWNER_REQUIRED')
    task_service.channel_admission=journal.task_reason
    worker=ExecutionWorker(journal,app.state.intent_execution)
    app.state.channel_execution=journal
    app.state.channel_execution_worker=worker

    @app.get('/api/fleet/channel-requests/{request_id}/execution',dependencies=read_guard,tags=['fleet-work'])
    def execution(request_id:str,principal=Depends(require_operator)):
        jobs.read(request_id,principal.principal_id)
        return journal.view(request_id)

    async def run():
        journal.recover()
        while True:
            try:
                for rid in worker.pending():await worker.step(rid)
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
