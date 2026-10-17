"""Multi-arm Cell Job dispatch (D-779 stages 3-4) and the Cell dispatcher that app.py runs.

``ArmJobDispatcher`` reuses ``StepJobDispatcher`` for everything that is not about arms: the grant
builder, the owner simulation identity check and its cache, GetAction readback with backoff, the
NOT_FOUND rule, receipt verification and the outcome recording path. It hands those helpers an *arm
view*: one arm's Action presented as the current step of a one-step Job, with the arm's owner
instance and inputs, and an ``ArmJobStore`` whose ``record_action_result`` settles that arm. Only
the work list differs: per tick it reads back every in-flight (or unresolved held) arm Action and
starts every ready step, where a step is ready when its ``depends_on`` are GOAL_CONFIRMED, its arms
are READY and its arm and zone claims are free (§2). A coordinated step starts all its arms or none
(D-778 §4); a held single-arm step may go to a READY alternate arm (one-arm mode, §4). The per-tick
I/O cap counts arm Actions, and a round-robin cursor over (Job, step, arm) keeps every Job moving.

Arm owners are configured as ordinary OMX instances (``omx_instances``: owner workcell -> instance,
so the StopLocal fan-out reaches every arm). Each arm names its owner workcell in the Job, and the
Job claims that workcell from admission to the end, so no other Job can drive the same owner. An
arm is dispatchable only when the configuration maps its instance to that same owner workcell,
the instance has simulation grant revisions, and its owner reports that workcell, instance and a
simulation identity. The grant names the owner's workcell; arm and zone claims name the Job's
cell (``<cell>.<arm>``).

``CellJobDispatcher`` is the single-arm dispatcher, unchanged, plus this pass when a multi-arm Job
exists; without one a tick is exactly the single-arm tick. With both, the two passes share one I/O
budget and alternate which goes first.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Mapping

from .cell_arm_claims import arm_key
from .cell_arm_store import ArmJobStore
from .local_action_transport import LocalActionRejected
from .mission_store import MissionConflict
from .step_action_kinds import dispatch_open, rejection_reason, step_grant_digest
from .step_dispatcher import _IN_FLIGHT, _SKIPPED, MAX_IO_PER_TICK, StepJobDispatcher

_ARM_SKIPPED = _SKIPPED | {"CLAIM_BUSY"}
PAIR_REASON = "PAIR_PARTNER_NOT_ACCEPTED"  # D-778 §4: one arm of a pair refused, the step does not run
_LOG = logging.getLogger(__name__)


def pair_fields(grant_model: type, *, role: str, partner_instance: str | None, pair_id: str | None,
                coupling: str, payload: Any) -> dict[str, Any]:
    """D-779 §7 / D-780 §5 grant fields, only those the installed grant model declares.

    The pair fields arrive with a protocol revision on another branch; until then the grant has none
    and this returns {}. ``coupling`` is sent only when the payload's own barrier coupling agrees
    (the grant refuses a mismatch); payloads compiled here carry no barriers yet.
    """
    fields = getattr(grant_model, "model_fields", {})
    extra: dict[str, Any] = {"arm_role": role} if "arm_role" in fields else {}
    if partner_instance is not None and {"pair_id", "partner_instance_id"} <= set(fields):
        extra.update(pair_id=pair_id, partner_instance_id=partner_instance)
        strongest = getattr(payload, "strongest_coupling", None)
        if "coupling" in fields and callable(strongest) and strongest() == coupling:
            extra["coupling"] = coupling
    return extra


class ArmJobDispatcher(StepJobDispatcher):
    """Fleet-owned submitter for admitted multi-arm Cell Jobs, one arm Action at a time per arm."""

    def __init__(self, store: ArmJobStore, task_store, transport, omx_instances: Mapping[str, str],
                 grant_revisions: Mapping[str, Mapping[str, str]], **kwargs: Any) -> None:
        super().__init__(store, task_store, transport, omx_instances, grant_revisions, **kwargs)
        self._owner_workcell = {instance: workcell for workcell, instance in self.omx_instances.items()}
        self._arm_cursor: tuple = ()
        self.io_floor = 0  # I/O the single-arm pass already spent this tick
        self.goal_hook = None  # (job, step_index) after an arm Action's recorded success: stored goal evidence

    def _outcome(self, job, index, grant, outcome, reason, result, *, event_id=None) -> dict[str, Any]:
        """The shared recording path, then the goal hook; the reported state stays the arm Action's own."""
        view = super()._outcome(job, index, grant, outcome, reason, result, event_id=event_id)
        if outcome == "SUCCEEDED" and self.goal_hook is not None and view["state"] == "ACTION_SUCCEEDED":
            try:  # goal processing never rewrites the recorded device success (main 3ef12ca3e)
                self.goal_hook(job, index)
            except Exception:
                _LOG.exception("Cell arm step success callback failed for %s", job["mission_id"])
        return view

    # Arm views handed to the shared StepJobDispatcher helpers -----------------------------------
    def _arm_job(self, job: Mapping[str, Any], action: Mapping[str, Any], inputs=None) -> dict[str, Any]:
        arm = next(item for item in job["arms"] if item["arm_role"] == action["arm_role"])
        step = job["steps"][action["step_index"]]
        return {
            "mission_id": job["mission_id"], "job_id": job["job_id"], "recipe_digest": job["recipe_digest"],
            "cell_digest": job["cell_digest"], "workcell_id": arm["owner_workcell"],
            "instance_id": arm["instance_id"], "authority_epoch": job["authority_epoch"],
            "dispatch_generation": job["dispatch_generation"], "arm_role": action["arm_role"],
            "current_step_index": action["step_index"], "status": action["status"], "reason": action["reason"],
            "steps": {action["step_index"]: {
                "step_index": action["step_index"], "step_id": step["step_id"], "action_kind": step["action_kind"],
                "action_id": action["action_id"], "attempt_id": action["attempt_id"], "grant": action["grant"],
                "step": {"inputs": inputs}}},
        }

    @staticmethod
    def _view(job, index, state, grant=None) -> dict[str, Any]:
        view = StepJobDispatcher._view(job, index, state, grant)
        if job is not None and "arm_role" in job:
            view["arm_role"] = job["arm_role"]
        return view

    def _unresolved(self, job: Mapping[str, Any], action: Mapping[str, Any]) -> bool:
        """A held arm Action whose own arm claim is UNKNOWN or DISPATCHING still needs its readback."""
        phases = self.store.claim_phases(job["mission_id"], [arm_key(job["workcell_id"], action["arm_role"])])
        return bool(phases) and phases <= {"UNKNOWN", "DISPATCHING"}

    def _readbacks(self, job: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [action for action in job["step_actions"] if action["action_id"] is not None and (
            action["status"] == "RUNNING" or (action["status"] == "HOLD" and self._unresolved(job, action)))]

    # Ready set (D-779 §2, §4) --------------------------------------------------------------------
    def _ready_set(self, job: Mapping[str, Any]) -> list[tuple[int, list[str]]]:
        arms = {arm["arm_role"]: arm for arm in job["arms"]}
        confirmed = {step["step_index"] for step in job["steps"] if step["status"] == "GOAL_CONFIRMED"}
        by_step: dict[int, list[Mapping[str, Any]]] = {}
        for action in job["step_actions"]:
            by_step.setdefault(action["step_index"], []).append(action)
        busy: set[str] = set()
        taken: set[str] = set()
        ready = []
        for placement in job["placements"]:
            index = placement["step_index"]
            actions = by_step.get(index, [])
            if (index in confirmed or not set(placement["depends_on"]) <= confirmed
                    or any(action["status"] in {"RUNNING", "HOLD"} for action in actions)):
                continue
            roles = sorted(action["arm_role"] for action in actions if action["status"] in {"WAITING", "READY"})
            assigned = placement["assigned"]
            if not roles or (len(assigned) > 1 and roles != sorted(assigned)):
                continue  # a coordinated step starts every arm together or not at all (D-778 §4)
            if len(assigned) == 1 and arms[assigned[0]]["status"] in {"HOLD", "OFFLINE"}:
                alternate = next((role for role in placement["alternates"]
                                  if arms[role]["status"] == "READY" and role not in busy), None)
                if alternate is None:
                    continue  # no alternate: the step, and every step after it, waits (§4)
                roles = [alternate]
            if any(arms[role]["status"] != "READY" or role in busy for role in roles):
                continue
            keys = {arm_key(job["workcell_id"], role) for role in roles}
            keys.add(f"zone:{job['workcell_id']}.{placement['zone_id']}")
            if keys & taken or self.store.held_keys(sorted(keys)):
                continue
            ready.append((index, roles))
            busy.update(roles)
            taken.update(keys)
        return ready

    # One tick ------------------------------------------------------------------------------------
    def dispatch_next(self) -> dict[str, Any] | None:
        self._io = self.io_floor
        work = []
        for job in self.store.active_jobs():
            for action in self._readbacks(job):
                work.append(((job["mission_id"], action["step_index"], action["arm_role"]), "readback", job, action))
            if job["status"] in {"READY", "RUNNING"}:
                for index, roles in self._ready_set(job):
                    work.append(((job["mission_id"], index, ",".join(roles)), "submit", job, (index, roles)))
        work.sort(key=lambda item: item[0])
        start = next((i for i, item in enumerate(work) if item[0] > self._arm_cursor), 0)
        outcomes = []
        for key, kind, job, item in work[start:] + work[:start]:
            if self._io + _cost(kind, item) > MAX_IO_PER_TICK:
                break
            if kind == "readback":
                view = self._arm_job(job, item)
                if not self._due(view):
                    continue
                self._io += 1
                outcomes.append(self._reconcile(view))
            else:
                outcomes.append(self._submit_step(job, *item))
            self._arm_cursor = key
        return _pick(outcomes)

    def reconcile(self, mission_id: str) -> dict[str, Any]:
        """Operator readback of every in-flight or unresolved arm Action of one Job now."""
        job = self.store.get(mission_id)
        if job is None:
            raise KeyError(mission_id)
        results = []
        for action in self._readbacks(job):
            self._readback.pop(action["action_id"], None)
            results.append(self._reconcile(self._arm_job(job, action)))
        if not results:
            return self._view(job, job["current_step_index"], job["status"])
        return {**results[0], "results": results} if len(results) > 1 else results[0]

    # Submit one ready step -----------------------------------------------------------------------
    def _arm_grant(self, job, index: int, role: str, roles: list[str], placement, pair_id: str):
        action = {"arm_role": role, "step_index": index, "status": "READY", "reason": None,
                  "action_id": None, "attempt_id": None, "grant": None}
        view = self._arm_job(job, action, placement["payloads"][role])
        grant = self._grant(view, view["steps"][index])
        partner = next((arm["instance_id"] for arm in job["arms"] if arm["arm_role"] in roles
                        and arm["arm_role"] != role), None)
        extra = pair_fields(type(grant), role=role, partner_instance=partner, pair_id=pair_id,
                            coupling=placement["coupling"], payload=grant.cell_transfer)
        if not extra:
            return grant
        document = {**grant.model_dump(mode="json"), **extra, "request_digest": "0" * 64}
        document["request_digest"] = step_grant_digest(type(grant).model_validate(document))
        return type(grant).model_validate(document)

    def _submit_step(self, job: Mapping[str, Any], index: int, roles: list[str]) -> dict[str, Any] | None:
        mission_id, step = job["mission_id"], job["steps"][index]
        arms = {arm["arm_role"]: arm for arm in job["arms"]}
        view = {**job, "arm_role": ",".join(roles)}
        if not dispatch_open(self.deployment_profile, step["action_kind"]):
            return self._view(view, index, "NOT_OPEN")
        owners = {role: arms[role]["owner_workcell"] for role in roles}
        claimed = {(kind, name) for kind, name in job["resources"]}
        if any(self._owner_workcell.get(arms[role]["instance_id"]) != owners[role] or ("workcell", owners[role])
               not in claimed or arms[role]["instance_id"] not in self.grant_revisions for role in roles):
            return self._view(view, index, "NOT_CONFIGURED")  # every arm owner is a Job-level claim too
        if not all(self._simulation_identity(owners[role], arms[role]["instance_id"]) for role in roles):
            return self._view(view, index, "NOT_SIMULATION")
        placement = next(item for item in job["placements"] if item["step_index"] == index)
        pair_id = str(uuid.uuid4()) if len(roles) > 1 else None
        try:
            grants = {role: self._arm_grant(job, index, role, roles, placement, pair_id) for role in roles}
            started = self.store.start_actions(
                mission_id, step_index=index, grants={role: g.model_dump(mode="json") for role, g in grants.items()},
                now=self.now(),
                owner_journal_ids={role: self._identity.get(arms[role]["instance_id"], (0, 0, None))[2]
                                   for role in roles})
        except MissionConflict:
            return self._view({**(self.store.get(mission_id) or view), "arm_role": view["arm_role"]}, index, None)
        except KeyError:
            return None
        except (TypeError, ValueError):
            held = self.store.hold_before_send(mission_id, roles=roles, reason="ACTION_GRANT_INVALID",
                                               event_key=f"grant-invalid:{index}")
            return self._view({**held, "arm_role": view["arm_role"]}, index, "HOLD")
        if started["state"] != "RUNNING":
            return self._view({**started, "arm_role": view["arm_role"]}, index, started["state"])
        # The fence was checked in start_actions' transaction; re-read it before sending (1d item 1).
        control = self.task_store.dispatch_control()
        first = grants[roles[0]]
        if (not control["dispatch_enabled"] or control["authority_epoch"] != first.authority_epoch
                or control["generation"] != first.dispatch_generation):
            held = self.store.hold_unsent(mission_id, action_ids=[g.action_id for g in grants.values()],
                                          reason="FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT")
            return self._view({**held, "arm_role": view["arm_role"]}, index, "HOLD", first)
        return self._send(started, index, roles, grants)

    def _fence_open(self, grant) -> bool:
        control = self.task_store.dispatch_control()
        return bool(control["dispatch_enabled"] and control["authority_epoch"] == grant.authority_epoch
                    and control["generation"] == grant.dispatch_generation)

    def _cancel(self, accepted) -> None:
        """Cancel arms that accepted a pair whose partner did not start; readback settles the outcome."""
        for other in accepted:
            self._io += 1
            try:
                self.transport.cancel(other, reason=PAIR_REASON)
            except Exception:
                self._forget_identity(other.instance_id)

    def _hold_rest(self, mission_id: str, action_ids: list[str], reason: str) -> None:
        for action_id in action_ids:  # one by one: a partner already held must not keep the rest RUNNING
            try:
                self.store.hold_unsent(mission_id, action_ids=[action_id], reason=reason)
            except MissionConflict:
                pass  # already held with its tight partner

    def _send(self, job, index: int, roles: list[str], grants) -> dict[str, Any]:
        """Send each arm's grant; if one is refused or unknown, nothing more of the step is sent, the
        unsent arms are held unsent and the accepted ones are cancelled (D-778 §4 pair rule).

        When the step did not start on every arm (a refusal, an unknown or held outcome, a fence
        change between two sends, or an exception out of this loop, after which the unsent arms are
        held too), every sent arm that may still run is cancelled: one whose device accepted it, whose
        submit outcome is unknown, or whose receipt did not end it in success. Only an arm refused
        outright or already succeeded is left alone. A step whose loop finished with every arm
        accepted or succeeded is never cancelled here; an exception after the last send may still
        cancel it (readback settles that)."""
        results, accepted, pending, started = [], [], list(roles), False
        try:
            for position, role in enumerate(roles):
                grant = grants[role]
                action = next(item for item in job["step_actions"]
                              if item["step_index"] == index and item["arm_role"] == role)
                arm_view = self._arm_job(job, action)
                if position and not self._fence_open(grant):
                    # A stop or authority change landed between two sends of a pair (1d item 1, per arm).
                    self._hold_rest(job["mission_id"], [grants[other].action_id for other in pending],
                                    "FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT")
                    break
                pending.remove(role)
                self._io += 1
                failure = None
                try:
                    receipt = self.transport.submit(grant)
                except LocalActionRejected as exc:
                    failure = ("REJECTED", rejection_reason(grant.action_kind, str(exc).split(":", 1)[0]),
                               {"detail": str(exc)[:256]})
                except Exception:
                    self._forget_identity(grant.instance_id)
                    failure = ("UNKNOWN", "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN", {})
                    accepted.append(grant)  # it may have reached the owner and be running
                if failure is None:
                    accepted.append(grant)  # until its receipt says it ended in success
                    result = self._apply(arm_view, index, grant, receipt)
                    results.append(result)
                    if result["state"] in _IN_FLIGHT:
                        continue
                    if result["state"] == "ACTION_SUCCEEDED":
                        accepted.remove(grant)
                        continue
                # This arm did not start (refused, unknown, or ended at once): the pair stops here.
                self._hold_rest(job["mission_id"], [grants[other].action_id for other in pending], PAIR_REASON)
                if failure is not None:
                    results.append(self._outcome(arm_view, index, grant, *failure))
                break
            else:
                started = True
        except Exception:
            # Unexpected error: nothing more is sent, the arms never sent are parked and the sent
            # ones still in flight are cancelled below (readback settles them).
            try:
                self._hold_rest(job["mission_id"], [grants[other].action_id for other in pending],
                                PAIR_REASON)
            except Exception:
                _LOG.exception("unsent arm Actions of %s step %s could not be held", job["mission_id"], index)
            raise
        finally:
            if not started:
                self._cancel(accepted)
        return {**results[-1], "results": results} if len(results) > 1 else results[0]


def _cost(kind: str, item) -> int:
    """Device exchanges a work item may take: a readback 1; a submit 2 per arm (identity, send), and a
    pair one more for cancelling an arm that accepted when its partner did not."""
    if kind == "readback":
        return 1
    return 2 * len(item[1]) + (1 if len(item[1]) > 1 else 0)


def _pick(outcomes: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    acted = [item for item in outcomes if item is not None and item["state"] not in _ARM_SKIPPED]
    seen = [item for item in outcomes if item is not None]
    return acted[0] if acted else (seen[0] if seen else None)


class CellJobDispatcher(StepJobDispatcher):
    """The single-arm dispatcher, unchanged, plus the multi-arm pass while a multi-arm Job is live."""

    def __init__(self, store, task_store, transport, omx_instances, grant_revisions, *, deployment_profile: str,
                 now=None, grant_ttl_s: float = 15.0, on_step_action_succeeded=None,
                 monotonic=time.monotonic) -> None:
        super().__init__(store, task_store, transport, omx_instances, grant_revisions,
                         deployment_profile=deployment_profile, now=now, grant_ttl_s=grant_ttl_s,
                         on_step_action_succeeded=on_step_action_succeeded, monotonic=monotonic)
        self.arms = ArmJobDispatcher(ArmJobStore(store), task_store, transport, omx_instances, grant_revisions,
                                     deployment_profile=deployment_profile, now=self.now,
                                     grant_ttl_s=grant_ttl_s, monotonic=monotonic)
        self.arms.goal_hook = on_step_action_succeeded  # per-step goal evidence (D-779 §3)
        self.arms._identity = self._identity  # one owner identity cache for both passes
        self._arms_first = False

    def dispatch_next(self) -> dict[str, Any] | None:
        if not self.arms.store.has_active():
            return super().dispatch_next()  # exactly the single-arm tick
        self._arms_first = not self._arms_first
        if self._arms_first:
            self.arms.io_floor = 0
            arm = self.arms.dispatch_next()
            self._io_floor = self.arms._io
            try:
                single = super().dispatch_next()
            finally:
                self._io_floor = 0
            return _pick([arm, single])
        single = super().dispatch_next()
        self.arms.io_floor = self._io
        return _pick([single, self.arms.dispatch_next()])

    def reconcile(self, mission_id: str) -> dict[str, Any]:
        job = self.store.get(mission_id)
        if job is not None and "arms" in job:
            return self.arms.reconcile(mission_id)
        return super().reconcile(mission_id)


__all__ = ["ArmJobDispatcher", "CellJobDispatcher", "PAIR_REASON", "pair_fields"]
