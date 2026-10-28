"""Bounded test-only station timing; delegate real RPCs, workers, connections and stops unchanged."""
import asyncio
from collections import deque
from contextvars import ContextVar
from functools import wraps
from itertools import count, islice
import json
from pathlib import Path
import sys
import threading
import time
import traceback

from pydantic import ValidationError
from fastapi.routing import APIRoute


def _api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        inner = getattr(route, 'original_router', None)
        if inner is not None:
            yield from _api_routes(inner.routes)


def install_timing_probe(*, owner, navigation, motion, ports, tasks, registry, app, clock, monkeypatch):
    from fastapi import routing
    from station_readback_probe import install_hold_probe

    events, ids, local = deque(maxlen=512), count(1), threading.local()
    rpc = ContextVar('station_probe_rpc', default=None)
    real = time.monotonic
    first, pending, latest_scope = {}, set(), {}
    cv2 = sys.modules.get('cv2')
    installed = dict(cv2_threads=cv2.getNumThreads() if cv2 is not None else None)

    def record(event, **fields):
        item = dict(event=event, real_monotonic=real(), sim=clock(), thread=threading.get_ident(),
                    process_cpu=time.process_time(), worker=getattr(local, 'job', None), rpc=rpc.get(), **fields)
        events.append(item)
        if event == 'fleet_stop_enter' and 'fleet_stop' not in first:
            first['fleet_stop'] = item
            pending.add('fleet_stop')
        elif event == 'fleet_stop_exit' and 'fleet_stop' in pending:
            pending.remove('fleet_stop')
            dump('first_fleet_stop')

    def dump(trigger):
        print('STATION_TIMING_DIAGNOSTIC '+json.dumps(dict(trigger=trigger,
              installed=installed, first=dict(first), events=list(events))), flush=True)

    def stack():
        return [dict(file=Path(frame.f_code.co_filename).name, line=line, call=frame.f_code.co_name)
                for frame, line in islice(traceback.walk_stack(None), 8)]

    original_invalidate = owner.invalidate

    def observe_scope(name):
        original = getattr(owner, name)

        @wraps(original)
        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            latest_scope[name] = dict(real_monotonic=real(), sim=clock(),
                scope=None if result is None else {key: result.get(key) for key in (
                    'mode', 'safety_latched', 'odom_epoch', 'odom_fresh')})
            return result
        monkeypatch.setattr(owner, name, observed)

    for name in ('local_scope', 'local_scope_nowait'):
        observe_scope(name)

    def invalidate(reason):
        initial = 'owner_hold' not in first and owner.state != 'HOLD'
        error = sys.exception()
        record('owner_invalidate_enter', state=owner.state, reason=reason,
               exception_type=None if error is None else type(error).__name__)
        if initial:
            code = str(error) if isinstance(error, ValueError) else ''
            first['owner_hold'] = dict(events[-1], stack=stack(), local_scope=dict(latest_scope),
                exception_code=code if code.startswith(('STATION_', 'CHARGE_'))
                    and code.replace('_', '').isalnum() and code.isupper() else None,
                validation_errors=[dict(loc=entry['loc'], type=entry['type'])
                    for entry in error.errors(include_input=False, include_url=False)]
                    if isinstance(error, ValidationError) else None,
                native_generations=dict(navigation=navigation.native.generation,
                    docking=owner.docking.native.generation), generation_observation='unlocked_not_atomic',
                execution_binding=dict(navigation=navigation._execution_binding is not None,
                    docking=owner.docking._execution_binding is not None))
        try:
            return original_invalidate(reason)
        finally:
            record('owner_invalidate_exit', state=owner.state, reason=owner.reason)
            if initial:
                dump('first_owner_hold')

    monkeypatch.setattr(owner, 'invalidate', invalidate)
    install_hold_probe(motion, clock, timing=record)
    original_call = motion.call

    @wraps(original_call)
    async def call(function, *args, **kwargs):
        token = rpc.set(next(ids))
        record('rpc_submit', method=getattr(function, '__name__', type(function).__name__))
        try:
            return await original_call(function, *args, **kwargs)
        finally:
            record('rpc_resume')
            rpc.reset(token)

    monkeypatch.setattr(motion, 'call', call)

    def observe_port(name):
        original = getattr(ports, name)

        @wraps(original)
        async def observed(*args, **kwargs):
            record('rpc_start', method=name)
            try:
                return await original(*args, **kwargs)
            finally:
                record('rpc_finish', method=name)
        monkeypatch.setattr(ports, name, observed)

    for name in ('read_operation', 'read_station', 'stop_operation'):
        observe_port(name)

    original_thread = asyncio.to_thread

    async def to_thread(function, /, *args, **kwargs):
        job = next(ids)
        record('thread_submit', job=job, method=getattr(function, '__qualname__', type(function).__name__))

        def work():
            previous = getattr(local, 'job', None)
            local.job = job
            record('thread_start', job=job)
            try:
                return function(*args, **kwargs)
            finally:
                record('thread_finish', job=job)
                local.job = previous
        try:
            return await original_thread(work)
        finally:
            record('thread_loop_resume', job=job)

    monkeypatch.setattr(asyncio, 'to_thread', to_thread)

    class Connection:
        def __init__(self, db, label, connection):
            self.db, self.label, self.connection = db, label, connection

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, statement, *args, **kwargs):
            begin = isinstance(statement, str) and statement.lstrip().upper().startswith('BEGIN IMMEDIATE')
            if begin:
                record('sql_begin_enter', db=self.label, connection=self.connection)
            try:
                return self.db.execute(statement, *args, **kwargs)
            finally:
                if begin:
                    record('sql_begin_exit', db=self.label, connection=self.connection)

        def __enter__(self):
            self.db.__enter__()
            return self

        def commit(self):
            record('sql_commit_enter', db=self.label, connection=self.connection)
            try:
                return self.db.commit()
            finally:
                record('sql_commit_exit', db=self.label, connection=self.connection)

        def rollback(self):
            record('sql_rollback_enter', db=self.label, connection=self.connection)
            try:
                return self.db.rollback()
            finally:
                record('sql_rollback_exit', db=self.label, connection=self.connection)

        def __exit__(self, kind, error, tb):
            action = ('commit' if kind is None else 'rollback') if self.db.in_transaction else 'context_exit'
            record('sql_'+action+'_enter', db=self.label, connection=self.connection)
            try:
                return self.db.__exit__(kind, error, tb)
            finally:
                record('sql_'+action+'_exit', db=self.label, connection=self.connection)

    def observe_database(store, label):
        original = store._connect

        def connect():
            connection = next(ids)
            record('sql_connect_enter', db=label, connection=connection)
            try:
                return Connection(original(), label, connection)
            finally:
                record('sql_connect_exit', db=label, connection=connection)
        monkeypatch.setattr(store, '_connect', connect)

    observe_database(tasks, 'tasks')
    observe_database(registry, 'stations')
    route = next(route for route in _api_routes(app.routes) if route.path == '/api/v1/docking/status')
    original_endpoint = route.endpoint
    original_pool = routing.run_in_threadpool

    async def run_in_threadpool(function, *args, **kwargs):
        if function is not original_endpoint:
            return await original_pool(function, *args, **kwargs)

        def endpoint(*args, **kwargs):
            record('http_sync_start')
            try:
                return function(*args, **kwargs)
            finally:
                record('http_sync_finish')
        return await original_pool(endpoint, *args, **kwargs)

    monkeypatch.setattr(routing, 'run_in_threadpool', run_in_threadpool)
    original_endpoint_function = routing.run_endpoint_function

    async def endpoint_function(*args, **kwargs):
        selected = getattr(kwargs.get('dependant'), 'call', None) is original_endpoint
        if selected:
            record('http_sync_submit')
        try:
            return await original_endpoint_function(*args, **kwargs)
        finally:
            if selected:
                record('http_loop_resume')

    monkeypatch.setattr(routing, 'run_endpoint_function', endpoint_function)
    return dump
