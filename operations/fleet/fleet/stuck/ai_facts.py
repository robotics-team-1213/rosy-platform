"""D-577 4: facts and heartbeats from the AI PC situation service (`ai_observer`).

Facts are values with confidence and evidence ids. Nothing here answers a stuck, grants a block or
moves a robot. A fact is ``shadow`` (D-577 6: audit table and console queue row only) unless its kind is
in ``ACTING_KINDS`` and its robot is configured acting; then the stuck resolver reads it and may only stop
a back-off (R5 WAIT + a human, D-577 7). A fact naming a command word is refused (D-523 2 rule). Without a heartbeat
for 6 s, or with ``owner_mode: owner_busy``, facts are ignored: Fleet runs rules then a human (D-577 5).
The audit write runs in a worker thread so a slow disk never holds the event loop (estop, resolver).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fleet.server.sqlite_policy import configure_connection

COMMAND_WORDS = frozenset({"WAIT", "RESUME", "BACK_AND_RETRY", "YIELD", "ABORT", "MANUAL", "STOP", "GO"})
FACT_KINDS = ("wait_cycle_confirmed", "wait_cycle_stale_input", "waiting_but_moving", "livelock", "stalled",
              "unknown_occupancy_long", "lane_obs_vs_range", "lane_conf_collapse", "shadow_active_drift",
              "pose_vs_paint", "pose_sources_disagree", "obstacle_identity",
              # D-577 개정 2026-10-10 (analyzer stuck_scene): the field stuck causes
              "rear_blocked", "path_blocked_by_robot", "incident_context", "trip_route_check")
#: D-577 7 (2) under the user's go 2026-10-10: these kinds, for the robots in
#: ``fleet.stuck_resolver.ai_facts_acting``, turn a resolver back-off into R5 WAIT + a human. Nothing else.
ACTING_KINDS = frozenset({"rear_blocked", "path_blocked_by_robot"})
MAX_FACTS, MAX_BODY, MAX_POSTS_PER_S = 32, 64 * 1024, 2
TTL_MAX_S = {"analyzer": 5.0, "vlm": 8.0}
ABSENT_AFTER_S = 6.0
FUTURE_SKEW_S = 1.0


def _words(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _words(item)
    elif isinstance(value, list):
        for item in value:
            yield from _words(item)


class AiFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[FACT_KINDS]  # type: ignore[valid-type]
    robot_ids: list[str] = Field(min_length=1, max_length=16)
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, Any]
    source: str = Field(pattern=r"^(analyzer:[a-z0-9_.-]+@[A-Za-z0-9_.-]+|vlm:[A-Za-z0-9_.:@/-]+)$", max_length=128)
    observed_at: float
    ttl_s: float = Field(gt=0.0)

    @field_validator("robot_ids")
    @classmethod
    def _ids(cls, ids: list[str]) -> list[str]:
        if any(not 0 < len(robot_id) <= 96 for robot_id in ids):
            raise ValueError("robot ids must be 1-96 characters")
        return ids

    def check(self, wall: float) -> None:
        """D-577 3·4: no command word as key or value, ttl within the source's bound, no future time."""
        if any(word.strip().upper() in COMMAND_WORDS for word in _words([self.value, self.evidence])):
            raise ValueError("facts carry no command word (D-523 2)")
        if self.ttl_s > TTL_MAX_S[self.source.split(":", 1)[0]]:
            raise ValueError("ttl_s exceeds the source's bound")
        if self.observed_at > wall + FUTURE_SKEW_S:
            raise ValueError("observed_at is in the future")


class AiFactsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[AiFact] = Field(max_length=MAX_FACTS)


class AiHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_version: str = Field(min_length=1, max_length=64)
    model_profiles: list[str] = Field(default_factory=list, max_length=8)
    owner_mode: Literal["available", "shared", "owner_busy"]
    gpu_used_mib: Optional[int] = Field(default=None, ge=0)
    mem_used_mib: Optional[int] = Field(default=None, ge=0)
    input_lag_s: Optional[float] = Field(default=None, ge=0)
    #: The git commit the AI PC service runs from (deploy/ai_pc/README.md), shown on the console.
    build_commit: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{7,40}(-dirty)?$")


