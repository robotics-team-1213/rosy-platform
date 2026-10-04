# D-438 Fleet Stuck Resolver — Phase 1 (rules + escalation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lane-follow robot that opens a D-407 stuck gets an answer from a Fleet-side resolver (rules R1–R3) without anyone watching the console; anything the rules cannot settle is escalated to a human.

**Architecture:** CORE gets a `STUCK_DECIDE` grant and a `stuck_resolver` role that carries only that grant (rank = viewer). Fleet gets a pure decision core (`stuck_resolver.py`: chains, budgets, deadline, rules, response handling) and an async loop (`stuck_resolver_loop.py`) that polls `console.snapshot()` every 1 s (woken early by `nav.line_stuck_*` hub events), refreshes the existing `LineStuckBoard`, sends answers with a per-robot resolver token, and records them as `principal_id="fleet-resolver"`. A human clicking a decision in the console claims the stuck; the resolver then stays silent for it.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest; ES modules for the console. No ROS needed for any test here.

**Spec:** `docs/adr/D-438-fleet-stuck-resolver-rules-model-human.md` (Accepted 2026-10-03). Phase 2 (OpenRouter model tier, §3) is a separate plan; in phase 1 every "go to tier 2" is an escalation to the human.

**Ground rules for this repo:**
- Worktree: `F:\Dev\Control\Robot\Rosy\rosy-platform\.worktrees\d438-fleet-resolver`, branch `docs/d438-fleet-stuck-resolver`. Commit after every task. Do not touch `main`'s checkout (another session has uncommitted work there).
- Change-scoped tests while iterating (user rule): run only the files named in each task. Full suites only at the end (Task 8).
- Korean prose in docs, English identifiers/comments/logs. Match surrounding comment density.
- Every `git commit` message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/runtime/api_web/core_api_web/api/grants.py` (modify) | `STUCK_DECIDE` grant; `stuck_resolver` role grants |
| `src/runtime/api_web/core_api_web/api/deps.py:106` (modify) | `ROLE_RANK["stuck_resolver"] = 0` |
| `src/runtime/api_web/core_api_web/api/v1/auth.py:86` (modify) | lifetime for the new role |
| `src/runtime/api_web/core_api_web/api/v1/line_follow.py:130-133` (modify) | decision route requires `STUCK_DECIDE` instead of `operator` |
| `src/runtime/gateway/test/test_stuck_resolver_role.py` (create) | role/grant matrix |
| `src/site/fleet/fleet/server/stuck_resolver.py` (create) | pure decision core, no I/O |
| `src/site/fleet/test/test_stuck_resolver.py` (create) | unit tests of the core |
| `src/site/fleet/fleet/server/line_stuck.py` (modify) | board keeps a resolver note per stuck; `view()` exposes it |
| `src/site/fleet/fleet/server/stuck_resolver_loop.py` (create) | async loop: snapshot → board → core → send → record |
| `src/site/fleet/fleet/server/console_routes.py` (modify) | claim endpoint; human decision claims |
| `src/site/fleet/fleet/server/app.py` (modify) | `stuck_resolver_clients` param, lifespan task, hub callback fan-out |
| `src/site/fleet/test/test_stuck_resolver_loop.py` (create) | loop + routes + fan-out tests |
| `src/site/fleet/fleet/swarm/robots.py` (modify) | optional `resolver_token` per robot |
| `src/site/fleet/fleet/cli.py` (modify) | `--stuck-resolver` flag builds resolver clients |
| `src/site/fleet/test/test_robots_file.py` (modify or create if absent) | `resolver_token` parsing |
| `src/site/fleet/fleet/server/web/line-stuck.js` (modify) | claim on click; show resolver note |
| `docs/reference/ROSY API & Protocol Reference.md` (modify) | D-18 rows |
| `docs/adr/D-438-...md` (modify) | implementation memo |

---

### Task 1: CORE — `STUCK_DECIDE` grant and `stuck_resolver` role

**Files:**
- Modify: `src/runtime/api_web/core_api_web/api/grants.py`
- Modify: `src/runtime/api_web/core_api_web/api/deps.py:106`
- Modify: `src/runtime/api_web/core_api_web/api/v1/auth.py:86`
- Modify: `src/runtime/api_web/core_api_web/api/v1/line_follow.py:130-133`
- Test: `src/runtime/gateway/test/test_stuck_resolver_role.py`

- [ ] **Step 1: Write the failing test**

Create `src/runtime/gateway/test/test_stuck_resolver_role.py`:

```python
"""D-438 §1: the stuck_resolver role answers stucks and reads; nothing else."""

import pytest

from test_line_follow_stuck_api import OPERATOR, URL, VIEWER, _stuck

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
RESOLVER = {"Authorization": "Bearer fleet-stuck-resolver-token-0001"}


def _resolver(client) -> dict:
    made = client.post("/api/v1/system/tokens", headers=ADMIN, json={
        "role": "stuck_resolver", "label": "site:fleet-resolver",
        "token": "fleet-stuck-resolver-token-0001"})
    assert made.status_code == 201, made.text
    return RESOLVER


@pytest.mark.parametrize("who,expected", [("viewer", 403), ("operator", 200), ("resolver", 200)])
def test_stuck_decision_needs_stuck_decide(core_client, who, expected):
    client, _, stuck_id = _stuck(core_client)
    headers = {"viewer": VIEWER, "operator": OPERATOR}.get(who) or _resolver(client)
    response = client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=headers)
    assert response.status_code == expected, response.text


def test_resolver_reads_but_cannot_drive_or_release(core_client):
    client, _, _ = _stuck(core_client)
    headers = _resolver(client)
    assert client.get("/api/v1/line-follow", headers=headers).status_code == 200
    assert client.get("/api/v1/robot/state", headers=headers).status_code == 200
    assert client.put("/api/v1/line-follow/mode", json={"mode": "OFF"},
                      headers=headers).status_code == 403
    assert client.post("/api/v1/safety/release", headers=headers).status_code == 403
    assert client.post("/api/v1/teleop", json={"linear": 0.0, "angular": 0.0},
                       headers=headers).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/runtime/gateway/test/test_stuck_resolver_role.py -q`
Expected: FAIL — token creation returns 400/422 (`stuck_resolver` not in `ROLE_RANK`).

Note: `PUT /api/v1/line-follow/mode` with `OFF` currently uses `operator`; a 403 is expected because the resolver's rank is 0. If any assertion above already fails for a different reason (e.g. `/api/v1/teleop` path differs), check `src/runtime/api_web/core_api_web/api/v1/` for the real teleop path and fix the test, not the code.

- [ ] **Step 3: Implement**

`grants.py` — add the grant and the role (keep the module docstring; add one bullet):

```python
NAVIGATE = "NAVIGATE"
LOCALIZE_ASSIST = "LOCALIZE_ASSIST"
STUCK_DECIDE = "STUCK_DECIDE"

