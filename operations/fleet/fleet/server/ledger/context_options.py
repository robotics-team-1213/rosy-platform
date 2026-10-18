"""D-796 console surface for the site-host context/log mirror (the ledger holder's own).

`add_cli_arguments` defines the `--context-db-*` flags and `activate_from_args` builds the
`ContextLog` and registers it as this process's active sink so a `DeliberationJournal` built
later mirrors into it. The wiring lives here, not in the frozen `cli.py`/`app.py` (D-766).
An absent `--context-db-host` leaves the SQLite-only path exactly as it was.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from fleet.server.context_log import ContextLog, set_active


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """The D-796 connection flags: the mirror is off unless a host is given."""
    parser.add_argument("--context-db-host", default=None,
                        help="D-796 optional site-host Postgres host for the advisory context/log "
                             "mirror; absent disables the mirror (the SQLite ledger is unchanged)")
    parser.add_argument("--context-db-port", type=int, default=5432,
                        help="D-796 Postgres port for the advisory context/log mirror (default 5432)")
    parser.add_argument("--context-db-name", default=None,
                        help="D-796 Postgres database for the advisory context/log mirror")
    parser.add_argument("--context-db-user", default=None,
                        help="D-796 Postgres user for the advisory context/log mirror")
    parser.add_argument("--context-db-password-file", default=None, type=str,
                        help="D-796 file (Docker secret) holding the Postgres password")


def activate_from_args(args: argparse.Namespace) -> Optional[ContextLog]:
    """Build the sink from the parsed flags and make it the active one (None when unset)."""
    host = getattr(args, "context_db_host", None)
    if host is None:
        return None
    if not getattr(args, "context_db_name", None) or not getattr(args, "context_db_user", None):
        sys.exit("--context-db-host requires --context-db-name and --context-db-user")
    log = ContextLog(host, args.context_db_name, args.context_db_user,
                     port=args.context_db_port,
                     password_file=args.context_db_password_file)
    set_active(log)
    return log
