"""Authenticated Console intake; no model or device policy in HTTP handlers."""
import sqlite3

from fastapi import BackgroundTasks, Depends, HTTPException, Path, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from core_common.protocol.assistant import AssistantMessage, AssistantResult, AssistantStatus, AssistantHistory, AssistantNavigation
from fleet.server.task_store import IdempotencyConflict

ID = r'^[A-Za-z0-9_-]{1,96}$'


def install_routes(app, service, *, require_named_operator, authorize, execution=None):
    def operator(principal=Depends(require_named_operator)):
        if principal.principal_id == 'site-console' or principal.principal_id.startswith('development-'):
            raise HTTPException(403, detail='OPERATOR_IDENTITY_REQUIRED')
        return principal

    def ready():
        if service is None:
            raise HTTPException(503, detail='ASSISTANT_STORAGE_UNAVAILABLE')
        return service

    def recheck(request, principal):
        probe = Request({**request.scope, 'method':'GET', 'state':{}})
        try:
            current = authorize(probe, authorization=request.headers.get('authorization'))
            return (current.principal_id == principal and not current.password_change_required
                    and current.permits_site('fleet.operate', {'operator'}))
        except HTTPException:
            return False

    def storage(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (sqlite3.Error, OSError):
            raise HTTPException(503, detail='ASSISTANT_STORAGE_UNAVAILABLE') from None

    @app.get('/api/fleet/assistant/status', response_model=AssistantStatus, tags=['fleet-assistant'])
    def status(response: Response, principal=Depends(operator)):
        response.headers['Cache-Control'] = 'no-store'
        available = service is not None and service.admitted()
        return AssistantStatus(available=available, reason=None if available else 'ASSISTANT_NOT_ADMITTED',
            execution_enabled=bool(available and execution is not None and execution.enabled()))

    @app.post('/api/fleet/assistant/messages/{request_id}/navigation', tags=['fleet-assistant'])
    async def navigate(request: Request, response: Response, body: AssistantNavigation,
                       request_id: str = Path(pattern=ID), principal=Depends(operator)):
        ready()
        if execution is None:
            raise HTTPException(503, detail='ASSISTANT_EXECUTION_NOT_ADMITTED')
        response.headers['Cache-Control'] = 'no-store'
        try:
            return await execution.submit(principal, request_id, body,
                authorized=lambda:recheck(request, principal.principal_id))
        except IdempotencyConflict:
            raise HTTPException(409, detail='ASSISTANT_NAVIGATION_CHANGED') from None
        except ValueError as error:
            raise HTTPException(404 if str(error) == 'UNKNOWN_ROBOT' else 400,
                                detail='ASSISTANT_NAVIGATION_INVALID') from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, detail='ASSISTANT_STORAGE_UNAVAILABLE') from None

    @app.post('/api/fleet/assistant/messages', response_model=AssistantResult, tags=['fleet-assistant'])
    async def submit(request: Request, response: Response, background: BackgroundTasks, principal=Depends(operator)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, detail='ASSISTANT_BODY_TOO_LARGE')
        try:
            message = AssistantMessage.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(422, detail='ASSISTANT_MESSAGE_INVALID') from None
        owner = ready()
        result, created = await run_in_threadpool(storage, owner.submit, principal.principal_id, message)
        response.status_code = 202 if created else 200
        response.headers['Cache-Control'] = 'no-store'
        if result.state == 'PENDING':
            background.add_task(owner.step, principal.principal_id, message.request_id,
                                reauthorize=lambda: recheck(request, principal.principal_id))
        return result

    @app.get('/api/fleet/assistant/messages/{request_id}', response_model=AssistantResult, tags=['fleet-assistant'])
    def read(response: Response, request_id: str = Path(pattern=ID), principal=Depends(operator)):
        response.headers['Cache-Control'] = 'no-store'
        return storage(ready().read, principal.principal_id, request_id)

    @app.get('/api/fleet/assistant/conversations/{conversation_id}', response_model=AssistantHistory, tags=['fleet-assistant'])
    def history(response: Response, conversation_id: str = Path(pattern=ID), principal=Depends(operator)):
        response.headers['Cache-Control'] = 'no-store'
        return AssistantHistory(conversation_id=conversation_id,
            messages=storage(ready().journal.history, principal.principal_id, conversation_id))