ROLE_GRANTS: dict[str, frozenset[str]] = {
    "viewer": frozenset(),
    # D-438 §1: Fleet's stuck resolver answers D-407 stucks and reads; rank stays viewer.
    "stuck_resolver": frozenset({STUCK_DECIDE}),
    "operator": frozenset({NAVIGATE, LOCALIZE_ASSIST, STUCK_DECIDE}),
    "administrator": frozenset({NAVIGATE, LOCALIZE_ASSIST, STUCK_DECIDE}),
}
```

Docstring bullet to add after `LOCALIZE_ASSIST`:

```
- `STUCK_DECIDE`: answer a D-407 lane stuck. Operators and administrators carry it;
  the `stuck_resolver` role (D-438, Fleet's resolver) carries only this.
```

`deps.py:106`:

```python
ROLE_RANK = {"viewer": 0, "stuck_resolver": 0, "operator": 1, "administrator": 2}
```

`v1/auth.py:86`:

```python
DEFAULT_LIFETIME_HOURS = {"viewer": 168.0, "stuck_resolver": 168.0, "operator": 168.0,
                          "administrator": 24.0}
```

`v1/line_follow.py` — import and use the grant on the decision route only:

```python
from core_api_web.api.grants import STUCK_DECIDE, require_grant
```

```python
@line_follow_router.post("/stuck/decision")
def decide_line_stuck(body: LineStuckDecisionRequest,
                      auth: AuthContext = Depends(require_grant(STUCK_DECIDE)),
                      svc: CoreServicesLike = Depends(get_services)):
```

(Leave the body unchanged: `require_calibration_owner`, `EMERGENCY_ACTIVE` and `stuck_decision(...)` already give the resolver exactly D-438's limits.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/runtime/gateway/test/test_stuck_resolver_role.py src/runtime/gateway/test/test_line_follow_stuck_api.py src/runtime/gateway/test/test_localization_api.py -q`
Expected: all PASS. If a UI-manifest or role-list test fails because it enumerates roles, add `stuck_resolver` to that test's expectation only when the failure is an exact role list; otherwise stop and report.

- [ ] **Step 5: Commit**

```bash
git add src/runtime/api_web/core_api_web/api/grants.py src/runtime/api_web/core_api_web/api/deps.py src/runtime/api_web/core_api_web/api/v1/auth.py src/runtime/api_web/core_api_web/api/v1/line_follow.py src/runtime/gateway/test/test_stuck_resolver_role.py
git commit -m "feat(D-438): CORE stuck_resolver role with STUCK_DECIDE grant only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Fleet — pure resolver core

**Files:**
- Create: `src/site/fleet/fleet/server/stuck_resolver.py`
- Test: `src/site/fleet/test/test_stuck_resolver.py`

The core takes snapshot rows (`console.snapshot()["robots"]`: `{"robot_id", "online", "state": {...}}`) and a monotonic `now`, and returns actions. It never does I/O.

- [ ] **Step 1: Write the failing tests**

Create `src/site/fleet/test/test_stuck_resolver.py`:

```python
"""D-438 resolver core: chains, budgets, deadline, rules R1-R3, CORE response handling."""

from fleet.server.stuck_resolver import Answer, Escalate, ResolverConfig, StuckResolver


def _row(robot_id="rosy_01", stuck=None, *, mode="CAMERA_LINE", pose=(0.0, 0.0, 0.0),
         online=True, estop=False):
    state = {"robot_id": robot_id, "safety": {"estop": estop},
             "pose": None if pose is None else {"x": pose[0], "y": pose[1], "yaw": pose[2]},
             "line_follow": {"mode": mode, "state": "HOLD" if stuck else "TRACKING",
                             "stuck": stuck}}
    return {"robot_id": robot_id, "online": online, "state": state}


def _stuck(stuck_id="stuck-1", cause="obstacle_ahead", *, local=True, attempts=0, max_attempts=2):
    return {"stuck_id": stuck_id, "cause": cause, "phase": "ASKING", "local_enabled": local,
            "attempts": attempts, "max_attempts": max_attempts}


def test_r2_backs_off_from_a_static_obstacle_once_per_stuck():
    r = StuckResolver(ResolverConfig())
    first = r.step(0.0, [_row(stuck=_stuck())])
    assert first == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]
    r.sent(first[0], 0.0)
    assert r.step(1.0, [_row(stuck=_stuck())]) == []          # one answer per stuck


def test_r1_waits_for_a_peer_in_the_front_band():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.03, 3.14))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]


def test_r1_ignores_a_peer_behind_or_beside_and_unknown_poses():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    behind = _row("rosy_02", None, pose=(-0.20, 0.0, 0.0))
    beside = _row("rosy_03", None, pose=(0.10, 0.40, 0.0))
    assert r.step(0.0, [me, behind, beside])[0].rule == "R2"
    r2 = StuckResolver(ResolverConfig())
    assert r2.step(0.0, [_row("rosy_01", _stuck(), pose=None),
                         _row("rosy_02", None, pose=(0.2, 0.0, 0.0))])[0].rule == "R2"


def test_r3_backs_off_on_lane_lost():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(cause="lane_lost"))]) == [
        Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_no_back_off_without_local_recovery_escalates():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(local=False))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]
    assert r.step(1.0, [_row(stuck=_stuck(local=False))]) == []      # escalate once


def test_attempts_exhausted_escalates():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(attempts=2, max_attempts=2))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]


def test_chain_budget_counts_restucks_of_any_close_kind():
    r = StuckResolver(ResolverConfig(rule_budget=2, restuck_s=30.0))
    for i, t in ((1, 0.0), (2, 10.0)):
        a = r.step(t, [_row(stuck=_stuck(f"stuck-{i}"))])[0]
        r.sent(a, t)
        r.step(t + 1.0, [_row(stuck=None)])                          # closed (any reason)
    assert r.step(20.0, [_row(stuck=_stuck("stuck-3"))]) == [
        Escalate("rosy_01", "stuck-3", "rule_budget")]


