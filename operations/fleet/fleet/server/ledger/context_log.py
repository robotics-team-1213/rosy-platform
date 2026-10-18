"""D-796 optional site-host context/log store; the Fleet ledger stays SQLite.

A best-effort, additive sink for completed D-640 advisory runs. It is never the
source of truth, never runs on a robot, and a failure here must never change a
Fleet decision or block the ledger transaction: the caller invokes it only after
the SQLite write has committed and treats any failure as a logged warning.
"""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_LOG = logging.getLogger(__name__)
SCHEMA_VERSION = 1

#: The sink the console configured for this process, if any. The journal reads it as
#: its default so the wiring lives in this holder instead of the frozen `cli.py`/`app.py`.
_ACTIVE: Optional["ContextLog"] = None


def set_active(log: Optional["ContextLog"]) -> None:
    global _ACTIVE
    _ACTIVE = log


def active() -> Optional["ContextLog"]:
    return _ACTIVE

_DDL = (
    """CREATE TABLE IF NOT EXISTS rosy_deliberation_run (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        subject_id text NOT NULL,
        case_id text NOT NULL,
        generation text NOT NULL,
        policy_id text NOT NULL,
        state text NOT NULL,
        choice text,
        calls integer,
        cost_usd double precision,
        cost_complete boolean,
        action_admissible boolean NOT NULL,
        detail jsonb NOT NULL)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS rosy_deliberation_run_key
        ON rosy_deliberation_run (subject_id, case_id, generation)""",
)

_INSERT = """INSERT INTO rosy_deliberation_run
        (subject_id, case_id, generation, policy_id, state, choice, calls,
         cost_usd, cost_complete, action_admissible, detail)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (subject_id, case_id, generation) DO NOTHING"""


def _default_connect(dsn: str) -> Any:
    """psycopg is imported lazily so this module is importable without the driver."""
    return importlib.import_module("psycopg").connect(dsn)


class ContextLog:
    """Append-only Postgres sink for terminal advisory runs (D-796).

    ``connect`` is injectable for tests; when omitted, psycopg is imported on
    first use. ``password_file`` is a Docker secret path read at connect time so
    no password is ever stored in the process environment or a config file.
    """

    def __init__(self, host: str, database: str, user: str, *, port: int = 5432,
                 password_file: Optional[Path | str] = None,
                 connect: Optional[Callable[[str], Any]] = None) -> None:
        if not host or not database or not user:
            raise ValueError("context log needs host, database and user")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("context log port must be 1..65535")
        self.host, self.database, self.user, self.port = host, database, user, port
        self.password_file = password_file
        self._connect = connect or _default_connect
        self._ready = False

    def _dsn(self) -> str:
        options = {"host": self.host, "port": self.port, "dbname": self.database,
                   "user": self.user, "connect_timeout": 5}
        if self.password_file is not None:
            secret = Path(self.password_file).read_text(encoding="utf-8").strip()
            if not secret:
                raise ValueError("context log password file is empty")
            options["password"] = secret
        return " ".join(f"{name}={value}" for name, value in options.items())

    def _connect_and(self, work: Callable[[Any], None]) -> None:
        conn = self._connect(self._dsn())
        try:
            work(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        if self._ready:
            return

        def work(conn: Any) -> None:
            for statement in _DDL:
                conn.execute(statement)

        self._connect_and(work)
        self._ready = True

    def record_run(self, *, subject_id: str, case_id: str, generation: str,
                   policy_id: str, result: Mapping[str, Any]) -> bool:
        """Mirror one terminal advisory run. Returns False on any failure."""
        row = {
            "state": str(result.get("state", "UNKNOWN")),
            "choice": result.get("choice"),
            "calls": result.get("calls"),
            "cost_usd": result.get("cost_usd"),
            "cost_complete": result.get("cost_complete"),
            "action_admissible": bool(result.get("action_admissible", False)),
        }

        def work(conn: Any) -> None:
            conn.execute(_INSERT, (
                subject_id, case_id, generation, policy_id, row["state"], row["choice"],
                row["calls"], row["cost_usd"], row["cost_complete"],
                row["action_admissible"], json.dumps(dict(result), sort_keys=True),
            ))

        try:
            self.ensure_schema()
            self._connect_and(work)
        except Exception as exc:  # never let the log store change a Fleet decision
            _LOG.warning("context log write skipped (D-796): %s", exc)
            return False
        return True
