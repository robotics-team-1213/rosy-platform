"""Internal request-scoped admission; never shared between concurrent callers."""
from contextlib import contextmanager
from contextvars import ContextVar

_guards = ContextVar('fleet_dispatch_guards', default=())


@contextmanager
def dispatch_guard(check):
    token = _guards.set((*_guards.get(), check))
    try:
        yield
    finally:
        _guards.reset(token)


def check_dispatch(request=None):
    if request is not None and request.method not in {'POST', 'PUT', 'DELETE'}:
        return
    for check in _guards.get():
        check()