def test_chain_ends_after_restuck_window_or_mode_change():
    r = StuckResolver(ResolverConfig(rule_budget=1, restuck_s=30.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck("stuck-1"))])[0], 0.0)
    r.step(1.0, [_row(stuck=None)])
    assert r.step(40.0, [_row(stuck=_stuck("stuck-2"))])[0].stuck_id == "stuck-2"  # new chain
    r.sent(Answer("rosy_01", "stuck-2", "BACK_AND_RETRY", "R2"), 40.0)
    r.step(41.0, [_row(stuck=None, mode="OFF")])
    assert isinstance(r.step(42.0, [_row(stuck=_stuck("stuck-3"))])[0], Answer)


def test_restuck_after_resolver_resume_goes_to_human():
    r = StuckResolver(ResolverConfig())
    r.sent(Answer("rosy_01", "stuck-1", "RESUME", "R1"), 0.0)
    r.step(0.0, [_row(stuck=_stuck("stuck-1"))])
    r.step(1.0, [_row(stuck=None)])
    assert r.step(5.0, [_row(stuck=_stuck("stuck-2"))]) == [
        Escalate("rosy_01", "stuck-2", "restuck_after_resume")]


def test_deadline_escalates():
    r = StuckResolver(ResolverConfig(escalate_after_s=60.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck())])[0], 0.0)
    assert r.step(61.0, [_row(stuck=_stuck())]) == [Escalate("rosy_01", "stuck-1", "deadline")]


def test_refused_retires_the_rule_and_tries_the_next():
    r = StuckResolver(ResolverConfig())
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.0, 3.14))
    a = r.step(0.0, [me, peer])[0]
    assert a.rule == "R1"
    r.sent(a, 0.0)
    r.result(a, code="STUCK_DECISION_REFUSED")
    b = r.step(1.0, [me, peer])[0]
    assert (b.decision, b.rule) == ("BACK_AND_RETRY", "R2")


def test_mismatch_forgets_and_other_codes_escalate():
    r = StuckResolver(ResolverConfig())
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    r.result(a, code="STUCK_ID_MISMATCH")
    assert r.step(1.0, [_row(stuck=_stuck())]) == []                 # same id: still answered
    r2 = StuckResolver(ResolverConfig())
    a2 = r2.step(0.0, [_row(stuck=_stuck())])[0]
    r2.sent(a2, 0.0)
    assert r2.result(a2, code="CALIBRATION_ACTIVE") == Escalate("rosy_01", "stuck-1",
                                                               "core:CALIBRATION_ACTIVE")


def test_transport_failure_retries_once_then_escalates():
    r = StuckResolver(ResolverConfig())
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") is None
    again = r.step(1.0, [_row(stuck=_stuck())])
    assert again == [a]
    r.sent(a, 1.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") == Escalate("rosy_01", "stuck-1",
                                                            "core:ROBOT_UNREACHABLE")


def test_human_claim_silences_the_resolver():
    r = StuckResolver(ResolverConfig())
    r.claim("rosy_01", "stuck-1")
    assert r.step(0.0, [_row(stuck=_stuck())]) == []


