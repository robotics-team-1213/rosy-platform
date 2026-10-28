"""The diagnostic must observe the installed endpoint and preserve real SQLite transactions."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from station_timing_probe import install_timing_probe
from test_station_docking_api import station_api  # noqa: F401


def test_probe_observes_the_installed_sync_route_and_real_transactions(station_api, monkeypatch, capsys):
    client, svc, now, auth, _, _ = station_api

    async def unused(*args, **kwargs):
        raise AssertionError('the read-only endpoint must not dispatch motion')

    tasks = SimpleNamespace(_connect=lambda: sqlite3.connect(':memory:'))
    registry = SimpleNamespace(_connect=lambda: sqlite3.connect(':memory:'))
    motion = SimpleNamespace(call=unused, stop_hold=unused)
    ports = SimpleNamespace(read_operation=unused, read_station=unused, stop_operation=unused)
    dump = install_timing_probe(owner=svc.station_docking, navigation=svc.nav, motion=motion,
        ports=ports, tasks=tasks, registry=registry, app=client.app, clock=lambda: now[0], monkeypatch=monkeypatch)
    response = client.get('/api/v1/docking/status', headers=auth['fleet-a'])
    assert response.status_code == 200, response.text
    connection = tasks._connect()
    try:
        connection.execute('CREATE TABLE evidence (value INTEGER)')
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT INTO evidence VALUES (1)')
        with pytest.raises(ValueError, match='rollback'):
            with connection:
                connection.execute('INSERT INTO evidence VALUES (2)')
                raise ValueError('rollback')
        connection.execute('INSERT INTO evidence VALUES (3)')
        connection.rollback()
        connection.execute('INSERT INTO evidence VALUES (4)')
        connection.commit()
        assert connection.execute('SELECT value FROM evidence ORDER BY value').fetchall() == [(1,), (4,)]
    finally:
        connection.close()
    dump('probe_self_check')
    reports = [json.loads(line.removeprefix('STATION_TIMING_DIAGNOSTIC '))
        for line in capsys.readouterr().out.splitlines() if line.startswith('STATION_TIMING_DIAGNOSTIC ')]
    events = reports[-1]['events']
    names = [event['event'] for event in events]
    assert names[:4] == ['http_sync_submit', 'http_sync_start', 'http_sync_finish', 'http_loop_resume']
    assert events[0]['thread'] != events[1]['thread']
    assert events[0]['thread'] == events[3]['thread']
    for action in ('begin', 'commit', 'rollback'):
        assert 'sql_'+action+'_enter' in names and 'sql_'+action+'_exit' in names
