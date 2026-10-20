"""Composition only: Console dialogue never installs a device execution worker."""
from functools import partial

from .context import build_context
from .journal import AssistantJournal
from .routes import install_routes
from .service import AssistantService
from .execution import AssistantExecution


def install_assistant(app, config, *, task_service, require_named_operator, authorize):
    service = None
    if task_service is not None:
        journal = AssistantJournal(task_service.store._connect)
        journal.recover()
        provider = None
        admitted = lambda: False
        if config is not None:
            from .provider import OperatorProvider
            provider = OperatorProvider(config)
            admitted = config.admitted
        service = AssistantService(journal, context=partial(build_context, app), provider=provider,
            admitted=admitted, authorized=lambda _: False)
    app.state.operator_assistant = service
    execution = AssistantExecution(service, app.state.intent_execution,
        enabled=lambda:config is not None and config.execution_enabled) if service else None
    install_routes(app, service, require_named_operator=require_named_operator, authorize=authorize,
                   execution=execution)