def test_offline_and_estop_robots_are_left_alone():
    r = StuckResolver(ResolverConfig())
    assert r.step(0.0, [_row(stuck=_stuck(), online=False)]) == []
    assert r.step(0.0, [_row(stuck=_stuck(), estop=True)]) == [
        Escalate("rosy_01", "stuck-1", "estop")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver.py -q`
Expected: FAIL — `ModuleNotFoundError: fleet.server.stuck_resolver`.

- [ ] **Step 3: Implement**

Create `src/site/fleet/fleet/server/stuck_resolver.py`:

```python
"""D-438 Fleet stuck resolver core: rules first, then (phase 2) a model, then a human.

Pure: the caller feeds console snapshot rows and a monotonic clock, sends the returned
Answers and reports CORE's reply with `result`. CORE re-checks every answer (D-407 §2);
nothing here widens a robot's local-recovery settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Union

#: CORE codes that mean "this answer was judged and refused": try the next candidate.
REFUSED = "STUCK_DECISION_REFUSED"
#: The stuck changed under us: drop this answer, re-read state.
MISMATCH = "STUCK_ID_MISMATCH"
#: Transport failures: one resend, then a human.
TRANSPORT = ("ROBOT_UNREACHABLE", "STUCK_DECISION_OUTCOME_UNKNOWN")


@dataclass(frozen=True)
class ResolverConfig:
    poll_s: float = 1.0
    restuck_s: float = 30.0
    rule_budget: int = 2
    escalate_after_s: float = 60.0
    peer_reach_m: float = 0.30
    # Own half width (Pinky 0.057 m) + a peer's rotation radius (0.083 m), rounded up.
    # ponytail: one body size for every robot; read per-robot geometry when kinds differ.
    peer_band_half_width_m: float = 0.15


@dataclass(frozen=True)
class Answer:
    robot_id: str
    stuck_id: str
    decision: str
    rule: str


@dataclass(frozen=True)
class Escalate:
    robot_id: str
    stuck_id: str
    reason: str


Action = Union[Answer, Escalate]


@dataclass
class _Chain:
    started_at: float
    mode: str
    stuck_id: Optional[str] = None
    closed_at: Optional[float] = None
    rule_answers: int = 0
    resumed: bool = False
    retired: set = field(default_factory=set)
    answered: set = field(default_factory=set)       # stuck ids with an answer in flight/done
    retries: dict = field(default_factory=dict)      # stuck id -> transport resends
    escalated: set = field(default_factory=set)      # stuck ids already escalated
    claimed: set = field(default_factory=set)        # stuck ids a human owns


def _stuck_of(row: Mapping) -> Optional[dict]:
    lf = (row.get("state") or {}).get("line_follow") or {}
    stuck = lf.get("stuck")
    return stuck if isinstance(stuck, dict) and stuck.get("stuck_id") else None


def _mode_of(row: Mapping) -> str:
    return str(((row.get("state") or {}).get("line_follow") or {}).get("mode") or "OFF")


def _pose_of(row: Mapping) -> Optional[tuple[float, float, float]]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


class StuckResolver:
    def __init__(self, config: ResolverConfig) -> None:
        self.config = config
        self._chains: dict[str, _Chain] = {}
        self._claims: set[tuple[str, str]] = set()

    # ---- inputs -----------------------------------------------------------------------

    def claim(self, robot_id: str, stuck_id: str) -> None:
        """A human opened this stuck's decision (D-438 §1): the resolver stays silent."""
        self._claims.add((robot_id, stuck_id))

    def sent(self, answer: Answer, now: float) -> None:
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            chain = self._chains[answer.robot_id] = _Chain(started_at=now, mode="")
        chain.answered.add(answer.stuck_id)
        if answer.rule.startswith("R"):
            chain.rule_answers += 1
        if answer.decision == "RESUME":
            chain.resumed = True

    def result(self, answer: Answer, *, code: Optional[str]) -> Optional[Escalate]:
        """CORE's reply: None code = accepted. Returns an escalation when one is due."""
        chain = self._chains.get(answer.robot_id)
        if chain is None or code is None or code == MISMATCH:
            return None
        if code == REFUSED:
            chain.retired.add(answer.rule)
            chain.answered.discard(answer.stuck_id)
            return None
        if code in TRANSPORT and chain.retries.get(answer.stuck_id, 0) == 0:
            chain.retries[answer.stuck_id] = 1
            chain.answered.discard(answer.stuck_id)
            return None
        chain.escalated.add(answer.stuck_id)
        return Escalate(answer.robot_id, answer.stuck_id, f"core:{code}")

    # ---- decision ---------------------------------------------------------------------

    def step(self, now: float, rows: Iterable[Mapping]) -> list[Action]:
        rows = [r for r in rows if isinstance(r, Mapping) and r.get("robot_id")]
        actions: list[Action] = []
        for row in rows:
            action = self._one(now, row, rows)
            if action is not None:
                actions.append(action)
        return actions

    def _one(self, now: float, row: Mapping, rows: list) -> Optional[Action]:
        rid = str(row["robot_id"])
        if not row.get("online", True):
            return None
        stuck, mode = _stuck_of(row), _mode_of(row)
        chain = self._chains.get(rid)
        if chain is not None and (mode != chain.mode and chain.mode
                                  or (chain.closed_at is not None
                                      and now - chain.closed_at > self.config.restuck_s)):
            chain = self._chains.pop(rid)          # mode changed or the window passed
            chain = None
        if stuck is None:
            if chain is not None and chain.closed_at is None:
                chain.closed_at, chain.stuck_id = now, None
            return None
        sid = str(stuck["stuck_id"])
        if chain is None:
            chain = self._chains[rid] = _Chain(started_at=now, mode=mode)
        elif not chain.mode:
            chain.mode = mode
        if chain.stuck_id != sid:
            new = chain.stuck_id is None and chain.closed_at is not None
            chain.stuck_id, chain.closed_at = sid, None
            if new and chain.resumed:
                return self._escalate(chain, rid, sid, "restuck_after_resume")
        if (rid, sid) in self._claims or sid in chain.escalated:
            return None
        if ((row.get("state") or {}).get("safety") or {}).get("estop"):
            return self._escalate(chain, rid, sid, "estop")
        if now - chain.started_at > self.config.escalate_after_s:
            return self._escalate(chain, rid, sid, "deadline")
        if sid in chain.answered:
            return None
        rule = self._rule(row, stuck, rows, chain)
        if rule is None:
            return self._escalate(chain, rid, sid, "no_rule")
        if chain.rule_answers >= self.config.rule_budget:
            return self._escalate(chain, rid, sid, "rule_budget")
        return Answer(rid, sid, rule[1], rule[0])

    def _escalate(self, chain: _Chain, rid: str, sid: str, reason: str) -> Escalate:
        chain.escalated.add(sid)
        return Escalate(rid, sid, reason)

    # ---- rules (D-438 §2) -------------------------------------------------------------

    def _rule(self, row, stuck, rows, chain) -> Optional[tuple[str, str]]:
        cause = stuck.get("cause")
        can_back = (bool(stuck.get("local_enabled"))
                    and int(stuck.get("attempts") or 0) < int(stuck.get("max_attempts") or 0))
        peer = cause == "obstacle_ahead" and self._peer_ahead(row, rows)
        candidates = []
        if peer:
            candidates.append(("R1", "WAIT"))
        if cause == "obstacle_ahead" and not peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))
        if cause == "lane_lost" and can_back:
            candidates.append(("R3", "BACK_AND_RETRY"))
        if peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))      # after a refused WAIT
        for rule in candidates:
            if rule[0] not in chain.retired:
                return rule
        return None

    def _peer_ahead(self, row, rows) -> bool:
        me = _pose_of(row)
        if me is None:
            return False
        x0, y0, yaw = me
        c, s = math.cos(yaw), math.sin(yaw)
        for other in rows:
            if other is row or not other.get("online", True):
                continue
            pose = _pose_of(other)
            if pose is None:
                continue
            dx, dy = pose[0] - x0, pose[1] - y0
            ahead, side = c * dx + s * dy, -s * dx + c * dy
            if 0.0 < ahead <= self.config.peer_reach_m and abs(side) <= self.config.peer_band_half_width_m:
                return True
        return False
```

Notes for the implementer:
- `peer_reach_m` is measured base-to-base; the test peer at 0.20 m is inside 0.30 m. Keep the test numbers.
- If `test_r2_backs_off_from_a_static_obstacle_once_per_stuck` fails because `step` after `sent` returns an answer again, `sent` must record into the same chain `step` created — it does, via `self._chains[answer.robot_id]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver.py -q`
Expected: all PASS. Fix the implementation (not the tests) until they do; if a test is genuinely wrong against D-438, stop and report which clause.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/server/stuck_resolver.py src/site/fleet/test/test_stuck_resolver.py
git commit -m "feat(D-438): Fleet stuck resolver core - chains, budgets, deadline, rules R1-R3

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Board keeps a resolver note

**Files:**
- Modify: `src/site/fleet/fleet/server/line_stuck.py` (class `LineStuckBoard`, `view()` at ~l.99)
- Test: `src/site/fleet/test/test_stuck_resolver_loop.py` (create; first test only)

- [ ] **Step 1: Write the failing test**

Create `src/site/fleet/test/test_stuck_resolver_loop.py`:

```python
"""D-438 resolver loop, board notes, claim route and hub wake-up."""

from __future__ import annotations

import asyncio

from fakes import FakeClock, FakeRobot
from fleet.server.line_stuck import LineStuckBoard

