"""Internal request-scoped admission; never shared between concurrent callers."""
from contextlib import contextmanager
from contextvars import ContextVar

_guards = ContextVar('fleet_dispatch_guards', default=())


@contextmanager
def dispatch_guard(check, *, paths=None):
    token = _guards.set((*_guards.get(), (check,paths)))
    try:
        yield
    finally:
        _guards.reset(token)


def check_dispatch(request=None, *, path=None):
    if request is not None and request.method not in {'POST', 'PUT', 'DELETE'}:
        return
    path=request.url.path if request is not None else path
    for check,paths in _guards.get():
        if paths is None or path is None or path in paths:
            check()
