"""Call a real mixin method with test-chosen module globals (D-171).

Before the calibration mixins were ROS-free, tests AST-extracted a method and
``exec``-ed it in a hand-built namespace. This helper keeps that contract —
the caller still chooses what ``time`` or ``match_motion`` mean — but runs the
method's real, imported code object. Globals are a copy, so a test that
updates ``fn.__globals__`` never leaks into the module other tests import.
"""
import importlib
import types


def mixin_method(module_name, name, **overrides):
    module = importlib.import_module(module_name)
    owners = [value for value in vars(module).values()
              if isinstance(value, type) and value.__module__ == module.__name__ and name in vars(value)]
    if len(owners) != 1:
        raise LookupError(f'{module_name}.{name}: expected one owning class, found {owners}')
    function = vars(owners[0])[name]
    namespace = dict(module.__dict__)
    namespace.update(overrides)
    return types.FunctionType(function.__code__, namespace, function.__name__,
                              function.__defaults__, function.__closure__)