STUCK = {"stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING",
         "held_s": 3.5, "attempts": 0, "max_attempts": 2, "local_enabled": True,
         "ask_remaining_s": 11.5, "last_answer": None,
         "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]}


def _state(stuck=STUCK) -> dict:
    return {"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
            "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}}


def test_board_view_carries_the_resolver_note():
    board = LineStuckBoard(clock=FakeClock())
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state()}])
    assert board.view("rosy_01")["resolver"] is None
    board.note_resolver("rosy_01", "stuck-abc", tier="rule", rule="R2",
                        decision="BACK_AND_RETRY", escalated=None)
    note = board.view("rosy_01")["resolver"]
    assert note["tier"] == "rule" and note["rule"] == "R2" and note["escalated"] is None
    board.note_resolver("rosy_01", "stuck-abc", tier="human", rule=None, decision=None,
                        escalated="no_rule")
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_rule"
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state(stuck=None)}])
    assert board.view("rosy_01") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py -q`
Expected: FAIL — `KeyError: 'resolver'` or `AttributeError: note_resolver`.

- [ ] **Step 3: Implement**

In `LineStuckBoard.__init__` add `self._resolver: dict[tuple[str, str], dict] = {}`.

Add the method:

```python
    def note_resolver(self, robot_id: str, stuck_id: str, *, tier: str, rule: Optional[str],
                      decision: Optional[str], escalated: Optional[str]) -> None:
        """D-438: what the resolver did for this stuck (shown on the console row)."""
        self._resolver[(robot_id, stuck_id)] = {
            "tier": tier, "rule": rule, "decision": decision, "escalated": escalated,
            "at": self._clock()}
```

In `view()`, before returning, add (the entry's stuck id is `entry["stuck_id"]`):

```python
        out["resolver"] = self._resolver.get((robot_id, entry["stuck_id"]))
```

(Use the local variable names `view()` already has; the snippet assumes the copied entry is `out` and the stored one is `entry`.)

In `observe()`, where an entry is removed because there is no `stuck_id` or the robot left the roster, also drop notes for that robot:

```python
        for key in [k for k in self._resolver if k[0] == robot_id]:
            del self._resolver[key]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py src/site/fleet/test/test_line_stuck_api.py -q`
Expected: PASS. If an existing test compares the whole `view()` dict, add `"resolver": None` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/server/line_stuck.py src/site/fleet/test/test_stuck_resolver_loop.py src/site/fleet/test/test_line_stuck_api.py
git commit -m "feat(D-438): line-stuck board carries the resolver note per stuck

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Resolver loop

**Files:**
- Create: `src/site/fleet/fleet/server/stuck_resolver_loop.py`
- Test: `src/site/fleet/test/test_stuck_resolver_loop.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
from fleet.server.console import FleetConsole
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import PRINCIPAL_ID, StuckResolverLoop
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError


