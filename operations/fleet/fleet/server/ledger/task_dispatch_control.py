"""Dispatch authority and resource claims for the existing task ledger."""

from __future__ import annotations

from contextlib import closing

from fleet.server.dispatch_admission import release as release_dispatch_claims
from fleet.server.dispatch_admission import reserve as reserve_dispatch_claims

from .task_store_types import InvalidTaskTransition, _now


class TaskDispatchControl:
    def reserve_resources(self, *, owner_kind: str, owner_id: str, generation: int,
                          resources: list[tuple[str, str]], phase: str = "CLAIMED") -> bool:
        """Atomically reserve canonical resources for a task, Mission, or direct Action."""
        if phase != "CLAIMED":
            raise ValueError("new resource reservations must use CLAIMED phase")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if (not control["dispatch_enabled"] or control["generation"] != generation):
                connection.commit()
                return False
            claimed = reserve_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation, resources=resources, phase="CLAIMED",
            )
            connection.commit()
        return claimed

    def restore_unresolved_action_claim(self, *, owner_kind: str, owner_id: str,
                                        generation: int, resources: list[tuple[str, str]],
                                        phase: str) -> bool:
        """Restore persisted in-flight device ownership while dispatch is closed.

        Only an external, durable Action reconciliation path should call this;
        regular admission cannot manufacture DISPATCHING or UNKNOWN claims.
        """
        if owner_kind not in {"mission", "direct_action"}:
            raise ValueError("only Mission or direct Action claims may be restored here")
        if phase not in {"DISPATCHING", "UNKNOWN"}:
            raise ValueError("restored Action claim phase must be DISPATCHING or UNKNOWN")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if control["dispatch_enabled"]:
                connection.rollback()
                raise ValueError("unresolved Action claims may only be restored while dispatch is closed")
            claimed = reserve_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation, resources=resources, phase=phase,
            )
            connection.commit()
        return claimed

    def release_resources(self, *, owner_kind: str, owner_id: str,
                          generation: int | None = None) -> bool:
        """Release only the matching owner generation after outcome reconciliation."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            released = release_dispatch_claims(
                connection, owner_kind=owner_kind, owner_id=owner_id,
                generation=generation,
            )
            if owner_kind == "task":
                connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?",
                                   (owner_id,))
            connection.commit()
        return released > 0

    def resource_claims(self, *, resource_kind: str, resource_id: str) -> list[dict]:
        resource_key = f"{resource_kind}:{resource_id}"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT resource_kind, resource_id, owner_kind, owner_id,
                          generation, phase
                   FROM fleet_action_claims WHERE resource_key=?""",
                (resource_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def dispatch_control(self) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT authority_epoch, generation, dispatch_enabled, reason
                   FROM fleet_dispatch_control WHERE control_id=1"""
            ).fetchone()
            queued = connection.execute(
                """SELECT COUNT(*) FROM fleet_tasks WHERE status='QUEUED'
                   AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"""
            ).fetchone()[0]
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM fleet_action_claims
                   WHERE phase IN ('DISPATCHING', 'UNKNOWN')"""
            ).fetchone()[0]
        return {"authority_epoch": row["authority_epoch"],
                "generation": row["generation"],
                "dispatch_enabled": bool(row["dispatch_enabled"]),
                "reason": row["reason"], "queued_tasks": int(queued),
                "unresolved_actions": int(unresolved),
                "rearm_available": not bool(row["dispatch_enabled"]) and unresolved == 0}

    def close_dispatch_for_startup(self) -> dict:
        return self._advance_dispatch_control(enabled=False, actor_id="system",
                                              reason="PROCESS_RESTARTED",
                                              release_pre_dispatch=True,
                                              advance_authority_epoch=True)

    def trip_stop_latch(self, *, actor_id: str, reason: str = "SITE_STOP") -> dict:
        if not actor_id or len(actor_id) > 96 or not reason or len(reason) > 64:
            raise ValueError("invalid stop latch attribution")
        return self._advance_dispatch_control(enabled=False, actor_id=actor_id,
                                              reason=reason, release_pre_dispatch=True)

    def rearm_dispatch(self, *, expected_generation: int, actor_id: str) -> dict:
        if (isinstance(expected_generation, bool) or not isinstance(expected_generation, int)
                or expected_generation < 0 or not actor_id or len(actor_id) > 96):
            raise ValueError("invalid dispatch rearm request")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if current["generation"] != expected_generation:
                raise InvalidTaskTransition("dispatch generation changed; refresh before rearm")
            if current["dispatch_enabled"]:
                raise InvalidTaskTransition("dispatch is already enabled")
            unresolved = connection.execute(
                "SELECT 1 FROM fleet_action_claims "
                "WHERE phase IN ('DISPATCHING', 'UNKNOWN') LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                raise InvalidTaskTransition("unresolved Action claims must be reconciled before rearm")
            connection.execute(
                """UPDATE fleet_dispatch_control SET generation=generation+1,
                   dispatch_enabled=1, reason='OPERATOR_REARM', actor_id=?, updated_at=?
                   WHERE control_id=1 AND generation=? AND dispatch_enabled=0""",
                (actor_id, now, expected_generation),
            )
            connection.commit()
        return self.dispatch_control()

    def dispatch_generation_is_current(self, generation: int) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT 1 FROM fleet_dispatch_control
                   WHERE control_id=1 AND dispatch_enabled=1 AND generation=?""",
                (generation,),
            ).fetchone()
        return row is not None

    def abort_dispatch_before_send(self, task_id: str, *, attempt_id: str) -> dict:
        """Return an attempt to READY only when a stale permit prevented any send."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM fleet_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if current is None:
                raise KeyError(task_id)
            if (current["dispatch_phase"] != "DISPATCHING"
                    or current["attempt_id"] != attempt_id
                    or (control["dispatch_enabled"]
                        and control["generation"] == current["dispatch_generation"])):
                raise InvalidTaskTransition("dispatch attempt is not fenced by a changed stop generation")
            reason = "STOP_GENERATION_CHANGED_BEFORE_SEND"
            connection.execute(
                """UPDATE fleet_tasks SET dispatch_phase='READY', attempt_id=NULL,
                   lease_owner=NULL, lease_until=NULL, reason=?, updated_at=?
                   WHERE task_id=?""",
                (reason, now, task_id),
            )
            connection.execute("DELETE FROM fleet_robot_reservations WHERE task_id=?", (task_id,))
            release_dispatch_claims(connection, owner_kind="task", owner_id=task_id)
            self._append_history(connection, task_id, "QUEUED", "system", "fleet-dispatch",
                                 now, reason)
            row = connection.execute("SELECT * FROM fleet_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()
            connection.commit()
        return self._task_dict(row)

    def _advance_dispatch_control(self, *, enabled: bool, actor_id: str,
                                  reason: str, release_pre_dispatch: bool = False,
                                  advance_authority_epoch: bool = False) -> dict:
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE fleet_dispatch_control SET generation=generation+1,
                   authority_epoch=authority_epoch+?,
                   dispatch_enabled=?, reason=?, actor_id=?, updated_at=? WHERE control_id=1""",
                (int(advance_authority_epoch), int(enabled), reason, actor_id, now),
            )
            if release_pre_dispatch:
                from fleet.server.cell_job_store import hold_for_site_stop  # Cell Jobs keep claims (D-403)
                from fleet.server.charge_store import retain_charge_claims_for_stop
                hold_for_site_stop(connection, now=now, hold_reason=None if advance_authority_epoch else "site_stop")
                retain_charge_claims_for_stop(connection)
                rows = connection.execute(
                    """SELECT owner_kind, owner_id FROM fleet_action_claims
                       WHERE phase='CLAIMED'"""
                ).fetchall()
                for row in rows:
                    if row["owner_kind"] == "task":
                        connection.execute(
                            """UPDATE fleet_tasks SET lease_owner=NULL, lease_until=NULL,
                               updated_at=? WHERE task_id=? AND status='QUEUED'
                               AND dispatch_phase='READY'""",
                            (now, row["owner_id"]),
                        )
                        connection.execute(
                            "DELETE FROM fleet_robot_reservations WHERE task_id=?",
                            (row["owner_id"],),
                        )
                connection.execute("DELETE FROM fleet_action_claims WHERE phase='CLAIMED'")
            connection.commit()
        return self.dispatch_control()
