"""Host regression for cleanup diagnostic failures, without importing ROS."""
import ast
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def cleanup_scope():
    source = Path(__file__).with_name('test_policy_runtime_ros.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'native_setup_cleanup')
    namespace = dict(contextmanager=contextmanager, sys=sys,
                     rclpy=SimpleNamespace(ok=lambda: False))
    import json
    namespace['json'] = json
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['native_setup_cleanup']


class UnwritableReceipt:
    def __truediv__(self, _):
        return self

    def write_text(self, _):
        raise OSError('injected receipt disk failure')


def test_diagnostic_write_does_not_replace_setup_error():
    cleaned = []
    with pytest.raises(RuntimeError, match='original SDK failure'):
        with cleanup_scope()(UnwritableReceipt()) as (own, _):
            own(lambda: cleaned.append('context'))
            raise RuntimeError('original SDK failure')
    assert cleaned == ['context']


def test_diagnostic_write_does_not_replace_setup_skip():
    with pytest.raises(pytest.skip.Exception, match='original dependency skip'):
        with cleanup_scope()(UnwritableReceipt()) as (own, _):
            own(lambda: None)
            pytest.skip('original dependency skip')


def test_unwritable_diagnostic_without_primary_is_failure():
    with pytest.raises(OSError, match='receipt disk failure'):
        with cleanup_scope()(UnwritableReceipt()) as (own, _):
            own(lambda: None)