def _setup(state=None, *, resolver_robot=None):
    robot = FakeRobot("rosy_01", state=state or _state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    resolver_robot = resolver_robot or FakeRobot("rosy_01", state=state or _state())
    board = LineStuckBoard(clock=FakeClock())
    clock = FakeClock()
    loop = StuckResolverLoop(console, board, StuckResolver(ResolverConfig()),
                             clients=lambda: {"rosy_01": resolver_robot}, clock=clock)
    return loop, board, resolver_robot


def test_one_pass_answers_and_records_as_the_resolver():
    loop, board, resolver_robot = _setup()
    asyncio.run(loop.run_once())
    assert ("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY") in resolver_robot.calls
    answer = board.answers()[-1]
    assert answer["principal_id"] == PRINCIPAL_ID and answer["accepted"] is True
    assert board.view("rosy_01")["resolver"]["rule"] == "R2"


def test_refusal_is_recorded_and_escalates_when_nothing_is_left():
    resolver_robot = FakeRobot("rosy_01", state=_state())
    resolver_robot.stuck_decision_error = RobotApiError(
        "rosy_01", 409, "STUCK_DECISION_REFUSED", "BACK_AND_RETRY refused: attempts_exhausted")
    loop, board, _ = _setup(resolver_robot=resolver_robot)
    asyncio.run(loop.run_once())
    asyncio.run(loop.run_once())
    assert board.answers()[-1]["code"] == "STUCK_DECISION_REFUSED"
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_rule"


def test_robot_without_resolver_token_escalates():
    robot = FakeRobot("rosy_01", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    board = LineStuckBoard(clock=FakeClock())
    loop = StuckResolverLoop(console, board, StuckResolver(ResolverConfig()),
                             clients=lambda: {}, clock=FakeClock())
    asyncio.run(loop.run_once())
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_resolver_token"
    assert robot.calls.count(("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY")) == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: fleet.server.stuck_resolver_loop`.

- [ ] **Step 3: Implement**

Create `src/site/fleet/fleet/server/stuck_resolver_loop.py`:

```python
"""D-438 §1: the resolver runs inside Fleet without a browser.

Every `poll_s` (or sooner, when a `nav.line_stuck_*` hub event sets `wake`) it reads the
console snapshot, refreshes the line-stuck board, and sends the core's answers with each
robot's stuck_resolver token. Answers are recorded as principal `fleet-resolver`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Mapping, Optional

import httpx

from fleet.server.console_routes import _transport_failure
from fleet.server.line_stuck import LineStuckBoard
from fleet.server.stuck_resolver import Answer, Escalate, StuckResolver
from fleet.swarm.transport import RobotApiError

PRINCIPAL_ID = "fleet-resolver"
log = logging.getLogger(__name__)


class StuckResolverLoop:
    def __init__(self, console, board: LineStuckBoard, resolver: StuckResolver, *,
                 clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._console, self._board, self._resolver = console, board, resolver
        self._clients, self._clock = clients, clock
        self.wake = asyncio.Event()

    def claim(self, robot_id: str, stuck_id: str) -> None:
        self._resolver.claim(robot_id, stuck_id)
        self._board.note_resolver(robot_id, stuck_id, tier="human", rule=None,
                                  decision=None, escalated="human_claimed")

    async def run_once(self) -> None:
        snapshot = await self._console.snapshot()
        robots = snapshot["robots"]
        self._board.observe(robots, self._console.hub.registry.events_since)
        now = self._clock()
        for action in self._resolver.step(now, robots):
            if isinstance(action, Escalate):
                self._escalated(action)
            else:
                await self._answer(action, now)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad pass must not stop the resolver
                log.exception("stuck resolver pass failed")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=self._resolver.config.poll_s)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    def _escalated(self, action: Escalate) -> None:
        log.warning("stuck %s on %s escalated to a human: %s",
                    action.stuck_id, action.robot_id, action.reason)
        self._board.note_resolver(action.robot_id, action.stuck_id, tier="human", rule=None,
                                  decision=None, escalated=action.reason)

    async def _answer(self, answer: Answer, now: float) -> None:
        client = self._clients().get(answer.robot_id)
        if client is None:
            self._resolver.claim(answer.robot_id, answer.stuck_id)   # never retry without a token
            self._escalated(Escalate(answer.robot_id, answer.stuck_id, "no_resolver_token"))
            return
        self._resolver.sent(answer, now)
        record = dict(robot_id=answer.robot_id, stuck_id=answer.stuck_id,
                      decision=answer.decision, principal_id=PRINCIPAL_ID)
        code: Optional[str] = None
        try:
            result = await client.line_stuck_decision(answer.stuck_id, answer.decision)
        except RobotApiError as exc:
            code = exc.code
            self._board.record(**record, accepted=False, code=exc.code, message=exc.message)
        except (httpx.HTTPError, OSError) as exc:
            code, message = _transport_failure(exc)
            self._board.record(**record, accepted=None, code=code,
                               message=f"{message} ({type(exc).__name__})")
        else:
            self._board.record(**record, accepted=True, outcome=result.get("outcome"))
        self._board.note_resolver(answer.robot_id, answer.stuck_id, tier="rule",
                                  rule=answer.rule, decision=answer.decision, escalated=None)
        escalation = self._resolver.result(answer, code=code)
        if escalation is not None:
            self._escalated(escalation)
            return
        if code == "STUCK_DECISION_REFUSED":
            # Try the next candidate now; if none is left the core escalates "no_rule".
            for action in self._resolver.step(self._clock(), [
                    {"robot_id": answer.robot_id, "online": True,
                     "state": (self._board_state(answer.robot_id))}]):
                if isinstance(action, Escalate):
                    self._escalated(action)

    def _board_state(self, robot_id: str) -> dict:
        view = self._board.view(robot_id) or {}
        stuck = {k: view.get(k) for k in ("stuck_id", "cause", "attempts", "max_attempts",
                                          "local_enabled")}
        return {"line_follow": {"mode": "", "stuck": stuck if stuck.get("stuck_id") else None}}
```

Implementer notes:
- `test_refusal_is_recorded_and_escalates_when_nothing_is_left` runs two passes: pass 1 sends R2 and gets refused (R2 retired); pass 2 has no candidate left → `Escalate(..., "no_rule")`. If the in-pass retry in `_answer` (the `STUCK_DECISION_REFUSED` branch) makes the test flaky or duplicates escalations, delete that branch and the `_board_state` helper: the next 1 s pass does the same. Prefer deleting (less code).
- `FakeRobot.line_stuck_decision` raises `stuck_decision_error` when set; check `fakes.py` and match.

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py src/site/fleet/test/test_stuck_resolver.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/server/stuck_resolver_loop.py src/site/fleet/test/test_stuck_resolver_loop.py
git commit -m "feat(D-438): resolver loop - poll, board refresh, answer as fleet-resolver, escalate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: App wiring — lifespan task, hub fan-out, claim route

**Files:**
- Modify: `src/site/fleet/fleet/server/app.py` (`create_app` signature l.89-117, lifespan l.286-333, hub callback l.360-362, `install_console_routes` call l.450-454)
- Modify: `src/site/fleet/fleet/server/console_routes.py` (`install_console_routes` l.66; decision route l.129-157)
- Test: `src/site/fleet/test/test_stuck_resolver_loop.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
from hashlib import sha256

from fastapi.testclient import TestClient

from fleet.server.app import create_app, _fan_out_events
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

OPERATOR = "operator-token"


def _app(tmp_path, resolver_robot):
    robot = FakeRobot("rosy_01", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    app = create_app(
        console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
        stuck_resolver_clients={"rosy_01": resolver_robot},
        site_users={sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "op-7",
                                                            "role": "operator"}})
    return app


def test_claim_route_silences_the_resolver(tmp_path):
    resolver_robot = FakeRobot("rosy_01", state=_state())
    app = _app(tmp_path, resolver_robot)
    with TestClient(app) as client:
        app.state.stuck_resolver.wake.set()
        response = client.post("/api/fleet/robots/rosy_01/line-stuck/claim",
                               json={"stuck_id": "stuck-abc"},
                               headers={"Authorization": f"Bearer {OPERATOR}"})
        assert response.status_code == 200
        asyncio.run(app.state.stuck_resolver.run_once())
    assert not [c for c in resolver_robot.calls if c[0] == "line_stuck_decision"]


def test_human_decision_claims_the_stuck(tmp_path):
    resolver_robot = FakeRobot("rosy_01", state=_state())
    app = _app(tmp_path, resolver_robot)
    app.state.stuck_resolver_disabled_for_test = True
    with TestClient(app) as client:
        client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                    json={"stuck_id": "stuck-abc", "decision": "WAIT"},
                    headers={"Authorization": f"Bearer {OPERATOR}"})
    assert ("rosy_01", "stuck-abc") in app.state.stuck_resolver._resolver._claims


def test_fan_out_feeds_the_task_projection_and_wakes_on_stuck_events():
    seen, wake = [], asyncio.Event()
    fan = _fan_out_events(lambda event: seen.append(event) or {"ok": True}, wake)
    assert fan({"type": "nav.goal_reached"}) == {"ok": True} and not wake.is_set()
    fan({"type": "nav.line_stuck_opened"})
    assert wake.is_set() and len(seen) == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py -q`
Expected: FAIL — `ImportError: _fan_out_events` / unexpected keyword `stuck_resolver_clients`.

- [ ] **Step 3: Implement**

`app.py`:

1. Imports:

```python
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import StuckResolverLoop
```

2. Module-level helper:

```python
def _fan_out_events(project, wake: "asyncio.Event"):
    """D-438 §1: the hub has one event slot; the task projection keeps its return value,
    and lane-stuck events wake the resolver (cheap, never raises into the hub)."""
    def callback(event):
        result = project(event) if project is not None else None
        if str(event.get("type", "")).startswith("nav.line_stuck_"):
            wake.set()
        return result
    return callback
```

3. `create_app(...)`: add keyword parameter `stuck_resolver_clients: Optional[Mapping[str, object]] = None` (next to `site_lanes`).

4. After `install_console_routes(...)` (l.450-454) — the board exists as `app.state.line_stuck`:

```python
    resolver_loop = None
    if stuck_resolver_clients is not None:
        resolver_loop = app.state.stuck_resolver = StuckResolverLoop(
            console, app.state.line_stuck, StuckResolver(ResolverConfig()),
            clients=lambda: stuck_resolver_clients)
```

5. Hub callback (l.360-362) becomes:

```python
    if hub is not None and (task_service is not None or stuck_resolver_clients is not None):
        project = task_service.project_core_event if task_service is not None else None
        wake = app.state.stuck_resolver.wake if stuck_resolver_clients is not None else None
        hub.set_event_callback(_fan_out_events(project, wake) if wake is not None else project)
```

Move this block below step 4 if it currently runs before `install_console_routes`; the callback needs `app.state.stuck_resolver`. If moving it is awkward, create `wake = asyncio.Event()` here, pass it into `StuckResolverLoop` (add an optional `wake` kwarg to its constructor, default `asyncio.Event()`), and keep the original position.

6. Lifespan (l.286-333): start and cancel the task like the others:

```python
        resolver_task = (asyncio.create_task(app.state.stuck_resolver.run())
                         if getattr(app.state, "stuck_resolver", None) is not None
                         and not getattr(app.state, "stuck_resolver_disabled_for_test", False)
                         else None)
```

and add `resolver_task` to the tuple at l.322-324.

`console_routes.py`:

1. `install_console_routes` keeps its signature. Inside, add the claim route after the decision route:

```python
    class LineStuckClaimRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/claim", dependencies=operator_guard,
              tags=["line-stuck"])
    async def line_stuck_claim(robot_id: str, body: LineStuckClaimRequest,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        """D-438 §1: a human opened this stuck; the resolver stops answering it."""
        loop = getattr(app.state, "stuck_resolver", None)
        if loop is not None:
            loop.claim(robot_id, body.stuck_id)
        return {"robot_id": robot_id, "stuck_id": body.stuck_id,
                "claimed_by": principal.principal_id}
```

(Define `LineStuckClaimRequest` at module level next to `LineStuckDecisionRequest` instead of inside the function — match the file.)

2. In `line_stuck_decision` (l.131), first line of the body:

```python
        loop = getattr(app.state, "stuck_resolver", None)
        if loop is not None:
            loop.claim(robot_id, body.stuck_id)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/site/fleet/test/test_stuck_resolver_loop.py src/site/fleet/test/test_line_stuck_api.py -q`
Expected: PASS. `test_claim_route_silences_the_resolver` drives `run_once()` itself; if the lifespan task races it, set `app.state.stuck_resolver_disabled_for_test = True` before entering `TestClient` in that test too.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/server/app.py src/site/fleet/fleet/server/console_routes.py src/site/fleet/test/test_stuck_resolver_loop.py
git commit -m "feat(D-438): run the resolver in Fleet, wake on stuck events, human claim route

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Configuration — per-robot resolver token and CLI flag

**Files:**
- Modify: `src/site/fleet/fleet/swarm/robots.py` (`RobotEndpoint`, `_endpoint`, `load_robots`, `write_robots`)
- Modify: `src/site/fleet/fleet/cli.py` (console command arguments; `create_app(...)` call ~l.495)
- Test: the existing robots-file test (find it: `grep -rl "load_robots" src/site/fleet/test`)

- [ ] **Step 1: Write the failing test** (append to the robots-file test file found above)

```python
def test_resolver_token_is_optional_and_must_differ(tmp_path):
    from fleet.swarm.robots import RobotsFileError, load_robots
    path = tmp_path / "robots.yaml"
    path.write_text('robots:\n  - robot_id: rosy_01\n    base_url: "http://10.0.0.5:8080"\n'
                    '    token: "rest-token"\n    resolver_token: "resolver-token"\n',
                    encoding="utf-8")
    assert load_robots(path)[0].resolver_token == "resolver-token"
    path.write_text('robots:\n  - robot_id: rosy_01\n    base_url: "http://10.0.0.5:8080"\n'
                    '    token: "rest-token"\n    resolver_token: "rest-token"\n',
                    encoding="utf-8")
    import pytest
    with pytest.raises(RobotsFileError):
        load_robots(path)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest <that test file> -q -k resolver_token`
Expected: FAIL — `AttributeError: resolver_token`.

- [ ] **Step 3: Implement**

`RobotEndpoint`: add `resolver_token: str | None = None  # D-438: CORE stuck_resolver token`.

`_endpoint(...)`: add parameter `resolver_token=None`; validate like `fleet_pairing_token` (non-empty quoted string, differs from `token`), and pass it to `RobotEndpoint(...)`.

`load_robots`: pass `row.get("resolver_token")`. `write_robots`: write `resolver_token` when not None (mirror how `fleet_pairing_token` is written).

`cli.py`: add to the console command parser (next to `--users-file`):

```python
    parser.add_argument("--stuck-resolver", action="store_true",
                        help="D-438: answer lane stucks with rules for robots that have a "
                             "resolver_token in robots.yaml; others go to the console")
```

and before `create_app(...)`:

```python
    stuck_resolver_clients = None
    if getattr(args, "stuck_resolver", False):
        stuck_resolver_clients = {
            ep.robot_id: HttpRobotClient(dataclasses.replace(ep, token=ep.resolver_token))
            for ep in endpoints if ep.resolver_token}
```

then pass `stuck_resolver_clients=stuck_resolver_clients` to `create_app`. Add `import dataclasses` if missing.

- [ ] **Step 4: Run tests**

Run: `python -m pytest <that test file> src/site/fleet/test/test_stuck_resolver_loop.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/swarm/robots.py src/site/fleet/fleet/cli.py <that test file>
git commit -m "feat(D-438): robots.yaml resolver_token and fleet --stuck-resolver

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Console — claim on click, show the resolver note

**Files:**
- Modify: `src/site/fleet/fleet/server/web/line-stuck.js`
- Test: the JS unit test for line-stuck if one exists (`grep -rl "line-stuck" src/site/fleet/test test`); otherwise `test/test_fleet_console_browser.py` covers the panel — run it only if Playwright is installed.

- [ ] **Step 1: Write the failing test**

If a JS unit test exists for `line-stuck.js` (e.g. a node test file), add:

```js
import { resolverText } from "../fleet/server/web/line-stuck.js";
assert.equal(resolverText(null), "");
assert.equal(resolverText({ tier: "rule", rule: "R2", decision: "BACK_AND_RETRY", escalated: null }),
             "자동 판단 R2: 후진 후 재시도");
assert.equal(resolverText({ tier: "human", escalated: "no_rule" }),
             "자동 판단 불가 — 사람 확인 필요 (맞는 규칙 없음)");
```

If none exists, add a Python test that greps the module (the repo's existing pattern for dashboard JS, see `test_dashboard.py:160`):

```python
def test_line_stuck_js_claims_and_shows_the_resolver_note():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "fleet/server/web/line-stuck.js").read_text(
        encoding="utf-8")
    assert "/line-stuck/claim" in js and "export function resolverText" in js
```

(put it in `src/site/fleet/test/test_stuck_resolver_loop.py`).

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL (string not found).

- [ ] **Step 3: Implement**

Add to `line-stuck.js` (near `REFUSAL_REASON`):

```js
const ESCALATION_REASON = Object.freeze({
  no_rule: "맞는 규칙 없음",
  rule_budget: "자동 판단 횟수 소진",
  deadline: "60초 안에 풀리지 않음",
  restuck_after_resume: "자동 재개 뒤 다시 막힘",
  estop: "비상정지",
  no_resolver_token: "자동 판단 토큰 없음",
  human_claimed: "운영자가 맡음",
});

/** D-438: one line about what the Fleet resolver did for this stuck. */
export function resolverText(note) {
  if (!note) return "";
  if (note.escalated) {
    if (note.escalated === "human_claimed") return "운영자가 맡음";
    const why = ESCALATION_REASON[note.escalated] || note.escalated;
    return `자동 판단 불가 — 사람 확인 필요 (${why})`;
  }
  return `자동 판단 ${note.rule}: ${DECISION_LABEL[note.decision] || note.decision}`;
}
```

Check that `DECISION_LABEL.BACK_AND_RETRY` is `"후진 후 재시도"`; if the existing label differs, change the JS test expectation to the existing label (do not rename labels).

In the panel render code (where `stuckFacts(stuck)` is shown), add a line with `resolverText(stuck.resolver)` when non-empty.

In the decision button click handler, before the confirm dialog or the POST, send the claim (fire-and-forget; a failure must not block the human):

```js
fetch(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-stuck/claim`, {
  method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
  body: JSON.stringify({ stuck_id: stuck.stuck_id }),
}).catch(() => {});
```

Use the file's existing fetch/auth helper instead of `authHeaders()` if it has one (look at how the decision POST is sent and copy that call).

- [ ] **Step 4: Run tests**

Run the test from Step 1. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site/fleet/fleet/server/web/line-stuck.js src/site/fleet/test/test_stuck_resolver_loop.py
git commit -m "feat(D-438): console claims a stuck on click and shows the resolver note

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs, harness, full Fleet/CORE suites, review

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md` (find the D-407 rows: `grep -n "line-stuck" "docs/reference/ROSY API & Protocol Reference.md"`)
- Modify: `docs/adr/D-438-fleet-stuck-resolver-rules-model-human.md` (append implementation memo)
- Modify: the Fleet module's `logs.md`/`progress.md` and CORE api_web module's `logs.md` (find with `python tools/harness/rosy_harness.py lint` output or `grep -rl "module: fleet" --include=progress.md src`)

- [ ] **Step 1: API Reference (D-18)** — add rows next to the D-407 rows, bump the API Ref minor version the same way the D-407 change did (look for the latest `v1.NN` in the file header and increment):
  - CORE: role `stuck_resolver` (rank viewer; grant `STUCK_DECIDE`); `POST /api/v1/line-follow/stuck/decision` now requires `STUCK_DECIDE` (operator/administrator/stuck_resolver).
  - Fleet: `POST /api/fleet/robots/{robot_id}/line-stuck/claim` `{stuck_id}` (operator) → `{robot_id, stuck_id, claimed_by}`; robot row `line_stuck.resolver` = `{tier, rule, decision, escalated, at}` or null; answer rows with `principal_id: "fleet-resolver"`; robots.yaml `resolver_token`; CLI `--stuck-resolver`.

- [ ] **Step 2: ADR memo** — append to D-438:

```markdown
## 구현 메모 (2026-10-03, 1단계: 규칙·사람, docs/d438-fleet-stuck-resolver)

- CORE: `stuck_resolver` 역할(순위 viewer)과 `STUCK_DECIDE` 권한. 막힘 답 경로는 역할 대신 이 권한을 본다(operator·administrator 도 가진다).
- Fleet: `fleet/server/stuck_resolver.py`(순수 판단), `stuck_resolver_loop.py`(1 s 폴링 + `nav.line_stuck_*` 사건으로 깨움, 보드 갱신, `fleet-resolver` 로 기록). 콘솔 버튼을 누르면 `.../line-stuck/claim` 으로 사람이 맡는다.
- 설정: robots.yaml `resolver_token`(로봇마다 CORE `stuck_resolver` 토큰), `fleet console --stuck-resolver`. 토큰이 없는 로봇의 막힘은 바로 사람에게 간다.
- 2단계(비전 모델)는 아직 없다. 규칙이 못 풀면 `no_rule` 로 사람에게 올린다.
- 해석: R1 의 "앞 경로 띠"는 기지 대 기지 0.30 m, 옆 0.15 m(자기 반폭 + 상대 회전반경)로 잰다. 로봇 종류별 몸 크기는 아직 읽지 않는다.
```

- [ ] **Step 3: Harness records** — append one entry to each touched module's `logs.md` (date, change, evidence = test commands + pass counts, gate change none) following the existing entries' format exactly; then:

Run: `python tools/harness/rosy_harness.py generate && python tools/harness/rosy_harness.py lint`
Expected: `0 error(s)`.

- [ ] **Step 4: Full suites for the touched areas**

Run (background, they take minutes):
```bash
python -m pytest src/site/fleet/test -q
python -m pytest src/runtime/gateway/test -q
python -m pytest test/test_harness_contracts.py -q
```
Expected: all PASS (record counts). Any failure: fix or report with output; do not skip tests.

- [ ] **Step 5: Commit**

```bash
git add docs src/site/fleet src/runtime STATUS.md
git commit -m "docs(D-438): API reference, implementation memo, harness records for phase 1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Independent review** — dispatch a reviewer (not the implementer) over `git diff main...HEAD` against D-438 §1, §2, §4–§8. Fix findings, re-run the Task 8 Step 4 suites.

---

## After phase 1 (not in this plan)

- Gazebo validation (D-438 검증): two robots face to face (R1 → `cleared`), wall stuck (R2 with local recovery on/off), lane lost (R3), restuck after resume → human.
- Real robots: user approval, one robot at a time, CORE `stuck_resolver` token minted per robot (`POST /api/v1/system/tokens`, administrator), robots.yaml `resolver_token`.
- Phase 2 plan: OpenRouter model tier (§3) between rules and human.
- Follow-up ADR: Fleet advisories.
