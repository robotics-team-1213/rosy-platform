"""Service-local HTTP surface, never mounted in CORE or Fleet."""

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from core_common.protocol.notification_delivery import DeliveryRequest, DeliveryReceipt
from .journal import DeliveryError


def create_app(service, *, worker_enabled=False):
    async def worker():
        while True:
            try:
                await service.run_once()
            except Exception as error:
                logging.getLogger(__name__).warning('delivery scan failed (%s)', type(error).__name__)
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker()) if worker_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(DeliveryError)
    async def rejected(request, error):
        return JSONResponse({'code': error.code}, status_code=error.status)

    @app.middleware('http')
    async def authenticate_and_bound(request: Request, call_next):
        try:
            request.state.machine = service.authenticate(request.headers.get('authorization', ''))
        except DeliveryError as error:
            return JSONResponse({'code': error.code}, status_code=error.status)
        # Bound chunked bodies too; content-length alone does not enforce a memory budget.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                return JSONResponse({'code': 'DELIVERY_BODY_TOO_LARGE'}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.post('/api/notifications/v1/deliveries', response_model=DeliveryReceipt)
    def accept(body: DeliveryRequest, request: Request):
        return service.accept(body, request.state.machine)

    @app.get('/api/notifications/v1/deliveries/{notification_id}', response_model=DeliveryReceipt)
    def read(notification_id: str, request: Request):
        return service.journal.read(request.state.machine.identity, notification_id)

    return app
