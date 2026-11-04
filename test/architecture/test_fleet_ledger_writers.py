"""Who may write Fleet's core ledger tables (D-750: one SQLite file, one transaction owner per change).

The task, history, robot reservation and Action claim tables share one SQLite file, and claims
are reserved inside each caller's own transaction (``dispatch_admission``). A new module that
writes one of these tables is a new ledger writer: it fails here until it is added below, so a
reviewer sees it. A listed module that stops writing fails too, so the list never goes stale; it
grows only through a reviewed change to KNOWN_WRITERS.

Honest holes: only literal SQL is seen (``INSERT``/``REPLACE``/``UPDATE``/``DELETE`` followed by a
listed table name). A table name built at runtime (``f"UPDATE {table} ..."``) is not seen; today
those f-strings in Fleet only read these tables.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLEET = ROOT / "operations/fleet/fleet"
LEDGER_TABLES = ("fleet_tasks", "fleet_task_history", "fleet_robot_reservations", "fleet_action_claims",
                 "fleet_control_stops", "fleet_control_stop_deliveries")
_WRITE = re.compile(r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+("
                    + "|".join(LEDGER_TABLES) + r")\b", re.IGNORECASE)

#: module (relative to operations/fleet/fleet) -> the ledger tables it writes, measured 2026-10-19 on local main.
KNOWN_WRITERS = {
    "server/ledger/task_store.py": {"fleet_tasks", "fleet_task_history", "fleet_robot_reservations"},
    "server/ledger/task_dispatch_control.py": {"fleet_tasks", "fleet_robot_reservations", "fleet_action_claims"},
    "server/ledger/task_dispatch_queue.py": {"fleet_tasks", "fleet_robot_reservations", "fleet_action_claims"},
    "server/ledger/control_stop_store.py": {"fleet_control_stops", "fleet_control_stop_deliveries"},
    "server/ledger/task_results.py": {"fleet_tasks", "fleet_robot_reservations"},
    "server/ledger/action_claims.py": {"fleet_action_claims"},
    "server/dispatch_admission.py": {"fleet_action_claims"},
    "server/ledger/charge_store.py": {"fleet_action_claims"},
    "server/ledger/task_schema.py": {"fleet_action_claims"},
    "server/cancel_all_store.py": {"fleet_tasks", "fleet_task_history", "fleet_robot_reservations"},
    "server/missions/mission_store.py": {"fleet_action_claims"},
    "server/cell/cell_job_store.py": {"fleet_action_claims"},
    "server/cell/cell_arm_claims.py": {"fleet_action_claims"},
    "server/cell/cell_arm_jobs.py": {"fleet_action_claims"},
    "server/cell/cell_sheet_checkpoints.py": {"fleet_action_claims"},
    "server/work/physical_transfer_schema.py": {"fleet_action_claims"},  # D-856: stop/startup retains HELD/UNKNOWN.
    "server/work/physical_transfer_execution.py": {"fleet_action_claims"},  # D-856: reviewed proof/fence/claim first-send transaction.
    "server/channel/execution/journal.py": {"fleet_action_claims"},
    "server/channel/execution/outcomes/reconcile.py": {"fleet_tasks", "fleet_robot_reservations",
                                                       "fleet_action_claims"},
    "server/channel/execution/outcomes/task_receipt.py": {"fleet_tasks", "fleet_robot_reservations",
                                                          "fleet_action_claims"},
}

#: Why each listed module writes (#233). These are reviewed transaction owners (D-750), not temporary
#: exceptions, so none has an expiry; a writer that should move under another owner says so here.
WRITER_REASONS = {
    "server/ledger/task_store.py": "task ledger owner: creates tasks, appends history, cancels queued tasks",
    "server/ledger/task_dispatch_control.py": "dispatch authority: rearm/abort and release task resources",
    "server/ledger/task_dispatch_queue.py": "queue admission: claims the next task and its robot reservation",
    "server/ledger/control_stop_store.py": "control-unit stop journal and local latch owner (D-862)",
    "server/ledger/task_results.py": "closes a dispatch attempt from CORE navigation events",
    "server/ledger/action_claims.py": "releases per-Action arm and zone claims (D-779 5)",
    "server/dispatch_admission.py": "reserves and releases claims inside the caller's transaction (D-750)",
    "server/ledger/charge_store.py": "charging sessions hold their claims in the work admission transaction (D-772)",
    "server/ledger/task_schema.py": "one-time migration of legacy reservations into claims",
    "server/cancel_all_store.py": "durable site-wide cancel-all record (D-421, safety path)",
    "server/missions/mission_store.py": "Mission admission moves its claims with the Mission (D-664)",
    "server/cell/cell_job_store.py": "fixed-cell job admission and hold move its claims (D-403)",
    "server/cell/cell_arm_claims.py": "per-Action arm and zone claim phases of a multi-arm job (D-779 5-6)",
    "server/cell/cell_arm_jobs.py": "multi-arm job creation, hold and recovery move its claims (D-779)",
    "server/cell/cell_sheet_checkpoints.py": "manual-sheet barrier holds the job's claims",
    "server/work/physical_transfer_schema.py": "site stop holds physical transfer claims (D-856)",
    "server/work/physical_transfer_execution.py": "physical preparation, hold and confirmation move claims (D-856)",
    "server/channel/execution/journal.py": "channel execution steps link and finish their claims",
    "server/channel/execution/outcomes/reconcile.py": "native evidence closes exactly one claim by CAS",
    "server/channel/execution/outcomes/task_receipt.py": "binds the first native task response by attempt CAS",
}


def _writers() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(FLEET.rglob("*.py")):
        tables = {match.group(1).lower() for match in _WRITE.finditer(path.read_text(encoding="utf-8"))}
        if tables:
            found[path.relative_to(FLEET).as_posix()] = tables
    return found


def test_ledger_tables_are_created_by_the_task_store():
    task_source = (FLEET / "server/ledger/task_store.py").read_text(encoding="utf-8")
    creators = {"fleet_control_stops": "server/ledger/control_stop_schema.py",
                "fleet_control_stop_deliveries": "server/ledger/control_stop_schema.py"}
    for table in LEDGER_TABLES:
        source = (FLEET / creators[table]).read_text(encoding="utf-8") if table in creators else task_source
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in source
    assert "ensure_control_stop_schema(connection)" in task_source


def test_only_the_listed_modules_write_the_ledger_tables():
    found = _writers()
    new = {path: sorted(tables) for path, tables in found.items() if not tables <= KNOWN_WRITERS.get(path, set())}
    gone = {path: sorted(tables - found.get(path, set()))
            for path, tables in KNOWN_WRITERS.items() if tables - found.get(path, set())}
    assert not new, f"new Fleet ledger writers; review and list them in KNOWN_WRITERS: {new}"
    assert not gone, f"listed ledger writes no longer occur; remove them from KNOWN_WRITERS: {gone}"


def test_every_ledger_writer_states_why_it_writes():
    """#233: a listed writer without a reason would turn the list into a standing permit."""
    assert set(WRITER_REASONS) == set(KNOWN_WRITERS)
    assert all(reason.strip() for reason in WRITER_REASONS.values())
