import asyncio
import json

import pytest

from fleet.server.context_log import ContextLog, active, set_active
from fleet.server.context_options import activate_from_args, add_cli_arguments
from fleet.server.deliberation_journal import DeliberationJournal
from rosy.decision.deliberation import Supervisor
from test_deliberation import Provider, problem


class FakeConnection:
    def __init__(self, *, fail=False):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail = fail

    def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError("database is unavailable")
        self.calls.append((statement, params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def factory(*, fail=False):
    connections = []

    def connect(dsn):
        connections.append(FakeConnection(fail=fail))
        return connections[-1]

    return connections, connect


def run_result(result):
    return dict(result)


def test_context_log_requests_a_full_identity_and_a_real_port():
    for host, database, user in (("", "db", "u"), ("h", "", "u"), ("h", "db", "")):
        with pytest.raises(ValueError, match="host, database and user"):
            ContextLog(host, database, user)
    for port in (0, 65536, "5432"):
        with pytest.raises(ValueError, match="port"):
            ContextLog("h", "db", "u", port=port)


def test_password_comes_from_the_secret_file_at_connect_time(tmp_path):
    path = tmp_path / "postgres_password"
    path.write_text("hunter2swordfish\n", encoding="utf-8")
    seen = []
    connections, connect = factory()

    def record(dsn):
        seen.append(dsn)
        return connect(dsn)

    log = ContextLog("postgres", "rosy_context", "rosy", port=5432,
                     password_file=path, connect=record)
    log.ensure_schema()

    assert seen == ["host=postgres port=5432 dbname=rosy_context user=rosy "
                    "connect_timeout=5 password=hunter2swordfish"]
    assert "hunter2swordfish" not in str(log.password_file)
    assert connections[0].closed is True

    empty = tmp_path / "empty"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="password file is empty"):
        ContextLog("postgres", "rosy_context", "rosy", password_file=empty,
                   connect=connect).ensure_schema()


def test_schema_is_created_once_and_the_insert_is_parameterized():
    connections, connect = factory()
    log = ContextLog("postgres", "rosy_context", "rosy", connect=connect)

    log.ensure_schema()
    log.ensure_schema()
    assert sum("CREATE TABLE" in call[0] for call in connections[0].calls) == 1

    result = {"state": "CANDIDATE", "choice": "goal-a", "calls": 3, "cost_usd": 0.25,
              "cost_complete": True, "action_admissible": True, "policy_id": "deliberation-v1"}
    assert log.record_run(subject_id="r1", case_id="c1", generation="g1",
                          policy_id="deliberation-v1", result=result) is True

    insert = next(call for call in connections[-1].calls if call[0].startswith("INSERT"))
    params = insert[1]
    assert params[:4] == ("r1", "c1", "g1", "deliberation-v1")
    assert params[4] == "CANDIDATE" and params[5] == "goal-a"
    assert params[6:10] == (3, 0.25, True, True)
    assert json.loads(params[-1]) == result
    assert connections[-1].commits == 1


def test_a_failing_store_returns_false_and_rolls_back_without_raising():
    connections, connect = factory(fail=True)
    log = ContextLog("postgres", "rosy_context", "rosy", connect=connect)
    assert log.record_run(subject_id="r1", case_id="c1", generation="g1",
                          policy_id="deliberation-v1", result={"state": "CANDIDATE"}) is False
    assert connections[0].rollbacks == 1

    def unreachable(dsn):
        raise RuntimeError("connection refused")

    log = ContextLog("postgres", "rosy_context", "rosy", connect=unreachable)
    assert log.record_run(subject_id="r1", case_id="c1", generation="g1",
                          policy_id="deliberation-v1", result={"state": "CANDIDATE"}) is False


def test_journal_mirrors_only_the_terminal_run(tmp_path):
    connections, connect = factory()
    log = ContextLog("postgres", "rosy_context", "rosy", connect=connect)
    journal = DeliberationJournal(tmp_path / "fleet.db", context_log=log)
    providers = [Provider("a"), Provider("b")]

    result = asyncio.run(journal.run(problem(), Supervisor(clock=lambda: 101), providers,
                                     current=lambda: True))

    inserts = [call for conn in connections for call in conn.calls
               if call[0].startswith("INSERT")]
    assert len(inserts) == 1
    assert inserts[0][1][4] == result["state"]
    assert result["state"] == "CANDIDATE"


def test_journal_run_survives_a_broken_mirror(tmp_path):
    def unreachable(dsn):
        raise RuntimeError("no server")

    journal = DeliberationJournal(tmp_path / "fleet.db",
                                  context_log=ContextLog("postgres", "rosy_context", "rosy",
                                                         connect=unreachable))
    providers = [Provider("a"), Provider("b")]
    result = asyncio.run(journal.run(problem(), Supervisor(clock=lambda: 101), providers,
                                     current=lambda: True))
    assert result["state"] == "CANDIDATE"
    assert result["choice"] is not None


def test_journal_without_a_context_log_mirrors_nothing(tmp_path, monkeypatch):
    set_active(None)
    journal = DeliberationJournal(tmp_path / "fleet.db")
    assert journal.context_log is None
    assert journal._mirror(problem(), run_result({"state": "CANDIDATE"})) is None


def test_cli_flags_activate_the_sink_the_journal_then_uses(tmp_path):
    import argparse

    parser = argparse.ArgumentParser()
    add_cli_arguments(parser)
    assert activate_from_args(parser.parse_args([])) is None
    assert active() is None
    with pytest.raises(SystemExit, match="--context-db-host requires"):
        activate_from_args(parser.parse_args(["--context-db-host", "postgres"]))

    args = parser.parse_args(["--context-db-host", "postgres", "--context-db-name", "rosy_context",
                              "--context-db-user", "rosy", "--context-db-password-file", "pw"])
    log = activate_from_args(args)
    try:
        assert log is not None and active() is log
        assert DeliberationJournal(tmp_path / "fleet.db").context_log is log
    finally:
        set_active(None)

