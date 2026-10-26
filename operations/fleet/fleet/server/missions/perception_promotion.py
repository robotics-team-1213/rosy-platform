"""D-891 perception promotion queue: a D-874 bundle uploaded by a policy admin, decided by another one.

Fleet re-checks the bytes and the shared D-874 shape, then records one human decision. Approval
records the bundle sha, model revision and file hashes only: it moves no registry pointer, writes
no `models/accepted`, and deploys nothing (D-446 stays separate). The D-874 §2 disk anchors (eval
set location, learning-cycle binding) are invisible here; that trust stays with Learning.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from rosy.contracts.learning.promotion_request import encoded, validate

from fleet.server.policy_governance import GovernanceError, PolicyGovernanceStore
from fleet.server.policy_governance_routes import _Confirmed

# A real bundle is a few KiB (one model's files and per-class IoU). 256 KiB still fits ~800 model files of
# 255-char names, is read fully before parsing, and is stored as one SQLite row, so it stays small.
MAX_BUNDLE_BYTES = 256 * 1024
_LIST = "bundle_sha256, model_revision, proposed_by, proposed_ns, state, decided_by, decided_ns"


def _refuse(status: int, code: str, message: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message} if message else {"code": code})


def checked(raw: bytes, claimed: str) -> dict:
    """The bundle only if its bytes hash to `claimed`, are the one canonical encoding, and pass D-874."""
    if hashlib.sha256(raw).hexdigest() != claimed:
        raise _refuse(422, "BUNDLE_HASH_MISMATCH")
    try:
        bundle = json.loads(raw)
        canonical = encoded(bundle) == raw
    except (ValueError, RecursionError):
        raise _refuse(422, "BUNDLE_NOT_JSON") from None
    if not canonical:
        raise _refuse(422, "BUNDLE_NOT_CANONICAL")
    try:
        validate(bundle)
    except ValueError as exc:
        raise _refuse(422, "BUNDLE_INVALID", str(exc)) from None
    return bundle


class PerceptionPromotionStore:
    """Rows live in the governance SQLite file and use its `_run` transaction."""

    def __init__(self, governance: PolicyGovernanceStore) -> None:
        self._g = governance
        with closing(governance._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_perception_proposal (
                bundle_sha256 TEXT PRIMARY KEY, bundle BLOB NOT NULL, model_revision TEXT NOT NULL,
                proposed_by TEXT NOT NULL, proposed_ns INTEGER NOT NULL, state TEXT NOT NULL,
                decided_by TEXT, decided_ns INTEGER)""")

    def propose(self, *, raw: bytes, bundle: dict, principal_id: str) -> dict:
        digest = hashlib.sha256(raw).hexdigest()

        def fn(db, now):
            try:
                db.execute("INSERT INTO fleet_perception_proposal VALUES (?,?,?,?,?,'PENDING',NULL,NULL)",
                           (digest, raw, bundle["model"]["revision"], principal_id, now))
            except sqlite3.IntegrityError:
                raise GovernanceError("PROPOSAL_ALREADY_EXISTS") from None
            return self._row(db, digest)
        return self._g._run(fn)

    def decide(self, *, bundle_sha256: str, state: str, principal_id: str) -> dict:
        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_perception_proposal WHERE bundle_sha256=?",
                             (bundle_sha256,)).fetchone()
            if row is None:
                raise GovernanceError("PROPOSAL_NOT_FOUND", 404)
            if row["state"] != "PENDING":
                raise GovernanceError("PROPOSAL_ALREADY_DECIDED")
            if row["proposed_by"] == principal_id:
                raise GovernanceError("APPROVER_MUST_DIFFER_FROM_PROPOSER", 403)
            db.execute("UPDATE fleet_perception_proposal SET state=?, decided_by=?, decided_ns=? "
                       "WHERE bundle_sha256=? AND state='PENDING'", (state, principal_id, now, bundle_sha256))
            return self._row(db, bundle_sha256)
        return self._g._run(fn)

    @staticmethod
    def _row(db, digest: str) -> dict | None:
        row = db.execute("SELECT * FROM fleet_perception_proposal WHERE bundle_sha256=?", (digest,)).fetchone()
        if row is None:
            return None
        found = dict(row)
        bundle = json.loads(found.pop("bundle"))
        return dict(found, files=bundle["model"]["files"], bundle=bundle)

    def get(self, digest: str) -> dict | None:
        with closing(self._g._connect()) as db:
            return self._row(db, digest)

    def listing(self, limit: int = 50) -> list[dict]:
        with closing(self._g._connect()) as db:
            return [dict(r) for r in db.execute(
                f"SELECT {_LIST} FROM fleet_perception_proposal ORDER BY proposed_ns DESC LIMIT ?", (limit,))]


class PerceptionDecision(_Confirmed):
    decision: Literal["APPROVED", "REJECTED"]


async def _bounded(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and (len(declared) > 12 or not declared.isdigit() or int(declared) > MAX_BUNDLE_BYTES):
        raise _refuse(413, "BUNDLE_TOO_LARGE")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BUNDLE_BYTES:
            raise _refuse(413, "BUNDLE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def install_perception_promotion_routes(app, *, store: PerceptionPromotionStore, require_viewer):
    base = "/api/fleet/perception-promotions"

    def policy_admin(principal):
        # Same role and CSRF path (require_viewer -> cookie Origin check) as policy_governance_routes.
        if not principal.permits_site("fleet.policy", {"policy-admin"}):
            raise _refuse(403, "FORBIDDEN", "policy-admin only")
        return principal

    def call(fn, **kwargs):
        try:
            return fn(**kwargs)
        except GovernanceError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None

    @app.get(base, tags=["fleet-policy"])
    def perception_promotions(principal=Depends(require_viewer)) -> dict:
        return {"proposals": store.listing()}

    @app.get(base + "/{bundle_sha256}", tags=["fleet-policy"])
    def perception_promotion(bundle_sha256: str, principal=Depends(require_viewer)) -> dict:
        row = store.get(bundle_sha256)
        if row is None:
            raise _refuse(404, "PROPOSAL_NOT_FOUND")
        return row

    @app.post(base, tags=["fleet-policy"])
    async def propose_perception(request: Request, sha256: str, principal=Depends(require_viewer)) -> dict:
        """Body: the bundle file's exact bytes; `?sha256=` the hash Learning printed for it."""
        policy_admin(principal)
        raw = await _bounded(request)
        bundle = checked(raw, sha256)
        return await run_in_threadpool(call, store.propose, raw=raw, bundle=bundle,
                                       principal_id=principal.principal_id)

    @app.post(base + "/{bundle_sha256}/decision", tags=["fleet-policy"])
    def decide_perception(bundle_sha256: str, body: PerceptionDecision, principal=Depends(require_viewer)) -> dict:
        policy_admin(principal)
        return call(store.decide, bundle_sha256=bundle_sha256, state=body.decision,
                    principal_id=principal.principal_id)
