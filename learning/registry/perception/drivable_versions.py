"""D-558 drivable model version ledger (drivable_versions.yaml).

drivable_versions.py show [<version>]
drivable_versions.py add <version> <revision> --onnx-sha256 <hex> --dataset <name>@<sha256>
                     --rule "D-554 1-8" [--rule ...] --status candidate --note "<one line>"
drivable_versions.py set-status <version> <candidate|shadow|rejected|retired>

One version names one revision; rejected and discarded candidates keep theirs.
intake.py refuses a v13-drivable-* manifest whose model_version is missing, malformed,
off the lineage major, or held in the ledger by another revision. No IPs, accounts or secrets."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

SCHEMA = "rosy.drivable-versions/1"
LEDGER = Path(__file__).resolve().parent / "drivable_versions.yaml"
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d{2})$")
LINEAGE_RE = re.compile(r"^v(\d+)-drivable-")
STATUSES = ("candidate", "shadow", "rejected", "retired")
FIELDS = ("version", "revision", "onnx_sha256", "dataset", "dataset_sha256", "rules", "status", "note")
# Hashes stay under *_sha256 keys: the secret scanner flags a bare 64-hex token (name@sha).


def version_error(version, revision: str) -> str | None:
    """None when version is v<major>.<minor>.<NN> and major is the revision's lineage number."""
    m = VERSION_RE.match(version) if isinstance(version, str) else None
    if not m:
        return f"model_version {version!r}: expected v<major>.<minor>.<two-digit patch> (D-558)"
    lineage = LINEAGE_RE.match(revision)
    if lineage and int(m[1]) != int(lineage[1]):
        return f"model_version {version} major {m[1]} differs from lineage {lineage[0][:-1]} (D-558)"
    return None


def _validate(doc) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("models"), list):
        raise ValueError(f"ledger: expected schema {SCHEMA} with a models list")
    seen = set()
    for e in doc["models"]:
        if not isinstance(e, dict) or set(e) != set(FIELDS):
            raise ValueError(f"ledger entry needs exactly {FIELDS}: {e!r}")
        error = version_error(e["version"], str(e["revision"]))
        if (error or not isinstance(e["revision"], str) or not LINEAGE_RE.match(e["revision"])
                or not all(re.fullmatch(r"[0-9a-f]{64}", str(e[k])) for k in ("onnx_sha256", "dataset_sha256"))
                or not isinstance(e["dataset"], str) or "@" in e["dataset"] or not isinstance(e["note"], str)
                or not isinstance(e["rules"], list) or not all(isinstance(r, str) for r in e["rules"])
                or e["status"] not in STATUSES):
            raise ValueError(f"ledger entry {e.get('version')!r} invalid: {error or 'field types/status'}")
        for key in ("version", "revision"):
            if (key, e[key]) in seen:
                raise ValueError(f"ledger: duplicate {key} {e[key]}")
            seen.add((key, e[key]))
    return doc["models"]


def load(path=LEDGER) -> list[dict]:
    try:
        return _validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        raise ValueError(f"ledger {path}: {exc}") from exc


def save(entries: list[dict], path=LEDGER) -> None:
    doc = {"schema": SCHEMA, "models": entries}
    _validate(doc)
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200),
                          encoding="utf-8", newline="\n")


def intake_error(manifest: dict, path=LEDGER) -> str | None:
    """None when a v13-drivable manifest carries a valid model_version the ledger does not give away."""
    revision, version = manifest.get("model_revision", ""), manifest.get("model_version")
    if version is None:
        return "v13-drivable needs model_version v<major>.<minor>.<patch> (D-558)"
    error = version_error(version, revision)
    if error:
        return error
    for e in load(path):
        if (e["version"] == version) != (e["revision"] == revision):
            return (f"ledger has {e['version']} as {e['revision']}; "
                    f"{revision} cannot be {version} (D-558: one version, one revision)")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    sub = ap.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show")
    show.add_argument("version", nargs="?")
    add = sub.add_parser("add")
    add.add_argument("version")
    add.add_argument("revision")
    add.add_argument("--onnx-sha256", required=True)
    add.add_argument("--dataset", required=True, help="<name>@<content sha256>")
    add.add_argument("--rule", action="append", required=True, dest="rules")
    add.add_argument("--status", choices=STATUSES, default="candidate")
    add.add_argument("--note", required=True)
    status = sub.add_parser("set-status")
    status.add_argument("version")
    status.add_argument("status", choices=STATUSES)
    args = ap.parse_args(argv)
    try:
        entries = load(args.ledger)
        if args.action == "show":
            rows = [e for e in entries if args.version in (None, e["version"])]
            if not rows:
                raise ValueError(f"no ledger entry {args.version}")
            for e in rows:
                print(f"{e['version']}  {e['revision']}  {e['status']}  {e['note']}")
            return 0
        if args.action == "add":
            name, _, dataset_sha = args.dataset.partition("@")
            entries.append({"version": args.version, "revision": args.revision,
                            "onnx_sha256": args.onnx_sha256, "dataset": name, "dataset_sha256": dataset_sha,
                            "rules": args.rules, "status": args.status, "note": args.note})
        else:
            match = [e for e in entries if e["version"] == args.version]
            if not match:
                raise ValueError(f"no ledger entry {args.version}")
            match[0]["status"] = args.status
        save(entries, args.ledger)
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"{args.action} {args.version} -> {args.ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
