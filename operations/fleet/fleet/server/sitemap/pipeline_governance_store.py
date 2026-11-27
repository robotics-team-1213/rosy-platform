"""Durable SQLite authority/idempotency/confirmation store & governance helpers for Fleet cell tasks."""
from __future__ import annotations

from contextlib import contextmanager, suppress
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from core_common.protocol.cell_failure_context import FALLBACK_VERBS
from fastapi import HTTPException
from fleet.server.pipeline_autonomous_policy import (
    allow_autonomous_policy_fallback, autonomous_approver,
    prepare_proposer_and_fallback, resolve_autonomous_status,
    validate_cas_fields as _validate_cas_fields,
)

_AMR_BED_SITES = frozenset({"tray", "vehicle_tray"})


def canonical_digest(value: Any) -> str:
    """Return a deterministic SHA-256 hex digest of JSON-serializable governance state."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def safe_canonical_digest(value: Any) -> str:
    """Compute canonical SHA-256 or raise 422 on non-finite numbers / unserializable payloads."""
    try:
        return canonical_digest(value)
    except (TypeError, ValueError):
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"}) from None


def is_named_operator(principal_id: str | None) -> bool:
    """True only for an explicit non-shared operator identity."""
    return isinstance(principal_id, str) and bool(principal_id.strip()) and principal_id.strip() != "site-console" and not principal_id.strip().startswith("development-")


def require_human_operator(principal: Any) -> str:
    """Enforce an authenticated non-service/non-AI human operator with a named identity."""
    role = getattr(principal, "role", None)
    pid = getattr(principal, "principal_id", None)
    if principal is None or role in ("service", "ai_observer", "viewer", None) or not is_named_operator(pid):
        raise HTTPException(403, detail={"code": "NAMED_OPERATOR_REQUIRED"})
    return pid.strip()


def validate_request_key(raw_key: Any) -> str | None:
    """Validate optional idempotency key type and length (1..128 chars)."""
    if raw_key is None:
        return None
    if not isinstance(raw_key, str) or not raw_key.strip() or len(raw_key) > 128:
        raise HTTPException(422, detail={"code": "INVALID_IDEMPOTENCY_KEY"})
    return raw_key.strip()


def scoped_idempotency_key(req_key: str, principal_id: str | None, principal_role: str | None) -> str:
    """Bind idempotency storage keys to the authenticated principal + role."""
    return f"{principal_role or ''}:{principal_id or ''}:{req_key}"


def resolve_task_proposer(spec: dict[str, Any], *, principal_id: str | None, principal_role: str | None) -> tuple[str, str | None]:
    """Derive task status and server-authenticated proposer; reject spoofed proposer or non-bool propose."""
    if "propose" in spec and spec["propose"] is not None and type(spec["propose"]) is not bool:
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
    if spec.get("proposer") is not None:
        raise HTTPException(422, detail={"code": "CLIENT_PROPOSER_FORBIDDEN"})
    target_status, proposer_val, _ = resolve_autonomous_status(spec, principal_id=principal_id, principal_role=principal_role)
    return target_status, proposer_val


def derive_interlock_scope(
    cell_id: str, src_site: str, dst_site: str, *, vehicle_sites: tuple[str, ...] | frozenset[str] = (),
) -> str:
    """Server-derived interlock scope; ignores client-supplied scope claims."""
    bed_names = _AMR_BED_SITES | {str(s).strip().lower() for s in vehicle_sites if s}
    bed_prefixes = ("bed", *(str(s).strip().lower() for s in vehicle_sites if s))
    for site in (src_site or "", dst_site or ""):
        low = str(site).strip().lower()
        if any(seg in bed_names or seg.startswith(bed_prefixes) for seg in low.split(":")):
            return "amr_bed"
    return "cell_internal"


def check_fallback_limits(tasks: dict[str, dict], spec: dict[str, Any]) -> int:
    """Compute authoritative chain depth, enforce depth <= 2 & single retry, and validate fallback_verb."""
    fb_verb = spec.get("fallback_verb")
    if fb_verb is not None and (not isinstance(fb_verb, str) or fb_verb not in FALLBACK_VERBS):
        raise HTTPException(422, detail={"code": "INVALID_FALLBACK_VERB"})
    raw_depth = spec.get("fallback_chain_depth")
    if raw_depth is not None and (type(raw_depth) is not int or raw_depth < 0 or raw_depth > 2):
        raise HTTPException(409, detail={"code": "FALLBACK_RETRY_LIMIT_EXCEEDED"})
    parent_id = spec.get("fallback_from_task_id")
    if not parent_id:
        if raw_depth is not None and raw_depth != 0:
            raise HTTPException(409, detail={"code": "FALLBACK_RETRY_LIMIT_EXCEEDED"})
        return 0
    if not isinstance(parent_id, str):
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
    parent = tasks.get(parent_id)
    if parent is None:
        raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
    depth = int(parent.get("fallback_chain_depth") or 0) + 1
    if (raw_depth is not None and raw_depth != depth) or depth > 2:
        raise HTTPException(409, detail={"code": "FALLBACK_RETRY_LIMIT_EXCEEDED"})
    if any(t.get("fallback_from_task_id") == parent_id and t.get("status") != "CANCELLED" for t in tasks.values()):
        raise HTTPException(409, detail={"code": "FALLBACK_RETRY_LIMIT_EXCEEDED"})
    return depth


def check_policy_fallback_guard(
    tasks: dict[str, dict], spec: dict[str, Any], *, role: str | None, principal_id: str | None, target_status: str,
) -> bool:
    """Block auto/unapproved/non-terminal act_policy -> guarded_pick replacement; returns requires_named_approval."""
    parent_id = spec.get("fallback_from_task_id")
    if not parent_id:
        return False
    parent = tasks.get(parent_id) or {}
    new_mode = spec.get("execution_mode") or "guarded_pick"
    if not (parent.get("execution_mode") == "act_policy" and new_mode != "act_policy"):
        return False
    if parent.get("status") not in ("COMPLETED", "CANCELLED", "ABORTED"):
        raise HTTPException(409, detail={"code": "POLICY_PARENT_NOT_TERMINAL"})
    if allow_autonomous_policy_fallback(target_status):
        return False
    if spec.get("auto_admit") is True:
        raise HTTPException(403, detail={"code": "POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL"})
    if target_status == "QUEUED" and (role in ("service", "ai_observer") or not is_named_operator(principal_id)):
        raise HTTPException(403, detail={"code": "POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL"})
    return True


def build_cell_readiness(
    app, cell_id: str, *, active_map_fn, resolve_cells_fn, is_human_detected_fn, arm_live_catalog_fn, gov: "PipelineGovernanceStore",
) -> dict[str, Any]:
    """Assemble strict `rosy.fleet-cell-readiness.v1` snapshot with digest for CAS admission."""
    active = active_map_fn()
    station = resolve_cells_fn(active[1], active[2]).get(cell_id)
    if station is None:
        raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
    cell_arms = ("arm_s",) if cell_id == "cell_s" else ("arm_a", "arm_b")
    cstate = (getattr(app.state, "omx_cell_states", None) or {}).get(cell_id) or {}
    holds = getattr(app.state, "arm_holds", None) or {}
    live_cat = arm_live_catalog_fn()
    tasks = list((getattr(app.state, "omx_cell_tasks", None) or {}).values())
    cell_tasks = [t for t in tasks if t.get("cell_id") == cell_id]
    arms = {}
    refusals = []
    human = bool(is_human_detected_fn(cell_id))
    estop = bool(is_human_detected_fn())
    if estop:
        refusals.append("active_estop")
    if human:
        refusals.append(f"{cell_id}:human_detected")
    if cstate.get("phase") in ("HUMAN_HOLD", "ABORTED"):
        refusals.append(f"{cell_id}:{cstate.get('phase')}")
    for aid in cell_arms:
        h = holds.get(aid) or {}
        st = live_cat.get(aid) or {}
        held = bool(h.get("held"))
        if held:
            refusals.append(f"{aid}:incident_held")
        arms[aid] = {
            "held": held,
            "reason": h.get("reason"),
            "folded": st.get("folded"),
            "observed": bool(st.get("observed")),
            "fresh": bool(st.get("fresh")),
            "active_task_id": st.get("active_task_id"),
        }
    auth = gov.snapshot()
    core = {
        "schema": "rosy.fleet-cell-readiness.v1",
        "observed_at": round(time.time(), 3),
        "cell_id": cell_id,
        "cell_phase": cstate.get("phase") or "IDLE",
        "human_detected": human,
        "active_estop": estop,
        "authority_epoch": auth["authority_epoch"],
        "dispatch_generation": auth["dispatch_generation"],
        "stop_generation": auth["stop_generation"],
        "arms": arms,
        "blocking_refusals": refusals,
        "counts": {
            "proposed": sum(1 for t in cell_tasks if t.get("status") == "PROPOSED"),
            "queued": sum(1 for t in cell_tasks if t.get("status") == "QUEUED"),
            "running": sum(1 for t in cell_tasks if t.get("status") == "RUNNING"),
        },
    }
    stable_core = {k: v for k, v in core.items() if k != "observed_at"}
    return {**core, "readiness_digest": canonical_digest(stable_core)}


def prepare_task_governance(
    app, spec: dict[str, Any], *, principal_id: str | None, principal_role: str | None,
    cell_id: str, src_site: str, dst_site: str, gov: "PipelineGovernanceStore | None",
    active_map_fn, resolve_cells_fn, is_human_detected_fn, arm_live_catalog_fn,
    vehicle_sites: tuple[str, ...] | frozenset[str] = (),
) -> tuple[str, dict[str, Any]]:
    """Run all governance, depth, policy-swap, and read-only CAS checks before task construction."""
    target_status, proposer_val, approval_mode, depth_val, req_named = prepare_proposer_and_fallback(
        app.state.omx_cell_tasks, spec, principal_id=principal_id, principal_role=principal_role,
        check_limits_fn=check_fallback_limits, check_fallback_fn=check_policy_fallback_guard)
    if any(spec.get(k) is not None for k in (
        "expected_context_sha256", "expected_readiness_digest", "expected_dispatch_generation",
        "expected_authority_epoch", "expected_stop_generation",
    )):
        if gov is None:
            raise HTTPException(503, detail={"code": "GOVERNANCE_STORE_UNAVAILABLE"})
        rdy = build_cell_readiness(
            app, cell_id, active_map_fn=active_map_fn, resolve_cells_fn=resolve_cells_fn,
            is_human_detected_fn=is_human_detected_fn, arm_live_catalog_fn=arm_live_catalog_fn, gov=gov,
        )
        ok_cas, reasons = gov.verify_cas(
            spec, {"context_sha256": spec.get("failure_context_sha256"), "readiness_digest": rdy["readiness_digest"]},
        )
        if not ok_cas:
            raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": reasons})
    meta = {
        "interlock_scope": derive_interlock_scope(cell_id, src_site, dst_site, vehicle_sites=vehicle_sites),
        "fallback_chain_depth": depth_val,
        "proposer": proposer_val,
        "approved_by": autonomous_approver(principal_id, principal_role, target_status, approval_mode, is_named_operator),
        **({"approval_mode": approval_mode} if approval_mode else {}),
        **({"requires_named_approval": True} if req_named else {}),
        **{k: spec[k] for k in ("fallback_from_task_id", "fallback_verb", "failure_bundle_id", "failure_context_sha256") if spec.get(k) is not None},
    }
    return target_status, meta


class PipelineGovernanceStore:
    """Single-owner SQLite store for authority_epoch, dispatch/stop generations, idempotency, and confirmations."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
        with self._write_tx():
            for ddl in (
                """CREATE TABLE IF NOT EXISTS pipeline_authority_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    authority_epoch INTEGER NOT NULL,
                    dispatch_generation INTEGER NOT NULL,
                    stop_generation INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS pipeline_idempotency (
                    request_key TEXT PRIMARY KEY,
                    body_sha256 TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS pipeline_confirmations (
                    kind TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (kind, task_id)
                )""",
                """CREATE TABLE IF NOT EXISTS pipeline_admitted_tasks (
                    task_id TEXT PRIMARY KEY,
                    approved_by TEXT NOT NULL,
                    admitted_at REAL NOT NULL
                )""",
            ):
                self._conn.execute(ddl)
            now = time.time()
            row = self._conn.execute("SELECT authority_epoch FROM pipeline_authority_state WHERE id = 1").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO pipeline_authority_state (id, authority_epoch, dispatch_generation, stop_generation, updated_at) VALUES (1, 1, 0, 0, ?)",
                    (now,),
                )
            else:
                self._conn.execute(
                    "UPDATE pipeline_authority_state SET authority_epoch = authority_epoch + 1, updated_at = ? WHERE id = 1",
                    (now,),
                )
            # D-1057 fail-closed across restart: purge unmonitored bed confirmations on startup epoch.
            self._conn.execute("DELETE FROM pipeline_confirmations WHERE kind = 'bed'")

    @contextmanager
    def _write_tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                if self._conn.in_transaction:
                    self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    with suppress(Exception):
                        self._conn.execute("ROLLBACK")
                raise

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT authority_epoch, dispatch_generation, stop_generation FROM pipeline_authority_state WHERE id = 1"
            ).fetchone()
            return {
                "authority_epoch": int(row["authority_epoch"]),
                "dispatch_generation": int(row["dispatch_generation"]),
                "stop_generation": int(row["stop_generation"]),
            }

    def bump_dispatch_generation(self) -> int:
        with self._write_tx():
            self._conn.execute(
                "UPDATE pipeline_authority_state SET dispatch_generation = dispatch_generation + 1, updated_at = ? WHERE id = 1",
                (time.time(),),
            )
            return int(self._conn.execute("SELECT dispatch_generation FROM pipeline_authority_state WHERE id = 1").fetchone()[0])

    def bump_stop_generation(self) -> int:
        with self._write_tx():
            self._conn.execute(
                "UPDATE pipeline_authority_state SET stop_generation = stop_generation + 1, updated_at = ? WHERE id = 1",
                (time.time(),),
            )
            return int(self._conn.execute("SELECT stop_generation FROM pipeline_authority_state WHERE id = 1").fetchone()[0])

    def check_idempotency(self, request_key: str, body_sha256: str) -> tuple[int, dict] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body_sha256, status_code, response_json FROM pipeline_idempotency WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            if row is None:
                return None
            if row["body_sha256"] != body_sha256:
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
            return int(row["status_code"]), json.loads(row["response_json"])

    def record_idempotency(self, request_key: str, body_sha256: str, status_code: int, payload: dict) -> None:
        self.commit_enqueue(bump_dispatch=False, idempotency=(request_key, body_sha256, status_code, payload))

    def commit_enqueue(
        self,
        *,
        bump_dispatch: bool,
        bump_stop: bool = False,
        idempotency: tuple[str, str, int, dict] | None = None,
        ledger_snapshot: dict | None = None,
        delete_confirmation: tuple[str, str] | None = None,
    ) -> int | None:
        """Record idempotency, ledger commit marker, confirmation delete, and generation bumps in one SQLite tx."""
        encoded = (
            json.dumps(idempotency[3], ensure_ascii=False, allow_nan=False, default=str)
            if idempotency is not None else None
        )
        ledger_encoded = (
            json.dumps(
                {"sha256": canonical_digest(ledger_snapshot), "payload": ledger_snapshot},
                ensure_ascii=False, allow_nan=False, default=str,
            )
            if ledger_snapshot is not None else None
        )
        now = time.time()
        with self._write_tx():
            if idempotency is not None:
                req_key, body_sha256, status_code, _ = idempotency
                row = self._conn.execute(
                    "SELECT body_sha256 FROM pipeline_idempotency WHERE request_key = ?", (req_key,),
                ).fetchone()
                if row is not None and row["body_sha256"] != body_sha256:
                    raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
                self._conn.execute(
                    "INSERT OR REPLACE INTO pipeline_idempotency (request_key, body_sha256, status_code, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (req_key, body_sha256, int(status_code), encoded, now),
                )
            if delete_confirmation is not None:
                self._conn.execute(
                    "DELETE FROM pipeline_confirmations WHERE kind = ? AND task_id = ?", delete_confirmation,
                )
            if ledger_encoded is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO pipeline_confirmations (kind, task_id, record_json, updated_at) VALUES ('ledger_commit', 'current', ?, ?)",
                    (ledger_encoded, now),
                )
            if bump_stop:
                self._conn.execute(
                    "UPDATE pipeline_authority_state SET stop_generation = stop_generation + 1, updated_at = ? WHERE id = 1",
                    (now,),
                )
            if not bump_dispatch:
                return None
            self._conn.execute(
                "UPDATE pipeline_authority_state SET dispatch_generation = dispatch_generation + 1, updated_at = ? WHERE id = 1",
                (now,),
            )
            return int(self._conn.execute("SELECT dispatch_generation FROM pipeline_authority_state WHERE id = 1").fetchone()[0])

    def load_committed_ledger(self) -> dict | None:
        return self.load_confirmations("ledger_commit").get("current")

    def save_confirmation(self, kind: str, task_id: str, rec: dict) -> None:
        encoded = json.dumps(rec, ensure_ascii=False, allow_nan=False, default=str)
        with self._write_tx():
            self._conn.execute(
                "INSERT OR REPLACE INTO pipeline_confirmations (kind, task_id, record_json, updated_at) VALUES (?, ?, ?, ?)",
                (kind, task_id, encoded, time.time()),
            )

    def delete_confirmation(self, kind: str, task_id: str) -> None:
        with self._write_tx():
            self._conn.execute("DELETE FROM pipeline_confirmations WHERE kind = ? AND task_id = ?", (kind, task_id))

    def load_confirmations(self, kind: str) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id, record_json FROM pipeline_confirmations WHERE kind = ?", (kind,),
            ).fetchall()
            return {r["task_id"]: json.loads(r["record_json"]) for r in rows}

    def verify_cas(self, expected: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, list[str]]:
        """Read-only CAS check without mutating dispatch_generation."""
        snap = self.snapshot()
        reasons = _validate_cas_fields(
            expected, actual, ep=snap["authority_epoch"], dg=snap["dispatch_generation"], sg=snap["stop_generation"],
            require_all=False, require_context_sha=False,
        )
        return (not reasons), reasons

    def admit_cas(
        self, expected: dict[str, Any], actual: dict[str, Any], *,
        task_id: str | None = None, approved_by: str | None = None, require_all: bool = True,
        ledger_snapshot: dict | None = None,
    ) -> tuple[bool, list[str], int]:
        """Single-transaction CAS checking context digest, readiness digest, and authority generations."""
        ledger_encoded = (
            json.dumps(
                {"sha256": canonical_digest(ledger_snapshot), "payload": ledger_snapshot},
                ensure_ascii=False, allow_nan=False, default=str,
            )
            if ledger_snapshot is not None else None
        )
        with self._write_tx():
            if task_id is not None and self._conn.execute(
                "SELECT 1 FROM pipeline_admitted_tasks WHERE task_id = ?", (task_id,),
            ).fetchone() is not None:
                row = self._conn.execute("SELECT dispatch_generation FROM pipeline_authority_state WHERE id = 1").fetchone()
                return False, ["task already admitted"], int(row["dispatch_generation"])
            row = self._conn.execute(
                "SELECT authority_epoch, dispatch_generation, stop_generation FROM pipeline_authority_state WHERE id = 1"
            ).fetchone()
            ep, dg, sg = int(row["authority_epoch"]), int(row["dispatch_generation"]), int(row["stop_generation"])
            reasons = _validate_cas_fields(
                expected, actual, ep=ep, dg=dg, sg=sg,
                require_all=require_all, require_context_sha=bool(actual.get("context_sha256")),
            )
            if reasons:
                return False, reasons, dg
            new_dg = dg + 1
            now = time.time()
            self._conn.execute(
                "UPDATE pipeline_authority_state SET dispatch_generation = ?, updated_at = ? WHERE id = 1",
                (new_dg, now),
            )
            if task_id is not None:
                self._conn.execute(
                    "INSERT INTO pipeline_admitted_tasks (task_id, approved_by, admitted_at) VALUES (?, ?, ?)",
                    (task_id, approved_by or "", now),
                )
            if ledger_encoded is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO pipeline_confirmations (kind, task_id, record_json, updated_at) VALUES ('ledger_commit', 'current', ?, ?)",
                    (ledger_encoded, now),
                )
            return True, [], new_dg

    def rollback_admitted_task(self, task_id: str) -> None:
        """Undo task admission record if ledger persistence fails."""
        with self._write_tx():
            self._conn.execute("DELETE FROM pipeline_admitted_tasks WHERE task_id = ?", (task_id,))

    def reconcile_unpersisted_admissions(self, tasks: dict[str, dict]) -> list[str]:
        """Clear orphan admission markers left by a crash between admit_cas() and ledger save."""
        reconciled: list[str] = []
        with self._write_tx():
            for row in self._conn.execute("SELECT task_id FROM pipeline_admitted_tasks").fetchall():
                tid = str(row["task_id"])
                task = tasks.get(tid)
                if task is not None and task.get("status") == "PROPOSED":
                    self._conn.execute("DELETE FROM pipeline_admitted_tasks WHERE task_id = ?", (tid,))
                    reconciled.append(tid)
        return reconciled


