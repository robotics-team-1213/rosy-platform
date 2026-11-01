"""Record a Fleet perception approval in the model store (D-898): verify everything, then accept.

approval_import.py --decision <decision.signed> --public-key <pinned pem> --key-id <pinned id>
    --state <learning state root> --ledger <learning cycle state.json> --results-root <result folders root>
    --store <model store> --work-root <model-code root>

The signed file is Fleet's GET /api/fleet/perception-promotions/<sha>/decision.signed, carried by a
person. Holding the model-code work.lock that model-watch's executor also takes, it checks in order and
before any write: the pinned key id and Ed25519 signature, state APPROVED; the local
<state>/promotion-requests/<sha>.json bytes, revision and files; the learning_cycle row
(promotion_request.ready_rows, the D-874 lookup) whose result folder lies inside --results-root and holds
exactly the approved files; decided_by differs from proposed_by. Then only the approved files (plus the
intake's model_manifest.json and intake_report.json, by exact name) are copied inbox -> models/accepted/<revision>
(store.accept), the copy is checked against the approved hashes, and the decision and its signed file go to
models/approvals/<sha>/. accepted/ still means only "intake passed"; approval is approvals/.
Nothing here moves the active pointer, shadow or a robot. Run it directly, not through
`rosy_model_code.py exec`: that executor already holds the lock, so this would exit 75.
Exit 0 recorded (or already recorded), 2 refused, 75 work lock busy (retry later)."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
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
# Written by the intake beside the model files and bound to them by sha256 (model_manifest.json); not approved bytes.
META = frozenset({"model_manifest.json", "intake_report.json"})
_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,96}")  # Fleet's rule; the signed message joins its fields with NUL


class Refused(ValueError):
    pass


@contextlib.contextmanager
def work_lock(root):
    """Exclusive, non-blocking flock on <model-code root>/work.lock; busy raises BlockingIOError.

    shortcut: a copy of work_lock() in deploy/site/rosy_model_code.py (the signed executor is not importable from a
    registry module). Both must keep the same file name and exclusive flock mode, or this stops excluding model-watch."""
    import fcntl
    with (Path(root) / "work.lock").open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _models(folder: Path) -> dict:
    """{name: sha256} of every file except the META names; compared exactly, so an extra file never passes."""
    return {name: sha for name, sha in file_hashes(folder).items() if name not in META}


def checked(signed_file, public_key: bytes, key_id: str, state, ledger, results_root):
    """(decision, decision bytes, signed file bytes, result folder, expected {name: sha256}); no writes."""
    if not _KEY_ID.fullmatch(str(key_id)):
        raise Refused("the pinned key id must match [A-Za-z0-9._-]{1,96}")
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
    expected = {item["name"]: item["sha256"] for item in doc["files"]}
    if len(expected) != len(doc["files"]) or any(
            name in (".", "..") or name in META or Path(name).name != name or "\\" in name for name in expected):
        raise Refused("the approved file names must be unique plain names")
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
    folder = Path(rows[-1]["result"]["location"]).resolve()
    if not folder.is_relative_to(Path(results_root).resolve()) or not folder.is_dir():
        raise Refused(f"the result folder {folder} is not a folder inside --results-root")
    try:
        same = _models(folder) == expected
    except OSError:
        same = False
    if not same:
        raise Refused(f"the result folder {folder} does not hold exactly the approved files")
    if doc["decided_by"] == doc["proposed_by"]:
        raise Refused("the approver is the proposer (D-793 needs two people)")
    return doc, raw, signed_raw, folder, expected


def _accept(store: Store, folder: Path, expected: dict, revision: str, sha: str) -> str:
    dest = store.accepted / revision
    if dest.exists():
        if _models(dest) != expected:
            raise Refused(f"{revision} is already accepted with different files")
        return f"{revision} already accepted"
    inbox = store.inbox / f"approval-{sha[:16]}"
    shutil.rmtree(inbox, ignore_errors=True)  # only this tool writes this name: an interrupted run's copy
    try:
        inbox.mkdir(parents=True)
        for name in [*expected, *(m for m in sorted(META) if (folder / m).is_file())]:
            shutil.copy2(folder / name, inbox / name)
        # The copy is checked against the approved hashes, not against its own source (which may have changed).
        if _models(inbox) != expected:
            raise Refused("the files copied from the result folder differ from the approved files")
        store.accept(inbox.name, revision)
    finally:
        shutil.rmtree(inbox, ignore_errors=True)
    return f"{revision} accepted"


def _approve(store: Store, sha: str, raw: bytes, signed_raw: bytes) -> str:
    final = store.root / "models" / "approvals" / sha
    if (final / "decision.json").is_file():
        if (final / "decision.json").read_bytes() != raw:
            raise Refused(f"approvals/{sha} already holds a different decision")
        return "approval already recorded"
    temporary = final.with_name(f".tmp-{sha}")  # a directory without decision.json is a crash leftover: absent
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.rmtree(final, ignore_errors=True)
    temporary.mkdir(parents=True)
    (temporary / "decision.signed").write_bytes(signed_raw)
    (temporary / "decision.json").write_bytes(raw)
    os.replace(temporary, final)
    return f"approval recorded in models/approvals/{sha}"


def run(signed_file, public_key: bytes, key_id: str, state, ledger, store_root, work_root, results_root) -> str:
    """Everything, including the checks, happens while holding the work lock model-watch also takes."""
    with work_lock(work_root):
        doc, raw, signed_raw, folder, expected = checked(signed_file, public_key, key_id, state, ledger, results_root)
        store, revision = Store(store_root), doc["model_revision"]
        if not safe_name(revision):
            raise Refused(f"revision {revision!r} is not a store folder name")
        done = _accept(store, folder, expected, revision, doc["bundle_sha256"])
        return f"{done}, {_approve(store, doc['bundle_sha256'], raw, signed_raw)}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name, text in (("--decision", "decision.signed file from Fleet"), ("--public-key", "pinned public key (PEM)"),
                       ("--key-id", "pinned perception-decision key id"), ("--state", "learning state root"),
                       ("--ledger", "learning cycle state.json (the D-874 anchor ledger)"),
                       ("--results-root", "folder that must contain the learning result folder"),
                       ("--store", "model store root"), ("--work-root", "model-code root holding work.lock")):
        ap.add_argument(name, required=True, help=text)
    args = ap.parse_args(argv)
    try:
        print(run(args.decision, Path(args.public_key).read_bytes(), args.key_id, args.state, args.ledger,
                  args.store, args.work_root, args.results_root))
    except BlockingIOError:
        print("work lock busy (model-watch or a model job is running); retry later", file=sys.stderr)
        return BUSY_EXIT
    except (ValueError, KeyError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return REFUSED_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
