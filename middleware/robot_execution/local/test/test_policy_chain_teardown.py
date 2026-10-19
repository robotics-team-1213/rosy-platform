"""Run the native probe's real cleanup against a pending guard-using callback."""
import ast
import json
from pathlib import Path
import sys
import threading
import time
import traceback
from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize('failure', [None, 'probe_alive', 'pool_failure'])
def test_pending_callback_drains_before_guard_destruction(tmp_path, failure):
    tree = ast.parse(Path(__file__).with_name('policy_chain_gazebo.py').read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    cleanup = next(n.finalbody for n in ast.walk(main) if isinstance(n, ast.Try) and n.finalbody)
    guard = {'alive': True}
    destroyed, callbacks = [], []
    def pool_shutdown(wait):
        assert wait and guard['alive'], 'pending handler touched an already destroyed guard'
        callbacks.append('completed')
        if failure == 'pool_failure':
            raise RuntimeError('pool failed')
    def executor_shutdown(timeout_sec):
        guard['alive'] = False
        return True
    primary = RuntimeError('original probe failure') if failure else None
    scope = dict(runtime=NS(_timer=NS(cancel=lambda: None), destroy=lambda: destroyed.append('runtime')),
        worker=NS(join=lambda **kw: None, is_alive=lambda: failure == 'probe_alive'),
        executor=NS(remove_node=lambda node: None, shutdown=executor_shutdown,
                    _executor=NS(shutdown=pool_shutdown)),
        node=NS(destroy_node=lambda: destroyed.append('node')),
        rclpy=NS(try_shutdown=lambda: destroyed.append('context')),
        threading=threading, traceback=traceback, sys=sys, json=json, time=time,
        out=tmp_path, cpu_group=tmp_path, errors=[primary] if primary else [],
        spin_error=None, teardown_errors=[], intake_trace=[])
    (tmp_path/'cpu.stat').write_text('')
    exec(compile(ast.Module(body=cleanup, type_ignores=[]), '<actual native cleanup>', 'exec'), scope)
    report = json.loads((tmp_path/'teardown.json').read_text())
    assert callbacks == ['completed']
    if failure:
        assert not destroyed and guard['alive']
        assert report['primary_error'] == repr(primary)
        assert report['teardown_errors'] == (["RuntimeError('pool failed')"] if failure == 'pool_failure' else [])
    else:
        assert destroyed == ['runtime', 'node', 'context']
        assert report['workers_stopped'] and report['executor_stopped'] and report['probe_stopped']