def admit_cell_task_guarded(
    app, task_id: str, raw_body: bytes, principal: Any, *,
    active_map_fn, resolve_cells_fn, is_human_detected_fn, arm_live_catalog_fn, enrich_fn, save_ledger_fn,
    gov: PipelineGovernanceStore | None, ledger_payload_fn=None, write_ledger_fn=None,
) -> dict[str, Any]:
    """Fail-closed atomic PROPOSED -> QUEUED transition with human operator check and ledger rollback."""
    if gov is None or getattr(app.state, "_pipeline_ledger_fault", False):
        raise HTTPException(503, detail={"code": "GOVERNANCE_STORE_UNAVAILABLE"})
    approver = require_human_operator(principal)
    try:
        body = json.loads(raw_body) if raw_body.strip() else {}
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"}) from None
    if not isinstance(body, dict):
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
    with gov._lock:
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        if task.get("status") != "PROPOSED":
            raise HTTPException(409, detail={"code": "CELL_TASK_NOT_PROPOSED"})
        proposer = str(task.get("proposer") or "").strip()
        if not proposer or proposer == approver:
            raise HTTPException(403, detail={"code": "SELF_APPROVAL_FORBIDDEN"})
        rdy = build_cell_readiness(
            app, task["cell_id"], active_map_fn=active_map_fn, resolve_cells_fn=resolve_cells_fn,
            is_human_detected_fn=is_human_detected_fn, arm_live_catalog_fn=arm_live_catalog_fn, gov=gov,
        )
        prev = {k: task.get(k) for k in ("status", "approved_by", "admitted_at", "health_summary")}
        actual_cas = {"context_sha256": task.get("failure_context_sha256"), "readiness_digest": rdy["readiness_digest"]}
        if callable(ledger_payload_fn) and callable(write_ledger_fn):
            task["status"], task["approved_by"], task["admitted_at"] = "QUEUED", approver, round(time.time(), 3)
            try:
                enrich_fn(task)
                payload = ledger_payload_fn()
                write_ledger_fn(payload)
                ok_cas, reasons, new_dg = gov.admit_cas(
                    body, actual_cas, task_id=task_id, approved_by=approver, require_all=True, ledger_snapshot=payload,
                )
                if not ok_cas:
                    raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": reasons})
            except Exception:
                for k, v in prev.items():
                    task.pop(k, None) if v is None else task.__setitem__(k, v)
                if not getattr(app.state, "_pipeline_ledger_fault", False):
                    with suppress(Exception):
                        write_ledger_fn(ledger_payload_fn())
                raise
            return {"ok": True, "task": task, "dispatch_generation": new_dg}
        ok_cas, reasons, new_dg = gov.admit_cas(body, actual_cas, task_id=task_id, approved_by=approver, require_all=True)
        if not ok_cas:
            raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": reasons})
        task["status"], task["approved_by"], task["admitted_at"] = "QUEUED", approver, round(time.time(), 3)
        try:
            enrich_fn(task)
            save_ledger_fn()
        except Exception:
            for k, v in prev.items():
                task.pop(k, None) if v is None else task.__setitem__(k, v)
            gov.rollback_admitted_task(task_id)
            raise
        return {"ok": True, "task": task, "dispatch_generation": new_dg}


def deterministic_idempotency_id(prefix: str, scoped_key: str) -> str:
    """Derive a collision-resistant deterministic task/batch ID from a scoped idempotency key."""
    return f"{prefix}-idemp-{hashlib.sha256(scoped_key.encode('utf-8')).hexdigest()[:12]}"