class AiProposal(BaseModel):
    """D-577 개정 2026-10-10 (사용자: "AI PC 제안 → Fleet 검증 후 실행"): one CORE decision word for one open
    stuck. Fleet checks the envelope (word for the cause, preconditions, freshness) and forwards it or falls
    back to its rules; CORE re-checks before acting."""
    model_config = ConfigDict(extra="forbid")
    robot_id: str = Field(min_length=1, max_length=96)
    stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    # D-610 4: LINE_OFF/STOP (stalled), IDENTIFY/STOP (pose_lost), REPLAN (deadlock) for `<kind>:...` problem ids.
    decision: Literal["WAIT", "BACK_AND_RETRY", "YIELD", "ABORT", "RESUME", "MANUAL", "LINE_OFF", "STOP", "IDENTIFY",
                      "REPLAN"]
    reason: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_:.-]+$")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(pattern=r"^(analyzer:[a-z0-9_.-]+@[A-Za-z0-9_.-]+|vlm:[A-Za-z0-9_.:@/-]+)$", max_length=128)
    observed_at: float
    ttl_s: float = Field(gt=0.0, le=8.0)
    body: dict[str, Any] = Field(default_factory=dict)    # D-610 7: REPLAN {blocked_edges: [...]}


class AiFactLog:
    """`fleet_ai_facts` beside the other Fleet journal tables (`--tasks-db`); one row per accepted fact."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_ai_facts (
                       fact_row INTEGER PRIMARY KEY AUTOINCREMENT, received_at REAL NOT NULL,
                       principal_id TEXT NOT NULL, kind TEXT NOT NULL, robot_ids TEXT NOT NULL,
                       value TEXT, confidence REAL NOT NULL, evidence TEXT NOT NULL, source TEXT NOT NULL,
                       observed_at REAL NOT NULL, ttl_s REAL NOT NULL, stage TEXT NOT NULL,
                       rule_input INTEGER NOT NULL DEFAULT 0, human_choice TEXT)""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS fleet_ai_facts_observed_at ON fleet_ai_facts(observed_at)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_ai_proposals (
                       proposal_row INTEGER PRIMARY KEY AUTOINCREMENT, judged_at REAL NOT NULL,
                       robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
                       confidence REAL NOT NULL, evidence TEXT NOT NULL, source TEXT NOT NULL,
                       observed_at REAL NOT NULL, verdict TEXT NOT NULL, outcome TEXT)""")

    def append(self, rows: list[dict]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """INSERT INTO fleet_ai_facts (received_at, principal_id, kind, robot_ids, value, confidence,
                   evidence, source, observed_at, ttl_s, stage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(r["received_at"], r["principal_id"], r["kind"], json.dumps(r["robot_ids"]), json.dumps(r["value"]),
                  r["confidence"], json.dumps(r["evidence"]), r["source"], r["observed_at"], r["ttl_s"], r["stage"])
                 for r in rows])

    def append_verdicts(self, rows: list[dict]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """INSERT INTO fleet_ai_proposals (judged_at, robot_id, stuck_id, decision, reason, confidence,
                   evidence, source, observed_at, verdict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(r["judged_at"], r["robot_id"], r["stuck_id"], r["decision"], r["reason"], r["confidence"],
                  json.dumps(r["evidence"]), r["source"], r["observed_at"], r["verdict"]) for r in rows])

    def set_outcome(self, robot_id: str, stuck_id: str, decision: str, outcome: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE fleet_ai_proposals SET outcome = ? WHERE robot_id = ? AND stuck_id = ? AND decision = ?
                   AND verdict = 'forwarded' AND outcome IS NULL""", (outcome, robot_id, stuck_id, decision))

    def _connect(self) -> sqlite3.Connection:
        return configure_connection(sqlite3.connect(self.path, timeout=5.0))


class AiFactsBoard:
    """Heartbeat status and live facts in memory (256 newest); the durable copy is `AiFactLog`."""

    def __init__(self, log: Optional[AiFactLog] = None, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, acting: frozenset = frozenset()) -> None:
        self.log, self.clock, self.wall, self.acting = log, clock, wall, acting
        self._beat: Optional[tuple[float, dict]] = None
        self._facts: deque = deque(maxlen=256)
        self._proposals: dict[str, dict] = {}            # robot id -> newest proposal
        # Judged proposals, newest last; GET /api/fleet/ai shows 64, the console counts the last hour.
        self.verdicts: deque = deque(maxlen=1024)
        #: Supervision row (app.py sets it once the resolver exists): resolver on/off, per-robot credential
        #: presence, AI acting flag and last resolver answer. Never a secret.
        self.chain: Callable[[], dict] = lambda: {"resolver": False, "robots": []}
        self.first = None                                   # D-610 3: `ai_first.AiFirst` (app.py)
        self._problems: dict[str, dict] = {}                # D-610 4: stalled/pose_lost/deadlock proposals by id
        self._posts: deque = deque()

    def heartbeat(self, beat: AiHeartbeat) -> dict:
        self._beat = (self.clock(), beat.model_dump())
        return self.status()

    def status(self) -> dict:
        if self._beat is None:
            return {"state": "absent", "owner_mode": None, "age_s": None, "service_version": None}
        at, beat = self._beat
        age = max(0.0, self.clock() - at)
        return {**beat, "state": "absent" if age > ABSENT_AFTER_S else "present", "age_s": round(age, 2)}

    def admit_post(self) -> bool:
        """D-577 4: at most two fact posts in any one second."""
        now = self.clock()
        while self._posts and now - self._posts[0] >= 1.0:
            self._posts.popleft()
        if len(self._posts) >= MAX_POSTS_PER_S:
            return False
        self._posts.append(now)
        return True

    def accept(self, facts: list[AiFact], principal_id: str) -> tuple[str, list[dict]]:
        status = self.status()
        state = "owner_busy" if status["state"] == "present" and status["owner_mode"] == "owner_busy" \
            else status["state"]
        if state != "present":
            return state, []
        received = self.wall()
        rows = [{**fact.model_dump(), "received_at": received, "principal_id": principal_id,
                 "stage": "acting" if fact.kind in ACTING_KINDS and fact.robot_ids[0] in self.acting else "shadow"}
                for fact in facts]
        self._facts.extend(rows)
        return state, rows

    def live(self, robot_id: Optional[str] = None) -> list[dict]:
        """Facts within their ttl while the service is present; none while it is absent (D-577 5)."""
        if self.status()["state"] != "present":
            return []
        now = self.wall()
        return [{key: row[key] for key in ("kind", "robot_ids", "value", "confidence", "evidence", "source",
                                          "observed_at", "ttl_s", "stage")}
                for row in self._facts
                if row["observed_at"] + row["ttl_s"] >= now and (robot_id is None or robot_id in row["robot_ids"])]

    def propose(self, proposal: AiProposal) -> str:
        status = self.status()
        if status["state"] != "present" or status["owner_mode"] == "owner_busy":
            return "absent" if status["state"] != "present" else "owner_busy"
        if not self._acting(proposal.robot_id):
            return "robot_not_acting"
        if proposal.stuck_id.split(":", 1)[0] in ("stalled", "pose_lost", "deadlock"):
            self._problems[proposal.stuck_id] = proposal.model_dump()
            return "queued"
        self._proposals[proposal.robot_id] = proposal.model_dump()
        return "queued"

    def _acting(self, robot_id: str) -> bool:
        return robot_id in self.acting or self.first is not None and self.first.on(robot_id)

    def problem_proposal(self, problem_id: str) -> Optional[dict]:
        row = self._problems.get(problem_id)
        if row is None or self.status()["state"] != "present" or row["observed_at"] + row["ttl_s"] < self.wall():
            return None
        return row

    def profiles(self) -> list:
        """D-610 5: the heartbeat's loaded VLM profiles while the service is present and the owner allows it."""
        status = self.status()
        return list(status.get("model_profiles") or ()) if (
            status["state"] == "present" and status["owner_mode"] == "available") else []

    def proposal(self, robot_id: str) -> Optional[dict]:
        """The resolver's AI input: this robot's newest proposal while live and the service is present."""
        row = self._proposals.get(robot_id)
        if row is None or self.status()["state"] != "present" or row["observed_at"] + row["ttl_s"] < self.wall():
            return None
        return row

    def waiting(self, robot_id: str) -> bool:
        """Fleet gives the AI PC its time (ResolverConfig.ai_wait_s) only for an acting robot while present."""
        status = self.status()
        return self._acting(robot_id) and status["state"] == "present" and status["owner_mode"] != "owner_busy"

    def acting_facts(self, robot_id: str) -> list[dict]:
        """D-577 7: the resolver's AI input, live ``acting`` facts about this robot (first id) only."""
        return [fact for fact in self.live(robot_id) if fact["stage"] == "acting" and fact["robot_ids"][0] == robot_id]

    def note_outcome(self, robot_id: str, stuck_id: str, decision: str, outcome: str) -> None:
        """CORE's reply to a forwarded proposal, on the in-memory verdict (the table gets it too)."""
        for verdict in reversed(self.verdicts):
            if (verdict["robot_id"], verdict["stuck_id"], verdict["decision"]) == (robot_id, stuck_id, decision)                     and verdict["verdict"] == "forwarded":
                verdict["outcome"] = outcome
                return

    def counts(self, window_s: float = 3600.0) -> dict:
        """Proposals judged in the window: accepted (CORE took it), refused (CORE did not), held (Fleet's
        gates kept it back), pending (forwarded, no reply yet)."""
        counts = {"accepted": 0, "held": 0, "refused": 0, "pending": 0}
        since = self.clock() - window_s
        for verdict in self.verdicts:
            if verdict["judged_at"] >= since:
                counts[_outcome_class(verdict)] += 1
        return counts

    def robot_view(self, robot_id: str, stuck_id: Optional[str] = None) -> dict:
        """What a stuck queue row carries: the AI chip, this robot's live facts and, for this stuck, the
        newest AI proposal with Fleet's verdict and CORE's outcome."""
        status = self.status()
        proposal = next(({key: verdict.get(key) for key in ("decision", "reason", "verdict", "outcome")}
                         | {"class": _outcome_class(verdict)}
                         for verdict in reversed(self.verdicts) if verdict["robot_id"] == robot_id
                         and verdict["stuck_id"] == stuck_id), None)
        return {"ai": {"state": status["state"], "owner_mode": status["owner_mode"]},
                "ai_facts": self.live(robot_id), "ai_proposal": proposal}


def _outcome_class(verdict: dict) -> str:
    if verdict["verdict"] != "forwarded":
        return "held"
    outcome = verdict.get("outcome")
    return "pending" if outcome is None else "accepted" if outcome == "accepted" else "refused"


def install_ai_routes(app, *, read_guard, authorize, db_path: Optional[Path],
                      acting: frozenset = frozenset()) -> AiFactsBoard:
    board = AiFactsBoard(AiFactLog(db_path) if db_path is not None else None, acting=acting)

    def require_ai_observer(principal=Depends(authorize)):
        if principal.role != "ai_observer":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "ai_observer role required"})
        return principal

    @app.post("/api/fleet/ai/heartbeat", tags=["ai"])
    def ai_heartbeat(body: AiHeartbeat, _principal=Depends(require_ai_observer)) -> dict:
        return board.heartbeat(body)

    @app.post("/api/fleet/ai/facts", tags=["ai"])
    async def ai_facts(request: Request, principal=Depends(require_ai_observer)) -> dict:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(status_code=413, detail={"code": "AI_FACTS_TOO_LARGE", "message": "body over 64 KiB"})
        if not board.admit_post():
            raise HTTPException(status_code=429, detail={"code": "AI_FACTS_RATE", "message": "over 2 posts per second"})
        try:
            body = AiFactsRequest.model_validate_json(raw)
            for fact in body.facts:
                fact.check(board.wall())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "AI_FACT_INVALID", "message": str(exc)[:500]}) \
                from None
        state, rows = board.accept(body.facts, principal.principal_id)
        if rows and board.log is not None:
            await asyncio.to_thread(board.log.append, rows)   # never on the event loop (estop, resolver)
        return {"accepted": len(rows), "ignored": len(body.facts) - len(rows), "ai": state}

    @app.post("/api/fleet/ai/proposals", tags=["ai"])
    def ai_proposals(body: AiProposal, _principal=Depends(require_ai_observer)) -> dict:
        if body.observed_at > board.wall() + FUTURE_SKEW_S:
            raise HTTPException(status_code=422, detail={"code": "AI_PROPOSAL_INVALID",
                                                         "message": "observed_at is in the future"})
        # Not on the facts' 2/s budget: one proposal per stuck, kept only newest per acting robot.
        return {"state": board.propose(body)}

    @app.get("/api/fleet/ai", dependencies=read_guard, tags=["ai"])
    def ai_status() -> dict:
        return {"status": board.status(), "facts": board.live(), "proposals": list(board.verdicts)[-64:],
                "chain": {**board.chain(), "proposals_1h": board.counts()}}

    return board
