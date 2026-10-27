"""Record a Fleet perception approval in the model store (D-898): verify everything, then accept.

approval_import.py --decision <decision.signed> --public-key <pinned pem> --key-id <pinned id>
    --state <learning state root> --ledger <learning cycle state.json> --store <model store>
    --work-root <model-code root>

The signed file is Fleet's GET /api/fleet/perception-promotions/<sha>/decision.signed, carried by a
person. Checks, in order, before any write: the pinned key id and Ed25519 signature, state APPROVED;
the local <state>/promotion-requests/<sha>.json bytes, revision and files; the learning_cycle row's
result folder (promotion_request.ready_rows, the D-874 lookup) holds those files; decided_by differs
from proposed_by. Then, holding the model-code work.lock that model-watch's executor holds, the result
folder goes inbox -> models/accepted/<revision> (store.accept) and the decision and its signed file go
to models/approvals/<sha>/. accepted/ still means only "intake passed"; approval is approvals/.
Nothing here moves the active pointer, shadow or a robot. Run it directly, not through
`rosy_model_code.py exec`: that executor already holds the lock, so this would exit 75.
Exit 0 recorded (or already recorded), 2 refused, 75 work lock busy (retry later)."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "learning/curation/perception", ROOT / "learning/registry/perception",
           ROOT / "contracts/learning/src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import promotion_request  # noqa: E402  the D-874 state.json row lookup, shared with build()
from rosy.contracts.learning.promotion_request import verify  # noqa: E402
from store import Store, file_hashes, safe_name  # noqa: E402

BUSY_EXIT, REFUSED_EXIT = 75, 2
MAX_SIGNED_BYTES = 256 * 1024  # the decision repeats the bundle's file list, which Fleet bounds at 256 KiB


class Refused(ValueError):
    pass


@contextlib.contextmanager
def work_lock(root):
    """The exclusive <model-code root>/work.lock of deploy/site/rosy_model_code.py; busy raises BlockingIOError."""
    import fcntl
    with (Path(root) / "work.lock").open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _same_files(folder: Path, files) -> bool:
    have = file_hashes(folder)
    return all(have.get(item["name"]) == item["sha256"] for item in files)


def checked(signed_file, public_key: bytes, key_id: str, state, ledger):
    """(decision, decision bytes, signed file bytes, result folder); every refusal comes before any write."""
    signed_raw = Path(signed_file).read_bytes()
    try:
        if len(signed_raw) > MAX_SIGNED_BYTES:
            raise ValueError
        signed = json.loads(signed_raw)
        if set(signed) != {"key_id", "decision", "signature"} or not all(isinstance(v, str) for v in signed.values()):
            raise ValueError
    except ValueError:
        raise Refused("not a Fleet decision.signed file") from None
    if signed["key_id"] != key_id:
        raise Refused(f"signed by key id {signed['key_id']!r}, the pinned key id is {key_id!r}")
    raw = signed["decision"].encode("utf-8")
    try:
        doc = verify(raw, signed["signature"], public_key, key_id)
    except ValueError as exc:
        raise Refused(f"signature check failed: {exc}") from None
    if doc["state"] != "APPROVED":
        raise Refused(f"the decision is {doc['state']}, not APPROVED")
    sha = str(doc["bundle_sha256"])
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise Refused("bundle_sha256 is not a sha256")
    try:
        bundle_raw = (Path(state) / "promotion-requests" / f"{sha}.json").read_bytes()
    except OSError:
        raise Refused("no local promotion request with this bundle sha256") from None
    if hashlib.sha256(bundle_raw).hexdigest() != sha:
        raise Refused("the local promotion request does not hash to bundle_sha256")
    model = json.loads(bundle_raw)["model"]
    if model["revision"] != doc["model_revision"] or model["files"] != doc["files"]:
        raise Refused("the decision's model revision or files differ from the local promotion request")
    rows = promotion_request.ready_rows(ledger, doc["model_revision"], doc["files"])
    if not rows:
        raise Refused("no learning_cycle row published this revision with these files")
    folder = Path(rows[-1]["result"]["location"])
    try:
        same = _same_files(folder, doc["files"])
    except OSError:
        same = False
    if not same:
        raise Refused(f"the result folder {folder} no longer holds the approved files")
    if doc["decided_by"] == doc["proposed_by"]:
        raise Refused("the approver is the proposer (D-793 needs two people)")
    return doc, raw, signed_raw, folder


def record(doc, raw: bytes, signed_raw: bytes, folder: Path, store_root, work_root) -> str:
    """Under the work lock: accepted/<revision> (no-op if the same files are there) and approvals/<sha>/."""
    store, revision, sha = Store(store_root), doc["model_revision"], doc["bundle_sha256"]
    if not safe_name(revision):
        raise Refused(f"revision {revision!r} is not a store folder name")
    with work_lock(work_root):
        dest = store.accepted / revision
        if dest.exists():
            if not _same_files(dest, doc["files"]):
                raise Refused(f"{revision} is already accepted with different files")
            done = f"{revision} already accepted"
        else:
            inbox = store.inbox / f"approval-{sha[:16]}"
            shutil.rmtree(inbox, ignore_errors=True)  # only this tool writes this name: an interrupted run's copy
            shutil.copytree(folder, inbox)
            if file_hashes(inbox) != file_hashes(folder):
                raise Refused("the inbox copy differs from the result folder")
            store.accept(inbox.name, revision)
            done = f"{revision} accepted"
        approvals = store.root / "models" / "approvals" / sha
        if approvals.exists():
            if (approvals / "decision.json").read_bytes() != raw:
                raise Refused(f"approvals/{sha} already holds a different decision")
            return done + ", approval already recorded"
        approvals.mkdir(parents=True)
        (approvals / "decision.signed").write_bytes(signed_raw)
        (approvals / "decision.json").write_bytes(raw)
        return done + f", approval recorded in models/approvals/{sha}"


def run(signed_file, public_key: bytes, key_id: str, state, ledger, store_root, work_root) -> str:
    return record(*checked(signed_file, public_key, key_id, state, ledger), store_root, work_root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name, text in (("--decision", "decision.signed file from Fleet"), ("--public-key", "pinned public key (PEM)"),
                       ("--key-id", "pinned perception-decision key id"), ("--state", "learning state root"),
                       ("--ledger", "learning cycle state.json (the D-874 anchor ledger)"),
                       ("--store", "model store root"), ("--work-root", "model-code root holding work.lock")):
        ap.add_argument(name, required=True, help=text)
    args = ap.parse_args(argv)
    try:
        print(run(args.decision, Path(args.public_key).read_bytes(), args.key_id, args.state, args.ledger,
                  args.store, args.work_root))
    except BlockingIOError:
        print("work lock busy (model-watch or a model job is running); retry later", file=sys.stderr)
        return BUSY_EXIT
    except (ValueError, KeyError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return REFUSED_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
